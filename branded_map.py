import base64
import time
import re
import html as html_mod
from textwrap import dedent

import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px
import plotly.graph_objects as go  # for label overlay & leader lines

# ============== 0. Secrets ==============

def get_secret(key: str, default: str = "") -> str:
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return default

GITHUB_TOKEN = get_secret("GITHUB_TOKEN", "")
GITHUB_USER_DEFAULT = get_secret("GITHUB_USER", "")

# === GitHub helpers ===================================================

def github_headers(token: str):
    headers = {
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers

def ensure_repo_exists(owner: str, repo: str, token: str) -> bool:
    """
    Ensure repo exists.
    Returns:
      True  -> repo was just created
      False -> repo already existed
    """
    api_base = "https://api.github.com"
    headers = github_headers(token)

    r = requests.get(f"{api_base}/repos/{owner}/{repo}", headers=headers)
    if r.status_code == 200:
        return False  # already exists
    if r.status_code != 404:
        raise RuntimeError(f"Error checking repo: {r.status_code} {r.text}")

    payload = {
        "name": repo,
        "auto_init": True,
        "private": False,
        "description": "Branded interactive map + tables widget (auto-created by Streamlit app).",
    }
    r = requests.post(f"{api_base}/user/repos", headers=headers, json=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Error creating repo: {r.status_code} {r.text}")

    return True  # newly created

def ensure_pages_enabled(owner: str, repo: str, token: str, branch: str = "main") -> None:
    """
    Attempt to enable GitHub Pages on the repo from the given branch root.
    If Pages is already enabled, this is a no-op.
    """
    api_base = "https://api.github.com"
    headers = github_headers(token)

    r = requests.get(f"{api_base}/repos/{owner}/{repo}/pages", headers=headers)
    if r.status_code == 200:
        return
    if r.status_code not in (404, 403):
        raise RuntimeError(f"Error checking GitHub Pages: {r.status_code} {r.text}")
    if r.status_code == 403:
        # No permission via API; nothing we can do programmatically.
        return

    payload = {"source": {"branch": branch, "path": "/"}}
    r = requests.post(f"{api_base}/repos/{owner}/{repo}/pages", headers=headers, json=payload)
    if r.status_code not in (201, 202):
        raise RuntimeError(f"Error enabling GitHub Pages: {r.status_code} {r.text}")

def upload_file_to_github(
    owner: str,
    repo: str,
    token: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
) -> None:
    """
    Create or update a file in the repo at the given path.
    """
    api_base = "https://api.github.com"
    headers = github_headers(token)

    get_url = f"{api_base}/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": branch}
    r = requests.get(get_url, headers=headers, params=params)
    sha = None
    if r.status_code == 200:
        sha = r.json().get("sha")
    elif r.status_code not in (404,):
        raise RuntimeError(f"Error checking file: {r.status_code} {r.text}")

    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    payload = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(get_url, headers=headers, json=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Error uploading file: {r.status_code} {r.text}")

def trigger_pages_build(owner: str, repo: str, token: str) -> bool:
    """
    Ask GitHub to build the Pages site (legacy mode).
    """
    api_base = "https://api.github.com"
    headers = github_headers(token)
    r = requests.post(f"{api_base}/repos/{owner}/{repo}/pages/builds", headers=headers)
    return r.status_code in (201, 202)

# --- Helpers for availability check -------------------------------

def check_repo_exists(owner: str, repo: str, token: str) -> bool:
    api_base = "https://api.github.com"
    headers = github_headers(token)
    r = requests.get(f"{api_base}/repos/{owner}/{repo}", headers=headers)
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        return False
    raise RuntimeError(f"Error checking repo: {r.status_code} {r.text}")

def check_file_exists(owner: str, repo: str, token: str, path: str, branch: str = "main") -> bool:
    api_base = "https://api.github.com"
    headers = github_headers(token)
    r = requests.get(
        f"{api_base}/repos/{owner}/{repo}/contents/{path}",
        headers=headers,
        params={"ref": branch},
    )
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        return False
    raise RuntimeError(f"Error checking file: {r.status_code} {r.text}")

def find_next_widget_filename(owner: str, repo: str, token: str, branch: str = "main") -> str:
    """
    Look at the root of the repo and find the next available tN.html filename.
    Returns 't1.html' if none are found or on fallback.
    """
    api_base = "https://api.github.com"
    headers = github_headers(token)
    r = requests.get(
        f"{api_base}/repos/{owner}/{repo}/contents",
        headers=headers,
        params={"ref": branch},
    )
    if r.status_code != 200:
        return "t1.html"

    max_n = 0
    try:
        items = r.json()
        for item in items:
            if item.get("type") == "file":
                name = item.get("name", "")
                m = re.fullmatch(r"t(\d+)\.html", name)
                if m:
                    max_n = max(max_n, int(m.group(1)))
    except Exception:
        return "t1.html"

    return f"t{max_n + 1}.html" if max_n >= 0 else "t1.html"

# === Brand metadata ===================================================

UNBRANDED_SCALE = ["#60A5FA", "#F97316", "#DC2626"]  # blue -> orange -> red

def get_brand_meta(brand: str, style_mode: str = "Branded") -> dict:
    """
    Brand metadata for map + tables page.

    style_mode:
        "Branded"   -> use brand-specific map palettes
        "Unbranded" -> use neutral UNBRANDED_SCALE for all brands
    """
    brand_clean = (brand or "").strip() or "Action Network"
    style_mode = (style_mode or "Branded").strip().lower()

    # base meta
    meta = {
        "name": brand_clean,
        "brand_class": "",
        "logo_url": "",
        "logo_alt": f"{brand_clean} logo",
        "accent": "#16A34A",
        "accent_soft": "#DCFCE7",
        "accent_softer": "#F3FBF7",
        "branded_scale": UNBRANDED_SCALE,
    }

    if brand_clean == "Action Network":
        meta.update({
            "brand_class": "brand-actionnetwork",
            "logo_url": "https://i.postimg.cc/x1nG117r/AN-final2-logo.png",
            "logo_alt": "Action Network logo",
            "accent": "#16A34A",
            "accent_soft": "#DCFCE7",
            "accent_softer": "#F3FBF7",
            "branded_scale": ["#BBF7D0", "#4ADE80", "#166534"],
        })
    elif brand_clean == "VegasInsider":
        meta.update({
            "brand_class": "brand-vegasinsider",
            "logo_url": "https://i.postimg.cc/kGVJyXc1/VI-logo-final.png",
            "logo_alt": "VegasInsider logo",
            "accent": "#FCBE31",
            "accent_soft": "#FFF3C7",
            "accent_softer": "#FFF9EC",
            "branded_scale": ["#FFF9EC", "#FCD34D", "#B45309"],
        })
    elif brand_clean == "Canada Sports Betting":
        meta.update({
            "brand_class": "brand-canadasb",
            "logo_url": "https://i.postimg.cc/ZKbrbPCJ/CSB-FN.png",
            "logo_alt": "Canada Sports Betting logo",
            "accent": "#DC2626",
            "accent_soft": "#FEE2E2",
            "accent_softer": "#FFF5F5",
            "branded_scale": ["#FECACA", "#FB7185", "#B91C1C"],
        })
    elif brand_clean == "RotoGrinders":
        meta.update({
            "brand_class": "brand-rotogrinders",
            "logo_url": "https://i.postimg.cc/PrcJnQtK/RG-logo-Fn.png",
            "logo_alt": "RotoGrinders logo",
            "accent": "#0EA5E9",
            "accent_soft": "#E0F2FE",
            "accent_softer": "#F3FAFF",
            "branded_scale": ["#BFDBFE", "#38BDF8", "#1D4ED8"],
        })

    # remember style_mode so downstream code can behave differently
    meta["style_mode"] = style_mode

    # Decide which scale & accent set to actually use on the map + legend
    if style_mode == "unbranded":
        meta["map_scale"] = UNBRANDED_SCALE
        # softer accent set based on red so it still feels neutral-ish
        meta["accent"] = "#EF4444"        # soft red
        meta["accent_soft"] = "#FEE2E2"   # very light red
        meta["accent_softer"] = "#FEF2F2" # almost white with red tint
    else:
        meta["map_scale"] = meta["branded_scale"]

    return meta

# === State mapping ====================================================

STATE_ABBR = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}

# Helper lookup that accepts full names or 2-letter codes
STATE_LOOKUP = {}
for name, code in STATE_ABBR.items():
    STATE_LOOKUP[name] = code
    STATE_LOOKUP[name.title()] = code
    STATE_LOOKUP[name.upper()] = code
    STATE_LOOKUP[name.lower()] = code
    STATE_LOOKUP[code] = code
    STATE_LOOKUP[code.upper()] = code
    STATE_LOOKUP[code.lower()] = code

# Small, dense Northeast states => callouts with leader lines
SMALL_STATE_CENTROIDS = {
    "CT": {"lat": 41.6, "lon": -72.7},
    "DE": {"lat": 39.0, "lon": -75.5},
    "MD": {"lat": 39.0, "lon": -76.7},
    "MA": {"lat": 42.3, "lon": -71.8},
    "NH": {"lat": 43.6, "lon": -71.6},
    "NJ": {"lat": 40.1, "lon": -74.5},
    "RI": {"lat": 41.7, "lon": -71.6},
    "VT": {"lat": 44.0, "lon": -72.7},
    "DC": {"lat": 38.9, "lon": -77.0},
}
SMALL_STATES = set(SMALL_STATE_CENTROIDS.keys())

UP_CALLOUT_STATES = {"VT", "MA", "NH"}

UP_CALLOUT_OFFSETS = {
    "MA": {"d_lon": 5.8, "d_lat": 3.2},
    "VT": {"d_lon": 5.3, "d_lat": 4.4},
    "NH": {"d_lon": 6.4, "d_lat": 6.8},
}

DOWN_CALLOUT_NUDGE = {
    "DE": {"d_lon": 0.45, "d_lat": 0.15},
    "MD": {"d_lon": -0.35, "d_lat": -0.20},
}

# === 2. HTML TEMPLATE: map + tables (tabbed tables) ===================

HTML_TEMPLATE_MAP_TABLE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>[[PAGE_TITLE]]</title>
</head>
<body style="margin:0;background:#F3F4F6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0F172A;">

<section class="vi-map-card [[BRAND_CLASS]]" style="width:100%;max-width:100%;margin:0;padding:0;">

<style>
.vi-map-card, .vi-map-card * { box-sizing:border-box; font-family:inherit; }

.vi-map-card{
  --accent:[[ACCENT]];
  --accent-soft:[[ACCENT_SOFT]];
  --accent-softer:[[ACCENT_SOFTER]];
}

/* Card container */
.vi-map-shell{
  background:#FFFFFF;
  border-radius:0;
  box-shadow:0 8px 24px rgba(15,23,42,.12);
  border:1px solid rgba(148,163,184,.25);
  padding:18px 18px 20px;

  max-height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
}

/* Scrollbar */
.vi-map-shell{
  scrollbar-width: thin;
  scrollbar-color: var(--accent) transparent;
}
.vi-map-shell::-webkit-scrollbar{
  width:6px;
  height:6px;
}
.vi-map-shell::-webkit-scrollbar-track{
  background:var(--accent-soft);
  border-radius:999px;
}
.vi-map-shell::-webkit-scrollbar-thumb{
  background:var(--accent);
  border-radius:999px;
}
.vi-map-shell::-webkit-scrollbar-thumb:hover{
  filter:brightness(0.9);
}

/* Top strapline + title */
.vi-map-header{
  margin-bottom:10px;
}
.vi-map-strapline{
  font-size:11px;
  letter-spacing:.12em;
  text-transform:uppercase;
  color:#64748B;
  font-weight:700;
}
.vi-map-title{
  margin:6px 0 4px;
  font-size:clamp(22px,2.6vw,26px);
  line-height:1.1;
  font-weight:800;
  color:#0F172A;
}
.vi-map-subtitle{
  margin:0;
  font-size:13px;
  color:#4B5563;
}

/* Gradient legend */
.vi-map-legend-labels{
  display:flex;
  justify-content:space-between;
  font-size:11px;
  text-transform:uppercase;
  font-weight:600;
  color:#6B7280;
  margin:14px 2px 4px;
}
.vi-map-legend-bar{
  height:6px;
  border-radius:999px;
  background:linear-gradient(90deg,[[SCALE_START]],[[SCALE_MID]],[[SCALE_END]]);
  overflow:hidden;
}

/* Map frame */
.vi-map-frame{
  margin-top:14px;
  border-radius:16px;
  background:#F9FAFB;
  border:1px solid #E5E7EB;
  overflow:hidden;
}

/* Tables & tabs */
.vi-map-section-sub{
  margin:0 0 10px;
  font-size:12px;
  color:#6B7280;
  padding-left:10px;
  border-left:3px solid var(--accent-soft);
}

.vi-tab-header{
  display:inline-flex;
  gap:6px;
  margin:20px 0 6px;
  padding:3px;
  background:rgba(15,23,42,.02);
  border-radius:999px;
  border:1px solid rgba(148,163,184,.35);
}
.vi-tab-header .vi-tab{
  border:0;
  background:transparent;
  border-radius:999px;
  padding:6px 14px;
  font-size:12px;
  font-weight:600;
  color:#6B7280;
  cursor:pointer;
  transition:background-color .18s ease, color .18s ease, box-shadow .18s ease, transform .06s ease;
}
.vi-tab-header .vi-tab.is-active{
  background:var(--accent);
  color:#FFFFFF;
  box-shadow:0 3px 8px rgba(15,23,42,.2);
  transform:translateY(-0.5px);
}
.vi-tab-header .vi-tab:hover:not(.is-active){
  background:var(--accent-soft);
  color:#111827;
}
.vi-tab-header .vi-tab:focus-visible{
  outline:none;
  box-shadow:0 0 0 2px var(--accent-soft),0 0 0 4px rgba(15,23,42,.25);
}

.vi-tab-panel{
  margin-top:6px;
}

/* Tables */
.vi-map-table{
  width:100%;
  border-collapse:collapse;
  font-size:13px;
  color:#111827;
}
.vi-map-table thead th{
  text-align:left;
  padding:8px 10px;
  font-size:11px;
  text-transform:uppercase;
  letter-spacing:.06em;
  color:var(--accent);
  background:var(--accent-soft);
  border-bottom:1px solid rgba(148,163,184,.35);
}
.vi-map-table tbody tr:nth-child(odd){
  background:#FFFFFF;
}
.vi-map-table tbody tr:nth-child(even){
  background:var(--accent-softer);
}
.vi-map-table tbody tr:hover{
  background:var(--accent-soft);
  filter:brightness(0.96);
  transition:background-color .15s ease, filter .15s ease;
}
.vi-map-table tbody td{
  padding:7px 10px;
  vertical-align:middle;
}

/* Rank pill */
.vi-rank-pill{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:22px;
  height:22px;
  padding:0 7px;
  border-radius:999px;
  font-size:11px;
  font-weight:600;
  background:var(--accent);
  color:#FFFFFF;
}
</style>

<div class="vi-map-shell">

  <header class="vi-map-header">
    <div class="vi-map-strapline">[[STRAPLINE]]</div>
    <h1 class="vi-map-title">[[PAGE_TITLE]]</h1>
    <p class="vi-map-subtitle">[[SUBTITLE]]</p>
  </header>

  <div class="vi-map-legend">
    <div class="vi-map-legend-labels">
      <span>[[LEGEND_LOW]]</span>
      <span>[[LEGEND_HIGH]]</span>
    </div>
    <div class="vi-map-legend-bar"></div>
  </div>

  <!-- Interactive map -->
  <div class="vi-map-frame">
    [[MAP_HTML]]
  </div>

  <!-- Tabbed tables -->
  <section class="vi-map-tables" style="margin-top:4px;">
    <div class="vi-tab-header" role="tablist" aria-label="State rankings">
      <button class="vi-tab is-active" data-tab="high" role="tab" aria-selected="true" tabindex="0">
        [[HIGH_TITLE]]
      </button>
      <button class="vi-tab" data-tab="low" role="tab" aria-selected="false" tabindex="-1">
        [[LOW_TITLE]]
      </button>
    </div>

    <p class="vi-map-section-sub vi-map-section-sub-tab" data-tab="high">[[HIGH_SUB]]</p>
    <p class="vi-map-section-sub vi-map-section-sub-tab" data-tab="low" style="display:none;">[[LOW_SUB]]</p>

    <div class="vi-tab-panel" data-panel="high">
      [[TABLE_HIGH_HTML]]
    </div>
    <div class="vi-tab-panel" data-panel="low" style="display:none;">
      [[TABLE_LOW_HTML]]
    </div>
  </section>

</div>

<script>
(function(){
  var widgets = document.querySelectorAll('.vi-map-card');
  widgets.forEach(function(root){
    var tabs = root.querySelectorAll('.vi-tab-header .vi-tab');
    var panels = root.querySelectorAll('.vi-tab-panel');
    var subs = root.querySelectorAll('.vi-map-section-sub-tab');
    if (!tabs.length) return;

    tabs.forEach(function(btn){
      btn.addEventListener('click', function(){
        var target = this.getAttribute('data-tab');

        tabs.forEach(function(b){
          var active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
          b.setAttribute('tabindex', active ? '0' : '-1');
        });

        panels.forEach(function(p){
          p.style.display = (p.getAttribute('data-panel') === target) ? 'block' : 'none';
        });

        subs.forEach(function(s){
          s.style.display = (s.getAttribute('data-tab') === target) ? 'block' : 'none';
        });
      });
    });
  });
})();
</script>

</section>
</body>
</html>
"""

# === 3. HTML generators ===============================================

def build_ranked_table_html(df: pd.DataFrame, value_col: str, top_n: int = 10) -> str:
    cols = list(df.columns)
    state_col = cols[0]  # assume first col is state
    other_cols = [c for c in cols if c not in (state_col,)]
    if value_col in other_cols:
        other_cols.remove(value_col)
        metric_cols = [value_col] + other_cols
    else:
        metric_cols = other_cols

    head_cells = ['<th scope="col">Rank</th>', f'<th scope="col">{html_mod.escape(state_col)}</th>']
    for c in metric_cols:
        head_cells.append(f'<th scope="col">{html_mod.escape(str(c))}</th>')
    thead_html = "<tr>" + "".join(head_cells) + "</tr>"

    body_rows = []
    for idx, (_, row) in enumerate(df.head(top_n).iterrows(), start=1):
        tds = [f'<td><span class="vi-rank-pill">{idx}</span></td>']
        tds.append(f'<td>{html_mod.escape(str(row[state_col]))}</td>')
        for c in metric_cols:
            val = row[c]
            text = "" if pd.isna(val) else str(val)
            tds.append(f'<td>{html_mod.escape(text)}</td>')
        body_rows.append("<tr>" + "".join(tds) + "</tr>")

    table_html = f"""
<table class="vi-map-table">
  <thead>
    {thead_html}
  </thead>
  <tbody>
    {''.join(body_rows)}
  </tbody>
</table>
"""
    return table_html

def generate_map_table_html_from_df(
    df: pd.DataFrame,
    brand_meta: dict,
    state_col: str,
    value_col: str,
    page_title: str,
    subtitle: str,
    strapline: str,
    legend_low: str,
    legend_high: str,
    high_title: str,
    high_sub: str,
    low_title: str,
    low_sub: str,
    top_n: int = 10,
    show_state_labels: bool = False,
    table_cols=None,
    hover_cols=None,
) -> str:
    df = df.copy()
    df[state_col] = df[state_col].astype(str).str.strip()

    s = df[state_col].astype(str).str.strip()
    name_mask = s.str.len() > 2
    code_mask = ~name_mask
    s_norm = s.copy()
    s_norm.loc[name_mask] = s_norm.loc[name_mask].str.title()
    s_norm.loc[code_mask] = s_norm.loc[code_mask].str.upper()
    df["state_abbr"] = s_norm.map(STATE_LOOKUP)

    df[value_col] = (
        df[value_col]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
    )
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

    df = df[~df["state_abbr"].isna()].copy()
    df = df[~df[value_col].isna()].copy()

    if df.empty:
        return "<p style='padding:16px;font-family:sans-serif;'>No valid state/metric data to display.</p>"

    df["rank"] = df[value_col].rank(ascending=False, method="min").astype(int)

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if value_col not in numeric_cols:
        numeric_cols = [value_col] + numeric_cols

    # Hover metrics
    if hover_cols is None or len(hover_cols) == 0:
        default_hover = [c for c in numeric_cols if c != "rank"]
        metrics_for_hover = [value_col] + [c for c in default_hover if c != value_col][:2]
    else:
        cleaned_hover = [c for c in hover_cols if c in df.columns and c != state_col]
        metrics_for_hover = [value_col] + [c for c in cleaned_hover if c != value_col]

    seen = set()
    metrics_for_hover = [c for c in metrics_for_hover if not (c in seen or seen.add(c))]

    custom_cols = [state_col] + metrics_for_hover

    v_min = df[value_col].min()
    v_max = df[value_col].max()
    if pd.isna(v_min) or pd.isna(v_max) or v_min == v_max:
        df["fill_norm"] = 0.5
    else:
        df["fill_norm"] = (df[value_col] - v_min) / (v_max - v_min)

    map_scale = brand_meta["map_scale"]
    accent = brand_meta.get("accent", "#16A34A")
    style_mode = brand_meta.get("style_mode", "branded")

    fig = px.choropleth(
        df,
        locations="state_abbr",
        locationmode="USA-states",
        scope="usa",
        color=value_col,
        color_continuous_scale=map_scale,
        custom_data=df[custom_cols],
    )

    lines = []
    for idx, col in enumerate(metrics_for_hover, start=1):
        nice_label = col.replace("_", " ").strip().title()
        value_fmt = f"%{{customdata[{idx}]}}"
        lines.append(
            f"<span style='color:{accent};font-weight:500;'>"
            f"{html_mod.escape(nice_label)}:</span> {value_fmt}"
        )

    hovertemplate = (
        f"<span style='font-weight:600;color:{accent};'>"
        "%{customdata[0]} (%{location})"
        "</span><br>"
        + "<br>".join(lines)
        + "<extra></extra>"
    )

    fig.update_traces(
        hovertemplate=hovertemplate,
        hoverlabel=dict(
            bgcolor="#FFFFFF",
            bordercolor="rgba(15,23,42,0.18)",
            font=dict(color="#111827", size=12),
            align="left",
            namelength=-1,
        ),
        marker_line_color="#F9FAFB",
        marker_line_width=1,
        showlegend=False,
    )

    if show_state_labels:
        label_df = df.copy()
        label_df["label_text"] = label_df["state_abbr"] + " (" + label_df["rank"].astype(str) + ")"

        small_mask = label_df["state_abbr"].isin(SMALL_STATES)
        df_big = label_df[~small_mask]
        df_small = label_df[small_mask]

        # ---------- Big states (labels inside map) ----------
        if not df_big.empty:
            def add_big_group(group, text_color):
                if group.empty:
                    return
                fig.add_trace(
                    go.Scattergeo(
                        locationmode="USA-states",
                        locations=group["state_abbr"],
                        text=group["label_text"],
                        mode="text",
                        textfont=dict(size=9, color=text_color),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

            if style_mode == "unbranded":
                # use high-contrast but not crazy-dark colours
                low_big = df_big[df_big["fill_norm"] < (1.0 / 3.0)]                 # blue states
                mid_big = df_big[(df_big["fill_norm"] >= (1.0 / 3.0)) &
                                 (df_big["fill_norm"] < (2.0 / 3.0))]               # orange states
                high_big = df_big[df_big["fill_norm"] >= (2.0 / 3.0)]               # red states

                # blue & red fills -> white text; orange fills -> dark text
                add_big_group(low_big, "#FFFFFF")
                add_big_group(mid_big, "#111827")
                add_big_group(high_big, "#FFFFFF")
            else:
                # original branded behavior
                label_light = "#FFFFFF"
                label_dark = map_scale[2] if len(map_scale) >= 3 else "#111827"

                dark_bg = df_big[df_big["fill_norm"] >= 0.55]
                light_bg = df_big[df_big["fill_norm"] < 0.55]

                add_big_group(dark_bg, label_light)
                add_big_group(light_bg, label_dark)

        # ---------- Small NE states (callouts) ----------
        if not df_small.empty:
            df_small = df_small.copy()
            df_small["centroid_lat"] = df_small["state_abbr"].map(
                lambda s: SMALL_STATE_CENTROIDS[s]["lat"]
            )
            df_small["centroid_lon"] = df_small["state_abbr"].map(
                lambda s: SMALL_STATE_CENTROIDS[s]["lon"]
            )

            df_small = df_small.sort_values("centroid_lat", ascending=False).reset_index(drop=True)

            min_lat = df_small["centroid_lat"].min()
            down_j = 0

            line_lons, line_lats = [], []
            label_lons, label_lats, label_texts = [], [], []
            label_colors = []

            for _, row in df_small.iterrows():
                abbr = row["state_abbr"]
                c = SMALL_STATE_CENTROIDS[abbr]
                lon0, lat0 = c["lon"], c["lat"]

                if abbr in UP_CALLOUT_STATES:
                    offs = UP_CALLOUT_OFFSETS.get(abbr, {"d_lon": 4.5, "d_lat": 3.0})
                    lon1 = lon0 - offs["d_lon"]
                    lat1 = lat0 + offs["d_lat"]
                else:
                    offset_lon = 4.8 - down_j * 0.4
                    lon1 = lon0 + offset_lon
                    lat1 = min_lat - 1.8 - down_j * 0.35

                    nudge = DOWN_CALLOUT_NUDGE.get(abbr)
                    if nudge:
                        lon1 += nudge.get("d_lon", 0.0)
                        lat1 += nudge.get("d_lat", 0.0)

                    down_j += 1

                # Always use dark accent for callouts (on white background)
                callout_color = accent

                line_lons += [lon0, lon1, None]
                line_lats += [lat0, lat1, None]

                label_lons.append(lon1)
                label_lats.append(lat1)
                label_texts.append(row["label_text"])
                label_colors.append(callout_color)

            # leader lines
            fig.add_trace(
                go.Scattergeo(
                    lon=line_lons,
                    lat=line_lats,
                    mode="lines",
                    line=dict(width=1, color=accent),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

            # labels (dark accent)
            fig.add_trace(
                go.Scattergeo(
                    lon=label_lons,
                    lat=label_lats,
                    mode="text",
                    text=label_texts,
                    textfont=dict(size=9, color=accent),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="#F9FAFB",
        plot_bgcolor="#F9FAFB",
        showlegend=False,
        geo=dict(
            bgcolor="#F9FAFB",
            lakecolor="#F9FAFB",
            showlakes=False,
            showland=True,
            landcolor="#F3F4F6",
            showframe=False,
            showcoastlines=False,
            showcountries=False,
        ),
        coloraxis_showscale=False,
    )

    map_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={
            "displayModeBar": False,
            "responsive": True,
            "scrollZoom": False,
        },
    )

    # Table columns
    if table_cols is None or len(table_cols) == 0:
        default_table_cols = [c for c in numeric_cols if c != "rank"]
        table_cols = [value_col] + [c for c in default_table_cols if c != value_col]
    else:
        table_cols = [c for c in table_cols if c in df.columns and c != state_col]
        table_cols = [value_col] + [c for c in table_cols if c != value_col]

    df_for_tables = pd.DataFrame({
        state_col: df[state_col],
        **{c: df[c] for c in table_cols},
    })

    df_high = df_for_tables.sort_values(by=value_col, ascending=False)
    df_low = df_for_tables.sort_values(by=value_col, ascending=True)

    high_table_html = build_ranked_table_html(df_high, value_col=value_col, top_n=top_n)
    low_table_html = build_ranked_table_html(df_low, value_col=value_col, top_n=top_n)

    scale_start, scale_mid, scale_end = map_scale[0], map_scale[1], map_scale[2]

    html = (
        HTML_TEMPLATE_MAP_TABLE
        .replace("[[PAGE_TITLE]]", html_mod.escape(page_title))
        .replace("[[SUBTITLE]]", html_mod.escape(subtitle or ""))
        .replace("[[STRAPLINE]]", html_mod.escape(strapline or ""))
        .replace("[[LEGEND_LOW]]", html_mod.escape(legend_low or "Lowest"))
        .replace("[[LEGEND_HIGH]]", html_mod.escape(legend_high or "Highest"))
        .replace("[[MAP_HTML]]", map_html)
        .replace("[[HIGH_TITLE]]", html_mod.escape(high_title))
        .replace("[[HIGH_SUB]]", html_mod.escape(high_sub or ""))
        .replace("[[LOW_TITLE]]", html_mod.escape(low_title))
        .replace("[[LOW_SUB]]", html_mod.escape(low_sub or ""))
        .replace("[[TABLE_HIGH_HTML]]", high_table_html)
        .replace("[[TABLE_LOW_HTML]]", low_table_html)
        .replace("[[BRAND_CLASS]]", brand_meta.get("brand_class", ""))
        .replace("[[ACCENT]]", brand_meta.get("accent", "#16A34A"))
        .replace("[[ACCENT_SOFT]]", brand_meta.get("accent_soft", "#DCFCE7"))
        .replace("[[ACCENT_SOFTER]]", brand_meta.get("accent_softer", "#F3FBF7"))
        .replace("[[SCALE_START]]", scale_start)
        .replace("[[SCALE_MID]]", scale_mid)
        .replace("[[SCALE_END]]", scale_end)
    )
    return html

# === 4. Streamlit App ================================================

st.set_page_config(page_title="Branded Map + Table Generator", layout="wide")

st.title("Branded Map + Table Generator")
st.write(
    "Upload a CSV of U.S. states and one or more metrics, choose a brand, then click "
    "**Update widget** to publish an interactive map + ranked tables page via GitHub Pages."
)

# Brand selection
brand_options = [
    "Action Network",
    "VegasInsider",
    "Canada Sports Betting",
    "RotoGrinders",
]
default_brand = st.session_state.get("map_brand", "VegasInsider")
if default_brand not in brand_options:
    default_brand = "Action Network"

brand = st.selectbox(
    "Choose a brand",
    options=brand_options,
    index=brand_options.index(default_brand),
    key="map_brand",
)

uploaded_file = st.file_uploader("Upload your CSV file", type=["csv"])

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    if df.empty:
        st.error("Uploaded CSV has no rows.")
        st.stop()

    all_columns = list(df.columns)

    # ---------- Widget text ----------
    st.markdown("### Widget text")

    default_page_title = "State Metric Map"
    default_subtitle = "Visualizing your selected metric by U.S. state."
    default_strapline = f"{brand.upper()} · DATA VISUALIZATION"

    col_copy1, col_copy2 = st.columns(2)
    with col_copy1:
        page_title = st.text_input(
            "Page title",
            value=st.session_state.get("map_page_title", default_page_title),
            key="map_page_title",
        )
    with col_copy2:
        subtitle = st.text_input(
            "Subtitle",
            value=st.session_state.get("map_subtitle", default_subtitle),
            key="map_subtitle",
        )

    col_meta1, col_meta2 = st.columns(2)
    with col_meta1:
        strapline = st.text_input(
            "Strapline (top small text)",
            value=st.session_state.get("map_strapline", default_strapline),
            key="map_strapline",
        )
    with col_meta2:
        guessed_state = next((c for c in all_columns if "state" in c.lower()), all_columns[0])
        state_col = st.selectbox(
            "State column (full U.S. state names or 2-letter codes)",
            options=all_columns,
            index=all_columns.index(guessed_state),
            key="map_state_col",
        )

    # Determine numeric columns after we know state_col
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if not numeric_cols:
        numeric_cols = [c for c in all_columns if c != state_col]

    # ---------- Map settings ----------
    st.markdown("### Map settings")

    value_col = st.selectbox(
        "Primary metric column (used to color the map)",
        options=[c for c in numeric_cols if c != state_col],
        key="map_value_col",
    )

    available_cols = [c for c in all_columns if c != state_col]

    # Hover columns (map) with "All columns" option
    hover_options = ["All columns"] + available_cols
    if "map_hover_cols" in st.session_state:
        default_hover_selection = st.session_state["map_hover_cols"]
    else:
        default_hover_selection = ["All columns"]

    raw_hover_cols = st.multiselect(
        "Columns to show in the map hover tooltip",
        options=hover_options,
        default=default_hover_selection,
        key="map_hover_cols",
        help="Select specific columns, or choose 'All columns' to include everything.",
    )

    if "All columns" in raw_hover_cols or len(raw_hover_cols) == 0:
        hover_cols = available_cols
    else:
        hover_cols = [c for c in raw_hover_cols if c in available_cols]

    col_leg1, col_leg2 = st.columns(2)
    with col_leg1:
        legend_low = st.text_input(
            "Legend left label",
            value=st.session_state.get("map_legend_low", "Lowest value"),
            key="map_legend_low",
        )
    with col_leg2:
        legend_high = st.text_input(
            "Legend right label",
            value=st.session_state.get("map_legend_high", "Highest value"),
            key="map_legend_high",
        )

    # ---------- Table settings ----------
    st.markdown("### Table settings")

    table_options = ["All columns"] + available_cols
    if "map_table_cols" in st.session_state:
        default_table_selection = st.session_state["map_table_cols"]
    else:
        default_table_selection = ["All columns"]

    raw_table_cols = st.multiselect(
        "Columns to include in the ranked tables (besides the state column)",
        options=table_options,
        default=default_table_selection,
        key="map_table_cols",
        help="Select specific columns, or choose 'All columns' to include everything in the tables.",
    )

    if "All columns" in raw_table_cols or len(raw_table_cols) == 0:
        table_cols = available_cols
    else:
        table_cols = [c for c in raw_table_cols if c in available_cols]

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        high_title = st.text_input(
            "High table title",
            value=st.session_state.get("map_high_title", "States With the Highest Values"),
            key="map_high_title",
        )
    with col_t2:
        low_title = st.text_input(
            "Low table title",
            value=st.session_state.get("map_low_title", "States With the Lowest Values"),
            key="map_low_title",
        )

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        high_sub = st.text_input(
            "High table subheading",
            value=st.session_state.get("map_high_sub", "Ranked by the selected metric."),
            key="map_high_sub",
        )
    with col_s2:
        low_sub = st.text_input(
            "Low table subheading",
            value=st.session_state.get("map_low_sub", "Ranked by the selected metric."),
            key="map_low_sub",
        )

    # ---------- GitHub / hosting settings ----------
    st.markdown("---")
    st.subheader("GitHub publishing")

    saved_gh_user = st.session_state.get("map_gh_user", "")
    saved_gh_repo = st.session_state.get("map_gh_repo", "branded-map-widget")

    username_options = ["GauthamBC", "ActionNetwork", "MoonWatcher", "SampleUser"]
    if GITHUB_USER_DEFAULT and GITHUB_USER_DEFAULT not in username_options:
        username_options.insert(0, GITHUB_USER_DEFAULT)

    if saved_gh_user in username_options:
        default_idx = username_options.index(saved_gh_user)
    else:
        default_idx = 0

    github_username_input = st.selectbox(
        "Username (GitHub username)",
        options=username_options,
        index=default_idx,
        key="map_gh_user",
    )
    effective_github_user = github_username_input.strip()

    repo_name = st.text_input(
        "Widget hosting repository name",
        value=saved_gh_repo,
        key="map_gh_repo",
    )

    base_filename = "branded_map.html"
    widget_file_name = st.session_state.get("map_widget_file_name", base_filename)

    def compute_expected_embed_url(user: str, repo: str, fname: str) -> str:
        if user and repo.strip():
            return f"https://{user}.github.io/{repo.strip()}/{fname}"
        return "https://example.github.io/your-repo/widget.html"

    expected_embed_url = compute_expected_embed_url(
        effective_github_user, repo_name, widget_file_name
    )

    st.caption(
        f"Expected GitHub Pages URL (iframe src):\n\n`{expected_embed_url}`"
    )

    st.markdown(
        "<p style='font-size:0.85rem; color:#c4c4c4;'>"
        "Use <strong>Page availability check</strong> to see whether a page already exists "
        "for this campaign, then click <strong>Update widget</strong> to publish."
        "</p>",
        unsafe_allow_html=True,
    )

    iframe_snippet = st.session_state.get("map_iframe_snippet")

    can_run_github = bool(GITHUB_TOKEN and effective_github_user and repo_name.strip())

    col_check, col_get = st.columns([1, 1])
    with col_check:
        page_check_clicked = st.button(
            "Page availability check",
            key="map_page_check",
            disabled=not can_run_github,
        )
    with col_get:
        update_clicked = st.button(
            "Update widget",
            key="map_update_widget",
            disabled=not can_run_github,
        )

    if not GITHUB_TOKEN:
        st.info(
            "Set `GITHUB_TOKEN` in `.streamlit/secrets.toml` (with `repo` scope) "
            "to enable automatic GitHub publishing."
        )
    elif not effective_github_user or not repo_name.strip():
        st.info("Fill in username and campaign name above.")

    # --- Page availability logic ---
    if page_check_clicked:
        if not can_run_github:
            st.error("Cannot run availability check – add your GitHub token, username and repo first.")
        else:
            try:
                repo_exists = check_repo_exists(
                    effective_github_user,
                    repo_name.strip(),
                    GITHUB_TOKEN,
                )
                file_exists = False
                next_fname = None
                if repo_exists:
                    file_exists = check_file_exists(
                        effective_github_user,
                        repo_name.strip(),
                        GITHUB_TOKEN,
                        base_filename,
                    )
                    if file_exists:
                        next_fname = find_next_widget_filename(
                            effective_github_user,
                            repo_name.strip(),
                            GITHUB_TOKEN,
                        )

                st.session_state["map_availability"] = {
                    "repo_exists": repo_exists,
                    "file_exists": file_exists,
                    "checked_filename": base_filename,
                    "suggested_new_filename": next_fname,
                }
                st.session_state.setdefault("map_widget_file_name", base_filename)

            except Exception as e:
                st.error(f"Availability check failed: {e}")

    # --- Update widget (publish) logic ---
    if update_clicked:
        if not can_run_github:
            st.error("Cannot update widget – add your GitHub token, username and repo first.")
        else:
            try:
                progress_placeholder = st.empty()
                progress = progress_placeholder.progress(0)
                for pct in (20, 45, 70):
                    time.sleep(0.12)
                    progress.progress(pct)

                style_mode = st.session_state.get("map_style_mode", "Branded")
                show_labels = st.session_state.get("map_show_labels", False)
                brand_meta_publish = get_brand_meta(st.session_state.get("map_brand", brand), style_mode)

                widget_file_name = st.session_state.get("map_widget_file_name", base_filename)
                expected_embed_url = compute_expected_embed_url(
                    effective_github_user, repo_name, widget_file_name
                )

                html_final = generate_map_table_html_from_df(
                    df,
                    brand_meta_publish,
                    state_col=state_col,
                    value_col=value_col,
                    page_title=page_title,
                    subtitle=subtitle,
                    strapline=strapline,
                    legend_low=legend_low,
                    legend_high=legend_high,
                    high_title=high_title,
                    high_sub=high_sub,
                    low_title=low_title,
                    low_sub=low_sub,
                    top_n=10,
                    show_state_labels=show_labels,
                    table_cols=table_cols,
                    hover_cols=hover_cols,
                )

                progress.progress(80)

                ensure_repo_exists(
                    effective_github_user,
                    repo_name.strip(),
                    GITHUB_TOKEN,
                )

                progress.progress(90)

                try:
                    ensure_pages_enabled(
                        effective_github_user,
                        repo_name.strip(),
                        GITHUB_TOKEN,
                        branch="main",
                    )
                except Exception:
                    pass

                upload_file_to_github(
                    effective_github_user,
                    repo_name.strip(),
                    GITHUB_TOKEN,
                    widget_file_name,
                    html_final,
                    f"Add/update {widget_file_name} from Branded Map app",
                    branch="main",
                )

                trigger_pages_build(
                    effective_github_user,
                    repo_name.strip(),
                    GITHUB_TOKEN,
                )

                progress.progress(100)
                time.sleep(0.15)
                progress_placeholder.empty()

                iframe_snippet = dedent(f"""\
                <iframe src="{expected_embed_url}"
                        title="{html_mod.escape(page_title)}"
                        width="100%" height="1000" scrolling="no"
                        style="border:0;" loading="lazy"></iframe>""")

                st.session_state["map_iframe_snippet"] = iframe_snippet
                st.session_state["map_has_generated"] = True

                st.success("Branded map widget updated. Open the tabs below to preview and embed it.")

            except Exception as e:
                progress_placeholder.empty()
                st.error(f"GitHub publish failed: {e}")

    # ---------- Availability result + options ----------
    availability = st.session_state.get("map_availability")
    if GITHUB_TOKEN and effective_github_user and repo_name.strip():
        if availability:
            repo_exists = availability.get("repo_exists", False)
            file_exists = availability.get("file_exists", False)
            checked_filename = availability.get("checked_filename", base_filename)
            suggested_new_filename = availability.get("suggested_new_filename") or "t1.html"

            if not repo_exists:
                st.info(
                    "No existing repo found for this campaign. "
                    "When you click **Update widget**, the repo will be created and "
                    f"your map will be saved as `{checked_filename}`."
                )
                st.session_state["map_widget_file_name"] = checked_filename
            elif repo_exists and not file_exists:
                st.success(
                    f"Repo exists and `{checked_filename}` is available. "
                    "Update widget will save your map to this file."
                )
                st.session_state["map_widget_file_name"] = checked_filename
            else:
                st.warning(
                    f"A page named `{checked_filename}` already exists in this repo."
                )
                choice = st.radio(
                    "What would you like to do?",
                    options=[
                        "Replace existing widget (overwrite file)",
                        f"Create additional widget file in same repo (use {suggested_new_filename})",
                        "Change campaign name instead",
                    ],
                    key="map_file_conflict_choice",
                )
                if choice.startswith("Replace"):
                    st.session_state["map_widget_file_name"] = checked_filename
                    st.info(f"Update widget will overwrite `{checked_filename}` in this repo.")
                elif choice.startswith("Create additional"):
                    st.session_state["map_widget_file_name"] = suggested_new_filename
                    st.info(
                        f"Update widget will create a new file `{suggested_new_filename}` "
                        "in the same repo for this widget."
                    )
                else:
                    st.info(
                        "Update the campaign name above, then run **Page availability check** again."
                    )

    st.markdown("---")

    # ---------- Preview / HTML / iframe tabs ----------
    widget_file_name = st.session_state.get("map_widget_file_name", base_filename)
    expected_embed_url = compute_expected_embed_url(
        effective_github_user, repo_name, widget_file_name
    )

    tab_config, tab_embed = st.tabs(
        [
            "Preview map page",
            "Widget HTML/Iframe",
        ]
    )

    with tab_config:
        col_style, col_labels = st.columns([3, 2])
        with col_style:
            style_mode = st.selectbox(
                "Color style",
                options=["Branded", "Unbranded"],
                index=0 if st.session_state.get("map_style_mode", "Branded") == "Branded" else 1,
                key="map_style_mode",
                help="Branded uses site-specific palettes; Unbranded uses a neutral multi-color palette.",
            )
        with col_labels:
            show_labels = st.checkbox(
                "Show state rank labels",
                value=st.session_state.get("map_show_labels", False),
                key="map_show_labels",
                help="Overlay labels like 'CA (3)' on the map (small Northeast states use callouts).",
            )

        brand_meta_preview = get_brand_meta(st.session_state.get("map_brand", brand), style_mode)
        html_preview = generate_map_table_html_from_df(
            df,
            brand_meta_preview,
            state_col=state_col,
            value_col=value_col,
            page_title=page_title,
            subtitle=subtitle,
            strapline=strapline,
            legend_low=legend_low,
            legend_high=legend_high,
            high_title=high_title,
            high_sub=high_sub,
            low_title=low_title,
            low_sub=low_sub,
            top_n=10,
            show_state_labels=show_labels,
            table_cols=table_cols,
            hover_cols=hover_cols,
        )

        components.html(html_preview, height=1000, scrolling=True)

    with tab_embed:
        style_mode = st.session_state.get("map_style_mode", "Branded")
        show_labels = st.session_state.get("map_show_labels", False)
        brand_meta_embed = get_brand_meta(st.session_state.get("map_brand", brand), style_mode)
        html_embed = generate_map_table_html_from_df(
            df,
            brand_meta_embed,
            state_col=state_col,
            value_col=value_col,
            page_title=page_title,
            subtitle=subtitle,
            strapline=strapline,
            legend_low=legend_low,
            legend_high=legend_high,
            high_title=high_title,
            high_sub=high_sub,
            low_title=low_title,
            low_sub=low_sub,
            top_n=10,
            show_state_labels=show_labels,
            table_cols=table_cols,
            hover_cols=hover_cols,
        )

        subtab_html, subtab_iframe = st.tabs(["HTML file contents", "Iframe code"])

        with subtab_html:
            st.text_area(
                label="",
                value=html_embed,
                height=350,
                label_visibility="collapsed",
            )

        with subtab_iframe:
            st.markdown("**Current iframe code:**")
            if st.session_state.get("map_iframe_snippet"):
                st.code(st.session_state["map_iframe_snippet"], language="html")
            else:
                st.info(
                    "No iframe yet – click **Update widget** above to generate it. "
                    "It will use height=700 and scrolling=\"no\"."
                )
