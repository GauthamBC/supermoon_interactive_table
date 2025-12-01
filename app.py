import base64
import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ==============
# 0. Secrets
# ==============

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
        "description": "Supermoon visibility widget (auto-created by Streamlit app).",
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
    r2 = requests.post(f"{api_base}/repos/{owner}/{repo}/pages", headers=headers, json=payload)
    if r2.status_code not in (201, 202):
        raise RuntimeError(f"Error enabling GitHub Pages: {r2.status_code} {r2.text}")

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

# === 1. State -> flag URL mapping =====================================
STATE_FLAG_URLS = {
    "Alabama": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Alabama.svg",
    "Alaska": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Alaska.svg",
    "Arizona": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Arizona.svg",
    "Arkansas": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Arkansas.svg",
    "California": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_California.svg",
    "Colorado": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Colorado.svg",
    "Connecticut": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Connecticut.svg",
    "Delaware": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Delaware.svg",
    "Florida": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Florida.svg",
    "Georgia": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Georgia_(U.S._state).svg",
    "Hawaii": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Hawaii.svg",
    "Idaho": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Idaho.svg",
    "Illinois": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Illinois.svg",
    "Indiana": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Indiana.svg",
    "Iowa": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Iowa.svg",
    "Kansas": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Kansas.svg",
    "Kentucky": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Kentucky.svg",
    "Louisiana": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Louisiana.svg",
    "Maine": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Maine.svg",
    "Maryland": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Maryland.svg",
    "Massachusetts": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Massachusetts.svg",
    "Michigan": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Michigan.svg",
    "Minnesota": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Minnesota.svg",
    "Mississippi": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Mississippi.svg",
    "Missouri": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Missouri.svg",
    "Montana": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Montana.svg",
    "Nebraska": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Nebraska.svg",
    "Nevada": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Nevada.svg",
    "New Hampshire": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_New_Hampshire.svg",
    "New Jersey": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_New_Jersey.svg",
    "New Mexico": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_New_Mexico.svg",
    "New York": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_New_York.svg",
    "North Carolina": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_North_Carolina.svg",
    "North Dakota": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_North_Dakota.svg",
    "Ohio": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Ohio.svg",
    "Oklahoma": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Oklahoma.svg",
    "Oregon": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Oregon.svg",
    "Pennsylvania": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Pennsylvania.svg",
    "Rhode Island": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Rhode_Island.svg",
    "South Carolina": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_South_Carolina.svg",
    "South Dakota": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_South_Dakota.svg",
    "Tennessee": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Tennessee.svg",
    "Texas": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Texas.svg",
    "Utah": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Utah.svg",
    "Vermont": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Vermont.svg",
    "Virginia": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Virginia.svg",
    "Washington": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Washington.svg",
    "West Virginia": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_West_Virginia.svg",
    "Wisconsin": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Wisconsin.svg",
    "Wyoming": "https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Wyoming.svg",
}

# === 2. HTML template =================================================
HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>[[TITLE]]</title>
</head>

<body style="margin:0;">

<section class="vi-compact-embed" role="region" aria-labelledby="vi-compact-embed-title"
  style="max-width:860px;margin:16px auto;font:14px/1.35 Inter,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         color:#181a1f;background:#ffffff;border:1px solid #DCEFE6;border-radius:12px;
         box-shadow:0 1px 2px rgba(0,0,0,.04),0 6px 16px rgba(86,194,87,.10);">
  <style>
    /* === SCOPING PATCH ============================================== */
    section.vi-compact-embed, section.vi-compact-embed * {
      box-sizing: border-box;
      font-family: inherit;
      color: inherit;
    }
    section.vi-compact-embed { color-scheme: light; }
    /* ================================================================= */

    .vi-compact-embed *{box-sizing:border-box}
    .vi-compact-embed{color-scheme:light}
    .vi-compact-embed{
      --brand-50:#F6FFF9; --brand-100:#DCF2EB; --brand-300:#BCE5D6;
      --brand-500:#56C257; --brand-600:#3FA94B; --brand-700:#2E8538; --brand-900:#1F5D28;
      --ink:#181a1f; --muted:#666b73; --border:#DCEFE6; --viz-h:88px;
      --hover-tint: rgba(86,194,87,.12); --hover-ring:#BCE5D6; --hover-shadow:0 10px 24px rgba(86,194,87,.18);
    }

    /* Header */
    .vi-compact-embed .head{
      padding:14px 16px;border-bottom:1px solid var(--border)!important;color:#fff!important;
      background:
        radial-gradient(120% 140% at 85% 10%, rgba(255,255,255,.10) 0%, transparent 60%),
        linear-gradient(90deg,var(--brand-900) 0%,var(--brand-600) 45%,var(--brand-500) 100%)!important;
    }
    .vi-compact-embed .title{margin:0 0 2px;font-size:clamp(16px,2.2vw,20px);line-height:1.2;font-weight:800;color:#fff!important}
    .vi-compact-embed .sub{margin:0;color:rgba(255,255,255,.92)!important;font-size:12px}
    .vi-compact-embed .meta{margin:4px 0 0;color:rgba(255,255,255,.85)!important;font-size:12px}

    /* Rows */
    .vi-compact-embed .table{padding:10px 12px}
    .vi-compact-embed .row{
      display:grid;grid-template-columns:36px 1fr minmax(240px,48%);gap:8px;align-items:center;margin:6px 0;
      border:1px solid var(--border)!important;border-radius:12px;padding:8px 10px;background:#fff!important;
      transition:transform .18s cubic-bezier(.2,.8,.2,1),box-shadow .18s ease,background-color .15s ease,border-color .15s ease;
      transform-origin:center;
    }
    .vi-compact-embed .row:hover,.vi-compact-embed .row:focus-within{
      background:linear-gradient(0deg,var(--hover-tint),var(--hover-tint)),#fff!important;
      transform:scale(1.01);box-shadow:var(--hover-shadow);border-color:var(--hover-ring)!important;
    }
    @media (prefers-reduced-motion:reduce){
      .vi-compact-embed .row{transition:none}
      .vi-compact-embed .row:hover,.vi-compact-embed .row:focus-within{transform:none;box-shadow:none}
    }
    @media (max-width:640px){
      .vi-compact-embed .row{grid-template-columns:30px 1fr}
      .vi-compact-embed .metric{grid-column:1 / -1}
    }

    .vi-compact-embed .rank{display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--muted)}
    .vi-compact-embed .state{display:flex;align-items:center;gap:8px;font-weight:700;color:var(--ink)}
    .vi-compact-embed .chip{width:18px;height:18px;border-radius:50%;overflow:hidden;border:1px solid #cfe4da;background:#fff;flex-shrink:0}
    .vi-compact-embed .chip img{width:100%;height:100%;object-fit:cover}

    .vi-compact-embed .metric{position:relative;height:28px;border-radius:999px;background:rgba(86,194,87,.10)!important;overflow:hidden}
    .vi-compact-embed .bar{position:absolute;inset:0 auto 0 0;border-radius:999px;background:linear-gradient(90deg,var(--brand-600),var(--brand-500))!important;box-shadow:inset 0 0 0 1px rgba(0,0,0,.04)}
    .vi-compact-embed .val{position:absolute;right:6px;top:50%;transform:translateY(-50%);font-variant-numeric:tabular-nums;font-weight:800;font-size:13px;color:#0e1a12!important;background:#fff!important;border:2px solid #e6e9ed!important;border-radius:999px;padding:2px 8px}

    /* Gradient bars by rank */
    .vi-compact-embed .row[data-rank="1"]  .bar{background:linear-gradient(90deg,#1F5D28,#56C257)!important}
    .vi-compact-embed .row[data-rank="2"]  .bar{background:linear-gradient(90deg,#2A7331,#5DC65F)!important}
    .vi-compact-embed .row[data-rank="3"]  .bar{background:linear-gradient(90deg,#2E8538,#63CA67)!important}
    .vi-compact-embed .row[data-rank="4"]  .bar{background:linear-gradient(90deg,#379744,#6ACE70)!important}
    .vi-compact-embed .row[data-rank="5"]  .bar{background:linear-gradient(90deg,#3FA94B,#71D279)!important}
    .vi-compact-embed .row[data-rank="6"]  .bar{background:linear-gradient(90deg,#52B760,#7AD783)!important}
    .vi-compact-embed .row[data-rank="7"]  .bar{background:linear-gradient(90deg,#64C274,#84DB8E)!important}
    .vi-compact-embed .row[data-rank="8"]  .bar{background:linear-gradient(90deg,#76CC88,#8FE099)!important}
    .vi-compact-embed .row[data-rank="9"]  .bar{background:linear-gradient(90deg,#8AD79D,#9AE5A5)!important}
    .vi-compact-embed .row[data-rank="10"] .bar{background:linear-gradient(90deg,#9FE1B3,#A7E6BA)!important}

    /* Details panel */
    .vi-compact-embed .details{
      margin:0;padding:0;border:1px solid var(--border);border-width:0;border-radius:12px;background:var(--brand-50);
      max-height:0;opacity:0;overflow:hidden;transform:translateY(-6px);
      transition:max-height .28s ease,opacity .28s ease,transform .28s ease,padding .20s ease,margin .20s ease,border-width .20s ease;
    }
    .vi-compact-embed .details.open{margin:8px 0 12px;padding:12px;border-width:1px;max-height:420px;opacity:1;transform:translateY(0)}
    .vi-compact-embed .metrics-title{margin:0 0 10px;font-weight:800;font-size:14px;color:var(--brand-900)}
    .vi-compact-embed .metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
    @media (max-width:640px){.vi-compact-embed .metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}

    /* Cards */
    .vi-compact-embed .metric-card{
      background:#fff;border:1px solid var(--border);border-radius:10px;padding:16px 12px 12px;
      display:grid;grid-template-rows:auto auto var(--viz-h) auto;gap:8px;align-content:start;
    }
    .vi-compact-embed .metric-label{font-size:12px;color:var(--muted);font-weight:700;margin:0;line-height:1.2}
    .vi-compact-embed .metric-number{font-weight:800;font-size:20px;color:#0e1a1f;margin:0;line-height:1.1;font-variant-numeric:tabular-nums}
    .vi-compact-embed .metric-scale{font-size:11px;color:#8a9099;margin:0}

    /* Sparkline (elevation) */
    .vi-compact-embed .spark{align-self:center}
    .vi-compact-embed .spark svg{width:100%;height:var(--viz-h)}
    .vi-compact-embed .spark-base{stroke:#e6f1ec;stroke-width:3;fill:none}
    .vi-compact-embed .spark-line{stroke:url(#az-elev-grad);stroke-width:4;fill:none;stroke-linecap:round;transition:stroke-dashoffset .6s ease}
    .vi-compact-embed .spark-dot{fill:var(--brand-500);stroke:#fff;stroke-width:2}
    .vi-compact-embed .donut > div{display:contents}
    .vi-compact-embed .donut circle.bg{stroke:#e6f4ee;stroke-width:10;fill:none}
    .vi-compact-embed .donut circle.fg{stroke:var(--brand-600);stroke-width:10;fill:none;stroke-linecap:round;transform:rotate(-90deg);transform-origin:50% 50%;transition:stroke-dashoffset .7s ease}

    /* Mini bars (clear days & humidity) */
    .vi-compact-embed .mini-bar{height:10px;border-radius:999px;background:rgba(86,194,87,.16);overflow:hidden;align-self:center}
    .vi-compact-embed .mini-bar .fill{display:block;height:100%;width:0%;border-radius:999px;background:linear-gradient(90deg,var(--brand-600),var(--brand-500));transition:width .6s ease}

    /* Clickable hint */
    .vi-compact-embed .row.is-clickable{cursor:pointer;position:relative}
    .vi-compact-embed .row.is-clickable .metric{padding-right:128px}
    .vi-compact-embed .row.is-clickable::after{
      content:"Click for viewing factors";position:absolute;right:12px;top:50%;transform:translateY(-50%);
      font-size:11px;color:#7cae85;white-space:nowrap;pointer-events:none;z-index:1;
    }
    .vi-compact-embed .metric .val{z-index:2}
    @media (max-width:640px){.vi-compact-embed .row.is-clickable::after{display:none}}
    .vi-compact-embed .row[aria-expanded="true"]::after{display:none}

    .vi-compact-embed .details-close{margin-top:10px;align-self:flex-end;background:#fff;border:1px solid var(--border);border-radius:999px;padding:6px 10px;font-weight:700;cursor:pointer}
    .vi-compact-embed .details-close:hover{border-color:var(--hover-ring)}

    /* Compact defaults / shared heights */
    .vi-compact-embed{ --viz-h:56px; --card-h:176px }
    .vi-compact-embed .metrics-grid{ grid-auto-rows:var(--card-h); gap:10px }
    .vi-compact-embed .metric-card{ height:100%; padding:12px 12px 10px; gap:6px; grid-template-rows:auto auto var(--viz-h) auto }
    .vi-compact-embed .metric-number{ font-size:19px }
    .vi-compact-embed .spark svg{ height:var(--viz-h) }
    .vi-compact-embed .donut{ row-gap:6px }
    .vi-compact-embed .donut svg{ width:var(--viz-h); height:var(--viz-h) }
    .vi-compact-embed .donut circle.bg,.vi-compact-embed .donut circle.fg{ stroke-width:8 }
    .vi-compact-embed .mini-bar{ height:8px }
    .vi-compact-embed .details.open{ padding:8px }

    /* Big ring */
    .vi-compact-embed{ --donut-h:104px; --card-h:196px }
    .vi-compact-embed .metric-card:has(.donut){ grid-template-rows:auto auto var(--donut-h) auto }
    .vi-compact-embed .donut,.vi-compact-embed .donut > div{ display:contents }
    .vi-compact-embed .donut svg{
      grid-row:3; width:var(--donut-h); height:var(--donut-h);
      justify-self:center !important; margin-inline:auto; display:block;
    }
    .vi-compact-embed .donut .metric-number{ grid-row:2 }
    .vi-compact-embed .donut .metric-scale{ grid-row:4 }

    /* Calendar viz */
    .vi-compact-embed{ --cal-h:80px }
    .vi-compact-embed .metric-card:has(.calendar){ grid-template-rows:auto auto var(--cal-h) auto }
    .vi-compact-embed .calendar{
      height:var(--cal-h); display:grid; grid-template-columns:repeat(6,1fr);
      grid-auto-rows:1fr; gap:6px; align-self:center;
    }
    .vi-compact-embed .calendar .day{ border-radius:6px; background:#eaf5ee; position:relative; overflow:hidden }
    .vi-compact-embed .calendar .day.filled{ background:linear-gradient(180deg,var(--brand-600),var(--brand-500)) }
    .vi-compact-embed .calendar .day.partial::after{
      content:""; position:absolute; inset:0; width:calc(var(--part,0)*100%);
      background:linear-gradient(90deg,var(--brand-600),var(--brand-500));
    }

    /* Shared viz row height */
    .vi-compact-embed{ --viz-row-h:104px }
    .vi-compact-embed .metric-card{ grid-template-rows:auto auto var(--viz-row-h) auto !important }
    .vi-compact-embed .metric-card:has(.donut), .vi-compact-embed .metric-card:has(.calendar){
      grid-template-rows:auto auto var(--viz-row-h) auto !important;
    }
    .vi-compact-embed .spark, .vi-compact-embed .calendar, .vi-compact-embed .mini-bar{ align-self:center !important }
    .vi-compact-embed .spark svg{ height:min(var(--viz-h,56px), calc(var(--viz-row-h) - 2px)) }
    .vi-compact-embed .calendar{ height:var(--viz-row-h) }

    /* Desktop layout */
    @media (min-width:641px){
      .vi-compact-embed .metrics-grid{ grid-template-columns: repeat(4, minmax(0,1fr)) !important; }
      .vi-compact-embed .row{ grid-template-columns: 36px 1fr minmax(240px,48%) !important; }
      .vi-compact-embed .metric{ grid-column: auto !important; }
    }
    @media (max-width:640px){
      .vi-compact-embed .metrics-grid{ grid-template-columns: repeat(2, minmax(0,1fr)) !important; }
      .vi-compact-embed{ --card-h:188px; --viz-row-h:92px; --donut-h:92px }
      .vi-compact-embed .calendar{ gap:5px }
      .vi-compact-embed .metric-number{ font-size:18px }
    }
    @media (max-width:360px){
      .vi-compact-embed .metrics-grid{ grid-template-columns: 1fr !important }
    }

    /* Desktop internal scroll */
    .vi-compact-embed{ --pane-max-h: min(72vh, 680px); }
    .vi-compact-embed .table{
      max-height: var(--pane-max-h); overflow:auto; -webkit-overflow-scrolling:touch;
      overscroll-behavior:contain; scrollbar-gutter:stable both-edges;
    }
    .vi-compact-embed .table::-webkit-scrollbar{ width:10px; height:8px }
    .vi-compact-embed .table::-webkit-scrollbar-track{ background:var(--brand-50); border-radius:999px }
    .vi-compact-embed .table::-webkit-scrollbar-thumb{
      background:linear-gradient(180deg,var(--brand-600),var(--brand-500)); border-radius:999px; border:2px solid #fff;
    }
    .vi-compact-embed .table::-webkit-scrollbar-thumb:hover{ background:linear-gradient(180deg,var(--brand-700),var(--brand-600)) }
    .vi-compact-embed .table{ scrollbar-width:thin; scrollbar-color:var(--brand-600) var(--brand-50) }

    /* Darkness gauge (styles only) */
    .vi-compact-embed .gauge-svg{ width:100%; height:var(--viz-row-h) }
    .vi-compact-embed .gauge-track{ stroke:#e6f4ee; stroke-width:10; fill:none; stroke-linecap:round }
    .vi-compact-embed .gauge-value{ stroke:url(#az-gauge-grad); stroke-width:10; fill:none; stroke-linecap:round; transition:stroke-dashoffset .7s ease }
    .vi-compact-embed .gauge-needle{ transform-origin:70px 70px; transition:transform .6s cubic-bezier(.2,.8,.2,1) }
    .vi-compact-embed .gauge-needle line{ stroke:#2E8538; stroke-width:3; stroke-linecap:round }
    .vi-compact-embed .gauge-needle circle{ fill:#fff; stroke:#cfe4da }

    /* Humidity droplet */
    .vi-compact-embed .donut .drop{
      fill: var(--brand-600);
      stroke: #ffffff;
      stroke-width: 2;
      paint-order: stroke;
      filter: drop-shadow(0 1px 0 rgba(0,0,0,.03));
      transform-box: fill-box;
      transform-origin: 50% 50%;
      transform: scale(.7);
      vector-effect: non-scaling-stroke;
    }

    /* Footer + embed button */
    .vi-compact-embed .vi-footer {
      display: block !important;
      text-align: center;
      padding: 6px 0;
      border-top: 1px solid var(--border);
      background:
        radial-gradient(120% 140% at 85% 10%, rgba(255,255,255,.10) 0%, transparent 60%),
        linear-gradient(90deg,var(--brand-900) 0%,var(--brand-600) 45%,var(--brand-500) 100%)!important;
      color: #fff;
      position: relative;
      overflow: visible; /* allow popup to show above on mobile */
    }
    .vi-compact-embed .footer-inner {
      display: flex; justify-content: center; align-items: center; gap: 12px; position: relative;
    }
    .vi-compact-embed .embed-btn {
      position: absolute; left: 14px; background: #56C257; color: #fff; border: 1px solid #56C257;
      border-radius: 8px; padding: 6px 14px; font: 13px/1.2 system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif; cursor: pointer; transition: .2s ease;
    }
    .vi-compact-embed .embed-btn:hover { background:#3FA94B; border-color:#3FA94B; }
    .vi-compact-embed .vi-footer img {
      height: 52px; width: auto; display: inline-block; filter: brightness(0) invert(1);
    }

    .vi-compact-embed .embed-wrapper{
      position: absolute;
      bottom: calc(100% + 10px);
      left: 50%;
      transform: translateX(-50%);
      width: min(600px, calc(100% - 24px));
      display: none;
      padding: 16px 20px;
      border: 1px solid #ccc;
      border-radius: 12px;
      background: #fff;
      color: #111;
      box-shadow: 0 12px 28px rgba(0,0,0,.18);
      z-index: 1000;
    }
    .vi-compact-embed .embed-wrapper::after{
      content:""; position:absolute; left:50%; transform:translateX(-50%); bottom:-8px;
      border:8px solid transparent; border-top-color:#fff; filter: drop-shadow(0 1px 1px rgba(0,0,0,.08));
    }
    .vi-compact-embed #copy-status { display:none; color:#008000; font-size:13px; margin-top:6px; }
    .vi-compact-embed .embed-wrapper textarea{
      width:100%; height:140px; font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
      color:#111; background:#fff; padding:10px 12px; border:1px solid #ddd; border-radius:8px; resize:none;
    }
    .vi-compact-embed .row.is-clickable::after{ display:none !important; } /* hide hint if it clips */

    /* ===================== MOBILE OVERRIDES (single block) ===================== */
    @media (max-width:640px){
      html, body { height:auto !important; overflow:auto !important; }
      /* Let the page behave normally; mirror desktop: .table scrolls, footer not sticky */
      .vi-compact-embed{
        display:block;
        min-height:auto;
        overflow:visible;
      }

      /* Keep .table as the scroll container (like desktop), a touch shorter for phones */
      .vi-compact-embed { --pane-max-h: min(70vh, 560px); }
      .vi-compact-embed .table{
        max-height: var(--pane-max-h) !important;
        overflow:auto !important;
        -webkit-overflow-scrolling:touch !important;
        padding-bottom:0 !important;
        margin-bottom:0 !important;
      }

      /* Make footer content not overlap: button smaller and in-flow */
      .vi-compact-embed .footer-inner{
        justify-content:space-between !important;
        padding:0 10px;
        gap:8px;
      }
      .vi-compact-embed .embed-btn{
        position:static !important;
        padding:6px 10px;
        font-size:12px;
        line-height:1.2;
        flex-shrink:0;
      }
      .vi-compact-embed .vi-footer img{
        height:44px;
      }

      /* Footer behaves like desktop (not sticky) */
      .vi-compact-embed .vi-footer{
        position: static !important;
        bottom: auto !important;
        z-index: auto !important;
        padding: 8px 0;
        border-top:1px solid var(--border);
        background:
          radial-gradient(120% 140% at 85% 10%, rgba(255,255,255,.10) 0%, transparent 60%),
          linear-gradient(90deg,var(--brand-900) 0%,var(--brand-600) 45%,var(--brand-500) 100%)!important;
        overflow:visible !important; /* ensure popup is visible */
      }

      /* Keep the embed popup positioned like desktop (relative to footer) */
      .vi-compact-embed .embed-wrapper{
        position: absolute !important;
        bottom: calc(100% + 10px) !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        width: min(600px, calc(100% - 24px)) !important;
        max-height:65vh;
        overflow:auto;
        z-index:1000;
      }

      /* Details panel UX (keep) */
      .vi-compact-embed .details.open{ max-height:none !important; }
      .vi-compact-embed .details{ display:flex; flex-direction:column; scroll-margin-top:8px; }
      .vi-compact-embed .details-close{
        order:-1; align-self:flex-end; position:sticky; top:8px; z-index:5;
        padding:8px 12px; border-radius:999px; background:#fff; box-shadow:0 2px 6px rgba(0,0,0,.08);
      }

      /* If the host iframe cannot resize, add .is-embedded on the <section> */
      section.vi-compact-embed.is-embedded{
        max-height:100dvh;
        overflow:auto !important;
        -webkit-overflow-scrolling:touch;
      }
      section.vi-compact-embed.is-embedded .table{
        overflow:visible !important;
        max-height:none !important;
      }
    }
    /* =================== END MOBILE OVERRIDES (desktop untouched) ============== */
  </style>

  <div class="head">
    <h3 id="vi-compact-embed-title" class="title">[[TITLE]]</h3>
    <p class="sub"><em>[[SUBTITLE]]</em></p>
    <p class="meta">Click <strong>a state</strong> to see viewing factors.</p>
  </div>

  <div class="table">
    [[ROWS]]

    <!-- Shared details panel -->
    <div id="az-details" class="details" aria-hidden="true" role="region" aria-labelledby="az-metrics-title">
      <h4 id="az-metrics-title" class="metrics-title">Supermoon Viewing Factors</h4>
      <div class="metrics-grid">
        <!-- Elevation -->
        <div class="metric-card">
          <div class="metric-label">Avg. Elevation</div>
          <div class="metric-number"><span id="az-elev-val">0 ft</span></div>
          <div class="spark" aria-hidden="true">
            <svg id="az-elev-spark" viewBox="0 0 160 60" preserveAspectRatio="none">
              <defs>
                <linearGradient id="az-elev-grad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stop-color="#2E8538"></stop>
                  <stop offset="100%" stop-color="#56C257"></stop>
                </linearGradient>
              </defs>
              <path class="spark-base" d="M0,58 L160,58"></path>
              <path id="az-elev-line" class="spark-line" d="M0,58 L160,58"></path>
              <circle id="az-elev-dot" class="spark-dot" cx="160" cy="58" r="4"></circle>
            </svg>
          </div>
          <div class="metric-scale">Above sea level</div>
        </div>

        <!-- Darkness gauge -->
        <div class="metric-card">
          <div class="metric-label">Darkness Score (1–5)</div>
          <div class="metric-number"><span id="az-dark-val">0.00 / 5</span></div>
          <div class="gauge" aria-hidden="true">
            <svg class="gauge-svg" viewBox="0 0 140 80" preserveAspectRatio="xMidYMid meet">
              <defs>
                <linearGradient id="az-gauge-grad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%"  stop-color="#3FA94B"/>
                  <stop offset="100%" stop-color="#56C257"/>
                </linearGradient>
              </defs>
              <path id="az-dark-track" class="gauge-track" d="M10,70 A60,60 0 0 1 130,70"></path>
              <path id="az-dark-value" class="gauge-value" d="M10,70 A60,60 0 0 1 130,70"></path>
              <g id="az-dark-needle-group" class="gauge-needle">
                <line x1="70" y1="70" x2="70" y2="22"></line>
                <circle cx="70" cy="70" r="4"></circle>
              </g>
            </svg>
          </div>
          <div class="metric-scale">0 • 5</div>
        </div>

        <!-- Clear days -->
        <div class="metric-card">
          <div class="metric-label">Avg. Clear-Sky Days (Dec)</div>
          <div class="metric-number"><span id="az-clear-val">0.0 days</span></div>
          <div id="az-clear-cal" class="calendar" aria-hidden="true"></div>
          <div class="metric-scale">0 • 31</div>
        </div>

        <!-- Humidity donut -->
        <div class="metric-card">
          <div class="metric-label">Avg. December Humidity</div>
          <div class="donut">
            <svg viewBox="0 0 72 72" aria-hidden="true">
              <circle class="bg" cx="36" cy="36" r="26"></circle>
              <circle id="az-humid-arc" class="fg" cx="36" cy="36" r="26" stroke-dasharray="0" stroke-dashoffset="0"></circle>
              <path id="az-humid-drop" class="drop"
                    d="M36 18
                       C 30 26, 26 32, 26 37
                       C 26 45, 31.5 50, 36 50
                       C 40.5 50, 46 45, 46 37
                       C 46 32, 42 26, 36 18 Z"/>
            </svg>
            <div>
              <div class="metric-number"><span id="az-humid-val">0%</span></div>
              <div class="metric-scale">0% • 100%</div>
            </div>
          </div>
        </div>
      </div>
      <button id="az-close" class="details-close" type="button" aria-label="Close viewing factors">Close ✕</button>
    </div>
  </div>

  <div class="vi-footer">
    <div class="footer-inner">
      <button id="copy-embed-btn" class="embed-btn" aria-controls="embed-wrapper" aria-expanded="false">🔗 Embed This Table</button>
      <img src="https://i.postimg.cc/x1nG117r/AN-final2-logo.png"
           alt="The Action Network logo"
           width="120" height="auto" loading="lazy" decoding="async" />
    </div>

    <div id="embed-wrapper" class="embed-wrapper">
      <textarea id="embed-code" readonly>&lt;iframe src="[[EMBED_URL]]"
      title="[[TITLE]]"
      width="100%" height="1140"
      scrolling="no"
      style="border:0;" loading="lazy"&gt;&lt;/iframe&gt;
      </textarea>
      <p id="copy-status">Embed code copied!</p>
    </div>
  </div>

  <script>
    (function(){
      /* --- dataset for all rows (December metrics) --- */
      const DATA = [[DATA]];
      const DARK_MAX = 5;

      const rows   = document.querySelectorAll('.vi-compact-embed .row.is-clickable[data-state]');
      const panel  = document.getElementById('az-details');
      const closeB = document.getElementById('az-close');

      /* elevation scale uses min/max across all states */
      const allElev = Object.values(DATA).map(d=>d.elev);
      const elevMin = Math.min(...allElev);
      const elevMax = Math.max(...allElev);

      function drawElevationSpark(val){
        const base = document.querySelector('#az-elev-spark .spark-base');
        const line = document.getElementById('az-elev-line');
        const dot  = document.getElementById('az-elev-dot');
        if(!line || !dot) return;

        const H=60, W=160, padX=6, baselineY=H-2, x0=padX, x1=W-padX;
        const pct  = (val - elevMin) / Math.max(1,(elevMax - elevMin));
        const yEnd = baselineY - (pct * (H - 12));

        if (base) base.setAttribute('d', `M${x0},${baselineY} L${x1},${baselineY}`);
        line.setAttribute('d', `M${x0},${baselineY} L${x1},${yEnd.toFixed(2)}`);
        dot.setAttribute('cx', x1);
        dot.setAttribute('cy', yEnd.toFixed(2));

        const L = line.getTotalLength();
        line.style.strokeDasharray = L;
        line.style.strokeDashoffset = L;
        requestAnimationFrame(()=>{ line.style.strokeDashoffset = 0; });
      }

      function drawDarknessGauge(val){
        const gVal    = document.getElementById('az-dark-value');
        const gNeedle = document.getElementById('az-dark-needle-group');
        if(!gVal || !gNeedle) return;

        const len = gVal.getTotalLength();
        gVal.style.strokeDasharray = len.toFixed(1);
        gVal.style.strokeDashoffset = len.toFixed(1);

        const pct = Math.max(0, Math.min(1, val / DARK_MAX));
        requestAnimationFrame(()=>{
          gVal.style.strokeDashoffset = (len * (1 - pct)).toFixed(1);
          const angle = -90 + 180 * pct;
          gNeedle.style.transform = `rotate(${angle}deg)`;
        });
      }

      function drawHumidityRing(pctVal){
        const arc = document.getElementById('az-humid-arc');
        if(!arc) return;
        const r=26, C=2*Math.PI*r;
        arc.style.strokeDasharray = C.toFixed(1);
        arc.style.strokeDashoffset = C.toFixed(1);
        const pct = Math.max(0, Math.min(1, pctVal/100));
        requestAnimationFrame(()=> arc.style.strokeDashoffset = (C*(1-pct)).toFixed(1));
      }

      function buildCalendar(days){
        const cal = document.getElementById('az-clear-cal');
        if(!cal) return;
        cal.innerHTML = '';
        const total = 31;
        const whole = Math.floor(days);
        const frac  = Math.max(0, Math.min(1, days - whole));
        for(let i=0;i<total;i++){
          const cell=document.createElement('span');
          cell.className='day';
          if(i<whole) cell.classList.add('filled');
          else if(i===whole && frac>0){ cell.classList.add('partial'); cell.style.setProperty('--part', frac.toFixed(2)); }
          cal.appendChild(cell);
        }
      }

      function renderState(name){
        const d = DATA[name]; if(!d) return;
        const title = document.getElementById('az-metrics-title'); if(title) title.textContent = name+' — Supermoon Viewing Factors';
        const ez = document.getElementById('az-elev-val');   if(ez) ez.textContent = d.elev.toLocaleString()+' ft';
        const dz = document.getElementById('az-dark-val');   if(dz) dz.textContent = d.dark.toFixed(2)+' / 5';
        const cz = document.getElementById('az-clear-val');  if(cz) cz.textContent = d.clear.toFixed(1)+' days';
        const hz = document.getElementById('az-humid-val');  if(hz) hz.textContent = Math.round(d.humid)+'%';

        drawElevationSpark(d.elev);
        drawDarknessGauge(d.dark);
        drawHumidityRing(d.humid);
        buildCalendar(d.clear);
      }

      function openUnderRow(row){
        const state = row.dataset.state;
        row.after(panel); // move shared panel under row
        document.querySelectorAll('.vi-compact-embed .row.is-clickable[aria-expanded]')
          .forEach(r=>r.setAttribute('aria-expanded','false'));
        row.setAttribute('aria-expanded','true');

        if(!panel.classList.contains('open')){
          panel.classList.add('open');
          panel.setAttribute('aria-hidden','false');
        }
        renderState(state);
        panel.scrollIntoView({block:'nearest', behavior:'smooth'});
      }

      function closePanel(){
        panel.classList.remove('open');
        panel.setAttribute('aria-hidden','true');
        document.querySelectorAll('.vi-compact-embed .row.is-clickable[aria-expanded]')
          .forEach(r=>r.setAttribute('aria-expanded','false'));
      }

      rows.forEach(row=>{
        row.addEventListener('click', ()=>{
          const isExpanded  = row.getAttribute('aria-expanded') === 'true';
          const panelIsOpen = panel.classList.contains('open');
          if (isExpanded && panelIsOpen) closePanel();
          else openUnderRow(row);
        });

        row.addEventListener('keydown', e=>{
          if(e.key==='Enter' || e.key===' '){
            e.preventDefault();
            const isExpanded  = row.getAttribute('aria-expanded') === 'true';
            const panelIsOpen = panel.classList.contains('open');
            if (isExpanded && panelIsOpen) closePanel();
            else openUnderRow(row);
          }
        });
      });

      if(closeB) closeB.addEventListener('click', closePanel);
      document.addEventListener('keydown', e=>{ if(e.key==='Escape' && panel.classList.contains('open')) closePanel(); });

      /* ---- Auto-resize messaging to parent (iframe) ---- */
      function sendHeightToParent() {
        try {
          const height = document.body.scrollHeight;
          window.parent.postMessage({ type: "resize-iframe", height: height, src: window.location.href }, "*");
        } catch (e) {}
      }
      window.addEventListener("load", sendHeightToParent);
      window.addEventListener("resize", sendHeightToParent);
      const observer = new MutationObserver(sendHeightToParent);
      observer.observe(document.body, { childList: true, subtree: true, attributes: true });

      /* ---- Embed button copy behavior ---- */
      const btn     = document.getElementById('copy-embed-btn');
      const wrapper = document.getElementById('embed-wrapper');
      const ta      = document.getElementById('embed-code');
      const status  = document.getElementById('copy-status');

      if (btn && ta && wrapper && status) {
        btn.addEventListener('click', () => {
          const isHidden = wrapper.style.display === 'none' || wrapper.style.display === '';
          wrapper.style.display = isHidden ? 'block' : 'none';
          btn.textContent = isHidden ? 'Hide Embed Code' : '🔗 Embed This Table';
          btn.setAttribute('aria-expanded', String(isHidden));
          if (isHidden) {
            ta.focus();
            ta.select();
            try { document.execCommand('copy'); } catch(e) {}
            status.style.display = 'block';
            setTimeout(() => status.style.display = 'none', 2500);
          } else {
            btn.focus();
          }
          sendHeightToParent();
        });

        // Close when clicking outside the popup
        document.addEventListener('click', (e)=>{
          const open = wrapper.style.display === 'block';
          if (open && !wrapper.contains(e.target) && !btn.contains(e.target)) {
            wrapper.style.display = 'none';
            btn.setAttribute('aria-expanded','false');
            btn.textContent = '🔗 Embed This Table';
            sendHeightToParent();
          }
        });

        // Close on Esc when popup is open
        document.addEventListener('keydown', (e)=>{
          if (e.key === 'Escape' && wrapper.style.display === 'block') {
            wrapper.style.display = 'none';
            btn.setAttribute('aria-expanded','false');
            btn.textContent = '🔗 Embed This Table';
            btn.focus();
            sendHeightToParent();
          }
        });
      }
    })();
  </script>
</section>
</body>
</html>
"""

# === 3. Generator: build rows + DATA ==================================
def generate_html_from_df(
    df: pd.DataFrame,
    title: str,
    subtitle: str,
    embed_url: str,
) -> str:
    df = df.copy()
    df = df.sort_values("probability", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    max_prob = float(df["probability"].max() or 1.0)

    row_snippets = []
    for _, row in df.iterrows():
        state = str(row["state"])
        rank = int(row["rank"])
        prob = float(row["probability"])
        odds = int(row["odds"])

        width_pct = prob / max_prob * 100.0
        bar_style = f"width:{width_pct:.2f}%;"

        flag_url = STATE_FLAG_URLS.get(state, "")
        if flag_url:
            img_html = (
                f'<img loading="lazy" decoding="async" alt="{state} flag" '
                f'width="18" height="18" src="{flag_url}">'
            )
        else:
            img_html = ""

        row_html = f"""
    <div class="row is-clickable" data-state="{state}" data-rank="{rank}" aria-expanded="false" tabindex="0" role="button">
      <div class="rank">{rank}</div>
      <div class="state">
        <span class="chip">{img_html}</span>
        {state}
      </div>
      <div class="metric">
        <span class="bar" style="{bar_style}"></span>
        <span class="val">{prob:.2f}% (+{odds})</span>
      </div>
    </div>""".rstrip()
        row_snippets.append(row_html)

    rows_html = "\n\n".join(row_snippets)

    data_lines = []
    for _, row in df.iterrows():
        state = str(row["state"])
        elev = float(row["elevation_ft"])
        dark = float(row["dark_score"])
        clear_days = float(row["clear_days_dec"])
        humid = float(row["humidity_dec"])
        data_lines.append(
            f'        "{state}":  {{ elev:{elev}, dark:{dark:.2f}, clear:{clear_days:.2f}, humid:{humid:.2f} }}'
        )
    data_js = "{\n" + ",\n".join(data_lines) + "\n      }"

    html = (
        HTML_TEMPLATE
        .replace("[[ROWS]]", rows_html)
        .replace("[[DATA]]", data_js)
        .replace("[[TITLE]]", title)
        .replace("[[SUBTITLE]]", subtitle)
        .replace("[[EMBED_URL]]", embed_url)
    )

    return html

# === 5. Streamlit App ================================================

st.set_page_config(page_title="Supermoon Table Generator", layout="wide")

st.title("Supermoon Visibility Table Generator")
st.write(
    "Upload a CSV, then use the tabs to preview, configure, and publish "
    "your Supermoon widget via GitHub Pages."
)

uploaded_file = st.file_uploader("Upload your CSV file", type=["csv"])

if uploaded_file is not None:
    # --- Step 1: read & clean CSV ---
    try:
        raw_df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    required_cols = [
        "State",
        "Implied Supermoon Viewing Probability (%)",
        "Supermoon Viewing Odds (Moneyline)",
        "Avg. Clear Sky Days (Dec)",
        "Avg. Humidity (Dec)",
        "Avg. Elevation (ft)",
        "Darkness Score (1–5)",
    ]
    missing = [c for c in required_cols if c not in raw_df.columns]
    if missing:
        st.error(f"Missing required columns in CSV: {missing}")
        st.stop()

    df = pd.DataFrame()
    df["state"] = raw_df["State"]
    df["probability"] = (
        raw_df["Implied Supermoon Viewing Probability (%)"]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.strip()
        .astype(float)
    )
    df["odds"] = (
        raw_df["Supermoon Viewing Odds (Moneyline)"]
        .astype(str)
        .str.replace("+", "", regex=False)
        .str.strip()
        .astype(int)
    )
    df["clear_days_dec"] = raw_df["Avg. Clear Sky Days (Dec)"].astype(float)
    df["humidity_dec"] = raw_df["Avg. Humidity (Dec)"].astype(float)
    df["elevation_ft"] = raw_df["Avg. Elevation (ft)"].astype(float)
    df["dark_score"] = raw_df["Darkness Score (1–5)"].astype(float)

    # Defaults for widget text
    default_title = "Top U.S. States for Supermoon Visibility in 2025"
    default_subtitle = (
        "Ranked by visibility factors such as sky clarity, elevation, and "
        "atmospheric conditions, converted into implied probabilities and "
        "moneyline odds."
    )

    # Load any existing GitHub settings from session state to drive the preview URL
    saved_gh_user = st.session_state.get("gh_user", "")
    saved_gh_repo = st.session_state.get("gh_repo", "supermoon-visibility-widget")

    if saved_gh_user and saved_gh_repo:
        current_embed_url = (
            f"https://{saved_gh_user}.github.io/{saved_gh_repo}/supermoon_table.html"
        )
    else:
        current_embed_url = "https://example.github.io/your-repo/supermoon_table.html"

    # --- Tabs layout ---
    tab1, tab2, tab3 = st.tabs(
        [
            "Detected columns & data",
            "Configure & preview widget",
            "Create repo & publish",
        ]
    )

    # -------- TAB 1: Detected columns & table preview --------
    with tab1:
        st.subheader("Detected columns")
        st.write(list(raw_df.columns))

        st.subheader("Cleaned data preview")
        st.dataframe(df.head())

    # -------- TAB 2: Configure widget + preview --------
    with tab2:
        st.subheader("Widget text")

        title = st.text_input(
            "Widget name",
            value=st.session_state.get("widget_title", default_title),
            key="widget_title",
        )
        subtitle = st.text_input(
            "Widget subtitle",
            value=st.session_state.get("widget_subtitle", default_subtitle),
            key="widget_subtitle",
        )

        st.caption(
            "GitHub username and campaign name live in the **Create repo & publish** tab.\n\n"
            f"Current embed URL used inside the preview widget: `{current_embed_url}`"
        )

        # Preview HTML uses the *current* embed URL (driven by GitHub settings if set)
        html_preview = generate_html_from_df(df, title, subtitle, current_embed_url)

        st.markdown("---")
        st.subheader("Interactive widget preview")
        components.html(html_preview, height=1140, scrolling=True)

        st.subheader("HTML file contents (preview)")
        st.text_area(
            "Preview only – when you change GitHub settings, this embed URL updates on the next run.",
            value=html_preview,
            height=350,
        )

    # -------- TAB 3: Create repo, upload HTML & publish --------
    with tab3:
        st.subheader("GitHub settings")

        # Read latest title/subtitle from session state (so publish uses what you configured)
        title_for_publish = st.session_state.get("widget_title", default_title)
        subtitle_for_publish = st.session_state.get("widget_subtitle", default_subtitle)

        username_options = ["GauthamBC", "ActionNetwork", "MoonWatcher", "SampleUser"]
        if GITHUB_USER_DEFAULT and GITHUB_USER_DEFAULT not in username_options:
            username_options.insert(0, GITHUB_USER_DEFAULT)

        # figure out default index for selectbox from saved_gh_user
        if saved_gh_user in username_options:
            default_idx = username_options.index(saved_gh_user)
        else:
            default_idx = 0

        github_username_input = st.selectbox(
            "Username (GitHub username)",
            options=username_options,
            index=default_idx,
            key="gh_user",
        )
        effective_github_user = github_username_input.strip()

        repo_name = st.text_input(
            "Campaign name (GitHub repo name)",
            value=saved_gh_repo,
            key="gh_repo",
        )

        if effective_github_user and repo_name.strip():
            expected_embed_url = (
                f"https://{effective_github_user}.github.io/{repo_name.strip()}/supermoon_table.html"
            )
        else:
            expected_embed_url = "https://example.github.io/your-repo/supermoon_table.html"

        st.caption(
            f"Expected GitHub Pages URL (used in final widget footer & iframe):\n\n`{expected_embed_url}`"
        )

        st.markdown("---")
        st.subheader("Create repo, upload HTML & trigger Pages build")

        if not GITHUB_TOKEN:
            st.info(
                "Set `GITHUB_TOKEN` in `.streamlit/secrets.toml` (with `repo` scope) "
                "to enable automatic GitHub publishing."
            )
        elif not effective_github_user or not repo_name.strip():
            st.info("Fill in username and campaign name above.")
        else:
            if st.button("Create repo, upload `supermoon_table.html` & trigger Pages build"):
                try:
                    # Generate final HTML with the real embed URL
                    html_final = generate_html_from_df(
                        df, title_for_publish, subtitle_for_publish, expected_embed_url
                    )

                    # 1) Ensure repo exists
                    created = ensure_repo_exists(
                        effective_github_user,
                        repo_name.strip(),
                        GITHUB_TOKEN,
                    )

                    # 2) Enable GitHub Pages (best effort)
                    try:
                        ensure_pages_enabled(
                            effective_github_user,
                            repo_name.strip(),
                            GITHUB_TOKEN,
                            branch="main",
                        )
                    except Exception as pages_err:
                        st.warning(
                            f"Repo exists/created, but enabling GitHub Pages via API may have failed: {pages_err}\n"
                            "You may need to finalize Pages settings manually in GitHub."
                        )

                    # 3) Upload HTML file
                    upload_file_to_github(
                        effective_github_user,
                        repo_name.strip(),
                        GITHUB_TOKEN,
                        "supermoon_table.html",
                        html_final,
                        "Add/update supermoon_table.html from Streamlit app",
                        branch="main",
                    )

                    # 4) Trigger Pages build
                    build_ok = trigger_pages_build(
                        effective_github_user,
                        repo_name.strip(),
                        GITHUB_TOKEN,
                    )

                    st.success(
                        f"Repo `{effective_github_user}/{repo_name.strip()}` is ready and "
                        "`supermoon_table.html` has been uploaded."
                    )
                    st.info(
                        f"Once GitHub Pages finishes building, your widget should be live at:\n\n"
                        f"`{expected_embed_url}`"
                    )

                    if not build_ok:
                        st.warning(
                            "Could not confirm a GitHub Pages build via API. "
                            "If the page never appears, check the Pages settings and build logs in GitHub."
                        )

                    st.subheader("Final iframe embed code")
                    iframe_snippet = f"""<iframe src="{expected_embed_url}"
  title="{title_for_publish}"
  width="100%" height="1140"
  scrolling="no"
  style="border:0;" loading="lazy"></iframe>"""
                    st.code(iframe_snippet, language="html")

                except Exception as e:
                    st.error(f"GitHub publish failed: {e}")

else:
    st.info("Upload a CSV to unlock the tabs and generate your widget.")
