import base64
import time
import re
import html as html_mod
import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
        "description": "Branded searchable table (auto-created by Streamlit app).",
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
    Brand metadata: name, logo, alt text, and a CSS class
    used to theme the table.
    """
    default_logo = "https://i.postimg.cc/x1nG117r/AN-final2-logo.png"
    brand_clean = (brand or "").strip() or "Action Network"

    meta = {
        "name": brand_clean,
        "logo_url": default_logo,
        "logo_alt": f"{brand_clean} logo",
        "brand_class": "brand-actionnetwork",
    }

    if brand_clean == "Action Network":
        meta["brand_class"] = "brand-actionnetwork"
        meta["logo_url"] = "https://i.postimg.cc/x1nG117r/AN-final2-logo.png"
        meta["logo_alt"] = "Action Network logo"

    elif brand_clean == "VegasInsider":
        meta["brand_class"] = "brand-vegasinsider"
        meta["logo_url"] = "https://i.postimg.cc/kGVJyXc1/VI-logo-final.png"
        meta["logo_alt"] = "VegasInsider logo"

    elif brand_clean == "Canada Sports Betting":
        meta["brand_class"] = "brand-canadasb"
        meta["logo_url"] = "https://i.postimg.cc/ZKbrbPCJ/CSB-FN.png"
        meta["logo_alt"] = "Canada Sports Betting logo"

    elif brand_clean == "RotoGrinders":
        meta["brand_class"] = "brand-rotogrinders"
        meta["logo_url"] = "https://i.postimg.cc/PrcJnQtK/RG-logo-Fn.png"
        meta["logo_alt"] = "RotoGrinders logo"

    return meta

# === 2. HTML TEMPLATE: branded searchable table =======================

HTML_TEMPLATE_TABLE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>[[TITLE]]</title>
</head>
<body style="margin:0;">

<section class="vi-table-embed [[BRAND_CLASS]]" style="max-width:960px;margin:16px auto;
         font:14px/1.35 Inter,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         color:#181a1f;background:#ffffff;border:1px solid #DCEFE6;border-radius:12px;
         box-shadow:0 1px 2px rgba(0,0,0,.04),0 6px 16px rgba(0,0,0,.09);">

  <style>
    /* Scope */
    .vi-table-embed, .vi-table-embed * { box-sizing:border-box; font-family:inherit; }

    .vi-table-embed{
      --brand-50:#F6FFF9; 
      --brand-100:#DCF2EB;
      --brand-300:#BCE5D6;
      --brand-500:#56C257; 
      --brand-600:#3FA94B; 
      --brand-700:#2E8538; 
      --brand-900:#1F5D28;

      --header-bg:var(--brand-500);
      --stripe:var(--brand-100);
      --hover:var(--brand-300);
      --scroll-track:#f7f8fb;
      --scroll-thumb:var(--brand-500);
      --scroll-thumb-hover:var(--brand-600);

      --footer-border:color-mix(in oklab,var(--brand-500) 35%, transparent);
    }

    /* Brand overrides – reuse palettes from the supermoon widget */
    .vi-table-embed.brand-vegasinsider{
      --brand-50:#FFF7DC;
      --brand-100:#FFE8AA;
      --brand-300:#FFE8AA;
      --brand-500:#F2C23A;
      --brand-600:#D9A72A;   /* matches embed button + requested yellow */
      --brand-700:#B9851A;
      --brand-900:#111111;
      --header-bg:var(--brand-500);
      --stripe:var(--brand-50);
      --hover:var(--brand-100);
      --scroll-thumb:var(--brand-600);
      --footer-border:color-mix(in oklab,var(--brand-500) 40%, transparent);
    }

    .vi-table-embed.brand-canadasb{
      --brand-50:#FEF2F2;
      --brand-100:#FEE2E2;
      --brand-300:#FECACA;
      --brand-500:#EF4444;
      --brand-600:#DC2626;
      --brand-700:#B91C1C;
      --brand-900:#7F1D1D;
      --header-bg:var(--brand-600);
      --stripe:var(--brand-50);
      --hover:var(--brand-100);
      --scroll-thumb:var(--brand-600);
      --footer-border:color-mix(in oklab,var(--brand-600) 40%, transparent);
    }

    .vi-table-embed.brand-rotogrinders{
      --brand-50:#E8F1FF;
      --brand-100:#D3E3FF;
      --brand-300:#9ABCF9;
      --brand-500:#2F7DF3;
      --brand-600:#0159D1;
      --brand-700:#0141A1;
      --brand-900:#011F54;
      --header-bg:var(--brand-700);
      --stripe:var(--brand-50);
      --hover:var(--brand-100);
      --scroll-thumb:var(--brand-600);
      --footer-border:color-mix(in oklab,var(--brand-600) 40%, transparent);
    }

    /* Header block (title + subtitle stacked) */
    .vi-table-embed .vi-table-header{
      padding:10px 16px 8px;
      border-bottom:1px solid var(--brand-100);
      background:linear-gradient(90deg,var(--brand-50),#ffffff);
      display:flex;
      flex-direction:column;
      align-items:flex-start;
      gap:2px;
    }
    .vi-table-embed .vi-table-header.centered{
      align-items:center;
      text-align:center;
    }
    .vi-table-embed .vi-table-header .title{
      margin:0;
      font-size:clamp(18px,2.3vw,22px);
      font-weight:750;
      color:#111827;
      display:block;
    }
    /* Branded title colour – uses brand-600 for every brand */
    .vi-table-embed .vi-table-header .title.branded{
      color:var(--brand-600);
    }
    .vi-table-embed .vi-table-header .subtitle{
      margin:0;
      font-size:13px;
      color:#6b7280;
      display:block;
    }

    /* Container for table block */
    #bt-block, #bt-block * { box-sizing:border-box; }
    #bt-block{
      --bg:#ffffff; --text:#1f2937;
      --gutter: clamp(8px, 4vw, 14px);
      --gutter-left: 0;
      --gutter-right: 0; 
      --edge-pad: 14px;
      --table-max-h: 500px;
      --vbar-w: 6px; --vbar-w-hover: 8px;

      padding: 8px var(--gutter);
      padding-top: 8px;
    }

    /* Controls layout: header = search + pager (no logo) */
    #bt-block .dw-controls{
      display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center;
      gap:12px; margin:4px 0 10px 0;
    }
    #bt-block .left{display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-start}
    #bt-block .right{display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end}

    #bt-block .dw-field{position:relative}
    #bt-block .dw-input,#bt-block .dw-select,#bt-block .dw-btn{
      font:14px/1.2 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif; border-radius:10px; padding:8px 10px; transition:.15s ease;
    }
    #bt-block .dw-input,#bt-block .dw-select{
      background:#fff;
      border:1px solid var(--brand-700);
      color:var(--text); box-shadow:inset 0 1px 2px rgba(16,24,40,.04);
    }
    #bt-block .dw-input{width:min(320px,100%); padding-right:36px}
    #bt-block .dw-input::placeholder{color:#9AA4B2}
    #bt-block .dw-input:focus,#bt-block .dw-select:focus{
      outline:none; border-color:var(--brand-500);
      box-shadow:0 0 0 3px color-mix(in oklab,var(--brand-500) 25%,transparent); background:#fff;
    }
    /* simpler select: remove custom chevron so we don't get duplicate icons */
    #bt-block .dw-select{
      appearance:none;
      -webkit-appearance:none;
      -moz-appearance:none;
      padding-right:26px;
      background:#fff;
      background-image:none;
    }

    #bt-block .dw-btn{
      background:var(--brand-500); color:#fff; border:1px solid var(--brand-500); padding-inline:12px; cursor:pointer
    }
    #bt-block .dw-btn:hover{background:var(--brand-600); border-color:var(--brand-600)} 
    #bt-block .dw-btn:active{transform:translateY(1px)}
    #bt-block .dw-btn[disabled]{background:#fafafa; border-color:#d1d5db; color:#6b7280; opacity:1; cursor:not-allowed; transform:none}
    #bt-block .dw-status{font:12px/1.2 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif; color:#6b7280}
    #bt-block .dw-counter{display:none !important;}

    /* Clear button */
    #bt-block .dw-clear{
      position:absolute; right:10px; top:50%; translate:0 -50%; width:22px; height:22px; border-radius:9999px; border:0;
      background:transparent; color:var(--brand-700); cursor:pointer; display:none; align-items:center; justify-content:center;
    }
    #bt-block .dw-field.has-value .dw-clear{display:flex}
    #bt-block .dw-clear:hover{background:var(--brand-100)}

    /* Card & table */
    #bt-block .dw-card {
      background: var(--bg);
      border: 0;
      box-shadow: none;
      overflow: hidden;
      margin: 0;
      width: 100%;
    }
    #bt-block .dw-scroll {
      overflow-x: auto;
      overflow-y: hidden;
      -webkit-overflow-scrolling: touch;
    }
    #bt-block .dw-scroll.no-scroll { overflow-x: hidden !important; }
    #bt-block table.dw-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
      color: var(--text);
      font-variant-numeric: tabular-nums;
      background: transparent;
      min-width: 600px;
      table-layout: auto;
    }

    /* Header row */
    #bt-block thead th{
      background:var(--header-bg); color:#ffffff; font-weight:700; text-align:center;
      padding:12px 14px; white-space:nowrap; vertical-align:middle; border:0;
      transition:background-color .15s, color .15s, box-shadow .15s, transform .05s;
    }
    #bt-block thead th.sortable{cursor:pointer; user-select:none}
    #bt-block thead th.sortable::after{content:"↕"; font-size:12px; opacity:.75; margin-left:8px; color:#ffffff}
    #bt-block thead th.sortable[data-sort="asc"]::after{content:"▲"}
    #bt-block thead th.sortable[data-sort="desc"]::after{content:"▼"}
    #bt-block thead th.sortable:hover,#bt-block thead th.sortable:focus-visible{background:var(--brand-600); color:#fff; box-shadow:inset 0 -3px 0 var(--brand-100)}
    #bt-block .dw-scroll.scrolled thead th{box-shadow:0 6px 10px -6px rgba(0,0,0,.25)}
    #bt-block thead th.is-sorted{background:var(--brand-700); color:#fff; box-shadow:inset 0 -3px 0 var(--brand-100)}

    #bt-block thead th,
    #bt-block tbody td {
      padding: 12px 10px;
      overflow: hidden;
      text-align:center;
    }
    #bt-block thead th { white-space: nowrap; }

    #bt-block tbody td:nth-child(2) {
      white-space: normal;
      word-break: keep-all;
      overflow-wrap: break-word;
      min-width: 100px;
      max-width: 220px;
      line-height: 1.3;
    }
    #bt-block tbody td {
      background-clip: padding-box;
      backface-visibility: hidden;
      transform: translateZ(0);
    }

    /* Body rows – zebra + hover injected here */
    [[STRIPE_CSS]]

    #bt-block tbody tr:hover{
      background:var(--hover);
      box-shadow:inset 3px 0 0 var(--brand-500);
      transform:translateY(-1px);
      transition:background-color .12s ease, box-shadow .12s ease, transform .08s ease;
    }

    #bt-block thead th{position:sticky; top:0; z-index:5}

    /* Scrollbars + height */
    #bt-block .dw-scroll{
      max-height:var(--table-max-h,360px); overflow-y:auto;
      -ms-overflow-style:auto; scrollbar-width:thin; scrollbar-color:var(--scroll-thumb) transparent
    }
    #bt-block .dw-scroll::-webkit-scrollbar:horizontal{height:0; display:none}
    #bt-block .dw-scroll::-webkit-scrollbar:vertical{width:var(--vbar-w)}
    #bt-block .dw-scroll:hover::-webkit-scrollbar:vertical{width:var(--vbar-w-hover)}
    #bt-block .dw-scroll::-webkit-scrollbar-thumb{
      background:var(--scroll-thumb); border-radius:9999px; border:2px solid transparent; background-clip:content-box;
    }

    /* Empty row */
    #bt-block tr.dw-empty td{text-align:center; color:#6b7280; font-style:italic; padding:18px 14px; background:linear-gradient(0deg,#fff,var(--brand-50))}

    /* Responsiveness */
    #bt-block .dw-input { width: clamp(160px, 26vw, 320px); }
    #bt-block .dw-select { min-width: 68px; }
    #bt-block .dw-btn { padding-inline: 8px; }

    @media (max-width: 600px){
      #bt-block .dw-controls{
        grid-template-columns:minmax(0,1fr) auto;
        column-gap:8px; row-gap:6px; margin:6px 0 8px;
      }
      #bt-block .dw-input{width:100%; padding:6px 24px 6px 10px; height:34px; font-size:13px;}
      #bt-block .dw-clear{width:20px; height:20px;}
      #bt-block thead th{ font-size:13px; line-height:1.2; }
      #bt-block .dw-select{min-width:68px; height:32px; padding:6px 22px 6px 8px; font-size:13px;}
      #bt-block .dw-btn{width:32px; height:32px; padding:0; border-radius:12px; display:inline-flex; align-items:center; justify-content:center;}
    }

    /* ========= Footer with logo + embed button ======== */
    .vi-table-embed .vi-footer {
      display:block;
      padding:10px 14px 8px;
      border-top:1px solid var(--footer-border);
      background:linear-gradient(90deg,var(--brand-50),#ffffff);
    }
    .vi-table-embed .footer-inner{
      display:flex;
      justify-content:space-between;  /* button left, logo right */
      align-items:center;
      gap:12px;
      position:relative;
    }
    .vi-table-embed .embed-btn {
      background: var(--brand-600);
      color: #fff;
      border: 1px solid var(--brand-600);
      border-radius: 999px;
      padding: 6px 16px;
      font: 13px/1.2 system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
      cursor: pointer;
      transition: .2s ease;
      white-space:nowrap;
    }
    .vi-table-embed .embed-btn:hover {
      background: var(--brand-700);
      border-color: var(--brand-700);
    }
    .vi-table-embed .vi-footer img{
      height: 38px;
      width:auto;
      display:inline-block;
    }

    /* Brand-specific logo recolor (Vegas tuned for #D9A72A) */
    .vi-table-embed.brand-actionnetwork .vi-footer img{
      filter:
        brightness(0) saturate(100%)
        invert(62%) sepia(23%) saturate(1250%) hue-rotate(78deg)
        brightness(96%) contrast(92%);
    }
    .vi-table-embed.brand-vegasinsider .vi-footer img{
      filter:
        brightness(0) saturate(100%)
        invert(72%) sepia(63%) saturate(652%) hue-rotate(6deg)
        brightness(95%) contrast(101%);
    }
    .vi-table-embed.brand-canadasb .vi-footer img{
      filter:
        brightness(0) saturate(100%)
        invert(32%) sepia(85%) saturate(2386%) hue-rotate(347deg)
        brightness(96%) contrast(104%);
    }
    .vi-table-embed.brand-rotogrinders .vi-footer img{
      filter:
        brightness(0) saturate(100%)
        invert(23%) sepia(95%) saturate(1704%) hue-rotate(203deg)
        brightness(93%) contrast(96%);
    }

    @media (max-width: 600px){
      .vi-table-embed .footer-inner{
        flex-direction:row;
        justify-content:space-between; /* still opposite ends on mobile */
        gap:8px;
      }
      .vi-table-embed .embed-btn{
        padding:6px 10px;
        font-size:12px;
      }
    }

    .vi-table-embed.brand-vegasinsider .vi-footer img{ height:32px; }
    .vi-table-embed.brand-rotogrinders .vi-footer img{ height:32px; }

    .vi-table-embed .embed-wrapper{
      position: absolute;
      bottom: calc(100% + 10px);
      left: 50%;
      transform: translateX(-50%);
      width: min(620px, calc(100% - 24px));
      display: none;
      padding: 12px 16px;
      border: 1px solid #ccc;
      border-radius: 10px;
      background: #fff;
      color: #111;
      box-shadow: 0 12px 28px rgba(0,0,0,.18);
      z-index: 1000;
    }
    .vi-table-embed .embed-wrapper textarea{
      width:100%; height:90px; font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
      color:#111; background:#fff; padding:8px 10px; border:1px solid #ddd; border-radius:8px; resize:none;
    }
    .vi-table-embed #bt-copy-status{ display:none; color:#008000; font-size:13px; margin-top:6px; }
    .vi-table-embed .embed-wrapper::after{
      content:""; position:absolute; left:50%; transform:translateX(-50%); bottom:-8px;
      border:8px solid transparent; border-top-color:#fff;
      filter: drop-shadow(0 1px 1px rgba(0,0,0,.08));
    }
  </style>

  <!-- Header -->
  <div class="vi-table-header [[HEADER_ALIGN_CLASS]]">
    <span class="title [[TITLE_CLASS]]">[[TITLE]]</span>
    <span class="subtitle">[[SUBTITLE]]</span>
  </div>

  <!-- Table block -->
  <div id="bt-block" data-dw="table">
    <div class="dw-controls">
      <div class="left">
        <div class="dw-field">
          <input type="search" class="dw-input" placeholder="Search table…" aria-label="Search table">
          <button type="button" class="dw-clear" aria-label="Clear search">×</button>
        </div>
        <span class="dw-status dw-counter" aria-live="polite"></span>
      </div>

      <div class="right">
        <label class="dw-status" for="bt-size" style="margin-right:4px;">Rows/page</label>
        <select id="bt-size" class="dw-select">
          <option value="10" selected>10</option>
          <option value="15">15</option>
          <option value="20">20</option>
          <option value="0">All</option>
        </select>
        <button class="dw-btn" data-page="prev" aria-label="Previous page">‹</button>
        <button class="dw-btn" data-page="next" aria-label="Next page">›</button>
      </div>
    </div>

    <div class="dw-card">
      <div class="dw-scroll">
        <table class="dw-table">
          <thead>
            <tr>
              [[TABLE_HEAD]]
            </tr>
          </thead>
          <tbody>
            [[TABLE_ROWS]]
            <tr class="dw-empty" style="display:none;"><td colspan="[[COLSPAN]]">No matches found.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Footer with logo + embed -->
  <div class="vi-footer" role="contentinfo">
    <div class="footer-inner">
      <button id="bt-embed-btn" class="embed-btn" aria-controls="bt-embed-wrapper" aria-expanded="false">🔗 Embed This Table</button>
      <img src="[[BRAND_LOGO_URL]]"
           alt="[[BRAND_LOGO_ALT]]"
           width="140" height="auto" loading="lazy" decoding="async" />
      <div id="bt-embed-wrapper" class="embed-wrapper">
        <textarea id="bt-embed-code" readonly>&lt;iframe src="[[EMBED_URL]]"
  title="[[TITLE]]"
  width="100%" height="700" scrolling="no"
  style="border:0;" loading="lazy"&gt;&lt;/iframe&gt;</textarea>
        <p id="bt-copy-status">Embed code copied!</p>
      </div>
    </div>
  </div>

  <script>
  (function(){
    const root = document.getElementById('bt-block');
    if (!root || root.dataset.dwInit === '1') return;
    root.dataset.dwInit='1';

    const table = root.querySelector('table.dw-table');
    const tb = table ? table.tBodies[0] : null;
    const scroller = root.querySelector('.dw-scroll');
    const controls = root.querySelector('.dw-controls');
    if(!table || !tb || !scroller || !controls) return;

    // Disable horizontal scrolling if 4 or fewer columns
    if (table.tHead && table.tHead.rows[0].cells.length <= 4) {
      scroller.classList.add('no-scroll');
    }

    const field = controls.querySelector('.dw-field');
    const searchInput = controls.querySelector('.dw-input');
    const clearBtn = controls.querySelector('.dw-clear');
    const statusEl = controls.querySelector('.dw-counter'); // hidden
    const sizeSel = controls.querySelector('#bt-size');
    const prevBtn = controls.querySelector('[data-page="prev"]');
    const nextBtn = controls.querySelector('[data-page="next"]');
    const emptyRow = tb.querySelector('.dw-empty');

    Array.from(tb.rows).forEach((r,i)=>{ if(!r.classList.contains('dw-empty')) r.dataset.idx=i; });

    let pageSize = parseInt(sizeSel.value,10) || 10;  // 0 = All
    let page = 1;
    let filter = '';

    const onScrollShadow = ()=> scroller.classList.toggle('scrolled', scroller.scrollTop > 0);
    scroller.addEventListener('scroll', onScrollShadow); onScrollShadow();

    const heads = Array.from(table.tHead.rows[0].cells);
    heads.forEach((th,i)=>{
      th.classList.add('sortable'); th.setAttribute('aria-sort','none'); th.dataset.sort='none'; th.tabIndex=0;
      const type = th.dataset.type || 'text';
      const go = ()=> sortBy(i,type,th);
      th.addEventListener('click',go);
      th.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); go(); } });
    });

    function textOf(tr,i){ return (tr.children[i].innerText||'').trim(); }

    function sortBy(colIdx, type, th){
      const rows = Array.from(tb.rows).filter(r=>!r.classList.contains('dw-empty'));
      const current = th.dataset.sort || 'none';
      const next = current==='none' ? 'asc' : current==='asc' ? 'desc' : 'none';

      heads.forEach(h=>{
        h.dataset.sort='none';
        h.setAttribute('aria-sort','none');
        h.classList.remove('is-sorted');
      });

      if(next === 'none'){
        rows.sort((a,b)=>(+a.dataset.idx)-(+b.dataset.idx));
        rows.forEach(r=>tb.insertBefore(r, emptyRow));
        renderPage();
        return;
      }

      th.dataset.sort = next;
      th.setAttribute('aria-sort', next==='asc'?'ascending':'descending');

      const mul = next==='asc'?1:-1;
      rows.sort((a,b)=>{
        let v1=textOf(a,colIdx), v2=textOf(b,colIdx);
        if((type||'text')==='num'){
          v1=parseFloat(v1.replace(/[^0-9.\-]/g,'')); if(isNaN(v1)) v1=-Infinity;
          v2=parseFloat(v2.replace(/[^0-9.\-]/g,'')); if(isNaN(v2)) v2=-Infinity;
        }else{
          v1=(v1+'').toLowerCase();
          v2=(v2+'').toLowerCase();
        }
        if(v1>v2) return 1*mul;
        if(v1<v2) return -1*mul;
        return 0;
      });
      rows.forEach(r=>tb.insertBefore(r, emptyRow));
      th.classList.add('is-sorted');
      renderPage();
    }

    function matchesFilter(tr){
      return !tr.classList.contains('dw-empty') &&
             tr.innerText.toLowerCase().includes(filter);
    }

    function renderPage(){
      const ordered = Array.from(tb.rows).filter(r=>!r.classList.contains('dw-empty'));
      const visible = ordered.filter(matchesFilter);
      const total = visible.length;

      ordered.forEach(r=>{ r.style.display='none'; });
      let shown = [];

      if(total===0){
        if(emptyRow){
          emptyRow.style.display='table-row';
          emptyRow.firstElementChild.colSpan = heads.length;
        }
        if(statusEl) statusEl.textContent = "";
        prevBtn.disabled = nextBtn.disabled = true;
      }else{
        if(emptyRow) emptyRow.style.display='none';
        if(pageSize===0){
          shown = visible;
          if(statusEl) statusEl.textContent = "";
          prevBtn.disabled = nextBtn.disabled = true;
        }else{
          const pages = Math.max(1, Math.ceil(total / pageSize));
          page = Math.min(Math.max(1, page), pages);
          const start = (page-1)*pageSize;
          const end = start + pageSize;
          shown = visible.slice(start,end);
          if(statusEl) statusEl.textContent = "";
          prevBtn.disabled = page<=1;
          nextBtn.disabled = page>=pages;
        }
      }

      shown.forEach(r=>{ r.style.display='table-row'; });
    }

    /* search + clear */
    const syncClearBtn = ()=> field.classList.toggle('has-value', !!searchInput.value);
    let t=null;
    searchInput.addEventListener('input', e=>{
      syncClearBtn();
      clearTimeout(t);
      t=setTimeout(()=>{
        filter=(e.target.value||'').toLowerCase().trim();
        page=1;
        renderPage();
      },120);
    });
    clearBtn.addEventListener('click', ()=>{
      searchInput.value='';
      syncClearBtn();
      filter='';
      page=1;
      renderPage();
      searchInput.focus();
    });
    syncClearBtn();

    /* page size + nav */
    sizeSel.addEventListener('change', e=>{
      pageSize = parseInt(e.target.value,10) || 0;
      page=1;
      renderPage();
    });
    prevBtn.addEventListener('click', ()=>{
      page--;
      renderPage();
    });
    nextBtn.addEventListener('click', ()=>{
      page++;
      renderPage();
    });

    renderPage();

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

    /* ---- Embed button in footer ---- */
    const btn     = document.getElementById('bt-embed-btn');
    const wrapper = document.getElementById('bt-embed-wrapper');
    const ta      = document.getElementById('bt-embed-code');
    const status  = document.getElementById('bt-copy-status');

    if (btn && wrapper && ta && status){
      function openPop(){
        wrapper.style.display='block';
        btn.setAttribute('aria-expanded','true');
        ta.focus();
        ta.select();
        try{ document.execCommand('copy'); }catch(e){}
        status.style.display='block';
        setTimeout(()=>status.style.display='none', 2500);
        sendHeightToParent();
      }
      function closePop(){
        wrapper.style.display='none';
        btn.setAttribute('aria-expanded','false');
        sendHeightToParent();
      }

      btn.addEventListener('click', (e)=>{
        e.stopPropagation();
        const isOpen = wrapper.style.display==='block';
        if(isOpen) closePop(); else openPop();
      });
      document.addEventListener('click', (e)=>{
        if(wrapper.style.display==='block' && !wrapper.contains(e.target) && !btn.contains(e.target)){
          closePop();
        }
      });
      document.addEventListener('keydown', (e)=>{
        if(e.key==='Escape' && wrapper.style.display==='block'){ closePop(); btn.focus(); }
      });
    }
  })();
  </script>

</section>
</body>
</html>
"""

# === 3. Generator: build TABLE_HEAD and TABLE_ROWS ====================

def guess_column_type(series: pd.Series) -> str:
    """
    Rough heuristic: return 'num' if the column is mostly numeric-ish, else 'text'.
    """
    if pd.api.types.is_numeric_dtype(series):
        return "num"
    sample = series.dropna().astype(str).head(20)
    if sample.empty:
        return "text"
    numeric_like = 0
    for v in sample:
        cleaned = re.sub(r"[^0-9.\-]", "", v)
        try:
            float(cleaned)
            numeric_like += 1
        except ValueError:
            continue
    return "num" if numeric_like >= max(3, len(sample) // 2) else "text"

def generate_table_html_from_df(
    df: pd.DataFrame,
    title: str,
    subtitle: str,
    embed_url: str,
    brand_logo_url: str,
    brand_logo_alt: str,
    brand_class: str,
    striped: bool = True,
    center_titles: bool = False,
    branded_title_color: bool = True,
) -> str:
    df = df.copy()

    # Build table head
    head_cells = []
    for col in df.columns:
        col_type = guess_column_type(df[col])
        safe_label = html_mod.escape(str(col))
        head_cells.append(
            f'<th scope="col" data-type="{col_type}">{safe_label}</th>'
        )
    table_head_html = "\n              ".join(head_cells)

    # Build rows
    row_html_snippets = []
    for _, row in df.iterrows():
        cells = []
        for col in df.columns:
            val = "" if pd.isna(row[col]) else str(row[col])
            cells.append(f"<td>{html_mod.escape(val)}</td>")
        row_html = "            <tr>" + "".join(cells) + "</tr>"
        row_html_snippets.append(row_html)

    table_rows_html = "\n".join(row_html_snippets)
    colspan = str(len(df.columns))

    if striped:
        stripe_css = """
    #bt-block tbody tr:nth-child(odd){background:var(--stripe);}
    #bt-block tbody tr:nth-child(even){background:#ffffff;}
"""
    else:
        stripe_css = """
    #bt-block tbody tr:nth-child(odd),
    #bt-block tbody tr:nth-child(even){background:#ffffff;}
"""

    header_class = "centered" if center_titles else ""
    title_class = "branded" if branded_title_color else ""

    html = (
        HTML_TEMPLATE_TABLE
        .replace("[[TABLE_HEAD]]", table_head_html)
        .replace("[[TABLE_ROWS]]", table_rows_html)
        .replace("[[COLSPAN]]", colspan)
        .replace("[[TITLE]]", html_mod.escape(title))
        .replace("[[SUBTITLE]]", html_mod.escape(subtitle or ""))
        .replace("[[EMBED_URL]]", html_mod.escape(embed_url))
        .replace("[[BRAND_LOGO_URL]]", brand_logo_url)
        .replace("[[BRAND_LOGO_ALT]]", html_mod.escape(brand_logo_alt))
        .replace("[[BRAND_CLASS]]", brand_class or "")
        .replace("[[STRIPE_CSS]]", stripe_css)
        .replace("[[HEADER_ALIGN_CLASS]]", header_class)
        .replace("[[TITLE_CLASS]]", title_class)
    )
    return html

# === 4. Streamlit App ================================================

st.set_page_config(page_title="Branded Table Generator", layout="wide")

st.title("Branded Table Generator")
st.write(
    "Upload a CSV, choose a brand and GitHub campaign, then click **Update widget** "
    "to publish a branded, searchable table via GitHub Pages."
)

# Brand selection
brand_options = [
    "Action Network",
    "VegasInsider",
    "Canada Sports Betting",
    "RotoGrinders",
]
default_brand = st.session_state.get("brand_table", "Action Network")
if default_brand not in brand_options:
    default_brand = "Action Network"

brand = st.selectbox(
    "Choose a brand",
    options=brand_options,
    index=brand_options.index(default_brand),
    key="brand_table",
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

    default_title = "Table 1"
    default_subtitle = "Subheading"

    # ---------- GitHub / hosting settings ----------
    saved_gh_user = st.session_state.get("bt_gh_user", "")
    saved_gh_repo = st.session_state.get("bt_gh_repo", "branded-table-widget")

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
        key="bt_gh_user",
    )
    effective_github_user = github_username_input.strip()

    repo_name = st.text_input(
        "Widget hosting repository name",
        value=saved_gh_repo,
        key="bt_gh_repo",
    )

    base_filename = "branded_table.html"
    widget_file_name = st.session_state.get("bt_widget_file_name", base_filename)

    def compute_expected_embed_url(user: str, repo: str, fname: str) -> str:
        if user and repo.strip():
            return f"https://{user}.github.io/{repo.strip()}/{fname}"
        return "https://example.github.io/your-repo/widget.html"

    expected_embed_url = compute_expected_embed_url(
        effective_github_user, repo_name, widget_file_name
    )

    st.caption(
        f"Expected GitHub Pages URL (used in widget footer & iframe):\n\n`{expected_embed_url}`"
    )

    st.markdown(
        "<p style='font-size:0.85rem; color:#c4c4c4;'>"
        "Use <strong>Page availability check</strong> to see whether a page already exists "
        "for this campaign, then click <strong>Update widget</strong> to publish."
        "</p>",
        unsafe_allow_html=True,
    )

    iframe_snippet = st.session_state.get("bt_iframe_snippet")

    # --- Buttons row: always visible, disabled when GitHub config missing ---
    can_run_github = bool(GITHUB_TOKEN and effective_github_user and repo_name.strip())

    col_check, col_get = st.columns([1, 1])
    with col_check:
        page_check_clicked = st.button(
            "Page availability check",
            key="bt_page_check",
            disabled=not can_run_github,
        )
    with col_get:
        update_clicked = st.button(
            "Update widget",
            key="bt_update_widget",
            disabled=not can_run_github,
        )

    # Helper info messages if disabled
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

                st.session_state["bt_availability"] = {
                    "repo_exists": repo_exists,
                    "file_exists": file_exists,
                    "checked_filename": base_filename,
                    "suggested_new_filename": next_fname,
                }
                st.session_state.setdefault("bt_widget_file_name", base_filename)

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

                title_for_publish = st.session_state.get("bt_widget_title", default_title)
                subtitle_for_publish = st.session_state.get("bt_widget_subtitle", default_subtitle)
                striped_for_publish = st.session_state.get("bt_striped_rows", True)
                center_titles_for_publish = st.session_state.get("bt_center_titles", False)
                branded_title_for_publish = st.session_state.get("bt_branded_title_color", True)
                brand_meta_publish = get_brand_meta(st.session_state.get("brand_table", brand))

                widget_file_name = st.session_state.get("bt_widget_file_name", base_filename)
                expected_embed_url = compute_expected_embed_url(
                    effective_github_user, repo_name, widget_file_name
                )

                html_final = generate_table_html_from_df(
                    df,
                    title_for_publish,
                    subtitle_for_publish,
                    expected_embed_url,
                    brand_meta_publish["logo_url"],
                    brand_meta_publish["logo_alt"],
                    brand_meta_publish["brand_class"],
                    striped=striped_for_publish,
                    center_titles=center_titles_for_publish,
                    branded_title_color=branded_title_for_publish,
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
                    f"Add/update {widget_file_name} from Branded Table app",
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

                iframe_snippet = f"""<iframe src="{expected_embed_url}"
  title="{title_for_publish}"
  width="100%" height="700" scrolling="no"
  style="border:0;" loading="lazy"></iframe>"""

                st.session_state["bt_iframe_snippet"] = iframe_snippet
                st.session_state["bt_has_generated"] = True

                st.success("Branded table iframe updated. Open the tabs below to preview and embed it.")

            except Exception as e:
                progress_placeholder.empty()
                st.error(f"GitHub publish failed: {e}")

    # ---------- Availability result + options ----------
    availability = st.session_state.get("bt_availability")
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
                    f"your table will be saved as `{checked_filename}`."
                )
                st.session_state["bt_widget_file_name"] = checked_filename
            elif repo_exists and not file_exists:
                st.success(
                    f"Repo exists and `{checked_filename}` is available. "
                    "Update widget will save your table to this file."
                )
                st.session_state["bt_widget_file_name"] = checked_filename
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
                    key="bt_file_conflict_choice",
                )
                if choice.startswith("Replace"):
                    st.session_state["bt_widget_file_name"] = checked_filename
                    st.info(f"Update widget will overwrite `{checked_filename}` in this repo.")
                elif choice.startswith("Create additional"):
                    st.session_state["bt_widget_file_name"] = suggested_new_filename
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
    has_generated = st.session_state.get("bt_has_generated", False)
    show_tabs = has_generated or not GITHUB_TOKEN

    widget_file_name = st.session_state.get("bt_widget_file_name", base_filename)
    expected_embed_url = compute_expected_embed_url(
        effective_github_user, repo_name, widget_file_name
    )

    if show_tabs:
        tab_config, tab_embed = st.tabs(
            [
                "Configure & preview table",
                "Widgets HTML/Iframe",
            ]
        )

        with tab_config:
            # First row: title + subtitle (separate lines, two big inputs)
            row1_col1, row1_col2 = st.columns(2)
            with row1_col1:
                widget_title = st.text_input(
                    "Table title",
                    value=st.session_state.get("bt_widget_title", default_title),
                    key="bt_widget_title",
                )
            with row1_col2:
                widget_subtitle = st.text_input(
                    "Table subtitle",
                    value=st.session_state.get("bt_widget_subtitle", default_subtitle),
                    key="bt_widget_subtitle",
                )

            # Second row: striped rows + center header + branded title colour
            row2_col1, row2_col2, row2_col3 = st.columns(3)
            with row2_col1:
                striped_rows = st.checkbox(
                    "Striped rows",
                    value=st.session_state.get("bt_striped_rows", True),
                    key="bt_striped_rows",
                )
            with row2_col2:
                center_titles = st.checkbox(
                    "Center title & subtitle",
                    value=st.session_state.get("bt_center_titles", False),
                    key="bt_center_titles",
                )
            with row2_col3:
                branded_title_color = st.checkbox(
                    "Branded title color",
                    value=st.session_state.get("bt_branded_title_color", True),
                    key="bt_branded_title_color",
                )

            brand_meta_preview = get_brand_meta(st.session_state.get("brand_table", brand))

            html_preview = generate_table_html_from_df(
                df,
                widget_title,
                widget_subtitle,
                expected_embed_url,
                brand_meta_preview["logo_url"],
                brand_meta_preview["logo_alt"],
                brand_meta_preview["brand_class"],
                striped=striped_rows,
                center_titles=center_titles,
                branded_title_color=branded_title_color,
            )

            components.html(html_preview, height=650, scrolling=True)

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
                if st.session_state.get("bt_iframe_snippet"):
                    st.code(st.session_state["bt_iframe_snippet"], language="html")
                else:
                    st.info("No iframe yet – click **Update widget** above to generate it.")
