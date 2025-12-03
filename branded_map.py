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

def get_brand_meta(brand: str) -> dict:
    """
    Brand metadata for map + tables page.
    """
    brand_clean = (brand or "").strip() or "Action Network"

    meta = {
        "name": brand_clean,
        "brand_class": "brand-actionnetwork",
        "logo_url": "https://i.postimg.cc/x1nG117r/AN-final2-logo.png",
        "logo_alt": "Action Network logo",
        # default palette (greens)
        "accent": "#16A34A",
        "accent_soft": "#DCFCE7",
        "map_scale": ["#E5F9ED", "#4ADE80", "#166534"],
    }

    if brand_clean == "Action Network":
        meta.update({
            "brand_class": "brand-actionnetwork",
            "logo_url": "https://i.postimg.cc/x1nG117r/AN-final2-logo.png",
            "logo_alt": "Action Network logo",
            "accent": "#16A34A",
            "accent_soft": "#DCFCE7",
            "map_scale": ["#DCFCE7", "#4ADE80", "#166534"],
        })
    elif brand_clean == "VegasInsider":
        meta.update({
            "brand_class": "brand-vegasinsider",
            "logo_url": "https://i.postimg.cc/kGVJyXc1/VI-logo-final.png",
            "logo_alt": "VegasInsider logo",
            "accent": "#F2C23A",
            "accent_soft": "#FFF7DC",
            # blue → yellow → red like the burnout map
            "map_scale": ["#7CB3FF", "#F2C23A", "#E6492D"],
        })
    elif brand_clean == "Canada Sports Betting":
        meta.update({
            "brand_class": "brand-canadasb",
            "logo_url": "https://i.postimg.cc/ZKbrbPCJ/CSB-FN.png",
            "logo_alt": "Canada Sports Betting logo",
            "accent": "#DC2626",
            "accent_soft": "#FEE2E2",
            "map_scale": ["#FEE2E2", "#FB7185", "#B91C1C"],
        })
    elif brand_clean == "RotoGrinders":
        meta.update({
            "brand_class": "brand-rotogrinders",
            "logo_url": "https://i.postimg.cc/PrcJnQtK/RG-logo-Fn.png",
            "logo_alt": "RotoGrinders logo",
            "accent": "#0EA5E9",
            "accent_soft": "#E0F2FE",
            "map_scale": ["#E0F2FE", "#38BDF8", "#1D4ED8"],
        })

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

# === 2. HTML TEMPLATE: map + tables =======================

HTML_TEMPLATE_MAP_TABLE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>[[PAGE_TITLE]]</title>
</head>
<body style="margin:0;background:#F3F4F6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0F172A;">

<section class="vi-map-card [[BRAND_CLASS]]" style="max-width:960px;margin:16px auto;padding:16px;">

<style>
.vi-map-card, .vi-map-card * { box-sizing:border-box; font-family:inherit; }

.vi-map-card{
  --accent:[[ACCENT]];
  --accent-soft:[[ACCENT_SOFT]];
}

/* Card container */
.vi-map-shell{
  background:#FFFFFF;
  border-radius:18px;
  box-shadow:0 8px 24px rgba(15,23,42,.12);
  border:1px solid rgba(148,163,184,.25);
  padding:18px 18px 20px;
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
  background:linear-gradient(90deg,#60A5FA,#F97316,#DC2626);
  overflow:hidden;
}
.vi-map-card.brand-actionnetwork .vi-map-legend-bar{
  background:linear-gradient(90deg,#BBF7D0,#4ADE80,#166534);
}
.vi-map-card.brand-vegasinsider .vi-map-legend-bar{
  background:linear-gradient(90deg,#93C5FD,#F2C23A,#E6492D);
}
.vi-map-card.brand-canadasb .vi-map-legend-bar{
  background:linear-gradient(90deg,#FECACA,#FB7185,#B91C1C);
}
.vi-map-card.brand-rotogrinders .vi-map-legend-bar{
  background:linear-gradient(90deg,#BFDBFE,#38BDF8,#1D4ED8);
}

/* Map frame */
.vi-map-frame{
  margin-top:14px;
  border-radius:16px;
  background:#F9FAFB;
  border:1px solid #E5E7EB;
  overflow:hidden;
}

/* Table titles */
.vi-map-section-title{
  margin:20px 0 4px;
  font-size:15px;
  font-weight:700;
  color:#0F172A;
}
.vi-map-section-sub{
  margin:0 0 10px;
  font-size:12px;
  color:#6B7280;
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
  color:#9CA3AF;
  border-bottom:1px solid #E5E7EB;
}
.vi-map-table tbody tr:nth-child(odd){
  background:#FFFFFF;
}
.vi-map-table tbody tr:nth-child(even){
  background:#F9FAFB;
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
  background:var(--accent-soft);
  color:#111827;
}

/* Brand recolor for logo if you add it later (optional) */
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

  <!-- Highest odds table -->
  <section class="vi-map-tables">
    <h2 class="vi-map-section-title">[[HIGH_TITLE]]</h2>
    <p class="vi-map-section-sub">[[HIGH_SUB]]</p>
    [[TABLE_HIGH_HTML]]

    <h2 class="vi-map-section-title" style="margin-top:22px;">[[LOW_TITLE]]</h2>
    <p class="vi-map-section-sub">[[LOW_SUB]]</p>
    [[TABLE_LOW_HTML]]
  </section>

</div>

</section>
</body>
</html>
"""

# === 3. HTML generators ===============================================

def build_ranked_table_html(df: pd.DataFrame, value_col: str, top_n: int = 10) -> str:
    """
    Returns a HTML table string (no <section> wrapper).
    Columns: Rank, State, metric + any extra numeric cols.
    """
    cols = list(df.columns)
    state_col = cols[0]  # assume first col is state
    other_cols = [c for c in cols if c not in (state_col,)]
    # keep primary metric first
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
) -> str:
    # Prepare dataframe
    df = df.copy()
    df[state_col] = df[state_col].astype(str).str.strip()

    # Robust state normalization: works with full names OR 2-letter codes
    s = df[state_col].astype(str).str.strip()
    # if length 2 -> treat as code, uppercase; else treat as name, title case
    name_mask = s.str.len() > 2
    code_mask = ~name_mask
    s_norm = s.copy()
    s_norm.loc[name_mask] = s_norm.loc[name_mask].str.title()
    s_norm.loc[code_mask] = s_norm.loc[code_mask].str.upper()
    df["state_abbr"] = s_norm.map(STATE_LOOKUP)

    # Coerce metric to numeric (handles strings like "6.51" or "6.51%")
    df[value_col] = (
        df[value_col]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
    )
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

    # Drop rows without a valid state or metric
    df = df[~df["state_abbr"].isna()].copy()
    df = df[~df[value_col].isna()].copy()

    if df.empty:
        # If everything got filtered out, just return a simple message
        return "<p style='padding:16px;font-family:sans-serif;'>No valid state/metric data to display.</p>"

    # Build map (all valid rows get colored)
    hover_cols = [c for c in df.columns if c not in ("state_abbr",)]
    fig = px.choropleth(
        df,
        locations="state_abbr",
        locationmode="USA-states",
        scope="usa",
        color=value_col,
        color_continuous_scale=brand_meta["map_scale"],
        hover_data=hover_cols,
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        geo=dict(
            bgcolor="rgba(0,0,0,0)",
            lakecolor="rgba(0,0,0,0)",
            showlakes=False,
            showland=True,
            landcolor="#F3F4F6",
        ),
        coloraxis_showscale=False,
    )
    map_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )

    # Ranked tables
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    df_for_tables = pd.DataFrame({
        state_col: df[state_col],
        **{c: df[c] for c in numeric_cols},
    })

    df_high = df_for_tables.sort_values(by=value_col, ascending=False)
    df_low = df_for_tables.sort_values(by=value_col, ascending=True)  # <-- fixed

    high_table_html = build_ranked_table_html(df_high, value_col=value_col, top_n=top_n)
    low_table_html = build_ranked_table_html(df_low, value_col=value_col, top_n=top_n)

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
        .replace("[[BRAND_CLASS]]", brand_meta["brand_class"])
        .replace("[[ACCENT]]", brand_meta["accent"])
        .replace("[[ACCENT_SOFT]]", brand_meta["accent_soft"])
    )
    return html

# === 4. Streamlit App ================================================

st.set_page_config(page_title="Branded Map + Table Generator", layout="wide")

st.title("Branded Map + Table Generator")
st.write(
    "Upload a CSV of U.S. states and a metric, choose a brand, then click "
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

    # ---------- Column selection ----------
    st.subheader("Data configuration")

    state_col = st.selectbox(
        "State column (full U.S. state names or 2-letter codes)",
        options=list(df.columns),
        key="map_state_col",
    )

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if not numeric_cols:
        numeric_cols = [c for c in df.columns if c != state_col]

    value_col = st.selectbox(
        "Primary metric column (used to color the map)",
        options=[c for c in numeric_cols if c != state_col],
        key="map_value_col",
    )

    default_page_title = "Winter Burnout Odds Index 2025"
    default_subtitle = "Burnout probability by U.S. state."
    default_strapline = f"{brand.upper()} · DATA-DRIVEN ODDS"

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

    strapline = st.text_input(
        "Strapline (top small text)",
        value=st.session_state.get("map_strapline", default_strapline),
        key="map_strapline",
    )

    col_leg1, col_leg2 = st.columns(2)
    with col_leg1:
        legend_low = st.text_input(
            "Legend left label",
            value=st.session_state.get("map_legend_low", "Lowest burnout odds"),
            key="map_legend_low",
        )
    with col_leg2:
        legend_high = st.text_input(
            "Legend right label",
            value=st.session_state.get("map_legend_high", "Highest burnout odds"),
            key="map_legend_high",
        )

    # Table copy
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        high_title = st.text_input(
            "High table title",
            value=st.session_state.get("map_high_title", "States With the Highest Winter Burnout Odds"),
            key="map_high_title",
        )
    with col_t2:
        low_title = st.text_input(
            "Low table title",
            value=st.session_state.get("map_low_title", "States With the Lowest Winter Burnout Odds"),
            key="map_low_title",
        )

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        high_sub = st.text_input(
            "High table subheading",
            value=st.session_state.get("map_high_sub", "Ranked by modeled burnout probability."),
            key="map_high_sub",
        )
    with col_s2:
        low_sub = st.text_input(
            "Low table subheading",
            value=st.session_state.get("map_low_sub", "Ranked by modeled burnout probability."),
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

                brand_meta_publish = get_brand_meta(st.session_state.get("map_brand", brand))

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
                        width="100%" height="700" scrolling="no"
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
    has_generated = st.session_state.get("map_has_generated", False)
    show_tabs = has_generated or not GITHUB_TOKEN

    widget_file_name = st.session_state.get("map_widget_file_name", base_filename)
    expected_embed_url = compute_expected_embed_url(
        effective_github_user, repo_name, widget_file_name
    )

    # Live preview HTML (even before publishing)
    brand_meta_preview = get_brand_meta(st.session_state.get("map_brand", brand))
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
    )

    tab_config, tab_embed = st.tabs(
        [
            "Preview map page",
            "Widget HTML/Iframe",
        ]
    )

    with tab_config:
        components.html(html_preview, height=700, scrolling=True)

    with tab_embed:
        subtab_html, subtab_iframe = st.tabs(["HTML file contents", "Iframe code"])

        with subtab_html:
            st.text_area(
                label="",
                value=html_preview,
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
