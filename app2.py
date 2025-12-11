import base64
import time
import re
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
        "description": "Stadium fan experience widget (auto-created by Streamlit app).",
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

# --- Availability helpers ---------------------------------------------

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
    Look at the root of the repo and find the next available wN.html filename.
    Returns 'w1.html' if none are found or on fallback.
    """
    api_base = "https://api.github.com"
    headers = github_headers(token)
    r = requests.get(
        f"{api_base}/repos/{owner}/{repo}/contents",
        headers=headers,
        params={"ref": branch},
    )
    if r.status_code != 200:
        return "w1.html"

    max_n = 0
    try:
        items = r.json()
        for item in items:
            if item.get("type") == "file":
                name = item.get("name", "")
                m = re.fullmatch(r"w(\d+)\.html", name)
                if m:
                    max_n = max(max_n, int(m.group(1)))
    except Exception:
        return "w1.html"

    return f"w{max_n + 1}.html" if max_n >= 0 else "w1.html"

# === Brand metadata ===================================================

def get_brand_meta(brand: str) -> dict:
    """
    Brand metadata: name, logo, alt text, and a CSS class
    used to theme the widget.
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

# === 1. HTML template for City / Stadium metrics ======================

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>[[TITLE]]</title>
</head>

<body style="margin:0;">

<section class="vi-compact-embed [[BRAND_CLASS]]" role="region" aria-labelledby="vi-compact-embed-title"
  style="max-width:860px;margin:16px auto;font:14px/1.35 Inter,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         color:#181a1f;background:#ffffff;border:1px solid #DCEFE6;border-radius:12px;
         box-shadow:0 1px 2px rgba(0,0,0,.04),0 6px 16px rgba(86,194,87,.10);">
  <style>
    section.vi-compact-embed, section.vi-compact-embed * {
      box-sizing: border-box;
      font-family: inherit;
      color: inherit;
    }
    section.vi-compact-embed { color-scheme: light; }

    .vi-compact-embed{
      --brand-50:#F6FFF9; --brand-100:#DCF2EB; --brand-300:#BCE5D6;
      --brand-500:#56C257; --brand-600:#3FA94B; --brand-700:#2E8538; --brand-900:#1F5D28;
      --ink:#181a1f; --muted:#666b73; --border:#DCEFE6;
      --hover-tint: rgba(86,194,87,.12); --hover-ring:#BCE5D6; --hover-shadow:0 10px 24px rgba(86,194,87,.18);
      --viz-soft-bg:#e6f4ee;
      --viz-soft-bar-bg:rgba(86,194,87,.16);
    }

    section.vi-compact-embed.brand-vegasinsider{
      --brand-50:#FFF7DC;
      --brand-100:#FFE8AA;
      --brand-300:#FFE8AA;
      --brand-500:#F2C23A;
      --brand-600:#D9A72A;
      --brand-700:#B9851A;
      --brand-900:#111111;
      --border:#F2C23A;
      --hover-tint: rgba(242,194,58,.20);
      --hover-ring:#F2C23A;
      --hover-shadow:0 10px 24px rgba(0,0,0,.40);
      --viz-soft-bg:#FFF4D9;
      --viz-soft-bar-bg:rgba(242,194,58,.18);
    }

    section.vi-compact-embed.brand-canadasb{
      --brand-50:#FEF2F2;
      --brand-100:#FEE2E2;
      --brand-300:#FECACA;
      --brand-500:#EF4444;
      --brand-600:#DC2626;
      --brand-700:#B91C1C;
      --brand-900:#7F1D1D;
      --border:#FECACA;
      --hover-tint:#FBE9E9;
      --hover-ring:#FECACA;
      --hover-shadow:0 10px 24px rgba(127,29,29,.32);
      --viz-soft-bg:#FEE2E2;
      --viz-soft-bar-bg:rgba(239,68,68,.18);
    }

    section.vi-compact-embed.brand-rotogrinders{
      --brand-50:#E8F1FF;
      --brand-100:#D3E3FF;
      --brand-300:#9ABCF9;
      --brand-500:#2F7DF3;
      --brand-600:#0159D1;
      --brand-700:#0141A1;
      --brand-900:#011F54;
      --border:#9ABCF9;
      --hover-tint:rgba(1,65,161,.12);
      --hover-ring:#2F7DF3;
      --hover-shadow:0 10px 24px rgba(1,65,161,.35);
      --viz-soft-bg:#E3EEFF;
      --viz-soft-bar-bg:rgba(1,65,161,.20);
    }

    .vi-compact-embed .head{
      padding:14px 16px;border-bottom:1px solid var(--border)!important;color:#fff!important;
      background:
        radial-gradient(120% 140% at 85% 10%, rgba(255,255,255,.10) 0%, transparent 60%),
        linear-gradient(90deg,var(--brand-900) 0%,var(--brand-600) 45%,var(--brand-500) 100%)!important;
    }
    .vi-compact-embed .title{margin:0 0 2px;font-size:clamp(16px,2.2vw,20px);line-height:1.2;font-weight:800;color:#fff!important}
    .vi-compact-embed .sub{margin:0;color:rgba(255,255,255,.92)!important;font-size:12px}
    .vi-compact-embed .meta{margin:4px 0 0;color:rgba(255,255,255,.85)!important;font-size:12px}

    .vi-compact-embed .table{padding:10px 12px}
    .vi-compact-embed .row{
      display:grid;grid-template-columns:36px 1.6fr minmax(220px,1.2fr);gap:8px;align-items:center;margin:6px 0;
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
    .vi-compact-embed .city{display:flex;flex-direction:column;gap:2px;font-weight:700;color:var(--ink)}
    .vi-compact-embed .city-main{font-size:14px}
    .vi-compact-embed .city-sub{
      font-size:12px;
      color:var(--muted);
      display:flex;
      flex-wrap:wrap;
      gap:2px 10px;
      align-items:center;
    }
    .vi-compact-embed .city-sub .metric-pill{
      white-space:nowrap;
      display:inline-flex;
      align-items:center;
    }

    .vi-compact-embed .metric{
      position:relative;height:28px;border-radius:999px;background:#f9fafb;overflow:hidden;
    }
    .vi-compact-embed .bar{
      position:absolute;inset:0 auto 0 0;border-radius:999px;
      background:linear-gradient(90deg,var(--brand-600),var(--brand-500))!important;
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.04)
    }

    /* Fan Experience gradient bands – smoother 6-step scale */
    .vi-compact-embed .bar.fan-band.band-1{
      background:linear-gradient(90deg,var(--brand-100),var(--brand-50))!important;
    } /* very low */

    .vi-compact-embed .bar.fan-band.band-2{
      background:linear-gradient(90deg,var(--brand-300),var(--brand-100))!important;
    } /* low */

    .vi-compact-embed .bar.fan-band.band-3{
      background:linear-gradient(90deg,var(--brand-500),var(--brand-300))!important;
    } /* mid */

    .vi-compact-embed .bar.fan-band.band-4{
      background:linear-gradient(90deg,var(--brand-600),var(--brand-500))!important;
    } /* mid-high */

    .vi-compact-embed .bar.fan-band.band-5{
      background:linear-gradient(90deg,var(--brand-700),var(--brand-600))!important;
    } /* high */

    .vi-compact-embed .bar.fan-band.band-6{
      background:linear-gradient(90deg,var(--brand-900),var(--brand-700))!important;
    } /* elite */

    .vi-compact-embed .val{
      position:absolute;right:6px;top:50%;transform:translateY(-50%);
      font-variant-numeric:tabular-nums;font-weight:800;font-size:13px;
      color:#0e1a12!important;background:#fff!important;border:2px solid #e6e9ed!important;border-radius:999px;padding:2px 8px
    }

    .vi-compact-embed .details{
      margin:0;padding:0;border:1px solid var(--border);border-width:0;border-radius:12px;background:var(--brand-50);
      max-height:0;opacity:0;overflow:hidden;transform:translateY(-6px);
      transition:max-height .28s ease,opacity .28s ease,transform .28s ease,padding .20s ease,margin .20s ease,border-width .20s ease;
    }
    .vi-compact-embed .details.open{margin:8px 0 12px;padding:12px;border-width:1px;max-height:420px;opacity:1;transform:translateY(0)}
    .vi-compact-embed .metrics-title{margin:0 0 10px;font-weight:800;font-size:14px;color:var(--brand-700)}
    .vi-compact-embed .metrics-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
    @media (max-width:640px){.vi-compact-embed .metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media (max-width:380px){.vi-compact-embed .metrics-grid{grid-template-columns:1fr}}

    .vi-compact-embed .metric-card{
      background:#fff;border:1px solid var(--border);border-radius:10px;padding:12px;
      display:grid;grid-template-rows:auto auto auto auto;gap:6px;align-content:start;
    }
    .vi-compact-embed .metric-label{font-size:12px;color:var(--muted);font-weight:700;margin:0;line-height:1.2;display:flex;align-items:center;gap:4px}
    .vi-compact-embed .metric-label .icon{font-size:14px}
    .vi-compact-embed .metric-number{font-weight:800;font-size:19px;color:#0e1a1f;margin:0;line-height:1.1;font-variant-numeric:tabular-nums}
    .vi-compact-embed .metric-scale{font-size:11px;color:#8a9099;margin:0}

    .vi-compact-embed .mini-bar{height:10px;border-radius:999px;background:var(--viz-soft-bg);overflow:hidden;align-self:center}
    .vi-compact-embed .mini-bar .fill{display:block;height:100%;width:0%;border-radius:999px;background:linear-gradient(90deg,var(--brand-600),var(--brand-500));transition:width .6s ease}

    /* Walk score "step track" */
    .vi-compact-embed .step-track{
      display:flex;gap:4px;align-items:center;justify-content:flex-start;margin-top:2px;
    }
    .vi-compact-embed .step-track .step{
      width:10px;height:10px;border-radius:999px;background:var(--viz-soft-bg);
    }
    .vi-compact-embed .step-track .step.filled{
      background:linear-gradient(180deg,var(--brand-600),var(--brand-500));
    }

    .vi-compact-embed .donut{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px;align-items:center}
    .vi-compact-embed .donut svg{width:56px;height:56px}
    .vi-compact-embed .donut circle.bg{stroke:var(--viz-soft-bg);stroke-width:8;fill:none}
    .vi-compact-embed .donut circle.fg{stroke:var(--brand-600);stroke-width:8;fill:none;stroke-linecap:round;transform:rotate(-90deg);transform-origin:50% 50%;transition:stroke-dashoffset .7s ease}

    .vi-compact-embed .details-close{margin-top:10px;align-self:flex-end;background:#fff;border:1px solid var(--border);border-radius:999px;padding:6px 10px;font-weight:700;cursor:pointer}
    .vi-compact-embed .details-close:hover{border-color:var(--hover-ring)}

    .vi-compact-embed .row.is-clickable{cursor:pointer}
    .vi-compact-embed .row.is-clickable[aria-expanded="true"]{border-color:var(--brand-600)!important}

    /* Scroll area: keep footer visible, only rows scroll */
    .vi-compact-embed{
      --pane-max-h:min(88vh,860px);
      max-height:var(--pane-max-h);
      display:flex;
      flex-direction:column;
    }

    .vi-compact-embed .table{
      flex:1 1 auto;
      min-height:0;
      overflow:auto;
      -webkit-overflow-scrolling:touch;
      overscroll-behavior:contain;
      scrollbar-gutter:stable both-edges;
    }

    .vi-compact-embed .table::-webkit-scrollbar{width:10px;height:8px}
    .vi-compact-embed .table::-webkit-scrollbar-track{background:var(--brand-50);border-radius:999px}
    .vi-compact-embed .table::-webkit-scrollbar-thumb{
      background:linear-gradient(180deg,var(--brand-600),var(--brand-500));border-radius:999px;border:2px solid #fff;
    }

    /* Footer + embed button */
    .vi-compact-embed .vi-footer {
      display:block!important;text-align:center;padding:12px 0 4px;min-height:64px;
      border-top:1px solid var(--border);
      background:
        radial-gradient(120% 140% at 85% 10%, rgba(255,255,255,.10) 0%, transparent 60%),
        linear-gradient(90deg,var(--brand-900) 0%,var(--brand-600) 45%,var(--brand-500) 100%)!important;
      color:#fff;position:relative;overflow:visible;
    }
    .vi-compact-embed .footer-inner{
      display:flex;justify-content:center;align-items:center;gap:12px;position:relative;
    }
    .vi-compact-embed .embed-btn{
      position:absolute;left:14px;top:50%;transform:translateY(-50%);
      background:var(--brand-600);color:#fff;border:1px solid var(--brand-600);
      border-radius:8px;padding:6px 14px;font:13px/1.2 system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
      cursor:pointer;transition:.2s ease;
    }
    .vi-compact-embed .embed-btn:hover{background:var(--brand-700);border-color:var(--brand-700);}
    .vi-compact-embed .vi-footer img{
      height:40px;width:auto;display:inline-block;filter:brightness(0) invert(1);
    }
    section.vi-compact-embed.brand-actionnetwork .vi-footer img{height:44px}
    section.vi-compact-embed.brand-vegasinsider .vi-footer img{height:32px}
    section.vi-compact-embed.brand-canadasb .vi-footer img{height:40px}
    section.vi-compact-embed.brand-rotogrinders .vi-footer img{height:32px}

    .vi-compact-embed .embed-wrapper{
      position:absolute;bottom:calc(100% + 10px);left:50%;transform:translateX(-50%);
      width:min(600px, calc(100% - 24px));display:none;padding:16px 20px;border:1px solid #ccc;border-radius:12px;
      background:#fff;color:#111;box-shadow:0 12px 28px rgba(0,0,0,.18);z-index:1000;
    }
    .vi-compact-embed .embed-wrapper::after{
      content:"";position:absolute;left:50%;transform:translateX(-50%);bottom:-8px;
      border:8px solid transparent;border-top-color:#fff;filter:drop-shadow(0 1px 1px rgba(0,0,0,.08));
    }
    .vi-compact-embed #copy-status{display:none;color:#008000;font-size:13px;margin-top:6px;}
    .vi-compact-embed .embed-wrapper textarea{
      width:100%;height:140px;font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
      color:#111;background:#fff;padding:10px 12px;border:1px solid #ddd;border-radius:8px;resize:none;
    }

    /* Mobile overrides (mirror Supermoon behaviour) */
    @media (max-width:640px){
      html, body { height:auto !important; overflow:auto !important; }

      .vi-compact-embed{
        display:block;
        min-height:auto;
        overflow:visible;
        --pane-max-h:min(70vh,560px);
      }
      .vi-compact-embed .table{
        max-height:var(--pane-max-h)!important;
        overflow:auto!important;
        -webkit-overflow-scrolling:touch!important;
      }

      .vi-compact-embed .footer-inner{
        justify-content:space-between!important;
        padding:0 10px;
        gap:8px;
      }
      .vi-compact-embed .embed-btn{
        position:static!important;
        transform:none!important;
        padding:6px 10px;
        font-size:12px;
        flex-shrink:0;
      }
      .vi-compact-embed .vi-footer img{height:44px;}

      .vi-compact-embed .embed-wrapper{
        position:absolute!important;
        bottom:calc(100% + 10px)!important;
        left:50%!important;
        transform:translateX(-50%)!important;
        width:min(600px, calc(100% - 24px))!important;
        max-height:65vh;
        overflow:auto;
        z-index:1000;
      }

      .vi-compact-embed .details.open{max-height:none!important;}
      .vi-compact-embed .details{
        display:flex;
        flex-direction:column;
        scroll-margin-top:8px;
      }
      .vi-compact-embed .details-close{
        order:-1;
        align-self:flex-end;
        position:sticky;
        top:8px;
        z-index:5;
        padding:8px 12px;
        border-radius:999px;
        background:#fff;
        box-shadow:0 2px 6px rgba(0,0,0,.08);
      }
    }
  </style>

  <div class="head">
    <h3 id="vi-compact-embed-title" class="title">[[TITLE]]</h3>
    <p class="sub"><em>[[SUBTITLE]]</em></p>
    <p class="meta">Click <strong>a city</strong> to see women's stadium fan experience metrics.</p>
  </div>

  <div class="table">
    [[ROWS]]

    <div id="city-details" class="details" aria-hidden="true" role="region" aria-labelledby="metrics-title">
      <h4 id="metrics-title" class="metrics-title">Stadium Fan Experience for Women</h4>
      <div class="metrics-grid">
        <!-- Crime index -->
        <div class="metric-card">
          <div class="metric-label"><span class="icon">🚨</span>City Crime Index</div>
          <div class="metric-number"><span id="city-crime-val">0.0</span></div>
          <div class="mini-bar"><span id="city-crime-bar" class="fill"></span></div>
          <div class="metric-scale">Lower is safer</div>
        </div>

        <!-- Walk score -->
        <div class="metric-card">
          <div class="metric-label"><span class="icon">🚶</span>Stadium Walk Score</div>
          <div class="metric-number"><span id="city-walk-val">0.0</span></div>
          <div class="step-track" id="city-walk-steps" aria-hidden="true"></div>
          <div class="metric-scale">0 • 100</div>
        </div>

        <!-- Sentiment donut -->
        <div class="metric-card">
          <div class="metric-label"><span class="icon">😊</span>Stadium Sentiment</div>
          <div class="donut">
            <svg viewBox="0 0 72 72" aria-hidden="true">
              <circle class="bg" cx="36" cy="36" r="26"></circle>
              <circle id="city-sent-arc" class="fg" cx="36" cy="36" r="26" stroke-dasharray="0" stroke-dashoffset="0"></circle>
            </svg>
            <div>
              <div class="metric-number"><span id="city-sent-val">0%</span></div>
              <div class="metric-scale">Percent positive</div>
            </div>
          </div>
        </div>
      </div>
      <button id="city-close" class="details-close" type="button" aria-label="Close metrics">Close ✕</button>
    </div>
  </div>

  <div class="vi-footer">
    <div class="footer-inner">
      <button id="copy-embed-btn" class="embed-btn" aria-controls="embed-wrapper" aria-expanded="false">🔗 Embed This Table</button>
      <img src="[[BRAND_LOGO_URL]]"
           alt="[[BRAND_LOGO_ALT]]"
           width="120" height="auto" loading="lazy" decoding="async" />
    </div>

    <div id="embed-wrapper" class="embed-wrapper">
      <textarea id="embed-code" readonly>&lt;iframe src="[[EMBED_URL]]"
      title="[[TITLE]]"
      width="100%" height="650"
      scrolling="no"
      style="border:0;" loading="lazy"&gt;&lt;/iframe&gt;
      </textarea>
      <p id="copy-status">Embed code copied!</p>
    </div>
  </div>

  <script>
    (function(){
      const DATA = [[DATA]];

      const rows   = document.querySelectorAll('.vi-compact-embed .row.is-clickable[data-city]');
      const panel  = document.getElementById('city-details');
      const closeB = document.getElementById('city-close');

      function setBar(id, value, max){
        const el = document.getElementById(id);
        if(!el || max <= 0) return;
        const pct = Math.max(0, Math.min(1, value / max)) * 100;
        el.style.width = pct.toFixed(1) + '%';
      }

      function setDonut(id, pctVal){
        const arc = document.getElementById(id);
        if(!arc) return;
        const r=26, C=2*Math.PI*r;
        arc.style.strokeDasharray = C.toFixed(1);
        arc.style.strokeDashoffset = C.toFixed(1);
        const pct = Math.max(0, Math.min(1, pctVal/100));
        requestAnimationFrame(()=> arc.style.strokeDashoffset = (C*(1-pct)).toFixed(1));
      }

      function buildWalkSteps(score){
        const track = document.getElementById('city-walk-steps');
        if(!track) return;
        track.innerHTML = '';
        const total = 10;
        const safeScore = Math.max(0, Math.min(100, score));
        const filled = Math.round(safeScore / 10);
        for(let i=0;i<total;i++){
          const dot = document.createElement('span');
          dot.className = 'step';
          if(i < filled) dot.classList.add('filled');
          track.appendChild(dot);
        }
      }

      function renderCity(name){
        const d = DATA[name];
        if(!d) return;

        const title = document.getElementById('metrics-title');
        if(title) title.textContent = name + ' — Stadium Fan Experience for Women';

        const cv = document.getElementById('city-crime-val');
        const wv = document.getElementById('city-walk-val');
        const sv = document.getElementById('city-sent-val');

        if(cv) cv.textContent = d.crime.toFixed(2);
        if(wv) wv.textContent = d.walk.toFixed(1);
        if(sv) sv.textContent = d.sentiment.toFixed(1) + '%';

        // Crime bar: inverted (lower crime => more green)
        setBar('city-crime-bar', 100 - d.crime, 100);

        // Walk steps
        buildWalkSteps(d.walk);

        // Sentiment donut
        setDonut('city-sent-arc', d.sentiment);
      }

      function openUnderRow(row){
        const city = row.dataset.city;
        row.after(panel);
        document.querySelectorAll('.vi-compact-embed .row.is-clickable[aria-expanded]')
          .forEach(r=>r.setAttribute('aria-expanded','false'));
        row.setAttribute('aria-expanded','true');

        if(!panel.classList.contains('open')){
          panel.classList.add('open');
          panel.setAttribute('aria-hidden','false');
        }
        renderCity(city);
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

        document.addEventListener('click', (e)=>{
          const open = wrapper.style.display === 'block';
          if (open && !wrapper.contains(e.target) && !btn.contains(e.target)) {
            wrapper.style.display = 'none';
            btn.setAttribute('aria-expanded','false');
            btn.textContent = '🔗 Embed This Table';
            sendHeightToParent();
          }
        });

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

# === 2. Generator: build rows + DATA ==================================

def generate_html_from_df(
    df: pd.DataFrame,
    title: str,
    subtitle: str,
    embed_url: str,
    brand_logo_url: str,
    brand_logo_alt: str,
    brand_class: str,
) -> str:
    df = df.copy()
    df = df.sort_values("rank", ascending=True).reset_index(drop=True)

    max_fan = float(df["fan_score"].max() or 1.0)

    def band_for_fan(score: float) -> str:
        # 6 bands for smoother color steps
        if score >= 75.0:
            return "band-6"
        elif score >= 65.0:
            return "band-5"
        elif score >= 55.0:
            return "band-4"
        elif score >= 45.0:
            return "band-3"
        elif score >= 35.0:
            return "band-2"
        else:
            return "band-1"

    row_snippets = []
    for _, row in df.iterrows():
        rank = int(row["rank"])
        city = str(row["city"])
        crime = float(row["crime_index"])
        walk = float(row["walk_score"])
        sent = float(row["sentiment_pct"])
        fan = float(row["fan_score"])

        width_pct = fan / max_fan * 100.0
        bar_style = f"width:{width_pct:.2f}%;"
        band_class = band_for_fan(fan)

        subtitle_line = (
            f'<span class="metric-pill">🚨 Crime index: {crime:.2f}</span>'
            f' &nbsp;•&nbsp; '
            f'<span class="metric-pill">🚶 Walk score: {walk:.1f}</span>'
            f' &nbsp;•&nbsp; '
            f'<span class="metric-pill">😊 Sentiment: {sent:.1f}%</span>'
        )

        row_html = f"""
    <div class="row is-clickable" data-city="{city}" data-rank="{rank}" aria-expanded="false" tabindex="0" role="button">
      <div class="rank">{rank}</div>
      <div class="city">
        <span class="city-main">{city}</span>
        <span class="city-sub">{subtitle_line}</span>
      </div>
      <div class="metric">
        <span class="bar fan-band {band_class}" style="{bar_style}"></span>
        <span class="val">{fan:.2f}</span>
      </div>
    </div>""".rstrip()
        row_snippets.append(row_html)

    rows_html = "\n\n".join(row_snippets)

    data_lines = []
    for _, row in df.iterrows():
        city = str(row["city"])
        crime = float(row["crime_index"])
        walk = float(row["walk_score"])
        sentiment = float(row["sentiment_pct"])
        fan = float(row["fan_score"])
        data_lines.append(
            f'        "{city}":  {{ crime:{crime:.2f}, walk:{walk:.2f}, sentiment:{sentiment:.2f}, fan:{fan:.2f} }}'
        )
    data_js = "{\n" + ",\n".join(data_lines) + "\n      }"

    html = (
        HTML_TEMPLATE
        .replace("[[ROWS]]", rows_html)
        .replace("[[DATA]]", data_js)
        .replace("[[TITLE]]", title)
        .replace("[[SUBTITLE]]", subtitle)
        .replace("[[EMBED_URL]]", embed_url)
        .replace("[[BRAND_LOGO_URL]]", brand_logo_url)
        .replace("[[BRAND_LOGO_ALT]]", brand_logo_alt)
        .replace("[[BRAND_CLASS]]", brand_class or "")
    )

    return html

# === 3. Streamlit App ================================================

st.set_page_config(page_title="Women's Stadium Fan Experience Table Generator", layout="wide")

st.title("Women's Stadium Fan Experience Table Generator")
st.write(
    "Upload a CSV, choose a brand and GitHub campaign, then click **Update widget** "
    "to publish your women's stadium fan experience table via GitHub Pages."
)

# Brand selection
brand_options = [
    "Action Network",
    "VegasInsider",
    "Canada Sports Betting",
    "RotoGrinders",
]
default_brand = st.session_state.get("brand", "Action Network")
if default_brand not in brand_options:
    default_brand = "Action Network"

brand = st.selectbox(
    "Choose a brand",
    options=brand_options,
    index=brand_options.index(default_brand),
    key="brand",
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
        "Rank",
        "City",
        "City Crime Index",
        "Stadium Walk Score",
        "Stadium Sentiment (%)",
        "Fan Experience Score",
    ]
    missing = [c for c in required_cols if c not in raw_df.columns]
    if missing:
        st.error(f"Missing required columns in CSV: {missing}")
        st.stop()

    df = pd.DataFrame()
    df["rank"] = raw_df["Rank"].astype(int)
    df["city"] = raw_df["City"].astype(str)
    df["crime_index"] = raw_df["City Crime Index"].astype(float)
    df["walk_score"] = raw_df["Stadium Walk Score"].astype(float)
    df["sentiment_pct"] = (
        raw_df["Stadium Sentiment (%)"]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.strip()
        .astype(float)
    )
    df["fan_score"] = raw_df["Fan Experience Score"].astype(float)

    # Defaults for widget text
    default_title = "Ranking 50 U.S. Cities for Women's Stadium Fan Experience"
    default_subtitle = (
        "All 50 cities in our dataset ranked on women's stadium fan experience, based on "
        "city crime index, walkability, stadium sentiment, and an overall fan experience score."
    )

    # ---------- GitHub / hosting settings ----------
    saved_gh_user = st.session_state.get("gh_user", "")
    saved_gh_repo = st.session_state.get("gh_repo", "stadium-fan-experience-widget")

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
        key="gh_user",
    )
    effective_github_user = github_username_input.strip()

    repo_name = st.text_input(
        "Widget hosting repository name (leave no spaces; letters, numbers and underscores are fine)",
        value=saved_gh_repo,
        key="gh_repo",
    )

    base_filename = "stadium_fan_experience.html"
    widget_file_name = st.session_state.get("widget_file_name", base_filename)

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

    iframe_snippet = st.session_state.get("iframe_snippet")

    # ---------- Button row: Page availability check & Update widget ----------
    col_check, col_get = st.columns([1, 1])

    if not GITHUB_TOKEN:
        with col_get:
            st.info(
                "Set `GITHUB_TOKEN` in `.streamlit/secrets.toml` (with `repo` scope) "
                "to enable automatic GitHub publishing."
            )
    elif not effective_github_user or not repo_name.strip():
        with col_get:
            st.info("Fill in username and campaign name above.")
    else:
        # --- Page availability check button ---
        with col_check:
            if st.button("Page availability check"):
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

                    st.session_state["availability"] = {
                        "repo_exists": repo_exists,
                        "file_exists": file_exists,
                        "checked_filename": base_filename,
                        "suggested_new_filename": next_fname,
                    }
                    st.session_state.setdefault("widget_file_name", base_filename)

                except Exception as e:
                    st.error(f"Availability check failed: {e}")

        # --- Update widget button (publishes to GitHub) ---
        with col_get:
            if st.button("Update widget"):
                try:
                    progress_placeholder = st.empty()
                    progress = progress_placeholder.progress(0)

                    for pct in (20, 45, 70):
                        time.sleep(0.12)
                        progress.progress(pct)

                    title_for_publish = st.session_state.get("widget_title", default_title)
                    subtitle_for_publish = st.session_state.get("widget_subtitle", default_subtitle)
                    brand_for_publish = st.session_state.get("brand", brand)
                    brand_meta_publish = get_brand_meta(brand_for_publish)

                    widget_file_name = st.session_state.get("widget_file_name", base_filename)
                    expected_embed_url = compute_expected_embed_url(
                        effective_github_user, repo_name, widget_file_name
                    )

                    html_final = generate_html_from_df(
                        df,
                        title_for_publish,
                        subtitle_for_publish,
                        expected_embed_url,
                        brand_meta_publish["logo_url"],
                        brand_meta_publish["logo_alt"],
                        brand_meta_publish["brand_class"],
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
                        pass  # soft failure

                    upload_file_to_github(
                        effective_github_user,
                        repo_name.strip(),
                        GITHUB_TOKEN,
                        widget_file_name,
                        html_final,
                        f"Add/update {widget_file_name} from Streamlit app",
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
  width="100%" height="650"
  scrolling="no"
  style="border:0;" loading="lazy"></iframe>"""

                    st.session_state["iframe_snippet"] = iframe_snippet
                    st.session_state["has_generated"] = True

                    st.success("Widget iframe updated. Open the tabs below to preview and embed it.")

                except Exception as e:
                    progress_placeholder.empty()
                    st.error(f"GitHub publish failed: {e}")

    # ---------- Availability result + options ----------
    availability = st.session_state.get("availability")
    if GITHUB_TOKEN and effective_github_user and repo_name.strip():
        if availability:
            repo_exists = availability.get("repo_exists", False)
            file_exists = availability.get("file_exists", False)
            checked_filename = availability.get("checked_filename", base_filename)
            suggested_new_filename = availability.get("suggested_new_filename") or "w1.html"

            if not repo_exists:
                st.info(
                    "No existing repo found for this campaign. "
                    "When you click **Update widget**, the repo will be created and "
                    f"your widget will be saved as `{checked_filename}`."
                )
                st.session_state["widget_file_name"] = checked_filename
            elif repo_exists and not file_exists:
                st.success(
                    f"Repo exists and `{checked_filename}` is available. "
                    "Update widget will save your table to this file."
                )
                st.session_state["widget_file_name"] = checked_filename
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
                    key="file_conflict_choice",
                )
                if choice.startswith("Replace"):
                    st.session_state["widget_file_name"] = checked_filename
                    st.info(f"Update widget will overwrite `{checked_filename}` in this repo.")
                elif choice.startswith("Create additional"):
                    st.session_state["widget_file_name"] = suggested_new_filename
                    st.info(
                        f"Update widget will create a new file `{suggested_new_filename}` "
                        "in the same repo for this widget."
                    )
                else:
                    st.info(
                        "Update the campaign name above, then run **Page availability check** again."
                    )

    st.markdown("---")

    # ---------- Output tabs ----------
    has_generated = st.session_state.get("has_generated", False)
    show_tabs = has_generated or not GITHUB_TOKEN  # allow preview when token missing

    widget_file_name = st.session_state.get("widget_file_name", base_filename)
    expected_embed_url = compute_expected_embed_url(
        effective_github_user, repo_name, widget_file_name
    )

    if show_tabs:
        tab_config, tab_embed = st.tabs(
            [
                "Configure & preview widget",
                "Widget HTML/Iframe",
            ]
        )

        with tab_config:
            col_title, col_sub = st.columns(2)

            with col_title:
                widget_title = st.text_input(
                    "Widget name",
                    value=st.session_state.get("widget_title", default_title),
                    key="widget_title",
                )

            with col_sub:
                widget_subtitle = st.text_input(
                    "Widget subtitle",
                    value=st.session_state.get("widget_subtitle", default_subtitle),
                    key="widget_subtitle",
                )

            brand_meta_preview = get_brand_meta(st.session_state.get("brand", brand))

            html_preview = generate_html_from_df(
                df,
                widget_title,
                widget_subtitle,
                expected_embed_url,
                brand_meta_preview["logo_url"],
                brand_meta_preview["logo_alt"],
                brand_meta_preview["brand_class"],
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
                if st.session_state.get("iframe_snippet"):
                    st.code(st.session_state["iframe_snippet"], language="html")
                else:
                    st.info("No iframe yet – click **Update widget** above to generate it.")
