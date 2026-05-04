# ============================================================
#  WordPress SEO Studio  —  Unified V1 + V2 • V20 Stable Fast API
#  Tab 1: SEO Formatter  (from V1 — article → Yoast fields)
#  Tab 2: Image SEO      (from V2 — upload/crop/AI generate)
#  NEW: AI Generate SEO Fields + Character Counters
#  FIXED: Embed (Twitter/YouTube/Facebook) in SEO Output + WP HTML
#  MODIFIED: Removed bottom 4-panel options display (kept all logic)
# ============================================================
import os
import sys
import subprocess
import shutil
import io
import re
import html
import json
import base64
import threading
import tempfile
from difflib import SequenceMatcher
import html as html_mod
import requests
import time
import random
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk, ImageEnhance, ImageFilter

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception

# ── Together AI config ────────────────────────────────────────────────────────
TOGETHER_BASE_URL      = "https://api.together.xyz/v1"
VISION_MODEL           = "moonshotai/Kimi-K2.5"
VISION_FALLBACK_MODEL  = "moonshotai/Kimi-K2.5"
SEO_MODEL              = "Qwen/Qwen2.5-7B-Instruct-Turbo"

# ── OpenAI config ─────────────────────────────────────────────────────────────
OPENAI_BASE_URL        = "https://api.openai.com/v1"
OPENAI_MODEL           = "gpt-4o"

# API-only optimization (keep UI/tool logic unchanged)
API_CONNECT_TIMEOUT    = 6
API_READ_TIMEOUT       = 30
API_VERIFY_TIMEOUT     = 8
API_MAX_RETRIES        = 0
API_RETRY_BACKOFF      = 0.35
API_USE_SESSION        = True
API_ENABLE_CHEAP_FALLBACK = True
API_DEFAULT_TEMPERATURE = 0.2
API_DEFAULT_TOP_P       = 0.9
API_MAX_TOKENS_SEO      = 420
API_MAX_TOKENS_VISION   = 260

# Ultra-fast / money-saving paths for specific heavy actions
AI_FAST_MODE = True
FAST_SEO_FIELDS_MODEL = SEO_MODEL
FAST_SEO_FIELDS_FALLBACK_MODEL = ""
FAST_IMAGE_SEO_MODEL = "moonshotai/Kimi-K2.5"
FAST_IMAGE_SEO_FALLBACK_MODEL = "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo"
FAST_AI_TIMEOUT = 24
FAST_IMAGE_TIMEOUT = 30   # Kimi-K2.5 needs up to 30s
FAST_SEO_FIELD_MAX_TOKENS = 220
FAST_IMAGE_SEO_MAX_TOKENS = 200

# Optional: if Twitter/X source only contains a tweet ID and no username,
# set this to a public account username like "RepSwalwell" to force
# final SEO Output / WP HTML to use https://twitter.com/USERNAME/status/ID
# instead of https://twitter.com/i/web/status/ID. Leave blank to disable.
FORCED_TWITTER_USERNAME = "RepSwalwell"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Update Configuration ──────────────────────────────────────────────────────
APP_VERSION = "1.5"
# This is the URL where the tool will check for updates.
# You can host a JSON file on GitHub Gist or your server.
# Format: {"version": "1.2", "url": "https://.../ImageSEOPromptENDVision1.2.py"}
UPDATE_JSON_URL = "https://gist.githubusercontent.com/username/gist_id/raw/version.json"
# ──────────────────────────────────────────────────────────────────────────────


def _forced_public_twitter_url(tweet_id: str, fallback_url: str = "") -> str:
    tweet_id = str(tweet_id or "").strip()
    fallback_url = str(fallback_url or "").strip()
    forced_username = str(globals().get("FORCED_TWITTER_USERNAME", "") or "").strip().lstrip("@")
    if tweet_id and forced_username:
        return f"https://twitter.com/{forced_username}/status/{tweet_id}"
    if fallback_url:
        return fallback_url
    if tweet_id:
        return _forced_public_twitter_url(tweet_id)
    return ""


def rewrite_twitter_embed_urls(html_text: str) -> str:
    html_text = str(html_text or "")

    def _replace_iweb(m):
        return _forced_public_twitter_url(m.group(1), m.group(0))

    html_text = re.sub(r'https?://(?:www\.)?twitter\.com/i/web/status/(\d+)', _replace_iweb, html_text, flags=re.I)

    def _replace_platform(m):
        url = html_mod.unescape(m.group(0))
        tid = re.search(r'[?&](?:id|tweetId)=(\d+)', url, re.I)
        if not tid:
            tid = re.search(r'data-tweet-id=["\'](\d+)["\']', url, re.I)
        if tid:
            return _forced_public_twitter_url(tid.group(1), url)
        return url

    html_text = re.sub(r'https?://platform\.twitter\.com/embed/Tweet\.html\?[^"\'\s<]+', _replace_platform, html_text, flags=re.I)
    return html_text


def optimize_image_for_api(pil_image, max_side=960, jpeg_quality=82):
    img = pil_image.copy().convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest > max_side:
        scale = max_side / float(longest)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=jpeg_quality, optimize=True)
    return bio.getvalue(), "image/jpeg"


def _preferred_picture_dir() -> str:
    candidates = []
    home = os.path.expanduser("~")
    if home:
        candidates.append(os.path.join(home, "Downloads"))
        candidates.append(os.path.join(home, "Desktop"))
        candidates.append(home)
    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            return folder
        except Exception:
            continue
    return os.getcwd()


def _export_settings_file() -> str:
    home = os.path.expanduser("~") or os.getcwd()
    base_dir = os.path.join(home, ".wordpressseostudio")
    try:
        os.makedirs(base_dir, exist_ok=True)
    except Exception:
        return os.path.join(os.getcwd(), "export_settings.json")
    return os.path.join(base_dir, "export_settings.json")


def load_export_folder() -> str:
    default_dir = _preferred_picture_dir()
    settings_file = _export_settings_file()
    try:
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            folder = str(data.get("export_folder", "") or "").strip()
            if folder:
                os.makedirs(folder, exist_ok=True)
                return folder
    except Exception:
        pass
    return default_dir


def save_export_folder(folder: str) -> str:
    folder = os.path.abspath(os.path.expanduser(str(folder or "").strip()))
    if not folder:
        folder = _preferred_picture_dir()
    os.makedirs(folder, exist_ok=True)
    settings_file = _export_settings_file()
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump({"export_folder": folder}, f, ensure_ascii=False, indent=2)
    return folder


def auto_save_export_image(pil_image, original_path: str = "", max_kb: int = 100, save_dir: str = "") -> tuple:
    img = pil_image.copy().convert("RGB")
    w, h = img.size
    if w < 1400:
        s = max(1.2, 1400 / max(w, 1))
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    img = ImageEnhance.Sharpness(img).enhance(1.35)
    img = ImageEnhance.Contrast(img).enhance(1.03)

    base_dir = save_export_folder(save_dir) if str(save_dir or "").strip() else load_export_folder()
    os.makedirs(base_dir, exist_ok=True)

    src_name = os.path.splitext(os.path.basename(original_path or "image"))[0]
    src_name = re.sub(r"[^A-Za-z0-9_-]+", "_", src_name).strip("_") or "image"
    rand = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_path = os.path.join(base_dir, f"{src_name}_{stamp}_{rand}.jpg")

    best_bytes = None
    best_q = None
    for q in range(95, 14, -5):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if len(buf.getvalue()) / 1024 <= max_kb:
            best_bytes = buf.getvalue()
            best_q = q
            break

    if best_bytes is None:
        tmp = img.copy()
        q = 85
        while True:
            buf = io.BytesIO()
            tmp.save(buf, "JPEG", quality=q, optimize=True)
            if len(buf.getvalue()) / 1024 <= max_kb or min(tmp.size) < 200:
                best_bytes = buf.getvalue()
                best_q = q
                break
            ew, eh = tmp.size
            tmp = tmp.resize((max(1, int(ew * .92)), max(1, int(eh * .92))), Image.LANCZOS)

    with open(save_path, 'wb') as f:
        f.write(best_bytes)

    return save_path, os.path.getsize(save_path) / 1024.0, best_q


# ══════════════════════════════════════════════════════════════════════════════
#  SMART CHARSET / DECODE HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _smart_charset(raw_bytes: bytes, content_type: str = "") -> str:
    m = re.search(r"charset=([\w-]+)", content_type, re.I)
    if m:
        cs = m.group(1).strip().lower()
        if cs and cs not in ("utf-8", "utf8"):
            return cs
    sniff = raw_bytes[:8192].decode("ascii", errors="ignore")
    for pat in [
        r'<meta[^>]+charset=["\']?([\w-]+)',
        r'<meta[^>]+content=["\'][^"\']*charset=([\w-]+)',
        r'charset\s*=\s*["\']?([\w-]+)',
    ]:
        mm = re.search(pat, sniff, re.I)
        if mm:
            cs = mm.group(1).strip().lower()
            if cs and cs not in ("utf-8", "utf8"):
                return cs
    try:
        import chardet
        r = chardet.detect(raw_bytes[:32768])
        if r and r.get("confidence", 0) >= 0.75:
            cs = (r.get("encoding") or "").lower().strip()
            if cs and cs not in ("utf-8", "utf8", "ascii"):
                return cs
    except ImportError:
        try:
            from charset_normalizer import from_bytes as _fn
            best = _fn(raw_bytes[:32768]).best()
            if best:
                cs = str(best.encoding).lower()
                if cs and cs not in ("utf-8", "utf8", "ascii"):
                    return cs
        except ImportError:
            pass
    if raw_bytes.startswith(b"\xff\xfe"):      return "utf-16-le"
    if raw_bytes.startswith(b"\xfe\xff"):      return "utf-16-be"
    if raw_bytes.startswith(b"\xef\xbb\xbf"):  return "utf-8-sig"
    return "utf-8"


def _smart_decode(raw_bytes: bytes, charset: str) -> str:
    if raw_bytes[:2] == b"\x1f\x8b":
        try:
            import gzip
            raw_bytes = gzip.decompress(raw_bytes)
        except Exception:
            pass
    ATTEMPTS = [charset, "utf-8", "utf-8-sig", "windows-1252",
                "cp1250", "iso-8859-1", "latin-1"]
    seen: set = set()
    for enc in ATTEMPTS:
        enc = (enc or "").strip().lower()
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            text = raw_bytes.decode(enc, errors="strict")
            bad_ratio = text.count("\ufffd") / max(len(text), 1)
            if bad_ratio < 0.02:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode("latin-1", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
#  THEME
# ══════════════════════════════════════════════════════════════════════════════
class T:
    APP_BG        = "#010d1e"
    PANEL_BG      = "#071629"
    PANEL_BG_2    = "#050f1e"
    PANEL_BORDER  = "#1e3d6e"
    INPUT_BG      = "#030d1d"
    INPUT_BORDER  = "#1e3a6a"
    TEXT_MAIN     = "#e8f0ff"
    TEXT_SOFT     = "#8eaacc"
    PLACEHOLDER   = "#4a6380"
    GREEN         = "#15803d"
    GREEN_H       = "#166534"
    BLUE          = "#1e3a70"
    BLUE_H        = "#1e40af"
    BLUE_BORDER   = "#2563eb"
    RED           = "#b91c1c"
    RED_H         = "#991b1b"
    YELLOW        = "#b45309"
    YELLOW_H      = "#92400e"
    PURPLE        = "#6d28d9"
    PURPLE_H      = "#5b21b6"
    CYAN          = "#0e7490"
    CYAN_H        = "#0c6479"
    TEAL          = "#0f766e"
    TEAL_H        = "#115e59"
    COUNTER_OK    = "#22c55e"
    COUNTER_WARN  = "#f59e0b"
    COUNTER_BAD   = "#ef4444"


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED WIDGETS
# ══════════════════════════════════════════════════════════════════════════════
class Btn(ctk.CTkButton):
    _PAL = {
        "green":  (T.GREEN,  T.GREEN_H,  None),
        "blue":   (T.BLUE,   T.BLUE_H,   T.BLUE_BORDER),
        "red":    (T.RED,    T.RED_H,    None),
        "yellow": (T.YELLOW, T.YELLOW_H, None),
        "purple": (T.PURPLE, T.PURPLE_H, None),
        "cyan":   (T.CYAN,   T.CYAN_H,   None),
        "teal":   (T.TEAL,   T.TEAL_H,   None),
    }
    def __init__(self, master, text, command, kind="blue",
                 width=None, height=36, **kw):
        fg, hv, bd = self._PAL.get(kind, self._PAL["blue"])
        if width is None:
            width = max(80, len(text) * 9 + 28)
        super().__init__(
            master, text=text, command=command,
            width=width, height=height, corner_radius=18,
            fg_color=fg, hover_color=hv,
            border_width=1 if bd else 0, border_color=bd or fg,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            **kw,
        )


def field_label(master, text):
    return ctk.CTkLabel(
        master, text=text,
        font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        text_color=T.TEXT_SOFT, anchor="w",
    )


def text_box(master, height=80, readonly=False):
    w = ctk.CTkTextbox(
        master, height=height, corner_radius=8,
        fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1,
        text_color=T.TEXT_MAIN,
        font=ctk.CTkFont(family="Segoe UI", size=12),
    )
    if readonly:
        w.configure(state="disabled")
    return w


def entry_box(master, placeholder=""):
    return ctk.CTkEntry(
        master, height=34, corner_radius=8,
        fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1,
        text_color=T.TEXT_MAIN,
        font=ctk.CTkFont(family="Segoe UI", size=12),
        placeholder_text=placeholder,
        placeholder_text_color=T.PLACEHOLDER,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  API KEY MANAGER
# ══════════════════════════════════════════════════════════════════════════════
class APIKeyManager:
    def __init__(self, app_name="WordPressSEOStudio"):
        self.base_dir  = os.path.join(os.path.expanduser("~"), f".{app_name.lower()}")
        self.data_file = os.path.join(self.base_dir, "settings.dat")
        self.key_file  = os.path.join(self.base_dir, "machine.key")
        try:
            os.makedirs(self.base_dir, exist_ok=True)
        except Exception:
            pass

    def encryption_available(self):
        return Fernet is not None

    def _get_or_create_fernet_key(self) -> bytes:
        if Fernet is None:
            raise RuntimeError("cryptography package not installed.")
        if os.path.exists(self.key_file):
            try:
                with open(self.key_file, "rb") as f:
                    key = f.read().strip()
                Fernet(key)
                return key
            except Exception:
                pass
        key = Fernet.generate_key()
        try:
            with open(self.key_file, "wb") as f:
                f.write(key)
        except Exception as e:
            raise RuntimeError(f"Cannot write key file: {self.key_file}\n{e}")
        return key

    def _fernet(self):
        return Fernet(self._get_or_create_fernet_key())

    def save(self, together_key: str, openai_key: str = ""):
        together_key = (together_key or "").strip()
        openai_key   = (openai_key or "").strip()
        payload = json.dumps({
            "together_api_key": together_key,
            "openai_api_key": openai_key,
            "v": 3
        }).encode()
        if Fernet is not None:
            try:
                enc = self._fernet().encrypt(payload)
                with open(self.data_file, "wb") as f:
                    f.write(b"ENC:" + enc)
                return
            except Exception as e:
                raise RuntimeError(f"Encryption failed: {e}")
        ob = base64.b64encode(payload)
        with open(self.data_file, "wb") as f:
            f.write(b"OB1:" + ob)

    def load(self) -> dict:
        default = {"together": "", "openai": ""}
        if not os.path.exists(self.data_file):
            return default
        try:
            with open(self.data_file, "rb") as f:
                raw = f.read().strip()
            payload = b""
            if raw.startswith(b"ENC:") and Fernet is not None:
                payload = self._fernet().decrypt(raw[4:])
            elif raw.startswith(b"OB1:"):
                payload = base64.b64decode(raw[4:])
            elif Fernet is not None:
                try:
                    payload = self._fernet().decrypt(raw)
                except Exception:
                    pass
            
            if not payload:
                try:
                    data = json.loads(raw)
                except Exception:
                    return default
            else:
                data = json.loads(payload)
            
            return {
                "together": data.get("together_api_key", ""),
                "openai": data.get("openai_api_key", "")
            }
        except Exception:
            pass
        return default

    def clear(self):
        for path in (self.data_file,):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
#  TOGETHER AI helpers
# ══════════════════════════════════════════════════════════════════════════════
_API_SESSION = None


def get_api_session():
    global _API_SESSION
    if _API_SESSION is not None and API_USE_SESSION:
        return _API_SESSION

    sess = requests.Session()
    adapter = HTTPAdapter(max_retries=0, pool_connections=10, pool_maxsize=10)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    if API_USE_SESSION:
        _API_SESSION = sess
    return sess


def _headers(key):
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "keep-alive",
    }


def verify_key(api_key, timeout=API_VERIFY_TIMEOUT):
    sess = get_api_session()
    r = sess.get(
        f"{TOGETHER_BASE_URL}/models",
        headers=_headers(api_key),
        timeout=(API_CONNECT_TIMEOUT, timeout),
    )
    if r.status_code >= 400:
        try:
            d = r.json(); detail = d.get("error", {}).get("message") or d.get("message") or r.text
        except Exception:
            detail = r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


def chat_completion(api_key, model, messages, temperature=API_DEFAULT_TEMPERATURE,
                    timeout=API_READ_TIMEOUT, response_format=None, top_p=API_DEFAULT_TOP_P,
                    reasoning=None, max_tokens=None):
    sess = get_api_session()
    
    # Determine provider based on model name
    is_openai = str(model).lower().startswith("gpt-")
    base_url = OPENAI_BASE_URL if is_openai else TOGETHER_BASE_URL
    
    payload = {"model": model, "messages": messages, "temperature": temperature, "top_p": top_p}
    if response_format:
        payload["response_format"] = response_format
    if reasoning is not None and not is_openai: # OpenAI doesn't use the same reasoning parameter
        payload["reasoning"] = reasoning
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    last_err = None
    for attempt in range(API_MAX_RETRIES + 1):
        try:
            r = sess.post(
                f"{base_url}/chat/completions",
                headers=_headers(api_key),
                json=payload,
                timeout=(API_CONNECT_TIMEOUT, timeout),
            )
            if r.status_code >= 400:
                try:
                    d = r.json(); detail = d.get("error", {}).get("message") or d.get("message") or r.text
                except Exception:
                    detail = r.text
                if not is_openai and API_ENABLE_CHEAP_FALLBACK and model == SEO_MODEL and r.status_code in (429, 500, 502, 503, 504):
                    fallback_payload = dict(payload)
                    fallback_payload["model"] = "meta-llama/Llama-3.2-3B-Instruct-Turbo"
                    rr = sess.post(
                        f"{TOGETHER_BASE_URL}/chat/completions",
                        headers=_headers(api_key),
                        json=fallback_payload,
                        timeout=(API_CONNECT_TIMEOUT, timeout),
                    )
                    if rr.status_code < 400:
                        return rr.json()
                raise RuntimeError(f"HTTP {r.status_code}: {detail}")
            return r.json()
        except Exception as e:
            last_err = e
            if attempt >= API_MAX_RETRIES:
                break
            sleep_s = (API_RETRY_BACKOFF ** attempt) + random.uniform(0.1, 0.35)
            time.sleep(sleep_s)
    raise RuntimeError(str(last_err) if last_err else "Unknown API request error")


def extract_content(resp):
    choices = resp.get("choices") or []
    if not choices: return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                t = item.get("text") or item.get("content") or ""
                if t: parts.append(str(t))
            elif item:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content or "").strip()


def parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Model returned empty content")

    def _repair_json_candidate(s: str) -> str:
        s = str(s or "").strip()
        if not s:
            return s
        s = s.replace("```json", "").replace("```", "").strip()
        s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            s = m.group(0).strip()
        if s and not s.startswith("{") and "{" in s:
            s = s[s.find("{"): ]
        if s and not s.endswith("}") and "}" in s:
            s = s[: s.rfind("}") + 1]
        s = re.sub(r'^\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*"\s*:', r'{"\1":', s)
        s = re.sub(r'([\{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s)
        s = re.sub(r':\s*"([^"\\]*(?:\\.[^"\\]*)*)"(?=\s*")', r': "\1", ', s)
        s = re.sub(r'"\s*([A-Za-z_][A-Za-z0-9_]*)\s*"\s*"\s*:', r'"\1":', s)
        s = re.sub(r',\s*([}\]])', r'\1', s)
        return s.strip()

    def _regex_extract_fields(s: str) -> dict:
        s = _repair_json_candidate(s)
        expected_keys = [
            "focus_keyphrase", "seo_title_1", "seo_title_2", "seo_title_3",
            "meta_description_1", "meta_description_2", "meta_description_3",
            "alt_text", "img_title", "caption",
        ]
        result = {}
        for i, key in enumerate(expected_keys):
            nxt = "|".join(re.escape(k) for k in expected_keys[i+1:])
            if nxt:
                pat = rf'["\{{,\s]{re.escape(key)}"?\s*:\s*"(.*?)"\s*(?=,\s*(?:"?(?:{nxt})"?\s*:)|\s*\}})'
            else:
                pat = rf'["\{{,\s]{re.escape(key)}"?\s*:\s*"(.*?)"\s*(?=\s*\}}|$)'
            m = re.search(pat, s, re.S)
            if m:
                val = m.group(1)
                val = val.replace('\"', '"').replace("\\n", " ").replace("\\t", " ")
                val = re.sub(r"\s+", " ", val).strip()
                result[key] = val
        return result

    candidates = []
    seen = set()
    for cand in [raw, raw.replace("```json", "").replace("```", "").strip(), _repair_json_candidate(raw)]:
        cand = (cand or "").strip()
        if cand and cand not in seen:
            seen.add(cand)
            candidates.append(cand)

    last_err = None
    for c in candidates:
        try:
            d = json.loads(c)
            if isinstance(d, dict):
                return d
        except Exception as e:
            last_err = e

    extracted = _regex_extract_fields(raw)
    if extracted:
        return extracted

    raise ValueError(f"Cannot parse JSON. Raw starts: {raw[:200]}") from last_err


# ══════════════════════════════════════════════════════════════════════════════
#  EMBED HELPER
# ══════════════════════════════════════════════════════════════════════════════
class EmbedHelper:
    YOUTUBE_PATTERNS = [
        r"youtube\.com/embed/([\w-]+)",
        r'youtube\.com/watch\?[^"\'\s]*v=([\w-]+)',
        r"youtu\.be/([\w-]+)",
        r"youtube\.com/v/([\w-]+)",
        r"youtube\.com/shorts/([\w-]+)",
    ]
    FACEBOOK_PATTERNS = [
        r'facebook\.com/[^\s"\'<>]+/videos/([\d]+)',
        r"facebook\.com/watch/?\?v=(\d+)",
        r"facebook\.com/video/watch\?v=(\d+)",
        r"facebook\.com/video\.php\?v=(\d+)",
        r"fb\.watch/([\w-]+)",
    ]

    @classmethod
    def _decode_url(cls, value: str) -> str:
        value = html_mod.unescape(str(value or "")).strip()
        try:
            from urllib.parse import unquote
            value = unquote(value)
        except Exception:
            pass
        return value

    @classmethod
    def _extract_public_twitter_url(cls, raw: str) -> str:
        raw = cls._decode_url(raw)
        if not raw:
            return ""

        direct = re.search(
            r'https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]+)/status(?:es)?/(\d+)',
            raw, re.I
        )
        if direct:
            return f"https://twitter.com/{direct.group(1)}/status/{direct.group(2)}"

        # publish.twitter.com/?url=<public tweet url>
        for key in ("url", "href"):
            m = re.search(rf'[?&]{key}=([^&"\']+)', raw, re.I)
            if m:
                decoded = cls._decode_url(m.group(1))
                direct2 = re.search(
                    r'https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]+)/status(?:es)?/(\d+)',
                    decoded, re.I
                )
                if direct2:
                    return f"https://twitter.com/{direct2.group(1)}/status/{direct2.group(2)}"

        # iframe src=...
        src_m = re.search(r'src=["\']([^"\']+)["\']', raw, re.I)
        if src_m:
            src = cls._decode_url(src_m.group(1))
            found = cls._extract_public_twitter_url(src)
            if found:
                return found

        return ""

    @classmethod
    def _extract_tweet_id(cls, raw: str) -> str:
        raw = cls._decode_url(raw)
        if not raw:
            return ""
        patterns = [
            r'https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+/status(?:es)?/(\d+)',
            r'(?:twitter|x)\.com/i/web/status/(\d+)',
            r'data-tweet-id=["\'](\d+)["\']',
            r'[?&](?:id|tweetId)=(\d+)',
            r'https?://publish\.twitter\.com/\?url=.*?/status(?:es)?/(\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, raw, re.I)
            if m:
                return m.group(1)
        src_m = re.search(r'src=["\']([^"\']+)["\']', raw, re.I)
        if src_m:
            src = cls._decode_url(src_m.group(1))
            for pat in patterns:
                m = re.search(pat, src, re.I)
                if m:
                    return m.group(1)
        return ""

    @classmethod
    def _normalize_twitter_public_url(cls, raw: str) -> str:
        public_url = cls._extract_public_twitter_url(raw)
        if public_url:
            return public_url

        tweet_id = cls._extract_tweet_id(raw)
        if not tweet_id:
            return ""

        return _forced_public_twitter_url(tweet_id)

    @classmethod
    def detect(cls, raw: str) -> dict:
        raw = str(raw or "")
        raw_lower = raw.lower()

        for pat in cls.YOUTUBE_PATTERNS:
            m = re.search(pat, raw, re.I)
            if m:
                vid_id = m.group(1).split("&")[0].split("?")[0].strip()
                watch_url = f"https://www.youtube.com/watch?v={vid_id}"
                return {
                    "type": "youtube",
                    "icon": "▶",
                    "label": f"YouTube Video  [ID: {vid_id}]",
                    "html": watch_url,
                    "html_classic": watch_url,
                    "src": watch_url,
                    "vid_id": vid_id,
                }

        tw_url = cls._normalize_twitter_public_url(raw)
        if tw_url:
            tweet_id = cls._extract_tweet_id(raw)
            return {
                "type": "twitter",
                "icon": "🐦",
                "label": f"Twitter/X Post  [ID: {tweet_id}]" if tweet_id else "Twitter/X Post",
                "html": tw_url,
                "html_classic": tw_url,
                "src": tw_url,
                "tweet_id": tweet_id,
            }

        for pat in cls.FACEBOOK_PATTERNS:
            m = re.search(pat, raw, re.I)
            if m:
                fb_url_m = re.search(r'https?://(?:www\.)?facebook\.com/[^\s"\'<>]+', raw, re.I)
                if fb_url_m:
                    fb_url = fb_url_m.group(0).rstrip('/"\'')
                    return {
                        "type": "facebook",
                        "icon": "📘",
                        "label": "Facebook Video",
                        "html": fb_url,
                        "html_classic": fb_url,
                        "src": fb_url,
                    }

        src_m = re.search(r'src=["\'](https?://[^"\'>\s]+)["\']', raw, re.I)
        if src_m and "<iframe" in raw_lower:
            src = cls._decode_url(src_m.group(1))
            yt = re.search(r'(?:youtube\.com/embed/|youtu\.be/|youtube\.com/watch\?v=)([\w-]+)', src, re.I)
            if yt:
                vid_id = yt.group(1)
                watch_url = f"https://www.youtube.com/watch?v={vid_id}"
                return {
                    "type": "youtube",
                    "icon": "▶",
                    "label": f"YouTube Video  [ID: {vid_id}]",
                    "html": watch_url,
                    "html_classic": watch_url,
                    "src": watch_url,
                    "vid_id": vid_id,
                }
            tw_url = cls._normalize_twitter_public_url(src)
            if tw_url:
                tweet_id = cls._extract_tweet_id(src)
                return {
                    "type": "twitter",
                    "icon": "🐦",
                    "label": f"Twitter/X Post  [ID: {tweet_id}]",
                    "html": tw_url,
                    "html_classic": tw_url,
                    "src": tw_url,
                    "tweet_id": tweet_id,
                }
            return {
                "type": "generic",
                "icon": "▶",
                "label": "Embedded Media",
                "html": src,
                "html_classic": src,
                "src": src,
            }

        return {"type": None, "icon": "▶", "label": "Embedded Media", "html": raw, "html_classic": raw, "src": ""}


# ══════════════════════════════════════════════════════════════════════════════
#  API SETTINGS POPUP
# ══════════════════════════════════════════════════════════════════════════════
class APISettingsPopup(ctk.CTkToplevel):
    def __init__(self, master, key_manager: APIKeyManager, on_apply):
        super().__init__(master)
        self.key_manager = key_manager
        self.on_apply    = on_apply
        self.title("API Settings — Together AI & OpenAI")
        self.geometry("700x520")
        self.resizable(False, False)
        self.configure(fg_color=T.PANEL_BG)
        self.transient(master)
        self.grab_set()
        self.show_var = ctk.BooleanVar(value=False)
        self.save_var = ctk.BooleanVar(value=True)
        self._build()
        
        current = getattr(master, "api_keys", {"together": "", "openai": ""})
        if current.get("together"):
            self.together_entry.insert(0, current["together"])
        if current.get("openai"):
            self.openai_entry.insert(0, current["openai"])
            
        if current.get("together") or current.get("openai"):
            self.status.configure(text="Existing keys loaded")
        else:
            self.status.configure(text="Paste your API keys below")
            
        if not key_manager.encryption_available():
            self.save_var.set(False)
            self.save_cb.configure(state="disabled")
        self.after(80, self.focus_force)
        self.after(120, self.together_entry.focus_set)

    def _build(self):
        wrap = ctk.CTkFrame(self, fg_color=T.PANEL_BG_2, corner_radius=16,
                            border_width=1, border_color=T.PANEL_BORDER)
        wrap.pack(fill="both", expand=True, padx=14, pady=14)
        
        # Together AI Section
        ctk.CTkLabel(wrap, text="Together AI API Key",
                     font=ctk.CTkFont("Segoe UI", 18, "bold"),
                     text_color=T.TEXT_MAIN).pack(anchor="w", padx=16, pady=(16, 2))
        ctk.CTkLabel(wrap, text="Used for Kimi-K2.5 and fast SEO generation.",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=T.TEXT_SOFT).pack(anchor="w", padx=16, pady=(0, 8))
        self.together_entry = ctk.CTkEntry(wrap, placeholder_text="Paste Together AI key here…", show="*",
                                          height=38, corner_radius=10,
                                          fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER,
                                          text_color=T.TEXT_MAIN,
                                          font=ctk.CTkFont("Consolas", 12))
        self.together_entry.pack(fill="x", padx=16, pady=(0, 12))
        
        # OpenAI Section
        ctk.CTkLabel(wrap, text="OpenAI API Key (Fast OpenAPI)",
                     font=ctk.CTkFont("Segoe UI", 18, "bold"),
                     text_color=T.TEXT_MAIN).pack(anchor="w", padx=16, pady=(8, 2))
        ctk.CTkLabel(wrap, text="Used for GPT-4o-mini — high speed and reliability.",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=T.TEXT_SOFT).pack(anchor="w", padx=16, pady=(0, 8))
        self.openai_entry = ctk.CTkEntry(wrap, placeholder_text="Paste OpenAI key here…", show="*",
                                        height=38, corner_radius=10,
                                        fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER,
                                        text_color=T.TEXT_MAIN,
                                        font=ctk.CTkFont("Consolas", 12))
        self.openai_entry.pack(fill="x", padx=16, pady=(0, 12))
        
        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkCheckBox(row, text="Show keys", variable=self.show_var,
                        command=self._toggle_show,
                        text_color=T.TEXT_SOFT).pack(side="left", padx=(0, 16))
        self.save_cb = ctk.CTkCheckBox(row, text="Save encrypted on this computer",
                                       variable=self.save_var, text_color=T.TEXT_SOFT)
        self.save_cb.pack(side="left")
        
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 10))
        for label, fn, kind, w in [
            ("Test Together",   lambda: self._test("together"), "cyan",   130),
            ("Test OpenAI",     lambda: self._test("openai"),   "teal",   130),
            ("Save & Use All",  self._save,                     "green",  140),
            ("Clear All",       self._clear,                    "red",    100),
        ]:
            Btn(btns, label, fn, kind, w, 36).pack(side="left", padx=(0, 6))
            
        self.status = ctk.CTkLabel(wrap, text="", height=30, corner_radius=8,
                                   fg_color=T.PANEL_BG, text_color=T.TEXT_SOFT,
                                   anchor="w", padx=12,
                                   font=ctk.CTkFont("Segoe UI", 11, "bold"))
        self.status.pack(fill="x", padx=16, pady=(0, 16))

    def _toggle_show(self):
        s = "" if self.show_var.get() else "*"
        self.together_entry.configure(show=s)
        self.openai_entry.configure(show=s)

    def _keys(self):
        return self.together_entry.get().strip(), self.openai_entry.get().strip()

    def _test(self, provider):
        tk, ok = self._keys()
        k = tk if provider == "together" else ok
        if not k:
            messagebox.showwarning("Missing Key", f"Paste your {provider.title()} API key first.", parent=self); return
        self.status.configure(text=f"Testing {provider.title()}…")
        
        def worker():
            try:
                if provider == "together":
                    verify_key(k)
                else:
                    # Basic OpenAI verification
                    r = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {k}"}, timeout=10)
                    if r.status_code >= 400:
                        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
                
                self.after(0, lambda: self.status.configure(text=f"✓ {provider.title()} key is valid"))
                self.after(0, lambda: messagebox.showinfo("Success", f"{provider.title()} API key is valid.", parent=self))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: self.status.configure(text=f"✗ {provider.title()}: {m[:60]}"))
                self.after(0, lambda m=msg: messagebox.showerror("Failed", f"{provider.title()} test failed: {m}", parent=self))
        threading.Thread(target=worker, daemon=True).start()

    def _save(self):
        tk, ok = self._keys()
        if not tk and not ok:
            messagebox.showwarning("Missing Keys", "Paste at least one API key first.", parent=self); return
            
        if self.save_var.get():
            try:
                self.key_manager.save(tk, ok)
                self.status.configure(text="✓ Keys saved & applied")
            except Exception as e:
                messagebox.showerror("Save Failed", f"Could not save keys: {e}", parent=self); return
                
        self.on_apply(tk, ok, self.save_var.get())
        self.destroy()

    def _clear(self):
        try:
            self.key_manager.clear()
            self.together_entry.delete(0, "end")
            self.openai_entry.delete(0, "end")
            self.on_apply("", "", False)
            self.status.configure(text="All saved keys cleared")
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)



# ══════════════════════════════════════════════════════════════════════════════
#  AI SEO FIELDS POPUP
# ══════════════════════════════════════════════════════════════════════════════
class AISEOFieldsPopup(ctk.CTkToplevel):
    SEO_TITLE_MAX = 60
    META_MAX      = 160

    def __init__(self, master, api_keys: dict, article_text: str, on_apply,
                 detected_lang: str = ""):
        super().__init__(master)
        self.api_keys      = api_keys
        self.api_key       = api_keys.get("together") or api_keys.get("openai") # Legacy support
        self.article_text  = article_text[:4000]
        self.on_apply      = on_apply
        self.detected_lang = detected_lang or "English"
        self.title("⚡ AI Generate — Yoast SEO Fields")
        self.geometry("780x660")
        self.resizable(True, True)
        self.configure(fg_color=T.PANEL_BG)
        self.transient(master)
        self.grab_set()
        self._build()
        self.after(200, self._auto_generate)

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color=T.PANEL_BG_2, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr,
            text="⚡  AI Generate — Focus Keyphrase · SEO Title · Meta Description",
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            text_color=T.TEXT_MAIN,
        ).pack(side="left", padx=16, pady=12)
        LANG_COLORS = {
            "Khmer":"#f59e0b","Chinese":"#ef4444","Japanese":"#ec4899",
            "Korean":"#8b5cf6","Arabic":"#10b981","Thai":"#06b6d4",
            "Vietnamese":"#84cc16","English":"#3b82f6",
        }
        lang_color = LANG_COLORS.get(self.detected_lang, "#64748b")
        ctk.CTkLabel(
            hdr, text=f"🌐 {self.detected_lang}",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=lang_color, fg_color=T.PANEL_BG, corner_radius=8, padx=10, pady=4,
        ).pack(side="right", padx=16, pady=12)

        wrap = ctk.CTkScrollableFrame(self, fg_color=T.PANEL_BG, corner_radius=0)
        wrap.pack(fill="both", expand=True, padx=0, pady=0)

        self._section(wrap, "🔑  Focus Keyphrase", "Short, specific phrase (2–4 words).")
        fk_row = ctk.CTkFrame(wrap, fg_color="transparent")
        fk_row.pack(fill="x", padx=16, pady=(0, 4))
        self.fk_entry = ctk.CTkEntry(
            fk_row, height=38, corner_radius=8,
            fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1,
            text_color="#4ade80", font=ctk.CTkFont("Segoe UI", 13),
            placeholder_text="e.g. cambodia election results",
            placeholder_text_color=T.PLACEHOLDER,
        )
        self.fk_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.fk_entry.bind("<KeyRelease>", lambda e: self._update_fk_counter())
        Btn(fk_row, "⧉ Copy", lambda: self._copy(self.fk_entry.get()), "cyan", 80, 36).pack(side="left")
        self.fk_counter = ctk.CTkLabel(wrap, text="", anchor="e", font=ctk.CTkFont("Segoe UI", 10), text_color=T.TEXT_SOFT)
        self.fk_counter.pack(fill="x", padx=16, pady=(0, 10))

        self._section(wrap, "📝  SEO Title", "Recommended: 50–60 characters.")
        seo_row = ctk.CTkFrame(wrap, fg_color="transparent")
        seo_row.pack(fill="x", padx=16, pady=(0, 4))
        self.seo_entry = ctk.CTkEntry(
            seo_row, height=38, corner_radius=8,
            fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1,
            text_color=T.TEXT_MAIN, font=ctk.CTkFont("Segoe UI", 13),
            placeholder_text="SEO Title will appear here…",
            placeholder_text_color=T.PLACEHOLDER,
        )
        self.seo_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.seo_entry.bind("<KeyRelease>", lambda e: self._update_seo_counter())
        Btn(seo_row, "⧉ Copy", lambda: self._copy(self.seo_entry.get()), "cyan", 80, 36).pack(side="left")

        seo_count_row = ctk.CTkFrame(wrap, fg_color="transparent")
        seo_count_row.pack(fill="x", padx=16, pady=(0, 2))
        self.seo_counter = ctk.CTkLabel(seo_count_row, text="0 / 60", anchor="w", font=ctk.CTkFont("Segoe UI", 10, "bold"), text_color=T.COUNTER_OK)
        self.seo_counter.pack(side="left")
        self.seo_hint = ctk.CTkLabel(seo_count_row, text="✓ Good length", anchor="e", font=ctk.CTkFont("Segoe UI", 10), text_color=T.COUNTER_OK)
        self.seo_hint.pack(side="right")
        self.seo_bar_bg = ctk.CTkFrame(wrap, height=6, corner_radius=3, fg_color="#1e3a6a")
        self.seo_bar_bg.pack(fill="x", padx=16, pady=(0, 12))
        self.seo_bar = ctk.CTkFrame(self.seo_bar_bg, height=6, corner_radius=3, fg_color=T.COUNTER_OK)
        self.seo_bar.place(relx=0, rely=0, relwidth=0.0, relheight=1.0)

        self._section(wrap, "   Variants (click to use)")
        self.seo_variants_frame = ctk.CTkFrame(wrap, fg_color="transparent")
        self.seo_variants_frame.pack(fill="x", padx=16, pady=(0, 12))

        self._section(wrap, "📋  Meta Description", "Recommended: 120–160 characters.")
        self.meta_box = ctk.CTkTextbox(wrap, height=90, corner_radius=8, fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1, text_color=T.TEXT_MAIN, font=ctk.CTkFont("Segoe UI", 12), wrap="word")
        self.meta_box.pack(fill="x", padx=16, pady=(0, 4))
        self.meta_box.bind("<KeyRelease>", lambda e: self._update_meta_counter())

        meta_count_row = ctk.CTkFrame(wrap, fg_color="transparent")
        meta_count_row.pack(fill="x", padx=16, pady=(0, 2))
        self.meta_counter = ctk.CTkLabel(meta_count_row, text="0 / 160", anchor="w", font=ctk.CTkFont("Segoe UI", 10, "bold"), text_color=T.COUNTER_OK)
        self.meta_counter.pack(side="left")
        self.meta_hint = ctk.CTkLabel(meta_count_row, text="✓ Good length", anchor="e", font=ctk.CTkFont("Segoe UI", 10), text_color=T.COUNTER_OK)
        self.meta_hint.pack(side="right")
        self.meta_bar_bg = ctk.CTkFrame(wrap, height=6, corner_radius=3, fg_color="#1e3a6a")
        self.meta_bar_bg.pack(fill="x", padx=16, pady=(0, 2))
        self.meta_bar = ctk.CTkFrame(self.meta_bar_bg, height=6, corner_radius=3, fg_color=T.COUNTER_OK)
        self.meta_bar.place(relx=0, rely=0, relwidth=0.0, relheight=1.0)
        Btn(wrap, "⧉  Copy Meta", lambda: self._copy(self.meta_box.get("1.0","end").strip()), "cyan", 130, 30).pack(anchor="e", padx=16, pady=(4, 12))

        self._section(wrap, "   Variants (click to use)")
        self.meta_variants_frame = ctk.CTkFrame(wrap, fg_color="transparent")
        self.meta_variants_frame.pack(fill="x", padx=16, pady=(0, 12))

        self._section(wrap, "🔍  Google Search Preview")
        self.preview_frame = ctk.CTkFrame(wrap, fg_color="#ffffff", corner_radius=10, border_width=1, border_color="#e0e0e0")
        self.preview_frame.pack(fill="x", padx=16, pady=(0, 12))
        self._build_preview(self.preview_frame)

        self.status_lbl = ctk.CTkLabel(wrap, text="⏳ Generating SEO fields with AI…", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color="#f59e0b", anchor="w")
        self.status_lbl.pack(fill="x", padx=16, pady=(0, 4))

        bot = ctk.CTkFrame(self, fg_color=T.PANEL_BG_2, corner_radius=0)
        bot.pack(fill="x", side="bottom")
        inner = ctk.CTkFrame(bot, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)
        self._regen_btn = Btn(inner, "⟳  Regenerate", self._auto_generate, "purple", 140, 36)
        self._regen_btn.pack(side="left", padx=(0, 8))
        Btn(inner, "✔  Apply to Editor", self._apply, "green", 160, 36).pack(side="left", padx=(0, 8))
        Btn(inner, "✕  Cancel", self.destroy, "red", 100, 36).pack(side="left")

    def _section(self, parent, title, subtitle=""):
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=T.TEXT_SOFT, anchor="w").pack(fill="x", padx=16, pady=(12, 0))
        if subtitle:
            ctk.CTkLabel(parent, text=subtitle, font=ctk.CTkFont("Segoe UI", 9), text_color=T.PLACEHOLDER, anchor="w").pack(fill="x", padx=16, pady=(1, 4))

    def _build_preview(self, parent):
        inner = tk.Frame(parent, bg="#ffffff")
        inner.pack(fill="x", padx=14, pady=10)
        site_row = tk.Frame(inner, bg="#ffffff")
        site_row.pack(fill="x", pady=(0, 2))
        tk.Label(site_row, text="🌐", bg="#ffffff", font=("Segoe UI", 12)).pack(side="left")
        tk.Label(site_row, text="  yoursite.com  ›  article", bg="#ffffff", fg="#202124", font=("Segoe UI", 11)).pack(side="left")
        self.preview_title = tk.Label(inner, text="SEO Title will appear here", bg="#ffffff", fg="#1a0dab", font=("Segoe UI", 16), wraplength=640, justify="left", anchor="w")
        self.preview_title.pack(fill="x", pady=(0, 2))
        self.preview_meta = tk.Label(inner, text="Meta description will appear here…", bg="#ffffff", fg="#4d5156", font=("Segoe UI", 12), wraplength=640, justify="left", anchor="w")
        self.preview_meta.pack(fill="x")

    def _update_preview(self):
        title = self.seo_entry.get().strip() or "SEO Title will appear here"
        meta  = self.meta_box.get("1.0", "end").strip() or "Meta description will appear here…"
        if len(title) > 60: title = title[:57] + "…"
        if len(meta)  > 160: meta  = meta[:157] + "…"
        try:
            self.preview_title.configure(text=title)
            self.preview_meta.configure(text=meta)
        except Exception:
            pass

    def _update_fk_counter(self):
        text  = self.fk_entry.get().strip()
        words = len(text.split()) if text else 0
        chars = len(text)
        if chars == 0:
            self.fk_counter.configure(text="", text_color=T.TEXT_SOFT); return
        if words < 1:
            color, hint = T.COUNTER_WARN, "⚠ Too short"
        elif words <= 4:
            color, hint = T.COUNTER_OK, f"✓ Good  ({words} words, {chars} chars)"
        else:
            color, hint = T.COUNTER_WARN, f"⚠ Try shorter  ({words} words — Yoast recommends ≤4)"
        self.fk_counter.configure(text=hint, text_color=color)

    def _update_seo_counter(self):
        n   = len(self.seo_entry.get())
        MAX = self.SEO_TITLE_MAX
        pct = min(1.0, n / MAX)
        if n == 0:   color, hint = T.TEXT_SOFT, "—"
        elif n < 30: color, hint = T.COUNTER_WARN, f"⚠ Too short ({n}/60)"
        elif n < 50: color, hint = T.COUNTER_WARN, f"⚠ Could be longer ({n}/60)"
        elif n <= MAX: color, hint = T.COUNTER_OK, f"✓ Good length ({n}/60)"
        else:        color, hint = T.COUNTER_BAD, f"✗ Too long — cut {n - MAX} chars ({n}/60)"
        self.seo_counter.configure(text=f"{n} / {MAX}", text_color=color)
        self.seo_hint.configure(text=hint, text_color=color)
        self.seo_bar.configure(fg_color=color)
        self.seo_bar.place(relx=0, rely=0, relwidth=pct, relheight=1.0)
        self._update_preview()

    def _update_meta_counter(self):
        n   = len(self.meta_box.get("1.0", "end").strip())
        MAX = self.META_MAX
        if n == 0:     color, hint, pct = T.TEXT_SOFT, "—", 0.0
        elif n < 120:  pct = n/MAX; color, hint = T.COUNTER_WARN, f"⚠ Too short ({n}/160)"
        elif n <= 155: pct = n/MAX; color, hint = T.COUNTER_OK, f"✓ Good length ({n}/160)"
        elif n <= MAX: pct = n/MAX; color, hint = T.COUNTER_OK, f"✓ Acceptable ({n}/160)"
        else:          pct = 1.0; color, hint = T.COUNTER_BAD, f"✗ Too long — cut {n - MAX} chars ({n}/160)"
        self.meta_counter.configure(text=f"{n} / {MAX}", text_color=color)
        self.meta_hint.configure(text=hint, text_color=color)
        self.meta_bar.configure(fg_color=color)
        self.meta_bar.place(relx=0, rely=0, relwidth=pct, relheight=1.0)
        self._update_preview()

    def _render_seo_variants(self, variants: list):
        for w in self.seo_variants_frame.winfo_children(): w.destroy()
        for i, v in enumerate(variants[:3]):
            v = v.strip(); n = len(v)
            color = T.COUNTER_OK if n <= self.SEO_TITLE_MAX else T.COUNTER_WARN
            row = ctk.CTkFrame(self.seo_variants_frame, fg_color=T.INPUT_BG, corner_radius=6, border_width=1, border_color=T.INPUT_BORDER)
            row.pack(fill="x", pady=3)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=8, pady=4)
            ctk.CTkLabel(inner, text=f"{i+1}.", width=20, font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=T.TEXT_SOFT).pack(side="left")
            ctk.CTkButton(inner, text=v, anchor="w", fg_color="transparent", hover_color=T.BLUE, text_color=T.TEXT_MAIN, font=ctk.CTkFont("Segoe UI", 12), command=lambda val=v: self._use_seo_variant(val)).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(inner, text=f"{n}/60", width=50, font=ctk.CTkFont("Consolas", 10), text_color=color).pack(side="right")

    def _render_meta_variants(self, variants: list):
        for w in self.meta_variants_frame.winfo_children(): w.destroy()
        for i, v in enumerate(variants[:3]):
            v = v.strip(); n = len(v)
            color = T.COUNTER_OK if n <= self.META_MAX else T.COUNTER_WARN
            row = ctk.CTkFrame(self.meta_variants_frame, fg_color=T.INPUT_BG, corner_radius=6, border_width=1, border_color=T.INPUT_BORDER)
            row.pack(fill="x", pady=3)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=8, pady=4)
            ctk.CTkLabel(inner, text=f"{i+1}.", width=20, font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=T.TEXT_SOFT).pack(side="left")
            ctk.CTkButton(inner, text=v[:120] + ("…" if len(v) > 120 else ""), anchor="w", fg_color="transparent", hover_color=T.BLUE, text_color=T.TEXT_MAIN, font=ctk.CTkFont("Segoe UI", 11), command=lambda val=v: self._use_meta_variant(val)).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(inner, text=f"{n}/160", width=55, font=ctk.CTkFont("Consolas", 10), text_color=color).pack(side="right")

    def _use_seo_variant(self, val):
        self.seo_entry.delete(0, "end"); self.seo_entry.insert(0, val); self._update_seo_counter()

    def _use_meta_variant(self, val):
        self.meta_box.delete("1.0", "end"); self.meta_box.insert("1.0", val); self._update_meta_counter()

    def _auto_generate(self):
        if not self.api_keys.get("together") and not self.api_keys.get("openai"):
            self.status_lbl.configure(text="✗ No API key — open API Settings first", text_color=T.COUNTER_BAD); return
        self._regen_btn.configure(state="disabled", text="⏳ Generating…")
        self.status_lbl.configure(text="⏳ Fast AI mode…", text_color="#f59e0b")
        threading.Thread(target=self._generate_worker, daemon=True).start()

    def _generate_worker(self):
        try:
            lang = self.detected_lang or "English"
            article = re.sub(r"\s+", " ", (self.article_text or "")).strip()[:900]
            tone = random.choice(["direct", "search-friendly", "newsy"])
            prompt = f"""Return ONLY valid JSON in {lang}.

Keys:
{{
  "focus_keyphrase": "2-4 word keyphrase in {lang}, lowercase",
  "seo_title_1": "50-60 chars",
  "seo_title_2": "50-60 chars",
  "seo_title_3": "50-60 chars",
  "meta_description_1": "120-160 chars",
  "meta_description_2": "120-160 chars",
  "meta_description_3": "120-160 chars"
}}

Rules:
- concise
- catchy
- Yoast-friendly
- no markdown
- no explanation
- tone: {tone}

ARTICLE:
{article}"""

            raw_model_plan = []
            # Priority: OpenAI for speed
            if self.api_keys.get("openai"):
                raw_model_plan.append(("gpt-4o-mini", 0.20, 15, 350))
            
            raw_model_plan.extend([
                (FAST_SEO_FIELDS_MODEL if AI_FAST_MODE else SEO_MODEL, 0.20, FAST_AI_TIMEOUT, FAST_SEO_FIELD_MAX_TOKENS),
                (SEO_MODEL, 0.18, 28, 280),
                (FAST_SEO_FIELDS_FALLBACK_MODEL, 0.24, 30, 300),
            ])
            seen_models = set()
            model_plan = []
            for model, temp, to_sec, max_tok in raw_model_plan:
                model = (model or "").strip()
                if not model or model in seen_models:
                    continue
                seen_models.add(model)
                model_plan.append((model, temp, to_sec, max_tok))

            last_err = None
            data = None
            for model, temp, to_sec, max_tok in model_plan:
                if not model:
                    continue
                try:
                    # Choose correct key for the model
                    is_openai = str(model).lower().startswith("gpt-")
                    active_key = self.api_keys.get("openai" if is_openai else "together")
                    if not active_key:
                        continue
                        
                    resp = chat_completion(
                        active_key,
                        model,
                        messages=[{"role":"user","content":prompt}],
                        temperature=temp,
                        response_format={"type":"json_object"},
                        timeout=to_sec,
                        max_tokens=max_tok,
                    )
                    data = parse_json(extract_content(resp))
                    if isinstance(data, dict) and any(data.get(k) for k in ("focus_keyphrase","seo_title_1","meta_description_1")):
                        break
                except Exception as e:
                    last_err = e
                    data = None

            if not isinstance(data, dict):
                raise RuntimeError(str(last_err) if last_err else "AI SEO fields failed")

            fk=str(data.get("focus_keyphrase","")).strip()
            title1=str(data.get("seo_title_1","")).strip()
            title2=str(data.get("seo_title_2","")).strip()
            title3=str(data.get("seo_title_3","")).strip()
            meta1=str(data.get("meta_description_1","")).strip()
            meta2=str(data.get("meta_description_2","")).strip()
            meta3=str(data.get("meta_description_3","")).strip()

            def _cap_title(t):
                if len(t)>60:
                    trimmed=t[:60].rsplit(" ",1)
                    t=trimmed[0].rstrip(" :-,") if len(trimmed)>1 else t[:60]
                return t

            title1=_cap_title(title1); title2=_cap_title(title2); title3=_cap_title(title3)
            meta1=meta1[:160].rsplit(" ",1)[0] if len(meta1)>160 else meta1
            meta2=meta2[:160].rsplit(" ",1)[0] if len(meta2)>160 else meta2
            meta3=meta3[:160].rsplit(" ",1)[0] if len(meta3)>160 else meta3

            def _apply():
                if not self.winfo_exists(): return
                try:
                    self.fk_entry.delete(0,"end"); self.fk_entry.insert(0,fk); self._update_fk_counter()
                    self.seo_entry.delete(0,"end"); self.seo_entry.insert(0,title1); self._update_seo_counter()
                    self.meta_box.delete("1.0","end"); self.meta_box.insert("1.0",meta1); self._update_meta_counter()
                    self._render_seo_variants([title1,title2,title3])
                    self._render_meta_variants([meta1,meta2,meta3])
                    self._update_preview()
                    self._regen_btn.configure(state="normal",text="⟳  Regenerate")
                    self.status_lbl.configure(text="✓ AI SEO fields ready", text_color=T.COUNTER_OK)
                except: pass

            self.after(0, _apply)
        except Exception as e:
            msg=str(e)[:200]
            def _err():
                self._regen_btn.configure(state="normal",text="⟳  Regenerate")
                self.status_lbl.configure(text=f"✗ Error: {msg}", text_color=T.COUNTER_BAD)
                try:
                    messagebox.showerror("AI SEO Fields Error", f"Could not generate AI SEO Fields.\n\nReason:\n{msg}")
                except Exception:
                    pass
            self.after(0, _err)

    def _apply(self):
        fk=self.fk_entry.get().strip(); title=self.seo_entry.get().strip(); meta=self.meta_box.get("1.0","end").strip()
        if not fk and not title and not meta:
            messagebox.showwarning("Empty Fields","Generate SEO fields first.",parent=self); return
        self.on_apply(fk,title,meta); self.destroy()

    def _copy(self, text):
        if not text.strip(): return
        root=self.winfo_toplevel(); root.clipboard_clear(); root.clipboard_append(text); root.update()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — SEO FORMATTER
#  MODIFIED: Removed the 4-column bottom options panel from the UI.
#            All backend logic (_finish, copy_section, etc.) is preserved.
#            The 4 CTkTextbox widgets are created but never packed (hidden),
#            so _finish() can still write to them without crashing.
# ══════════════════════════════════════════════════════════════════════════════
class SEOFormatterTab(ctk.CTkFrame):
    def __init__(self, master, set_status, get_api_key=None):
        super().__init__(master, fg_color=T.APP_BG, corner_radius=0)
        self.set_status   = set_status
        self.get_api_key  = get_api_key or (lambda: "")
        self.current_sections = {}
        self.generated_plain  = ""
        self._input_placeholder = True
        self._build()

    def _build(self):
        # ── Top action bar ────────────────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color=T.PANEL_BG, corner_radius=12, border_width=1, border_color=T.PANEL_BORDER)
        bar.pack(fill="x", padx=0, pady=(0, 8))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)
        self._seo_gen_btn = Btn(inner, "⚡ Generate SEO", self.process_article, "green", 148, 34)
        self._seo_gen_btn.pack(side="left", padx=(0, 6))
        self._ai_seo_btn = Btn(inner, "🤖 AI SEO Fields", self._open_ai_seo_popup, "purple", 148, 34)
        self._ai_seo_btn.pack(side="left", padx=(0, 6))
        Btn(inner, "⧉  Copy WP HTML", self.copy_all_output, "teal",  140, 34).pack(side="left", padx=(0, 6))
        Btn(inner, "✕  Clear Input",  self.clear_input,    "red",   120, 34).pack(side="left", padx=(0, 6))
        Btn(inner, "✕  Clear Output", self.clear_output,   "red",   120, 34).pack(side="left")

        # ── URL fetch bar ─────────────────────────────────────────────────────
        url_bar = ctk.CTkFrame(self, fg_color=T.PANEL_BG, corner_radius=10, border_width=1, border_color=T.PANEL_BORDER)
        url_bar.pack(fill="x", padx=0, pady=(0, 6))
        url_inner = ctk.CTkFrame(url_bar, fg_color="transparent")
        url_inner.pack(fill="x", padx=10, pady=7)
        ctk.CTkLabel(url_inner, text="🔗 Article URL:", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=T.TEXT_SOFT).pack(side="left", padx=(0, 8))
        self.url_entry = ctk.CTkEntry(
            url_inner, placeholder_text="Paste article URL here e.g. https://example.com/article",
            height=32, corner_radius=8, fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1,
            text_color=T.TEXT_MAIN, font=ctk.CTkFont("Segoe UI", 12), placeholder_text_color=T.PLACEHOLDER,
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.url_entry.bind("<Return>", lambda e: self.fetch_and_generate())
        self._lang_badge = ctk.CTkLabel(url_inner, text="🌐 —", font=ctk.CTkFont("Segoe UI", 10, "bold"), text_color=T.TEXT_SOFT, fg_color=T.PANEL_BG_2, corner_radius=6, padx=8, pady=2)
        self._lang_badge.pack(side="left", padx=(0, 6))
        self._fetch_btn = Btn(url_inner, "⬇  Fetch & Generate", self.fetch_and_generate, "purple", 160, 32)
        self._fetch_btn.pack(side="left")
        self._detected_lang = ""
        self._last_ai_fields_key = None
        self._last_ai_fields_data = None

        # ── Quick Copy pill bar ───────────────────────────────────────────────
        pill_bar = ctk.CTkFrame(self, fg_color=T.PANEL_BG_2, corner_radius=10, border_width=1, border_color=T.PANEL_BORDER)
        pill_bar.pack(fill="x", padx=0, pady=(0, 8))
        pill_inner = ctk.CTkFrame(pill_bar, fg_color="transparent")
        pill_inner.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(pill_inner, text="Quick Copy:", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=T.TEXT_SOFT).pack(side="left", padx=(0, 8))
        for name, kind in [("Focus Keyphrase","cyan"),("SEO Title","purple"),("Meta Description","yellow"),("#Hashtags","green")]:
            Btn(pill_inner, name, lambda n=name: self.copy_section(n), kind, None, 30).pack(side="left", padx=(0, 5))

        # ── Main body: input left, output right ───────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1); body.grid_columnconfigure(1, weight=1); body.grid_rowconfigure(0, weight=1)

        # Left — input panel
        lf = ctk.CTkFrame(body, fg_color=T.PANEL_BG, corner_radius=14, border_width=1, border_color=T.PANEL_BORDER)
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ctk.CTkLabel(lf, text="Input Article", font=ctk.CTkFont("Segoe UI", 13, "bold"), text_color=T.TEXT_MAIN).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(lf, text="Paste plain text or full WordPress HTML", font=ctk.CTkFont("Segoe UI", 10), text_color=T.TEXT_SOFT).pack(anchor="w", padx=12, pady=(0, 6))
        self.input_text = ctk.CTkTextbox(lf, fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1, text_color=T.TEXT_MAIN, font=ctk.CTkFont("Consolas", 12), corner_radius=8, wrap="word")
        self.input_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.input_text.insert("1.0", "Paste article text or full HTML code here…")
        self.input_text.bind("<FocusIn>",  self._on_input_focus_in)
        self.input_text.bind("<FocusOut>", self._on_input_focus_out)
        self.input_text.bind("<<Paste>>",  lambda e: self._clear_placeholder_if_needed())
        self.input_text.bind("<KeyPress>", lambda e: self._clear_placeholder_if_needed())
        self.input_text.bind("<Button-1>", lambda e: self._clear_placeholder_if_needed())

        # Right — output panel
        rf = ctk.CTkFrame(body, fg_color=T.PANEL_BG, corner_radius=14, border_width=1, border_color=T.PANEL_BORDER)
        rf.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(rf, text="SEO Output", font=ctk.CTkFont("Segoe UI", 13, "bold"), text_color=T.TEXT_MAIN).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(rf, text="Formatted article preview with Yoast SEO fields", font=ctk.CTkFont("Segoe UI", 10), text_color=T.TEXT_SOFT).pack(anchor="w", padx=12, pady=(0, 6))

        out_frame = ctk.CTkFrame(rf, fg_color=T.INPUT_BG, border_color=T.INPUT_BORDER, border_width=1, corner_radius=8)
        out_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.output_text = tk.Text(
            out_frame, bg=T.INPUT_BG, fg=T.TEXT_MAIN,
            insertbackground=T.TEXT_MAIN, font=("Georgia", 12),
            wrap="word", state="disabled", relief="flat", bd=0,
            padx=10, pady=8, selectbackground="#1e3a70", selectforeground=T.TEXT_MAIN,
        )
        _sb_out = tk.Scrollbar(out_frame, command=self.output_text.yview, bg=T.PANEL_BG, troughcolor=T.INPUT_BG, activebackground=T.BLUE_BORDER, relief="flat", bd=0)
        _sb_out.pack(side="right", fill="y")
        self.output_text.pack(fill="both", expand=True)
        self.output_text.configure(yscrollcommand=_sb_out.set)

        for tag, cfg in [
            ("h1",         dict(font=("Segoe UI", 17, "bold"), foreground="#ffffff", spacing1=10, spacing3=6)),
            ("h1_label",   dict(font=("Segoe UI",  9, "bold"), foreground="#2563eb")),
            ("h2",         dict(font=("Segoe UI", 13, "bold"), foreground="#60c0ff", spacing1=12, spacing3=4)),
            ("h2_label",   dict(font=("Segoe UI",  8, "bold"), foreground="#1e6acc")),
            ("h3",         dict(font=("Segoe UI", 11, "bold"), foreground="#4ade80", spacing1=8,  spacing3=2)),
            ("h3_label",   dict(font=("Segoe UI",  8, "bold"), foreground="#166534")),
            ("intro",      dict(font=("Georgia",  12, "italic"), foreground="#c8d8f0", spacing3=6)),
            ("body",       dict(font=("Georgia",  12),           foreground=T.TEXT_MAIN, spacing3=8)),
            ("embed_yt",   dict(font=("Segoe UI", 11, "bold"), foreground="#ff4444", background="#1a0000", spacing1=6, spacing3=6)),
            ("embed_tw",   dict(font=("Segoe UI", 11, "bold"), foreground="#1d9bf0", background="#00111a", spacing1=6, spacing3=6)),
            ("embed_fb",   dict(font=("Segoe UI", 11, "bold"), foreground="#4267B2", background="#00091a", spacing1=6, spacing3=6)),
            ("embed_gen",  dict(font=("Segoe UI", 11, "bold"), foreground="#f59e0b", background="#100800", spacing1=6, spacing3=6)),
            ("embed_url",  dict(font=("Consolas", 10),          foreground="#64748b", spacing3=4)),
        ]:
            self.output_text.tag_configure(tag, **cfg)

        # Process log
        err_header = ctk.CTkFrame(rf, fg_color="transparent")
        err_header.pack(fill="x", padx=10, pady=(0, 2))
        ctk.CTkLabel(err_header, text="📋  Process Log", font=ctk.CTkFont("Segoe UI", 9, "bold"), text_color=T.TEXT_SOFT, anchor="w").pack(side="left")
        Btn(err_header, "Clear Log", self._clear_error_log, "red", 80, 22).pack(side="right")
        self.error_log = ctk.CTkTextbox(rf, height=64, fg_color="#020810", border_color="#1e3a6a", border_width=1, text_color="#f87171", font=ctk.CTkFont("Consolas", 10), corner_radius=6, state="disabled")
        self.error_log.pack(fill="x", padx=10, pady=(0, 10))

        # ── HIDDEN backend widgets (never packed — kept so _finish() works) ───
        # These 4 textboxes store data for copy_section() and _apply_ai_seo()
        # but are NOT displayed in the UI.
        _hidden_parent = ctk.CTkFrame(self, fg_color="transparent", width=0, height=0)
        # Do NOT pack _hidden_parent — keeps it truly invisible
        self.title_options         = ctk.CTkTextbox(_hidden_parent, height=72)
        self.meta_options          = ctk.CTkTextbox(_hidden_parent, height=72)
        self.short_caption_options = ctk.CTkTextbox(_hidden_parent, height=72)
        self.hashtags_options      = ctk.CTkTextbox(_hidden_parent, height=72)

        # Hidden counter labels (referenced in _refresh_counters)
        self._seo_title_counter = ctk.CTkLabel(_hidden_parent, text="")
        self._meta_counter      = ctk.CTkLabel(_hidden_parent, text="")

        # Bind counter refresh to hidden meta_options (no-op visually)
        self.title_options.bind("<KeyRelease>", lambda e: self._refresh_counters())
        self.meta_options.bind("<KeyRelease>",  lambda e: self._refresh_counters())

    # ── Refresh counters (operates on hidden meta_options widget) ─────────────
    def _refresh_counters(self):
        try:
            raw = self.meta_options.get("1.0", "end")
            seo_m = re.search(r"SEO Title:\s*(.+)", raw)
            seo_v = seo_m.group(1).strip() if seo_m else ""
            n = len(seo_v)
            if n == 0:    seo_txt, seo_col = "SEO Title: —", T.TEXT_SOFT
            elif n < 30:  seo_txt = f"SEO Title: {n}/60  ⚠ Too short"; seo_col = T.COUNTER_WARN
            elif n < 50:  seo_txt = f"SEO Title: {n}/60  ⚠ Could be longer"; seo_col = T.COUNTER_WARN
            elif n <= 60: seo_txt = f"SEO Title: {n}/60  ✓ Good"; seo_col = T.COUNTER_OK
            else:         seo_txt = f"SEO Title: {n}/60  ✗ Too long (cut {n-60})"; seo_col = T.COUNTER_BAD
            self._seo_title_counter.configure(text=seo_txt, text_color=seo_col)

            meta_m = re.search(r"Meta Description:\s*(.+)", raw)
            meta_v = meta_m.group(1).strip() if meta_m else ""
            n = len(meta_v)
            if n == 0:     meta_txt, meta_col = "Meta: —", T.TEXT_SOFT
            elif n < 120:  meta_txt = f"Meta: {n}/160  ⚠ Too short"; meta_col = T.COUNTER_WARN
            elif n <= 160: meta_txt = f"Meta: {n}/160  ✓ Good"; meta_col = T.COUNTER_OK
            else:          meta_txt = f"Meta: {n}/160  ✗ Too long (cut {n-160})"; meta_col = T.COUNTER_BAD
            self._meta_counter.configure(text=meta_txt, text_color=meta_col)
        except Exception:
            pass

    # ── Open AI SEO popup ─────────────────────────────────────────────────────
    def _open_ai_seo_popup(self):
        all_keys = self.get_api_key(provider=None)
        if not all_keys.get("together") and not all_keys.get("openai"):
            messagebox.showerror("API Key Required", "No API key found.\n\nOpen API Settings → paste Together AI or OpenAI key → Save.", parent=self); return
        article = self._raw_input()
        if not article:
            messagebox.showwarning("No Article", "Please paste an article first, then click AI SEO Fields.", parent=self); return
        lang = self._detected_lang or self._detect_language(article)
        AISEOFieldsPopup(self.winfo_toplevel(), all_keys, article, self._apply_ai_seo, lang)

    def _apply_ai_seo(self, fk: str, seo_title: str, meta: str):
        if not self.current_sections: self.current_sections = {}
        self.current_sections["focus_keyphrase_copy"] = fk
        self.current_sections["seo_title_copy"]       = seo_title
        self.current_sections["meta_description_copy"]= meta
        existing = self.meta_options.get("1.0", "end")
        existing = re.sub(r"Focus Keyphrase:.*",  f"Focus Keyphrase: {fk}",    existing, flags=re.MULTILINE)
        existing = re.sub(r"SEO Title:.*",        f"SEO Title: {seo_title}",   existing, flags=re.MULTILINE)
        existing = re.sub(r"Meta Description:.*", f"Meta Description: {meta}", existing, flags=re.MULTILINE)
        self.meta_options.delete("1.0", "end"); self.meta_options.insert("1.0", existing.strip())
        self._refresh_counters()
        self.set_status("AI SEO Fields applied ✓")

    # ── Generate state ────────────────────────────────────────────────────────
    def _set_generating(self, busy: bool):
        try:
            if busy: self._seo_gen_btn.configure(text="⏳ Generating...", state="disabled", fg_color="#1a3a1a")
            else:    self._seo_gen_btn.configure(text="⚡ Generate SEO", state="normal",   fg_color=T.GREEN)
        except Exception: pass

    def _clear_placeholder_if_needed(self):
        text = self.input_text.get("1.0", "end").strip()
        if self._input_placeholder or text in ("Paste article text or full HTML code here…","Paste article text or full HTML code here.."):
            self.input_text.delete("1.0", "end"); self._input_placeholder = False

    def _on_input_focus_in(self, _e=None):
        if self._input_placeholder: self.input_text.delete("1.0", "end"); self._input_placeholder = False

    def _on_input_focus_out(self, _e=None):
        if not self.input_text.get("1.0", "end").strip():
            self.input_text.insert("1.0", "Paste article text or full HTML code here…"); self._input_placeholder = True

    def _raw_input(self):
        placeholder  = "Paste article text or full HTML code here…"
        placeholder2 = "Paste article text or full HTML code here.."
        raw = self.input_text.get("1.0", "end").strip()
        if raw.startswith(placeholder):  raw = raw[len(placeholder):].strip()
        if raw.startswith(placeholder2): raw = raw[len(placeholder2):].strip()
        if raw: self._input_placeholder = False; return raw
        return ""

    def clear_input(self):
        self.input_text.delete("1.0", "end"); self._input_placeholder = False; self.set_status("Input cleared")

    def clear_output(self):
        self.output_text.config(state="normal"); self.output_text.delete("1.0", "end"); self.output_text.config(state="disabled")
        self.title_options.delete("1.0","end"); self.meta_options.delete("1.0","end")
        self.short_caption_options.delete("1.0","end"); self.hashtags_options.delete("1.0","end")
        self.generated_plain=""; self.current_sections={}
        self._seo_title_counter.configure(text="SEO Title: — chars", text_color=T.TEXT_SOFT)
        self._meta_counter.configure(text="Meta: — chars", text_color=T.TEXT_SOFT)
        self.set_status("Output cleared")

    def copy_all_output(self):
        fragment = self._build_wp_html()
        payload  = fragment or self.generated_plain
        if not payload.strip(): self.set_status("Nothing to copy — generate first"); return
        self._clipboard(payload)
        self.set_status("Copied WordPress-ready HTML" if fragment else "Copied plain text")

    def copy_section(self, name):
        if not self.current_sections: self.set_status("Generate SEO output first"); return
        MAP = {
            "Focus Keyphrase": self.current_sections.get("focus_keyphrase_copy",""),
            "SEO Title":       self.current_sections.get("seo_title_copy",""),
            "Meta Description":self.current_sections.get("meta_description_copy",""),
            "#Hashtags":       self.current_sections.get("hashtags_copy",""),
        }
        val = str(MAP.get(name,"")).strip()
        if not val: self.set_status(f"No content for {name}"); return
        val = re.sub(r"\s+", " ", val).strip()
        self._clipboard(val); self.set_status(f"Copied: {name}")

    def _clipboard(self, text):
        root = self.winfo_toplevel(); root.clipboard_clear(); root.clipboard_append(text); root.update()

    # ── Language detection ────────────────────────────────────────────────────
    def _detect_language(self, text: str) -> str:
        sample = re.sub(r"<[^>]+>", " ", text)
        sample = re.sub(r"https?://\S+", " ", sample)
        sample = re.sub(r"\s+", " ", sample).strip()[:2000]
        SCRIPTS = [
            ("Khmer",    0x1780, 0x17FF, 0.03), ("Arabic",   0x0600, 0x06FF, 0.05),
            ("Thai",     0x0E00, 0x0E7F, 0.05), ("Hindi",    0x0900, 0x097F, 0.05),
            ("Korean",   0xAC00, 0xD7AF, 0.05), ("Japanese", 0x3040, 0x309F, 0.02),
            ("Japanese", 0x30A0, 0x30FF, 0.02), ("Chinese",  0x4E00, 0x9FFF, 0.10),
            ("Russian",  0x0400, 0x04FF, 0.05),
        ]
        total = max(len(sample), 1); seen: set = set()
        for name, start, end, min_ratio in SCRIPTS:
            if name in seen: continue
            count = sum(1 for ch in sample if start <= ord(ch) <= end)
            if count / total >= min_ratio: seen.add(name); return name
        freq: dict = {}
        for w in sample.lower().split():
            w = re.sub(r"[^a-zàáâãäåæçèéêëìíîïðñòóôõöùúûüý]", "", w)
            if len(w) >= 3: freq[w] = freq.get(w, 0) + 1
        LANG_WORDS = {
            "French":     ["le","la","les","de","du","des","est","dans","pour","avec"],
            "Spanish":    ["el","la","los","de","del","que","en","es","con","por"],
            "Portuguese": ["de","da","do","que","em","para","com","uma","por","não"],
            "German":     ["der","die","das","und","von","ist","mit","dem","für","auf"],
            "Italian":    ["il","la","di","che","per","una","non","del","con","sono"],
            "Vietnamese": ["của","và","là","có","trong","được","không","này","cho","với"],
            "Indonesian": ["yang","dan","di","ke","dari","untuk","dengan","ini","pada","ada"],
        }
        best_lang, best_score = "English", 0
        for lang, markers in LANG_WORDS.items():
            score = sum(freq.get(w,0) for w in markers)
            if score > best_score: best_score = score; best_lang = lang
        return best_lang

    def _lang_badge_color(self, lang: str) -> str:
        COLORS = {"Khmer":"#f59e0b","Chinese":"#ef4444","Japanese":"#ec4899","Korean":"#8b5cf6","Arabic":"#10b981","Thai":"#06b6d4","Vietnamese":"#84cc16","English":"#3b82f6"}
        return COLORS.get(lang, "#64748b")

    def fetch_and_generate(self):
        url = self.url_entry.get().strip()
        if not url: self._log_error("ERROR: Please paste an article URL first."); self.set_status("Paste a URL first"); return
        clean_url = re.sub(r"[?&](utm_\w+|fbclid|aem_\w*|ref|source|medium|campaign)=[^&]*", "", url)
        clean_url = clean_url.rstrip("?&")
        if clean_url != url:
            url = clean_url; self.url_entry.delete(0,"end"); self.url_entry.insert(0,url)
        if not url.startswith("http"): url="https://"+url; self.url_entry.delete(0,"end"); self.url_entry.insert(0,url)
        self._fetch_btn.configure(text="⏳ Fetching...", state="disabled", fg_color=T.PURPLE_H)
        self._lang_badge.configure(text="🌐 …", text_color=T.TEXT_SOFT)
        self._detected_lang = ""
        self._last_ai_fields_key = None
        self._last_ai_fields_data = None
        self.set_status(f"Fetching: {url[:60]}...")
        self._log_error(f"Fetching URL: {url}")

        def _worker():
            import urllib.request, urllib.error, time
            STRATEGIES = [
                {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"en-US,en;q=0.9","Accept-Encoding":"gzip, deflate, br","Cache-Control":"no-cache"},
                {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"en-US,en;q=0.5"},
                {"User-Agent":"Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            ]
            html_content = None; last_err = None
            for i, hdrs in enumerate(STRATEGIES):
                try:
                    req = urllib.request.Request(url, headers=hdrs)
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        raw_bytes = resp.read(); ct = resp.headers.get("Content-Type","")
                        charset = _smart_charset(raw_bytes, ct); html_content = _smart_decode(raw_bytes, charset)
                    body_lower = html_content.lower()
                    blocked = any(kw in body_lower for kw in ["access denied","403 forbidden","blocked","captcha","cloudflare","enable javascript"])
                    if blocked and len(html_content) < 8000: html_content = None; time.sleep(0.4); continue
                    break
                except Exception as e: last_err=e; time.sleep(0.3)

            if html_content:
                lang = self._detect_language(html_content)
                self.after(0, lambda h=html_content, lg=lang: self._on_fetch_done(h, url, lg))
            else:
                err_msg = str(last_err) if last_err else "All fetch strategies failed"
                self.after(0, lambda m=err_msg: self._on_fetch_error_detail(m, url))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_fetch_error_detail(self, err_msg: str, url: str):
        self._fetch_btn.configure(text="⬇  Fetch & Generate", state="normal", fg_color=T.PURPLE)
        self._lang_badge.configure(text="🌐 —", text_color=T.TEXT_SOFT)
        self._log_error(f"All urllib strategies failed: {err_msg}")
        self.set_status("Fetch failed — paste article manually")
        messagebox.showwarning("Fetch Failed", f"Could not fetch URL:\n{err_msg[:120]}\n\nPlease paste article text manually.", parent=self.winfo_toplevel())

    def _on_fetch_done(self, html_content: str, url: str, lang: str = "English"):
        try:
            self.input_text.delete("1.0","end"); self.input_text.insert("1.0",html_content)
            self._input_placeholder=False; self._detected_lang=lang
            badge_color=self._lang_badge_color(lang)
            self._lang_badge.configure(text=f"🌐 {lang}", text_color=badge_color)
            self._log_error(f"Fetched {len(html_content)} chars | Language: {lang}")
            self.set_status(f"Fetched {len(html_content):,} chars | 🌐 {lang} — generating SEO...")
            self._fetch_btn.configure(text="⬇  Fetch & Generate", state="normal", fg_color=T.PURPLE)
            self.process_article()
        except Exception as e:
            self._log_error("Error after fetch", exc=e)
            self._fetch_btn.configure(text="⬇  Fetch & Generate", state="normal", fg_color=T.PURPLE)

    def _log_error(self, msg: str, exc: Exception = None):
        import traceback as _tb, datetime as _dt
        ts    = _dt.datetime.now().strftime("%H:%M:%S")
        lines = [f"[{ts}]  {msg}"]
        if exc is not None:
            lines.append(f"         Detail : {str(exc)}")
            tb_str = _tb.format_exc()
            if tb_str and "NoneType" not in tb_str:
                tb_lines = [l for l in tb_str.strip().splitlines() if l.strip()]
                for tl in tb_lines[-3:]: lines.append(f"         {tl.strip()}")
        entry = "\n".join(lines) + "\n" + ("-"*60) + "\n"
        try:
            self.error_log.configure(state="normal"); self.error_log.insert("end",entry)
            self.error_log.see("end"); self.error_log.configure(state="disabled")
        except Exception: pass

    def _clear_error_log(self):
        try:
            self.error_log.configure(state="normal"); self.error_log.delete("1.0","end")
            self.error_log.configure(state="disabled")
        except Exception: pass

    def process_article(self):
        self._set_generating(True); self._log_error("Generate SEO started…")
        try:
            raw = self._raw_input()
            if not raw: self._log_error("ERROR: Input is empty."); self.set_status("Please paste an article first"); return
            self._log_error(f"Input length: {len(raw)} chars")

            has_wp_blocks = "<!-- wp:" in raw or "<!-- /wp:" in raw
            if has_wp_blocks:
                self._log_error("WP Gutenberg blocks detected — processing embeds then stripping…")
                raw = self._strip_wp_block_comments(raw)
                # After stripping, always use HTML path because __PRESV_EMBED__ markers
                # and leftover HTML tags need the HTML processor to render correctly
                self._log_error("Mode: HTML parsing (post-Gutenberg strip)")
                self._process_html(raw)
            elif self._looks_html(raw):
                self._log_error("Mode: HTML parsing")
                self._process_html(raw)
            else:
                self._log_error("Mode: Plain text parsing")
                self._process_plain(raw)

            self._log_error("✓ Generate SEO completed successfully.")
        except Exception as e:
            self._log_error("GENERATE SEO FAILED", exc=e); self.set_status(f"Error: {str(e)[:120]}")
        finally:
            self._set_generating(False)

    def _strip_wp_block_comments(self, raw):
        # ── STEP 1: Preserve wp:embed blocks BEFORE stripping WP comments ──────
        # wp:embed contains the video URL as plain text inside the figure wrapper.
        # We must convert these to __PRESV_EMBED__ markers FIRST so they survive
        # the generic wp: comment stripping below.
        def _save_wp_embed(m):
            block_json = m.group(1)  # JSON attributes e.g. {"url":"https://..."}
            inner_html = m.group(2).strip()
            # Extract URL from JSON attrs
            url_m = re.search(r'"url"\s*:\s*"([^"]+)"', block_json)
            embed_url = url_m.group(1) if url_m else ""
            # Also look for bare URL inside the figure wrapper div
            if not embed_url:
                bare_m = re.search(
                    r'<div[^>]*class=["\'][^"\']*wp-block-embed__wrapper[^"\']*["\'][^>]*>\s*(https?://[^\s<]+)',
                    inner_html, re.I|re.S
                )
                if bare_m:
                    embed_url = bare_m.group(1).strip()
            if not embed_url:
                # last resort: any URL in inner block
                any_url = re.search(r'(https?://[^\s<"\']{10,})', inner_html)
                if any_url:
                    embed_url = any_url.group(1).strip()
            if embed_url:
                info = EmbedHelper.detect(embed_url)
                if info["type"]:
                    return f"\n__PRESV_EMBED_START__{info['html']}__PRESV_EMBED_END__\n"
                # Unknown URL — keep as generic iframe placeholder
                return f"\n__PRESV_EMBED_START__{inner_html}__PRESV_EMBED_END__\n"
            # No URL found — preserve inner HTML
            return f"\n{inner_html}\n"

        # Match <!-- wp:embed {...} --> ... <!-- /wp:embed --> (any video/embed type)
        raw = re.sub(
            r'<!--\s*wp:embed\s*(\{[^}]*\}|\S*)\s*-->(.*?)<!--\s*/wp:embed\s*-->',
            _save_wp_embed, raw, flags=re.I|re.S
        )

        # ── STEP 2: Preserve wp:video blocks ──────────────────────────────────
        def _save_wp_video(m):
            inner_html = m.group(1).strip()
            src_m = re.search(r'src=["\']([^"\']+)["\']', inner_html, re.I)
            url_m = re.search(r'"url"\s*:\s*"([^"]+)"', m.group(0))
            embed_url = (url_m or src_m) and (url_m.group(1) if url_m else src_m.group(1))
            if embed_url:
                info = EmbedHelper.detect(embed_url)
                if info["type"]:
                    return f"\n__PRESV_EMBED_START__{info['html']}__PRESV_EMBED_END__\n"
            return f"\n{inner_html}\n"

        raw = re.sub(
            r'<!--\s*wp:video[^-]*-->(.*?)<!--\s*/wp:video\s*-->',
            _save_wp_video, raw, flags=re.I|re.S
        )

        # ── STEP 3: Convert bare video URLs that appear as plain text inside
        #    wp:paragraph blocks (common in Gutenberg copy-paste) ──────────────
        def _convert_bare_video_url(m):
            url = m.group(0).strip()
            info = EmbedHelper.detect(url)
            if info["type"]:
                return f"\n__PRESV_EMBED_START__{info['html']}__PRESV_EMBED_END__\n"
            return url

        VIDEO_URL_PAT = (
            r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s<"\']+|'
            r'youtu\.be/[\w\-]+[^\s<"\']*|'
            r'(?:twitter|x)\.com/[A-Za-z0-9_]+/status/\d+[^\s<"\']*|'
            r'facebook\.com/[^\s<"\']+/videos/[^\s<"\']+|'
            r'fb\.watch/[\w\-]+[^\s<"\']*)'
        )
        raw = re.sub(VIDEO_URL_PAT, _convert_bare_video_url, raw)

        # ── STEP 4: Normal paragraph block unwrapping ─────────────────────────
        def fix_paragraph_block(m):
            inner = m.group(1).strip()
            if not inner: return ""
            if re.match(r"^<p[\s>]", inner, re.I): return inner + "\n"
            if re.search(r"^<(h[1-6]|div|figure|ul|ol|blockquote|iframe)", inner, re.I): return inner + "\n"
            # Bare text with __PRESV_EMBED__ → keep as-is
            if "__PRESV_EMBED_START__" in inner: return inner + "\n"
            return f"<p>{inner}</p>\n"

        cleaned = re.sub(
            r"<!--\s*wp:paragraph[^>]*-->\s*(.*?)\s*<!--\s*/wp:paragraph\s*-->",
            fix_paragraph_block, raw, flags=re.I|re.S
        )

        # ── STEP 5: Strip remaining wp: comments (but NOT PRESV markers) ──────
        cleaned = re.sub(r"<!--\s*/?\s*wp:[^>]*-->", "", cleaned, flags=re.I|re.S)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def _looks_html(self, text):
        s = text.strip().lower()
        return any(m in s for m in ("<html","<body","<div","<section","<article","<p","<h1","<h2","<h3","<iframe","<figure","__presv_embed_start__"))

    def _process_plain(self, raw):
        raw = re.sub(r"&nbsp;", " ", raw, flags=re.I)
        raw = re.sub(r"&#\d+;|&[a-z]+;", " ", raw, flags=re.I)
        raw = re.sub(r"\u00a0", " ", raw)

        # Convert __PRESV_EMBED_START__...__PRESV_EMBED_END__ (from _strip_wp_block_comments)
        # into the standard __EMBED__....__EMBED__ markers used by _render_output
        raw = re.sub(
            r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__',
            lambda m: f"\n__EMBED__{m.group(1).strip()}__EMBED__\n",
            raw, flags=re.S
        )

        def _url_to_embed(m):
            url = m.group(0).strip()
            info = EmbedHelper.detect(url)
            if info["type"]:
                return f"\n__EMBED__{info['html']}__EMBED__\n"
            return " "

        # Convert any remaining bare video URLs not yet converted
        raw = re.sub(r"https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+/status/\d+[^\s]*", _url_to_embed, raw)
        raw = re.sub(r"https?://(?:www\.)?youtube\.com/watch\?[^\s]{5,}", _url_to_embed, raw)
        raw = re.sub(r"https?://youtu\.be/[^\s]{5,}", _url_to_embed, raw)
        raw = re.sub(r"https?://(?:www\.)?youtube\.com/shorts/[^\s]{5,}", _url_to_embed, raw)
        raw = re.sub(r"https?://(?:www\.)?youtube\.com/embed/[^\s]{5,}", _url_to_embed, raw)
        raw = re.sub(r"https?://(?:www\.)?facebook\.com/[^\s]+/videos/[^\s]+", _url_to_embed, raw)
        raw = re.sub(r"https?://(?:www\.)?facebook\.com/watch/?\?[^\s]+", _url_to_embed, raw)
        raw = re.sub(r"https?://fb\.watch/[^\s]+", _url_to_embed, raw)

        # If result now contains HTML tags or PRESV markers → use HTML processor
        if self._looks_html(raw): self._process_html(raw); return

        lines  = self._clean_lines(raw)
        lines  = self._strip_seo_lines(lines)
        if not lines: self.set_status("No valid content found"); return
        h1    = self._guess_title(lines)
        intro = self._build_intro(lines)
        
        # Calculate remaining lines (Skip H1 and Intro)
        other_lines = []
        if len(lines) > 0:
            h1_seen = False
            intro_seen = False
            for l in lines:
                if not h1_seen and l.strip() == h1.strip():
                    h1_seen = True
                    continue
                if h1_seen and not intro_seen and l.strip() == intro.strip():
                    intro_seen = True
                    continue
                other_lines.append(l)

        secs = self._split_body(other_lines)
        struct = self._build_structure(secs)
        self._finish(h1, intro, struct, html_mode=False, cleaned_html=None)

    def _sanitize_wp_html(self, raw):
        raw = raw or ""
        
        # ── UNIVERSAL TWITTER HUNTER ──────────────────────────────────────────
        # Catch bare Twitter links and Gutenberg JSON URLs BEFORE stripping tags.
        # This solves the 'All Twitter' requirement for even the messiest code.
        def _early_tw_wrap(m):
            url = m.group(1).strip()
            info = EmbedHelper.detect(url)
            if info["type"] == "twitter":
                return f"__PRESV_EMBED_START__{info['html']}__PRESV_EMBED_END__"
            return m.group(0)

        # Detect within Gutenberg JSON or bare strings
        raw = re.sub(r'["\'](https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+/status/\d+[^\s"\'<>]*?)["\']', _early_tw_wrap, raw)
        
        # Aggressively remove all messy tags while keeping their content
        # PROTECT IFRAMES and DIVS that might contain social data attributes
        tags_to_strip = ("script", "style", "noscript", "svg", "canvas", "button")
        for tag in tags_to_strip:
            raw = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", raw, flags=re.I|re.S)
        
        # Remove most inline attributes but keep 'src', 'data-tweet-id', and 'href' for embeddings
        raw = re.sub(r'\b(?:style|class|id|loading|decoding|srcset|sizes|width|height|border|cellspacing|cellpadding)\s*=\s*["\'][^"\']*["\']', '', raw, flags=re.I)
        
        # សម្អាត entities &nbsp; និង non-breaking spaces
        raw = re.sub(r"&nbsp;|\xa0", " ", raw, flags=re.I)
        try:
            import html as html_mod
            raw = html_mod.unescape(raw)
        except:
            pass

        # Clean up excessive whitespace
        raw = re.sub(r'[ \t]+', ' ', raw)
        return raw.strip()

    def _parse_html_blocks(self, raw):
        import html as html_mod
        blocks = []
        raw = self._sanitize_wp_html(raw)

        def strip_tags_text(t):
            t = re.sub(r"<a\b[^>]*>(.*?)</a>", r"\1", t, flags=re.I|re.S)
            t = re.sub(r"<[^>]+>", " ", t); t = html_mod.unescape(t)
            t = re.sub(r"https?://\S+", " ", t)
            return re.sub(r"\s+", " ", t).strip()

        def clean_para_html(t):
            t = re.sub(r"<(?:script|style|noscript|form|button|svg|canvas)\b[^>]*>.*?</(?:script|style|noscript|form|button|svg|canvas)>", "", t, flags=re.I|re.S)
            t = html_mod.unescape(t); t = re.sub(r"\s+", " ", t).strip(); return t

        og_title=""; m=re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\'>]*)["\']', raw, re.I|re.S)
        if not m: m=re.search(r'<meta[^>]+content=["\']([^"\'>]*)["\'][^>]+property=["\']og:title["\']', raw, re.I|re.S)
        if m: og_title=strip_tags_text(m.group(1))
        page_title=""; m=re.search(r"<title[^>]*>(.*?)</title>", raw, re.I|re.S)
        if m: page_title=strip_tags_text(m.group(1))
        first_h1=""; m=re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.I|re.S)
        if m: first_h1=strip_tags_text(m.group(1))
        page_h1=og_title or first_h1 or page_title
        if page_h1:
            page_h1=re.sub(r"\s+[|\-–—]\s+.*$","",page_h1).strip()
            if page_h1: blocks.append({"type":"h1","content":page_h1})

        def make_embed(raw_tag):
            info = EmbedHelper.detect(raw_tag)
            return info["html"] if info["type"] else raw_tag

        token_pat = re.compile(
            r"(__PRESV_EMBED_START__.*?__PRESV_EMBED_END__)"
            r"|(<h[1-6][^>]*>.*?</h[1-6]>)"
            r"|(<blockquote\b[^>]*>.*?</blockquote>(?:\s*<script[^>]*>[^<]*</script>)?)"
            r"|(<iframe\b[^>]*>.*?</iframe>)"
            r"|(<video\b[^>]*>.*?</video>)"
            r"|(<figure\b[^>]*>.*?</figure>)"
            r"|(<img\b[^>]*>)"
            r"|(<p\b[^>]*>.*?</p>)"
            r"|(<div\b[^>]*>.*?</div>)",
            re.I|re.S)

        seen_text=set(); h1_lower=page_h1.lower().strip() if page_h1 else ""

        for m in token_pat.finditer(raw):
            tag=m.group(0); tag_lower=tag.lower()

            if tag.startswith("__PRESV_EMBED_START__"):
                embed_html=tag[len("__PRESV_EMBED_START__"):-len("__PRESV_EMBED_END__")].strip()
                if embed_html:
                    blocks.append({"type":"embed","content":embed_html,"raw":embed_html})
                continue

            hm=re.match(r"<(h[1-6])[^>]*>(.*?)</h[1-6]>", tag, re.I|re.S)
            if hm:
                level=hm.group(1).lower(); text=strip_tags_text(hm.group(2))
                if not text: continue
                low=text.lower()
                if low in {"share","related articles","recommended","read more","follow us","comments","leave a reply"}: continue
                if level=="h1" and blocks and blocks[0]["type"]=="h1":
                    if SequenceMatcher(None,blocks[0]["content"].lower(),text.lower()).ratio()>=0.80: continue
                norm=text.lower().strip()
                if norm in seen_text and level!="h2": continue
                seen_text.add(norm); blocks.append({"type":level,"content":text}); continue

            is_embed=(tag_lower.startswith("<blockquote") or tag_lower.startswith("<iframe") or tag_lower.startswith("<video") or tag_lower.startswith("<figure") or tag_lower.startswith("<img"))
            if is_embed:
                emb=make_embed(tag)
                if emb: blocks.append({"type":"embed","content":emb,"raw":tag}); continue

            pm=re.match(r"<(p|div)[^>]*>(.*?)</\1>", tag, re.I|re.S)
            if pm:
                inner_html=pm.group(2).strip()

                # V10 FIX: consume preserved embed markers inside <p>/<div> tags
                # so they do not leak into intro/body text.
                segs = re.split(r'(__PRESV_EMBED_START__.*?__PRESV_EMBED_END__)', inner_html, flags=re.S)
                for seg in segs:
                    seg = (seg or '').strip()
                    if not seg:
                        continue

                    if seg.startswith("__PRESV_EMBED_START__") and seg.endswith("__PRESV_EMBED_END__"):
                        embed_html = seg[len("__PRESV_EMBED_START__"):-len("__PRESV_EMBED_END__")].strip()
                        if embed_html:
                            blocks.append({"type":"embed","content":embed_html,"raw":embed_html})
                        continue

                    # CHECK FOR IFRAMES/EMBEDS inside the segment
                    part_html = seg
                    while True:
                        found_any = False
                        # Target tags that should be treated as separate block-level embeds
                        for emb_pat in (r"<iframe\b[^>]*>.*?</iframe>", r"<video\b[^>]*>.*?</video>", r"<blockquote\b[^>]*>.*?</blockquote>"):
                            emb_m = re.search(emb_pat, part_html, re.I|re.S)
                            if emb_m:
                                raw_emb = emb_m.group(0)
                                # Split segment into part before the embed and the rest
                                split_parts = part_html.split(raw_emb, 1)
                                before_text = split_parts[0]
                                after_text = split_parts[1]
                                
                                # Process the text appearing BEFORE this embed
                                if before_text.strip():
                                    b_plain = strip_tags_text(before_text)
                                    b_html = clean_para_html(before_text)
                                    if b_html:
                                        blocks.append({"type":"p", "content":b_html, "plain":b_plain})
                                
                                # Process and add the embed itself
                                emb_info = EmbedHelper.detect(raw_emb)
                                if emb_info["type"]:
                                    blocks.append({"type":"embed", "content":emb_info["html"], "raw":raw_emb})
                                else:
                                    # Fallback for unknown iframes/blocks - keep raw but wrap if needed
                                    blocks.append({"type":"embed", "content":raw_emb, "raw":raw_emb})
                                
                                part_html = after_text
                                found_any = True
                                break # Found one, restart the search on the 'after' text
                        
                        if not found_any:
                            break # No more embeds found in this segment

                    # Process any remaining text in this segment
                    text_plain = strip_tags_text(part_html)
                    if text_plain:
                        para_html = clean_para_html(part_html)
                        if para_html:
                            blocks.append({"type":"p", "content":para_html, "plain":text_plain})
        return blocks

    def _is_mixed_content(self, text: str) -> bool:
        """
        True when input has plain text paragraphs (no <p> wrapping) mixed with
        HTML embeds/iframes — e.g. a WordPress article copy-pasted from the
        browser that contains bare tweet URLs + platform.twitter.com iframes
        but whose text paragraphs have no <p> tags.
        """
        has_embed = bool(re.search(r'<iframe|<blockquote|<figure', text, re.I))
        p_tag_count = len(re.findall(r'<p\b', text, re.I))
        has_plain_para = bool(re.search(r'\n[ \t]*\n[A-Z\u1780-\u17ff\"\'\u2018\u201c]', text))
        return has_embed and (p_tag_count == 0 or (has_plain_para and p_tag_count < 3))

    def _wrap_plain_paragraphs(self, text: str) -> str:
        """
        For mixed content: wrap bare text blocks (not HTML/embed markers)
        in <p> tags so _parse_html_blocks can find them via token_pat.
        Also converts bare video URLs to __PRESV_EMBED__ markers.
        """
        VIDEO_URL_PAT = (
            r'https?://(?:www\.)?(?:'
            r'youtube\.com/watch\?[^\s<>"\']{5,}|'
            r'youtu\.be/[\w\-]{5,}[^\s<>"\']*|'
            r'youtube\.com/shorts/[\w\-]{5,}[^\s<>"\']*|'
            r'(?:twitter|x)\.com/[A-Za-z0-9_]+/status/\d{5,}[^\s<>"\']*|'
            r'facebook\.com/[^\s<>"\']+/videos/\d{5,}[^\s<>"\']*|'
            r'|(?<!["\'=>])https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+/status/\d+[^\s<>"\']*'
            r')'
        )

        blocks = re.split(r'\n[ \t]*\n', text)
        result = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            # Already an HTML tag or preserved embed marker → keep as-is
            if re.match(r'^<|^__PRESV_EMBED', block, re.I):
                result.append(block)
                continue
            # Pure whitespace / &nbsp; → skip
            if re.match(r'^(?:&nbsp;|\xa0|\s)+$', block, re.I):
                continue
            # Bare video/social URL on its own line → convert to embed
            bare_url_m = re.match(r'^(' + VIDEO_URL_PAT + r')$', block.strip(), re.I)
            if bare_url_m:
                url = bare_url_m.group(1).strip()
                info = EmbedHelper.detect(url)
                if info["type"]:
                    result.append(f"__PRESV_EMBED_START__{info['html']}__PRESV_EMBED_END__")
                    continue
            
            # Plain text paragraph → wrap in <p>
            # Search for and pull out video URLs even if semi-merged with text to ensure POSITION PRESERVATION
            def _inline_url_to_embed(m):
                url = m.group(0).strip()
                info = EmbedHelper.detect(url)
                if info["type"]:
                    return f"</p>\n__PRESV_EMBED_START__{info['html']}__PRESV_EMBED_END__\n<p>"
                return url
            
            block = re.sub(VIDEO_URL_PAT, _inline_url_to_embed, block)
            result.append(f'<p>{block}</p>')

        joined = '\n\n'.join(result)
        # Remove any empty <p> tags created by the inline URL replacement
        joined = re.sub(r'<p>\s*</p>', '', joined)
        joined = re.sub(r'<p>\s*\n__PRESV_EMBED', '__PRESV_EMBED', joined)
        joined = re.sub(r'__PRESV_EMBED_END__\s*\n<p>\s*</p>', '__PRESV_EMBED_END__', joined)
        return joined

    def _process_html(self, raw):
        if self._is_mixed_content(raw):
            self._log_error("Mixed content detected")
            raw = self._wrap_plain_paragraphs(raw)

        cleaned_html = self._sanitize_wp_html(raw)
        blocks = self._parse_html_blocks(cleaned_html)

        h1 = ""
        intro = ""
        struct = []

        # PRE-SCAN: Look for a real <h1> tag first to ensure it takes priority
        for b in blocks:
            if b.get("type") == "h1":
                h1 = (b.get("content") or "").strip()
                break

        intro_taken = False
        h1_captured = False # True if we've handled the H1 block (either <h1> or promoted <p>)
        current_section = None

        for b in blocks:
            btype = b.get("type")
            content = (b.get("content") or "").strip()

            if not content:
                continue

            # Case A: We found the primary H1 block (from our pre-scan)
            if btype == "h1" and not h1_captured and h1 and content == h1:
                h1_captured = True
                continue

            # Case B: No <h1> tag existed in the whole document -> Promote the first <p> or <h> to H1
            if not h1 and not h1_captured:
                if btype in ["p", "h2", "h3", "h4", "h5", "h6"]:
                    h1 = re.sub(r"<[^>]+>", "", content).strip() # Title should be plain text
                    h1_captured = True
                    continue

            # Case C: We have an H1, now look for the first paragraph to be the Intro
            if h1_captured and not intro_taken:
                if btype == "p":
                    intro = content
                    intro_taken = True
                    continue

            # everything else goes to struct
            if current_section is None:
                current_section = {"h2": "", "subsections": []}
                struct.append(current_section)

            body_content = content
            # Convert any headings in the body (or extra H1s) to bold paragraphs
            if btype in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                body_content = f"<strong>{content}</strong>"

            current_section["subsections"].append({
                "h3": "",
                "h4": "",
                "body": body_content
            })

        self._finish(
            h1,
            intro,
            struct,
            html_mode=True,
            cleaned_html=cleaned_html
        )

    def _finish(self, h1, intro, struct, html_mode, cleaned_html):
        h1 = re.sub(r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__', ' ' , str(h1 or ''), flags=re.S).strip()
        intro = re.sub(r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__', ' ' , str(intro or ''), flags=re.S).strip()

        # Keep all sections and preserve their content for dynamic re-sectioning.
        struct = list(struct or [])
        ordered_chunks = []
        existing_h2_titles = []
        for sec in struct:
            h2t = str(sec.get('h2', '') or '').strip()
            if h2t:
                existing_h2_titles.append(h2t)
            for sub in sec.get('subsections', []) or []:
                body_text = str(sub.get('body', '') or '')
                body_text = re.sub(r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__', lambda m: f"__EMBED__{m.group(1).strip()}__EMBED__", body_text, flags=re.S)
                parts = re.split(r'(__EMBED__.*?__EMBED__)', body_text, flags=re.S)
                for part in parts:
                    if not part: continue
                    if part.startswith('__EMBED__') and part.endswith('__EMBED__'):
                        emb = part[len('__EMBED__'):-len('__EMBED__')].strip()
                        if emb: ordered_chunks.append({'type': 'embed', 'content': emb})
                        continue
                    for block in [x.strip() for x in re.split(r'(?:\n\s*\n)+', part) if x.strip()]:
                        ordered_chunks.append({'type': 'text', 'content': block})

        def _guess_h2_from_chunks(chunks, fallback='Section', consume=False):
            for i, ch in enumerate(chunks):
                if ch.get('type') == 'text':
                    orig_content = ch.get('content', '')
                    # Strip internal HTML tags to analyze plain text sentence boundaries
                    plain = re.sub(r'<[^>]+>', ' ', orig_content)
                    # Find the first sentence using common sentence terminators (. ! ?)
                    sentences = re.split(r'(?<=[.!?])\s+', plain.strip())
                    if sentences and sentences[0].strip():
                        first_sentence = sentences[0].strip()
                        # Clean up punctuation from the end for the heading
                        heading_title = first_sentence.rstrip(' .!?:;')
                        
                        if consume:
                            # We must remove the used sentence from the ORIGINAL content (keeping tags if possible)
                            # Easiest way is to find the sentence text and cut it out
                            words = orig_content.split()
                            sentence_words = first_sentence.split()
                            # Match and skip the first sentence's word-count
                            remaining = " ".join(words[len(sentence_words):]).strip()
                            if not remaining or len(remaining) < 10:
                                chunks.pop(i) # Section was only one sentence, so we consume the whole block
                            else:
                                ch['content'] = remaining
                                
                        return heading_title
            return fallback

        text_chunk_count = sum(1 for ch in ordered_chunks if ch.get('type') == 'text')
        sections_data = []
        current_sec_chunks = []
        text_in_current = 0
        
        for ch in ordered_chunks:
            if ch.get('type') == 'text':
                if text_in_current >= 3:
                    sections_data.append(current_sec_chunks)
                    current_sec_chunks = []
                    text_in_current = 0
                text_in_current += 1
            current_sec_chunks.append(ch)
            
        if current_sec_chunks:
            sections_data.append(current_sec_chunks)

        def _chunks_to_body(chunks):
            out = []
            for ch in chunks:
                if ch.get('type') == 'embed':
                    out.append(f"__EMBED__{ch.get('content','').strip()}__EMBED__")
                else:
                    out.append(ch.get('content', '').strip())
            return '\n\n'.join([x for x in out if x])

        struct = []
        for i, chunks in enumerate(sections_data):
            h2_found = existing_h2_titles[i] if i < len(existing_h2_titles) else _guess_h2_from_chunks(chunks, f'Section {i+1}', consume=True)
            if not h2_found or h2_found.strip() == f'Section {i+1}':
                h2_found = f"Section {i+1}"
            struct.append({
                'h2': h2_found,
                'subsections': [{'h3': '', 'h4': '', 'body': _chunks_to_body(chunks)}]
            })

        fk            = self._make_keyphrase(h1)
        slug          = self._make_slug(h1)
        src           = re.sub(r"\s+", " ", h1 or intro or "article").strip()
        short_summary = self._trim_words(src, 200, chars=True)
        short_caption = self._build_short_caption(h1, intro, struct)
        seo_titles    = self._seo_title_options(h1)
        meta_options  = self._meta_options(intro, h1)
        seo_title     = seo_titles[0]   if seo_titles   else h1
        meta          = meta_options[0] if meta_options  else self._trim_words(intro or h1, 160, chars=True)
        full_text = h1 + " " + intro
        for sec in struct:
            full_text += " " + sec.get("h2","")
            for sub in sec.get("subsections",[]):
                full_text += " " + sub.get("h3","") + " " + sub.get("body","")
        try:   hashtags=self._generate_hashtags(full_text, h1)
        except: hashtags=[]
        parts=[]
        if h1:    parts+=[h1,""]
        if intro: parts+=[intro,""]
        for sec in struct:
            parts+=[sec.get("h2",""),""]
            for sub in sec["subsections"]:
                if sub.get("h3"): parts.append(sub["h3"])
                if sub.get("h4"): parts.append(sub["h4"])
                parts+=[sub.get("body",""),""]
        self.generated_plain="\n".join(parts).strip()
        self._render_output(h1, intro, struct)
        heads,body_blocks=[],[]
        for sec in struct:
            if sec["h2"]: heads.append(sec["h2"])
            sub_bodies=[s["body"].strip() for s in sec["subsections"] if s["body"].strip()]
            if sub_bodies: body_blocks.append("\n\n".join(sub_bodies))
        # Write to hidden backend widgets (not displayed, but preserves copy functionality)
        self.title_options.delete("1.0","end"); self.title_options.insert("1.0","SEO Title Options\n\n"+"\n".join(seo_titles or [h1]))
        self.meta_options.delete("1.0","end")
        self.meta_options.insert("1.0",f"Meta + SEO Fields\n\nFocus Keyphrase: {fk}\nSEO Title: {seo_title}\nMeta Description: {meta}\nSlug (URL): {slug}\nShort Summary: {short_summary}")
        self.short_caption_options.delete("1.0","end"); self.short_caption_options.insert("1.0",f"Short Caption (H1·H2·H3)\n\n{short_caption}")
        self.hashtags_options.delete("1.0","end"); self.hashtags_options.insert("1.0","Hashtags\n\n"+"  ".join(hashtags))
        self.current_sections=dict(
            html_input_mode=html_mode, raw_html_fragment=cleaned_html or "",
            h1_copy=h1, intro_copy=intro, headings_copy="\n".join(heads),
            structure_copy=struct, body_copy="\n\n".join(body_blocks),
            focus_keyphrase_copy=fk, seo_title_copy=seo_title,
            meta_description_copy=meta, slug_copy=slug,
            short_summary_copy=short_summary, short_caption_copy=short_caption,
            hashtags_copy=" ".join(hashtags),
        )
        self.set_status("SEO output generated ✓  —  Click 🤖 AI SEO Fields for AI-optimised Yoast fields")
        self.after(100, self._refresh_counters)

    def _generate_hashtags(self, full_text: str, h1: str) -> list:
        STOP={"the","a","an","and","or","but","in","on","at","to","for","of","with","is","are","was","were","be","been","being","have","has","had","do","does","did","will","would","could","should","may","might","shall","can","need","that","this","these","those","it","its","by","from","as","into","through","during","before","after","above","below","up","down","out","off","over","under","again","further","then","once","here","there","when","where","why","how","all","each","every","both","few","more","most","other","some","such","no","not","only","same","so","than","too","very","just","about","also","which","who","whom","what","he","she","they","we","you","i","my","your","his","her","our","their","its","new","one","two","three","get","got","use","used","make","made","take","taken","give","given","said","say","look","see"}
        clean=re.sub(r'<[^>]+>',' ',full_text); clean=re.sub(r'[^\w\s\'-]',' ',clean)
        clean=re.sub(r'\s+',' ',clean).strip().lower(); words=clean.split(); total=max(len(words),1)
        word_scores: dict={}
        for idx,word in enumerate(words):
            w=re.sub(r"[^a-z0-9']","",word)
            if len(w)<4 or w in STOP: continue
            pos_weight=1.5 if idx/total<0.20 else 1.0
            word_scores[w]=word_scores.get(w,0)+pos_weight
        bigram_scores: dict={}
        for i in range(len(words)-1):
            w1=re.sub(r"[^a-z0-9']","",words[i]); w2=re.sub(r"[^a-z0-9']","",words[i+1])
            if len(w1)>=3 and len(w2)>=3 and w1 not in STOP and w2 not in STOP:
                bg=f"{w1} {w2}"; bigram_scores[bg]=bigram_scores.get(bg,0)+1
        h1_words=set(re.sub(r"[^a-z0-9\s]","",h1.lower()).split())
        for w in list(word_scores.keys()):
            if w in h1_words: word_scores[w]=word_scores[w]*2.0
        candidates: list=[]
        for bg,score in bigram_scores.items():
            if score>=2:
                tag="#"+"".join(p.capitalize() for p in bg.split())
                candidates.append((score*1.8,tag,bg))
        for w,score in sorted(word_scores.items(),key=lambda x:-x[1]):
            tag="#"+w.capitalize()
            already=any(w in bg for _,_,bg in candidates)
            if not already: candidates.append((score,tag,w))
        candidates.sort(key=lambda x:-x[0]); seen_tags: set=set(); result: list=[]
        for _,tag,_ in candidates:
            t_lower=tag.lower()
            if t_lower not in seen_tags: seen_tags.add(t_lower); result.append(tag)
            if len(result)==8: break
        if len(result)<6:
            for w in sorted(h1_words-STOP,key=lambda x:-len(x)):
                if len(w)>=4:
                    tag="#"+w.capitalize()
                    if tag.lower() not in seen_tags: seen_tags.add(tag.lower()); result.append(tag)
                if len(result)==6: break
        return result[:8] if len(result)>=6 else result

    def _render_output(self, h1, intro, struct):
        t = self.output_text
        t.configure(state="normal"); t.delete("1.0", "end")

        def ins(text, *tags): t.insert("end", text, tags)

        # Display H1 and Intro separately at the top for a professional flow
        if h1: 
            ins("H1  ", "h1_label")
            ins(h1 + "\n\n", "h1")
        if intro and intro.strip().lower() != h1.strip().lower(): 
            ins(intro + "\n\n", "intro") 

        for sec in struct:
            if sec.get("h2"): ins("H2  ", "h2_label"); ins(sec["h2"] + "\n\n", "h2")
            for sub in sec["subsections"]:
                if sub.get("h3"): ins("H3  ", "h3_label"); ins(sub["h3"] + "\n\n", "h3")
                if sub.get("h4"): ins("H4  ", "h3_label"); ins(sub["h4"] + "\n\n", "h3")
                if sub.get("body"):
                    body   = sub["body"]
                    body = re.sub(r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__', lambda m: f"__EMBED__{m.group(1).strip()}__EMBED__", body, flags=re.S)
                    chunks = re.split(r'(__EMBED__.*?__EMBED__)', body, flags=re.S)
                    for chunk in chunks:
                        if chunk.startswith("__EMBED__") and chunk.endswith("__EMBED__"):
                            embed_raw = chunk[9:-9].strip()
                            info = EmbedHelper.detect(embed_raw)
                            embed_type = info.get("type") or "generic"
                            icon       = info.get("icon", "▶")
                            label      = info.get("label", "Embedded Media")
                            src        = info.get("src", "")
                            tag_map = {
                                "youtube": "embed_yt",
                                "twitter": "embed_tw",
                                "facebook": "embed_fb",
                                "generic":  "embed_gen",
                            }
                            embed_tag = tag_map.get(embed_type, "embed_gen")
                            ins(f"{icon}  {label}\n", embed_tag)
                            if src:
                                ins(f"    ↳ {src[:80]}\n\n", "embed_url")
                            else:
                                ins("\n", "body")
                        elif chunk.strip():
                            ins(chunk.strip() + "\n\n", "body")

        t.configure(state="disabled")

    def _clean_lines(self, text):
        text=re.sub(r"&nbsp;"," ",(text or "").replace("\r\n","\n"),flags=re.I)
        text=re.sub(r"&#\d+;|&[a-zA-Z]+;"," ",text); text=re.sub(r"\u00a0"," ",text)
        text=re.sub(r"[ \t]+"," ",text)
        raw=[l.strip() for l in text.split("\n")]
        out,last_blank=[],True
        for line in raw:
            stripped_tags=re.sub(r"<[^>]+>","",line).strip()
            if line.startswith("<") and not stripped_tags: continue
            if not line:
                if not last_blank: out.append(""); last_blank=True
            else: out.append(line); last_blank=False
        while out and out[-1]=="": out.pop()
        return out

    def _strip_seo_lines(self, lines):
        prefixes=("Focus Keyphrase:","SEO Title:","Meta Description:","Slug (URL):","Slug:","Short Summary:")
        out=[]
        for l in lines:
            s=l.strip()
            if any(s.startswith(p) for p in prefixes): continue
            if re.match(r'^https?://[^\s]+$',s) and "__EMBED__" not in s: continue
            if re.match(r'^(&nbsp;|\s)+$',s,re.I): continue
            text_only=re.sub(r"<[^>]+>","",s).strip()
            if s.startswith("<") and len(s)<200 and not text_only: continue
            if out and s and out[-1].strip()==s: continue
            out.append(l)
        while out and out[-1]=="": out.pop()
        return out

    def _trim_to_words(self, text, max_words=20):
        words=(text or "").split()
        if len(words)<=max_words: return " ".join(words).strip(" .,:-")
        trimmed=" ".join(words[:max_words])
        for punct in (".","!","?"):
            idx=trimmed.rfind(punct)
            if idx>len(trimmed)//2: return trimmed[:idx+1].strip()
        return trimmed.rstrip(" .,:-")

    def _guess_title(self, lines):
        if not lines: return "Untitled Article"
        return lines[0].strip()

    def _build_intro(self, lines):
        content=[l for l in lines[1:] if l.strip()]
        if not content: return ""
        return content[0].strip()

    def _split_body(self, lines):
        # STRICT DOUBLE-NEWLINE SPLITTING
        # We join all lines and then split only on empty lines to keep sentences intact.
        full_text = "\n".join(lines)
        # Split on one or more empty lines
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', full_text) if p.strip()]
        return paragraphs

    def _build_structure(self, sections):
        struct = []
        seen_headings = set()
        for idx, section in enumerate(sections):
            h2 = ""
            # Option ចាស់៖ ចាក់បញ្ចូល H2 រៀងរាល់ ៣ កថាខណ្ឌ សម្រាប់អត្ថបទដែលជា Plain Text
            if idx == 0 or (idx > 0 and idx % 3 == 0):
                h2 = self._choose_heading(section, seen_headings)
            
            struct.append({
                "h2": h2, 
                "subsections": [{"h3": "", "h4": "", "body": section.strip()}]
            })
        return struct

    def _choose_heading(self, text, seen):
        text=text.replace("\n"," ")
        sentences=re.split(r'(?<=[.!?])\s+',text); ranked=[]
        for s in sentences:
            s=re.sub(r"[_-]+"," ",s).strip(' "\'""''.,:;!?-'); s=re.sub(r"^[^A-Za-z0-9]+","",s)
            words=s.split()
            if len(words)<4: continue
            score=4 if 5<=len(words)<=10 else (2 if len(words)<=12 else 0)
            ranked.append((score,s))
        ranked.sort(key=lambda x:-x[0])
        for _,cand in ranked:
            key=cand.lower()
            if key in seen: continue
            if any(SequenceMatcher(None,key,p).ratio()>=0.72 for p in seen): continue
            seen.add(key); return cand
        return ""

    def _norm(self, text, title=False):
        text=re.sub(r"[_-]+"," ",text or ""); text=re.sub(r"\s+"," ",text).strip(" .,:;|-_")
        if not text: return ""
        low=text.lower()
        low=re.sub(r"(?:untitled|design|image|photo|copy|edited|edit|thumb|thumbnail|final|new|jpeg|jpg|png|webp)"," ",low)
        low=re.sub(r"\d{2,}"," ",low); low=re.sub(r"\s+"," ",low).strip() or text.strip()
        if title:
            small={"and","or","with","at","in","on","for","to","of","the","a","an"}
            return " ".join(w if (i>0 and w in small) else w.capitalize() for i,w in enumerate(low.split()))
        return low

    def _trim_words(self, text, limit, chars=False):
        text=re.sub(r"\s+"," ",text or "").strip()
        if chars:
            if len(text)<=limit: return text
            cut=text[:limit].rstrip()
            return (cut.rsplit(" ",1)[0] if " " in cut else cut).rstrip(" ,.-:;")
        return " ".join(text.split()[:limit]).strip()

    def _make_slug(self, title):
        slug=re.sub(r"[^a-z0-9\s-]","",title.lower())
        slug=re.sub(r"\s+","-",slug).strip("-")
        return re.sub(r"-{2,}","-",slug)

    def _make_keyphrase(self, title):
        return " ".join(re.sub(r"[^\w\s-]","",title).split()[:10]).strip()

    def _seo_title_options(self, title):
        base=re.sub(r"\s+"," ",title).strip()
        if not base: return []
        opts=[self._trim_words(base,70,chars=True),self._trim_words(base+" | Full Report",70,chars=True),self._trim_words(base+" | Key Updates",70,chars=True)]
        out,seen=[],set()
        for x in opts:
            if x and x.lower() not in seen: out.append(x); seen.add(x.lower())
        return out[:4]

    def _meta_options(self, intro, title):
        src=re.sub(r"\s+"," ",intro or title).strip()
        if not src: return []
        opts=[self._trim_words(src,160,chars=True),self._trim_words(title+" — "+src,160,chars=True)]
        out,seen=[],set()
        for x in opts:
            if x and x.lower() not in seen: out.append(x); seen.add(x.lower())
        return out[:3]

    def _build_short_caption(self, h1, intro, struct):
        def _clean(t): return re.sub(r"\s+"," ",(t or "").strip(" .,:-"))
        h1_part=_clean(self._norm(h1,title=True)) if h1 else ""
        intro_words=(intro or "").split(); snippet=" ".join(intro_words[:80])
        for punct in (".","!","?"):
            last=snippet.rfind(punct)
            if last>len(snippet)//2: snippet=snippet[:last+1]; break
        else: snippet=" ".join(intro_words[:100])
        snippet=_clean(snippet)
        if h1_part and snippet: cap=f"{h1_part}. {snippet}"
        elif h1_part: cap=h1_part
        else: cap=snippet
        if len(cap)<120:
            for sec in struct[:1]:
                h2=_clean(self._norm(sec.get("h2",""),title=True))
                if h2 and h2.lower() not in cap.lower(): cap=f"{cap} — {h2}"; break
        if len(cap)>160:
            cut=cap[:160]; last_space=cut.rfind(" ")
            cap=cut[:last_space].rstrip(" .,:-") if last_space>80 else cut.rstrip(" .,:-")
        cap=cap.strip(" .,:-")
        if cap and not cap.endswith((".",  "!","?")): cap+="."
        return cap

    def _html_to_plain(self, raw):
        def save_iframe(m):
            info = EmbedHelper.detect(m.group(0))
            emb_html = info["html"] if info["type"] else m.group(0)
            return f"\n__EMBED__{emb_html}__EMBED__\n"
        t=re.sub(r"<iframe\b[^>]*>.*?</iframe>",save_iframe,raw,flags=re.I|re.S)
        t=re.sub(r"<br\s*/?>","\n",t,flags=re.I)
        t=re.sub(r"</(p|div|section|article|h1|h2|h3|h4|li|blockquote)>","\n",t,flags=re.I)
        t=re.sub(r"<[^>]+>"," ",t); t=html.unescape(t)
        t=re.sub(r"(?<!__EMBED__)https?://\S+(?!__EMBED__)"," ",t)
        t=re.sub(r"[ \t]+"," ",t); t=re.sub(r"\n{3,}","\n\n",t)
        return t.strip()


    def _build_wp_html(self):
        h1=self.current_sections.get("h1_copy","")
        intro=self.current_sections.get("intro_copy","")
        struct=self.current_sections.get("structure_copy",[])
        if not h1 and not intro and not struct:
            return ""

        esc=lambda v: html.escape(str(v), quote=True)
        parts=[]

        def _clean_chunk(text: str) -> str:
            # ១. លុប placeholder/junk tags
            t = str(text or '')
            
            # សម្អាត entities &nbsp; និង non-breaking spaces ជាមុន
            t = re.sub(r'&nbsp;|\xa0', ' ', t, flags=re.I)
            t = html.unescape(t)
            
            # លុប escaped junk ដូចជា &lt;div &gt;
            t = re.sub(r'&lt;(?:div|span|iframe|p)\s*&gt;\s*&lt;/(?:div|span|iframe|p)\s*&gt;', ' ', t, flags=re.I)
            t = re.sub(r'&lt;(?:div|span|p|br)\b[^&]*&gt;', ' ', t, flags=re.I)
            t = re.sub(r'&lt;/(?:div|span|p)\s*&gt;', ' ', t, flags=re.I)
            
            # លុប tags ទទេៗពិតប្រាកដ
            t = re.sub(r'<(div|span|p|blockquote)\b[^>]*>\s*</\1>', ' ', t, flags=re.I)
            t = re.sub(r'<(div|span|p|br)\b[^>]*>', ' ', t, flags=re.I)
            t = re.sub(r'</(div|span|p)\s*>', ' ', t, flags=re.I)
            
            # ២. លុប markers ផ្សេងៗ
            t = re.sub(r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__', ' ', t, flags=re.S)
            t = re.sub(r'\bRead\s+More\b', '', t, flags=re.I).strip()
            t = re.sub(r'<button[^>]*>.*?</button>', '', t, flags=re.I|re.S).strip()
            
            # ៣. សម្អាត whitespace
            t = re.sub(r'\s+', ' ', t).strip()
            return t

        H1_S    = "font-family:Georgia,'Times New Roman',serif;font-size:clamp(26px,5.5vw,36px);font-weight:700;color:#111111;margin:0 0 20px 0;line-height:1.25;text-align:center;letter-spacing:-0.01em;"
        INTRO_S = "font-family:Georgia,'Times New Roman',serif;font-size:clamp(17px,3.8vw,20px);line-height:1.75;color:#333333;margin:0 0 30px 0;font-style:italic;text-align:center;border-top:1px solid #eeeeee;padding-top:20px;"
        H2_S    = "font-family:Georgia,'Times New Roman',serif;font-size:clamp(22px,4.5vw,28px);font-weight:700;color:#111111;margin:40px 0 15px 0;line-height:1.3;display:block;text-align:center;letter-spacing:-0.01em;"
        P_S     = "font-family:Georgia,'Times New Roman',serif;font-size:clamp(17px,3.8vw,19px);line-height:1.8;color:#222222;margin:0 0 1.6em 0;text-align:center;letter-spacing:0.01em;-webkit-font-smoothing:antialiased;"
        IMG_S   = "max-width:100%;height:auto;display:block;margin:25px auto;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,0.1);text-align:center;"
        WRAP_S  = "max-width:780px;margin:0 auto;padding:0 20px;background:#ffffff;text-align:center;"


        synthesized_h1 = str(h1 or self.current_sections.get("h1_copy", "") or "").strip()
        synthesized_h2 = [str(sec.get("h2", "") or "").strip() for sec in (struct or []) if str(sec.get("h2", "") or "").strip()]
        # Clean synthesized H2s to avoid raw URLs as headings
        synthesized_h2 = [h for h in synthesized_h2 if not h.startswith("http")]

        parts = []
        embed_count = 0
        current_in_wrapper = False

        def _open_wrapper():
            nonlocal current_in_wrapper
            if not current_in_wrapper:
                parts.append(f'<div style="{WRAP_S}">')
                current_in_wrapper = True

        def _close_wrapper():
            nonlocal current_in_wrapper
            if current_in_wrapper:
                parts.append('</div>')
                current_in_wrapper = False

        def _process_embed(embed_raw: str) -> str:
            nonlocal embed_count
            info = EmbedHelper.detect(embed_raw)
            url = (info.get("src") or info.get("html") or str(embed_raw)).strip()
            if url:
                embed_count += 1
                return f'\n\n<p style="text-align:center;">{url}</p>\n\n'
            return ""

        _open_wrapper() # Open once at the very top

        raw_fragment = str(self.current_sections.get("raw_html_fragment", "") or "")
        html_input_mode = bool(self.current_sections.get("html_input_mode"))
        
        if html_input_mode and raw_fragment.strip():
            src = rewrite_twitter_embed_urls(raw_fragment)
            token_pat = re.compile(
                r'(__PRESV_EMBED_START__.*?__PRESV_EMBED_END__)'
                r'|(<!--\s*wp:embed.*?<!--\s*/wp:embed\s*-->)'
                r'|(<iframe\b[^>]*>.*?</iframe>)'
                r'|(<blockquote\b[^>]*>.*?</blockquote>)'
                r'|(<figure\b[^>]*>.*?</figure>)'
                r'|(<img\b[^>]*>)'
                r'|(<div\b[^>]*>.*?</div>)'
                r'|(<h[1-6][^>]*>.*?</h[1-6]>)'
                r'|(<p\b[^>]*>.*?</p>)',
                re.I|re.S
            )
            raw_has_h1 = bool(re.search(r'<h1\b', src, re.I))
            raw_has_h2 = bool(re.search(r'<h2\b', src, re.I))
            synth_mode = (not raw_has_h1) or (len(synthesized_h2) >= 1 and not raw_has_h2)
            
            # Injection សម្រាប់ Synth Mode ក្នុង HTML input
            if synth_mode:
                if synthesized_h1:
                    parts.append(f'<h1 class="wp-block-heading" style="{H1_S}">{esc(synthesized_h1)}</h1>\n')
            
            text_para_seen = 0
            last = 0
            h1_seen = 1 if (raw_has_h1 or synth_mode) else 0
            h2_seen = 0 
            div_open = False

            def _append_text_paragraph(text_html: str):
                cleaned = _clean_chunk(text_html)
                if not cleaned:
                    return
                # Avoid repeating H1 as a paragraph if it's identical
                if synthesized_h1 and cleaned.lower() == synthesized_h1.lower():
                    return
                nonlocal text_para_seen
                text_para_seen += 1
                curr_style = INTRO_S if (text_para_seen == 1 and h1_seen > 0) else P_S
                parts.append('<!-- wp:paragraph -->')
                if re.search(r'<a\b|<strong|<em|<b>|<i>', cleaned, re.I):
                    parts.append(f'<p style="{curr_style}">{cleaned}</p>')
                else:
                    parts.append(f'<p style="{curr_style}">{html.escape(cleaned, quote=False)}</p>')
                parts.append('<!-- /wp:paragraph -->\n')

            for m in token_pat.finditer(src):
                before = src[last:m.start()]
                if before and re.sub(r'<[^>]+>', ' ', before).strip():
                    _append_text_paragraph(before)
                tok = m.group(0)
                low = tok.lower().strip()
                last = m.end()

                if tok.startswith('__PRESV_EMBED_START__') and tok.endswith('__PRESV_EMBED_END__'):
                    _open_wrapper()
                    embed_raw = tok[len('__PRESV_EMBED_START__'):-len('__PRESV_EMBED_END__')].strip()
                    emb = _process_embed(embed_raw)
                    if emb:
                        parts.append(emb)
                    continue

                if low.startswith('<iframe') or low.startswith('<blockquote') or low.startswith('<figure') or low.startswith('<img'):
                    _open_wrapper()
                    emb = _process_embed(tok)
                    if emb:
                        parts.append(emb)
                    continue

                if low.startswith('<!-- wp:embed'):
                    _open_wrapper()
                    parts.append(tok)
                    embed_count += 1
                    continue

                if re.match(r'<div\b', tok, re.I):
                    if not div_open:
                        div_open = True
                    continue
                if tok == '</div>':
                    if div_open:
                        div_open = False
                    continue

                hm = re.match(r'<(h[1-6])[^>]*>(.*?)</h[1-6]>', tok, re.I|re.S)
                if hm:
                    level = hm.group(1).lower()
                    heading_text = re.sub(r'<[^>]+>', ' ', hm.group(2))
                    heading_text = re.sub(r'__PRESV_EMBED_(?:START|END)__', ' ', heading_text)
                    heading_text = html.unescape(re.sub(r'\s+', ' ', heading_text)).strip()
                    if not heading_text:
                        continue
                    if level == 'h1':
                        if h1_seen == 0:
                            parts.append('<!-- wp:heading {"level":1} -->')
                            parts.append(f'<h1 class="wp-block-heading" style="{H1_S}">{esc(heading_text)}</h1>')
                            parts.append('<!-- /wp:heading -->\n')
                            h1_seen += 1
                        else:
                            _append_text_paragraph(heading_text)
                        continue
                    if level == 'h2':
                        parts.append('<!-- wp:heading -->')
                        parts.append(f'<h2 class="wp-block-heading" style="{H2_S}">{esc(heading_text)}</h2>')
                        parts.append('<!-- /wp:heading -->\n')
                        h2_seen += 1
                        continue
                    _append_text_paragraph(heading_text)
                    continue

                pm = re.match(r'<p\b[^>]*>(.*?)</p>', tok, re.I|re.S)
                if pm:
                    inner = pm.group(1).strip()
                    # បំប្លែង markers និង embedded media ចេញពី paragraph
                    # ១. បំប្លែង Presley markers
                    inner = re.sub(
                        r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__',
                        lambda mm: f"\n\n__EMBED__{mm.group(1).strip()}__EMBED__\n\n",
                        inner, flags=re.S
                    )
                    # ២. បំប្លែង raw iframes ឬ blockquotes ដែលជាប់ក្នុង paragraph
                    inner = re.sub(
                        r'((?:<iframe\b[^>]*>.*?</iframe>)|(?:<blockquote\b[^>]*>.*?</blockquote>))',
                        lambda mm: f"\n\n__EMBED__{mm.group(1).strip()}__EMBED__\n\n",
                        inner, flags=re.I|re.S
                    )
                    
                    chunks = [x.strip() for x in re.split(r'(?:\n\n)+', inner) if x.strip()]
                    if not chunks:
                        chunks = [inner]
                        
                    for chunk in chunks:
                        if chunk.startswith('__EMBED__') and chunk.endswith('__EMBED__'):
                            emb = _process_embed(chunk[9:-9].strip())
                            if emb:
                                parts.append(emb)
                        else:
                            cleaned = _clean_chunk(chunk)
                            if not cleaned:
                                continue
                            
                            # Avoid repeating H1 as a paragraph if it's identical
                            if synthesized_h1 and cleaned.lower() == synthesized_h1.lower():
                                continue
                            
                            text_para_seen += 1
                            
                            # Dynamic Heading Injection Logic
                            # Dynamic Heading Injection Logic
                            if synth_mode:
                                if h1_seen == 0 and synthesized_h1:
                                    parts.append(f'<h1 class="wp-block-heading" style="{H1_S}">{esc(synthesized_h1)}</h1>\n')
                                    h1_seen = 1
                                
                                # Injects the next H2 whenever we reach a 3-paragraph boundary
                                if h2_seen < len(synthesized_h2):
                                    target_p = 1 + (h2_seen + 1) * 3
                                    if text_para_seen == target_p:
                                        parts.append(f'<h2 class="wp-block-heading" style="{H2_S}">{esc(synthesized_h2[h2_seen])}</h2>\n')
                                        h2_seen += 1
                                    
                            # ពិនិត្យថាជា Intro ឬអត់
                            curr_style = INTRO_S if (text_para_seen == 1 and h1_seen > 0) else P_S

                            # ពិនិត្យថាមាន block tags (blockquote, div, etc) ដែរឬទេ
                            is_html_block = bool(re.search(r"<(?:blockquote|figure|table|div|iframe|h\d)\b", cleaned, re.I))
                            
                            if is_html_block:
                                parts.append(f"\n{cleaned}\n")
                            else:
                                if re.search(r'<[a-z!/]', cleaned, re.I):
                                    parts.append(f'<p style="{curr_style}">{cleaned}</p>\n')
                                else:
                                    parts.append(f'<p style="{curr_style}">{html.escape(cleaned, quote=False)}</p>\n')
            tail = src[last:]
            if tail and re.sub(r'<[^>]+>', ' ', tail).strip():
                _append_text_paragraph(tail)
        else:
            if h1:
                parts.append(f'<h1 class="wp-block-heading" style="{H1_S}">{esc(h1)}</h1>\n')
            if intro and intro.strip().lower() != h1.strip().lower():
                parts.append(f'<p style="{INTRO_S}">{esc(intro)}</p>\n')

            for i, sec in enumerate(struct):
                h2_text = str(sec.get("h2", "") or "").strip()
                # Clean H2 if it's a URL
                if h2_text.startswith("http"): h2_text = ""
                
                if h2_text and i > 0:
                    parts.append(f'<h2 class="wp-block-heading" style="{H2_S}">{esc(h2_text)}</h2>\n')

                for sub in sec.get("subsections", []):
                    body_text = re.sub(r'__PRESV_EMBED_START__(.*?)__PRESV_EMBED_END__', lambda m: f"\n\n__EMBED__{m.group(1).strip()}__EMBED__\n\n", sub.get("body", ""), flags=re.S)
                    body_text = re.sub(r'<img\b([^>]*)>', f'<img style="{IMG_S}" \\1>', body_text, flags=re.I)
                    
                    for chunk in [x.strip() for x in body_text.split("\n\n") if x.strip()]:
                        if chunk.startswith("__EMBED__") and chunk.endswith("__EMBED__"):
                            parts.append(_process_embed(chunk[9:-9].strip()))
                        else:
                            chunk_stripped = _clean_chunk(chunk.replace("\n", " ").strip())
                            if not chunk_stripped: continue
                            
                            is_html_block = bool(re.search(r"<(?:blockquote|figure|table|div|iframe|h\d)\b", chunk_stripped, re.I))
                            if is_html_block:
                                parts.append(f"\n{chunk_stripped}\n")
                            else:
                                if re.search(r"<a\b|<strong|<em|<b>|<i>", chunk_stripped, re.I):
                                    parts.append(f'<p style="{P_S}">{chunk_stripped}</p>\n')
                                else:
                                    parts.append(f'<p style="{P_S}">{html.escape(chunk_stripped, quote=False)}</p>\n')

        _close_wrapper()
        result = "\n".join(parts).strip()

        if embed_count > 0:
            note = (
                f'\n\n<!-- \n'
                f'  ✅ This HTML contains {embed_count} embed(s) as WordPress oEmbed URLs.\n'
                f'  📋 PASTE INSTRUCTIONS:\n'
                f'     • Classic Editor → "Text" tab: Paste → WordPress auto-embeds URLs ✓\n'
                f'     • Block Editor: Paste → WordPress auto-converts URLs to embed blocks ✓\n'
                f'     • Works in BOTH editors without any plugin required\n'
                f'-->'
            )
            result += note

        result = rewrite_twitter_embed_urls(result)
        # ជម្រះ markers ដែលនៅសេសសល់ (បើសិនមាន)
        result = re.sub(r'__PRESV_EMBED_(?:START|END)__', '', result)
        return result


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — IMAGE SEO
# ══════════════════════════════════════════════════════════════════════════════
class ImageSEOTab(ctk.CTkFrame):
    def __init__(self, master, set_status, api_key_getter):
        super().__init__(master, fg_color=T.APP_BG, corner_radius=0)
        self.set_status     = set_status
        self.api_key_getter = api_key_getter
        self.client         = None
        self.image_path = self.original_image = self.tk_canvas_image = None
        self.cropped_image = self.cropped_temp_path = None
        self.zoom_factor = self.base_scale = self.display_scale = 1.0
        self.display_w = self.display_h = 1
        self.image_offset_x = self.image_offset_y = 0.0
        self.current_ratio  = 1200/366
        self.lock_ratio_var = ctk.BooleanVar(value=True)
        self.safe_zone_var  = ctk.BooleanVar(value=False)
        self.crop_rect      = [120.0,60.0,720.0,243.0]
        self.dragging_crop = self.dragging_image = False
        self.resizing_handle = None
        self.crop_drag_start = self.image_drag_start = (0.0,0.0)
        self.start_crop_rect = self.start_offset = None
        self.handle_size     = 12.0
        self.canvas_image_item = None
        self._redraw_id = None
        self._preview_cache_sz = self._preview_cache_img = None
        self._last_canvas_size = (0,0)
        self.show_crop_overlay = True
        self.export_folder = load_export_folder()
        # Ensure SEO fields are initialized to None to prevent AttributeError
        self.scene_entry = self.alt_text = self.img_title = self.caption = self.description = None
        self.auto_seo_var = tk.BooleanVar(value=True)
        self._build()
        self.init_client()

    def init_client(self):
        t_key = self.api_key_getter("together").strip()
        o_key = self.api_key_getter("openai").strip()
        self.client = t_key or o_key # For backward compatibility in some places
        self.api_keys = {"together": t_key, "openai": o_key}
        
        if not t_key and not o_key:
            self.set_status("Image SEO — open API Settings to enable AI generation")
            return
            
        status = []
        if t_key: status.append("Together AI")
        if o_key: status.append("OpenAI")
        self.set_status(f"{' & '.join(status)} keys loaded ✓")
        if t_key:
            threading.Thread(target=self._verify_bg, args=(t_key,), daemon=True).start()

    refresh_client = init_client

    def _verify_bg(self, key):
        try:
            verify_key(key, timeout=15)
            self.after(0, lambda: self.set_status("Together AI API ready ✓"))
        except Exception as e:
            self.after(0, lambda msg=str(e)[:100]: self.set_status(f"Together AI warning: {msg}"))

    def _build(self):
        bar=ctk.CTkFrame(self,fg_color=T.PANEL_BG,corner_radius=12,border_width=1,border_color=T.PANEL_BORDER)
        bar.pack(fill="x",padx=0,pady=(0,8))
        inner=ctk.CTkFrame(bar,fg_color="transparent")
        inner.pack(fill="x",padx=12,pady=8)
        Btn(inner,"⬆  Upload Image",self.upload_image,"purple",148,34).pack(side="left",padx=(0,6))
        self._gen_btn=Btn(inner,"⚡ Generate SEO",self.generate_seo,"green",148,34)
        self._gen_btn.pack(side="left",padx=(0,6))
        Btn(inner,"⧉  Copy All SEO",self.copy_all,"teal",140,34).pack(side="left",padx=(0,6))
        Btn(inner,"✕  Clear",self.clear_fields,"red",100,34).pack(side="left")
        body=ctk.CTkFrame(self,fg_color="transparent")
        body.pack(fill="both",expand=True)
        body.grid_columnconfigure(0,weight=70); body.grid_columnconfigure(1,weight=30); body.grid_rowconfigure(0,weight=1)
        cf=ctk.CTkFrame(body,fg_color=T.PANEL_BG_2,corner_radius=14,border_width=1,border_color=T.PANEL_BORDER)
        cf.grid(row=0,column=0,sticky="nsew",padx=(0,6))
        self._build_crop_panel(cf)
        
        # Sidebar for SEO Fields
        rf=ctk.CTkFrame(body,fg_color=T.PANEL_BG_2,corner_radius=14,border_width=1,border_color=T.PANEL_BORDER)
        rf.grid(row=0,column=1,sticky="nsew")
        self._build_seo_fields(rf)

    def _build_seo_fields(self, rf):
        P=dict(padx=12,pady=(0,8)); INP=ctk.CTkFont("Segoe UI",12)
        def lbl(text): ctk.CTkLabel(rf,text=text,font=ctk.CTkFont("Segoe UI",10,"bold"),text_color=T.TEXT_SOFT,anchor="w").pack(fill="x",padx=12,pady=(10,2))
        
        lbl("KEYWORD / SCENE NOTES")
        self.scene_entry=ctk.CTkEntry(rf,height=34,corner_radius=8,fg_color=T.INPUT_BG,border_color=T.INPUT_BORDER,border_width=1,text_color=T.TEXT_MAIN,font=INP,placeholder_text="car review / news context…",placeholder_text_color=T.PLACEHOLDER)
        self.scene_entry.pack(fill="x",**P)

        # Quick Copy Pill Buttons (Restored)
        g=ctk.CTkFrame(rf,fg_color="transparent"); g.pack(fill="x",padx=12,pady=(0,4))
        g.grid_columnconfigure((0,1),weight=1)
        Btn(g,"⧉ Alt Text",self.copy_alt,"blue",90,28).grid(row=0,column=0,sticky="ew",padx=(0,3),pady=2)
        Btn(g,"⧉ Img Title",self.copy_title,"blue",90,28).grid(row=0,column=1,sticky="ew",padx=(3,0),pady=2)
        Btn(g,"⧉ Caption",self.copy_caption,"blue",90,28).grid(row=1,column=0,sticky="ew",padx=(0,3),pady=2)
        Btn(g,"⧉ Description",self.copy_description,"blue",90,28).grid(row=1,column=1,sticky="ew",padx=(3,0),pady=2)
        Btn(g,"⧉ Copy All SEO",self.copy_all,"teal",180,28).grid(row=2,column=0,columnspan=2,sticky="ew",pady=(2,4))
        
        lbl("ALT TEXT (SEO)")
        self.alt_text = ctk.CTkEntry(rf,height=34,corner_radius=8,fg_color=T.INPUT_BG,border_color=T.INPUT_BORDER,border_width=1,text_color=T.TEXT_MAIN,font=INP)
        self.alt_text.pack(fill="x",**P)
        
        lbl("IMAGE TITLE")
        self.img_title = ctk.CTkEntry(rf,height=34,corner_radius=8,fg_color=T.INPUT_BG,border_color=T.INPUT_BORDER,border_width=1,text_color=T.TEXT_MAIN,font=INP)
        self.img_title.pack(fill="x",**P)
        
        lbl("CAPTION")
        self.caption = ctk.CTkTextbox(rf,height=80,corner_radius=8,fg_color=T.INPUT_BG,border_color=T.INPUT_BORDER,border_width=1,text_color=T.TEXT_MAIN,font=INP)
        self.caption.pack(fill="x",**P)
        
        lbl("DESCRIPTION")
        self.description = ctk.CTkTextbox(rf,height=100,corner_radius=8,fg_color=T.INPUT_BG,border_color=T.INPUT_BORDER,border_width=1,text_color=T.TEXT_MAIN,font=INP)
        self.description.pack(fill="both",expand=True,padx=12,pady=(0,12))

    def _build_crop_panel(self,cf):
        tb=ctk.CTkFrame(cf,fg_color="transparent"); tb.pack(fill="x",padx=10,pady=(8,6))
        for label,w,h in [("1200×366",1200,366),("800×445",800,445),("1:1",1,1),("16:9",16,9),("4:3",4,3)]:
            Btn(tb,label,lambda _w=w,_h=h: self.set_preset(_w,_h),"blue",72,26).pack(side="left",padx=(0,4))
        ctk.CTkSwitch(tb,text="Lock Ratio",variable=self.lock_ratio_var,progress_color=T.GREEN,text_color=T.TEXT_SOFT,font=ctk.CTkFont("Segoe UI",11,"bold")).pack(side="left",padx=(6,6))
        ctk.CTkSwitch(tb,text="Safe Zone",variable=self.safe_zone_var,progress_color=T.PURPLE,text_color=T.TEXT_SOFT,font=ctk.CTkFont("Segoe UI",11,"bold"),command=self.redraw).pack(side="left",padx=(0,8))
        ctk.CTkCheckBox(tb,text="Auto SEO",variable=self.auto_seo_var,border_width=2,corner_radius=4,font=ctk.CTkFont("Segoe UI",11,"bold"),text_color=T.TEXT_SOFT,fg_color=T.GREEN,hover_color="#1d6e3e").pack(side="left",padx=(0,10))
        ctk.CTkLabel(tb,text="Zoom",font=ctk.CTkFont("Segoe UI",11),text_color=T.TEXT_SOFT).pack(side="left",padx=(0,4))
        self.zoom_slider=ctk.CTkSlider(tb,from_=0.5,to=3.0,width=110,number_of_steps=250,command=self._on_zoom)
        self.zoom_slider.set(1.0); self.zoom_slider.pack(side="left")
        cw=tk.Frame(cf,bg="#020c1a",highlightthickness=1,highlightbackground="#1e3d60")
        cw.pack(fill="both",expand=True,padx=10,pady=(0,6))
        self.canvas=tk.Canvas(cw,bg="#020c1a",highlightthickness=0,cursor="crosshair")
        self.canvas.pack(fill="both",expand=True)
        for seq,fn in [("<Button-1>",self._press),("<B1-Motion>",self._drag),("<ButtonRelease-1>",self._release),("<MouseWheel>",self._mousewheel),("<Configure>",lambda e: self._request_redraw(20))]:
            self.canvas.bind(seq,fn)
        save_row=ctk.CTkFrame(cf,fg_color="transparent")
        save_row.pack(fill="x",padx=10,pady=(0,6))
        ctk.CTkLabel(save_row,text="Save Folder",font=ctk.CTkFont("Segoe UI",10,"bold"),text_color=T.TEXT_SOFT).pack(side="left",padx=(0,6))
        self.save_folder_entry=ctk.CTkEntry(save_row,height=30,corner_radius=8,fg_color=T.INPUT_BG,border_color=T.INPUT_BORDER,border_width=1,text_color=T.TEXT_MAIN,font=ctk.CTkFont("Segoe UI",11))
        self.save_folder_entry.pack(side="left",fill="x",expand=True,padx=(0,6))
        self.save_folder_entry.insert(0,self.export_folder)
        self.save_folder_entry.bind("<FocusOut>", lambda e: self.save_export_folder_from_entry())
        self.save_folder_entry.bind("<Return>", lambda e: self.save_export_folder_from_entry())
        Btn(save_row,"📁 Browse",self.choose_export_folder,"blue",96,30).pack(side="left")

        bot=ctk.CTkFrame(cf,fg_color="transparent"); bot.pack(fill="x",padx=10,pady=(0,8))
        Btn(bot,"✔ Apply Crop",self.apply_crop,"green",124,30).pack(side="left",padx=(0,6))
        Btn(bot,"💾 Export <100KB",self.export_under_100kb,"yellow",148,30).pack(side="left",padx=(0,6))
        Btn(bot,"✕ Clear Crop",self.clear_crop,"red",110,30).pack(side="left")
        self.crop_info=ctk.CTkLabel(bot,text="No image loaded",font=ctk.CTkFont("Segoe UI",11),text_color=T.TEXT_SOFT,anchor="e")
        self.crop_info.pack(side="right")

    def upload_image(self):
        path=filedialog.askopenfilename(title="Choose Image",filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path: return
        try:
            self.image_path=path; self.original_image=Image.open(path).convert("RGB")
            self.cropped_image=None; self._clear_temp(); self._preview_cache_sz=self._preview_cache_img=None
            self.show_crop_overlay=True
            self.zoom_factor=1.0; self.zoom_slider.set(1.0); self.image_offset_x=self.image_offset_y=0.0
            self._reset_crop(); self._request_redraw(30)
            n=os.path.basename(path); w,h=self.original_image.size
            self.crop_info.configure(text=f"Loaded: {n}  •  {w}×{h}px"); self.set_status("Image loaded")
        except Exception as e: messagebox.showerror("Image Error",str(e))

    def _active_image(self):
        return self.cropped_image or self.original_image

    def _current_image_bounds(self):
        left = float(self.image_offset_x)
        top = float(self.image_offset_y)
        right = left + float(self.display_w)
        bottom = top + float(self.display_h)
        return left, top, right, bottom

    def _reset_crop(self):
        try:
            cw=max(300,self.canvas.winfo_width() or 860); ch=max(220,self.canvas.winfo_height() or 520)
        except Exception:
            cw,ch=1020,560
        active = self._active_image()
        if active:
            iw, ih = active.size
            self.base_scale=min(cw/max(iw,1),ch/max(ih,1))
            self.display_scale=self.base_scale*self.zoom_factor
            self.display_w=max(1,int(iw*self.display_scale))
            self.display_h=max(1,int(ih*self.display_scale))
            self.image_offset_x=(cw-self.display_w)/2
            self.image_offset_y=(ch-self.display_h)/2
            left, top, right, bottom = self._current_image_bounds()
            area_w=max(120.0, right-left)
            area_h=max(80.0, bottom-top)
            r=self.current_ratio
            tw=min(area_w,max(80.0,area_w*0.82))
            th=tw/r
            if th>area_h:
                th=area_h*0.82
                tw=th*r
            tw=max(80.0,min(tw,area_w))
            th=max(50.0,min(th,area_h))
            x1=left+(area_w-tw)/2
            y1=top+(area_h-th)/2
            self.crop_rect=[x1,y1,x1+tw,y1+th]
            self._clamp()
            return
        r=self.current_ratio; tw=min(cw-100,max(320,int(cw*0.72))); th=tw/r
        if th>ch-100: th=ch-100; tw=th*r
        x1=(cw-tw)/2; y1=(ch-th)/2; self.crop_rect=[x1,y1,x1+tw,y1+th]

    def set_preset(self,w,h):
        self.current_ratio=w/max(h,1)
        self.show_crop_overlay=True
        self._reset_crop()
        self._request_redraw(10)
        self.set_status(f"Crop preset: {w}×{h}")

    def _request_redraw(self,delay=10):
        if self._redraw_id is not None:
            try: self.after_cancel(self._redraw_id)
            except: pass
        self._redraw_id=self.after(delay,self.redraw)

    def _get_preview(self):
        active=self._active_image()
        if active is None:
            return None
        sz=(self.display_w,self.display_h,id(active))
        if self._preview_cache_img is None or self._preview_cache_sz!=sz:
            self._preview_cache_img=ImageTk.PhotoImage(active.resize((self.display_w,self.display_h),Image.LANCZOS))
            self._preview_cache_sz=sz
        return self._preview_cache_img

    def redraw(self):
        self._redraw_id=None
        active=self._active_image()
        if not active:
            self.canvas.delete("all")
            self.canvas_image_item=None
            return
        self.canvas.update_idletasks()
        cw,ch=self.canvas.winfo_width(),self.canvas.winfo_height()
        if cw<10 or ch<10:
            return
        iw,ih=active.size
        self.base_scale=min(cw/max(iw,1),ch/max(ih,1))
        self.display_scale=self.base_scale*self.zoom_factor
        self.display_w=max(1,int(iw*self.display_scale))
        self.display_h=max(1,int(ih*self.display_scale))
        csz=(cw,ch,id(active))
        if (self.image_offset_x==0 and self.image_offset_y==0) or self._last_canvas_size!=csz:
            self.image_offset_x=(cw-self.display_w)/2
            self.image_offset_y=(ch-self.display_h)/2
            self._last_canvas_size=csz
            self._clamp()
        self.tk_canvas_image=self._get_preview()
        if self.tk_canvas_image is None:
            return
        if self.canvas_image_item is None:
            self.canvas_image_item=self.canvas.create_image(self.image_offset_x,self.image_offset_y,image=self.tk_canvas_image,anchor="nw",tags=("base_image",))
        else:
            self.canvas.itemconfig(self.canvas_image_item,image=self.tk_canvas_image)
            self.canvas.coords(self.canvas_image_item,self.image_offset_x,self.image_offset_y)
        if self.show_crop_overlay:
            if self.show_crop_overlay:
                self._draw_overlay()

    def _draw_overlay(self):
        self.canvas.delete("overlay")
        x1,y1,x2,y2=self.crop_rect; cw=max(1,self.canvas.winfo_width()); ch=max(1,self.canvas.winfo_height())
        for coords in [(0,0,cw,y1),(0,y2,cw,ch),(0,y1,x1,y2),(x2,y1,cw,y2)]:
            self.canvas.create_rectangle(*coords,fill="#000000",stipple="gray25",outline="",tags=("overlay",))
        self.canvas.create_rectangle(x1,y1,x2,y2,outline="#5eead4",width=2,tags=("overlay",))
        if self.safe_zone_var.get():
            self.canvas.create_text(
                x1 + 10, max(12, y1 - 12),
                text="Crop Area",
                anchor="w",
                fill="#5eead4",
                font=("Segoe UI", 10, "bold"),
                tags=("overlay",),
            )
        s=self.handle_size/2
        for hx,hy in self._handles():
            self.canvas.create_rectangle(hx-s,hy-s,hx+s,hy+s,fill="#ffffff",outline="#1e40af",tags=("overlay",))

    def _handles(self):
        x1,y1,x2,y2=self.crop_rect; mx,my=(x1+x2)/2,(y1+y2)/2
        return [(x1,y1),(mx,y1),(x2,y1),(x1,my),(x2,my),(x1,y2),(mx,y2),(x2,y2)]

    def _detect_handle(self,x,y):
        labels=["nw","n","ne","w","e","sw","s","se"]
        for label,(hx,hy) in zip(labels,self._handles()):
            if abs(x-hx)<=self.handle_size and abs(y-hy)<=self.handle_size: return label
        return None

    def _in_crop(self,x,y): x1,y1,x2,y2=self.crop_rect; return x1<=x<=x2 and y1<=y<=y2
    def _in_image(self,x,y): return (self.image_offset_x<=x<=self.image_offset_x+self.display_w and self.image_offset_y<=y<=self.image_offset_y+self.display_h)

    def _press(self,e):
        self.show_crop_overlay=True
        self.resizing_handle=self._detect_handle(e.x,e.y); self.crop_drag_start=(e.x,e.y)
        self.start_crop_rect=self.crop_rect[:]; self.start_offset=(self.image_offset_x,self.image_offset_y)
        if self.resizing_handle:
            self.dragging_crop=True; self.dragging_image=False
        elif self._in_crop(e.x,e.y):
            self.dragging_crop=True; self.dragging_image=False
        elif self._in_image(e.x,e.y):
            crop_w=max(80.0, self.crop_rect[2]-self.crop_rect[0])
            crop_h=max(50.0, self.crop_rect[3]-self.crop_rect[1])
            left, top, right, bottom = self._current_image_bounds()
            nx1=max(left, min(right - crop_w, e.x - crop_w/2))
            ny1=max(top, min(bottom - crop_h, e.y - crop_h/2))
            self.crop_rect=[nx1, ny1, nx1 + crop_w, ny1 + crop_h]
            self._clamp()
            self.dragging_crop=True; self.dragging_image=False
            self.start_crop_rect=self.crop_rect[:]
            self._draw_overlay()
        else:
            self.dragging_crop=self.dragging_image=False

    def _drag(self,e):
        dx=e.x-self.crop_drag_start[0]; dy=e.y-self.crop_drag_start[1]
        if self.dragging_image:
            self.image_offset_x=self.start_offset[0]+dx; self.image_offset_y=self.start_offset[1]+dy
            if self.canvas_image_item: self.canvas.coords(self.canvas_image_item,self.image_offset_x,self.image_offset_y)
            if self.show_crop_overlay:
                self._draw_overlay()
            return
        if self.dragging_crop:
            if self.resizing_handle: self._resize(self.resizing_handle,dx,dy)
            else:
                x1,y1,x2,y2=self.start_crop_rect; w,h=x2-x1,y2-y1
                self.crop_rect=[x1+dx,y1+dy,x1+dx+w,y1+dy+h]; self._clamp()
            self._draw_overlay()

    def _release(self,_e): self.dragging_crop=self.dragging_image=False; self.resizing_handle=None

    def _clamp(self):
        if self._active_image() and self.display_w > 0 and self.display_h > 0:
            left, top, right, bottom = self._current_image_bounds()
        else:
            left, top = 0.0, 0.0
            right=max(1,self.canvas.winfo_width())
            bottom=max(1,self.canvas.winfo_height())
        x1,y1,x2,y2=self.crop_rect
        mw,mh=80.0,50.0
        max_x1=max(left, right-mw)
        max_y1=max(top, bottom-mh)
        x1=max(left,min(max_x1,x1))
        y1=max(top,min(max_y1,y1))
        x2=max(x1+mw,min(right,x2))
        y2=max(y1+mh,min(bottom,y2))
        self.crop_rect=[x1,y1,x2,y2]

    def _resize(self,handle,dx,dy):
        x1,y1,x2,y2=self.start_crop_rect
        if "w" in handle: x1+=dx
        if "e" in handle: x2+=dx
        if "n" in handle: y1+=dy
        if "s" in handle: y2+=dy
        if self.lock_ratio_var.get():
            r=self.current_ratio; w=max(80,x2-x1); h=max(50,y2-y1)
            if abs(dx)>=abs(dy): h=w/r; y1=(y2-h if "n" in handle and "s" not in handle else y1); y2=y1+h
            else: w=h*r; x1=(x2-w if "w" in handle and "e" not in handle else x1); x2=x1+w
        self.crop_rect=[x1,y1,x2,y2]; self._clamp()

    def _mousewheel(self,e):
        delta=0.08 if e.delta>0 else -0.08; v=min(3.0,max(0.5,self.zoom_factor+delta))
        if abs(v-self.zoom_factor)<0.0001: return
        self.zoom_factor=v; self.zoom_slider.set(v); self._request_redraw(5)

    def _on_zoom(self,v): self.zoom_factor=float(v); self._request_redraw(5)

    def apply_crop(self):
        active=self._active_image()
        if not active:
            self.set_status("Upload an image first")
            return
        if self.display_scale <= 0:
            self.redraw()
        iw,ih=active.size
        x1,y1,x2,y2=[float(v) for v in self.crop_rect]
        scale=max(self.display_scale,0.0001)
        left=max(0,min(iw,int(round((x1-self.image_offset_x)/scale))))
        top=max(0,min(ih,int(round((y1-self.image_offset_y)/scale))))
        right=max(left+1,min(iw,int(round((x2-self.image_offset_x)/scale))))
        bottom=max(top+1,min(ih,int(round((y2-self.image_offset_y)/scale))))
        try:
            cropped=active.crop((left,top,right,bottom)).convert("RGB")
            self.cropped_image=cropped
            self._clear_temp()
            tmp=tempfile.NamedTemporaryFile(delete=False,suffix=".jpg")
            tmp.close()
            cropped.save(tmp.name,"JPEG",quality=95)
            self.cropped_temp_path=tmp.name
            self._preview_cache_sz=self._preview_cache_img=None
            self.image_offset_x=self.image_offset_y=0.0
            self._last_canvas_size=(0,0)
            self._reset_crop()
            self.show_crop_overlay=False
            self._request_redraw(10)
            self.crop_info.configure(text=f"Cropped: {cropped.size[0]}×{cropped.size[1]}px")
            self.set_status(f"Crop applied: showing only cropped image {cropped.size[0]}×{cropped.size[1]}px")
            
            if self.auto_seo_var.get():
                self.after(200, self.generate_seo)
        except Exception as e:
            self.set_status(f"Crop error: {str(e)[:120]}")

    def clear_crop(self):
        self.show_crop_overlay=True
        self.cropped_image=None
        self._clear_temp()
        self._preview_cache_sz=self._preview_cache_img=None
        self.image_offset_x=self.image_offset_y=0.0
        self._last_canvas_size=(0,0)
        if self.original_image:
            self._reset_crop()
            self.redraw()
        self.set_status("Crop cleared")

    def _clear_temp(self):
        if self.cropped_temp_path and os.path.exists(self.cropped_temp_path):
            try: os.remove(self.cropped_temp_path)
            except: pass
        self.cropped_temp_path=None

    def _active_path(self):
        if self.cropped_temp_path and os.path.exists(self.cropped_temp_path): return self.cropped_temp_path
        return self.image_path

    def save_export_folder_from_entry(self):
        try:
            folder = self.save_folder_entry.get().strip() if hasattr(self, "save_folder_entry") else ""
            self.export_folder = save_export_folder(folder)
            if hasattr(self, "save_folder_entry"):
                self.save_folder_entry.delete(0, "end")
                self.save_folder_entry.insert(0, self.export_folder)
            self.set_status(f"Save folder set: {self.export_folder}")
            return self.export_folder
        except Exception as e:
            self.set_status(f"Save folder error: {str(e)[:120]}")
            return self.export_folder

    def choose_export_folder(self):
        start_dir = self.export_folder or load_export_folder()
        try:
            folder = filedialog.askdirectory(title="Choose Save Folder", initialdir=start_dir)
        except Exception:
            folder = filedialog.askdirectory(title="Choose Save Folder")
        if not folder:
            return
        self.export_folder = save_export_folder(folder)
        if hasattr(self, "save_folder_entry"):
            self.save_folder_entry.delete(0, "end")
            self.save_folder_entry.insert(0, self.export_folder)
        self.set_status(f"Save folder saved: {self.export_folder}")

    def export_under_100kb(self):
        if not self.original_image and not self.cropped_image:
            self.set_status("Upload or crop an image first")
            return
        try:
            img=(self.cropped_image or self.original_image).copy()
            source_path=self._active_path() or self.image_path or "image.jpg"
            save_folder = self.save_export_folder_from_entry()
            save_path, final_kb, best_q = auto_save_export_image(img, source_path, max_kb=100, save_dir=save_folder)
            self.set_status(f"Saved JPG {final_kb:.1f}KB  quality={best_q}  →  {save_path}")
        except Exception as e:
            self.set_status(f"Export error: {str(e)[:120]}")

    def _set_generating(self,busy:bool):
        try:
            if busy: self._gen_btn.configure(text="⏳ Generating…",state="disabled",fg_color="#1a3a1a")
            else:    self._gen_btn.configure(text="⚡ Generate SEO",state="normal",fg_color=T.GREEN)
        except: pass

    def generate_seo(self):
        active=self._active_path()
        if not active or not os.path.exists(active): self.set_status("Upload an image first"); return
        
        t_key = self.api_key_getter("together")
        o_key = self.api_key_getter("openai")
        
        if not t_key and not o_key:
            messagebox.showerror("API Not Ready", "No API key loaded.\nOpen API Settings → paste key → Test → Save & Use."); return
        scene_notes=self.scene_entry.get().strip()
        self._set_generating(True); self.set_status("Reading image & generating WordPress SEO fields…")
        threading.Thread(target=self._worker,args=(scene_notes,active),daemon=True).start()

    def _prepare_image_bytes(self,path:str)->tuple:
        img=Image.open(path).convert("RGB"); w,h=img.size
        MAX=1024
        if max(w,h)>MAX: scale=MAX/max(w,h); img=img.resize((int(w*scale),int(h*scale)),Image.LANCZOS)
        buf=io.BytesIO(); img.save(buf,"JPEG",quality=88,optimize=True)
        b64=base64.b64encode(buf.getvalue()).decode(); return b64,"image/jpeg"

    def _worker(self, scene_notes: str, path: str):
        try:
            self.after(0, lambda: self.set_status("Preparing image…"))
            b64, media_type = self._prepare_image_bytes(path)
            data_url = f"data:{media_type};base64,{b64}"
            scene_hint = f"\n\nContext/keyword hint from editor: \"{scene_notes}\"" if scene_notes else ""
            
            # បន្ថែម Random Tone ដើម្បីឲ្យការ Generate លើកក្រោយៗទទួលបានលទ្ធផលថ្មីៗ មិនជាន់គ្នា
            tones = [
                "highly engaging and click-driven", 
                "professional and descriptive", 
                "compelling and action-oriented", 
                "journalistic and precise",
                "SEO-optimized and descriptive"
            ]
            chosen_tone = random.choice(tones)

            prompt = f"""You are a WordPress SEO specialist writing metadata for a FEATURED IMAGE.
Write fresh, {chosen_tone} variations. DO NOT give the same output as before.

Look at the image carefully and return ONLY valid JSON with exactly these 4 keys:

{{
  "alt_text": "8-12 words. Max 80 chars. Describe main subject and setting. NO 'image of' or 'picture of'. Include focus keyword naturally.",
  "img_title": "4-8 words, Title Case. Short, clickable, matches on-image headline if present.",
  "caption": "ONE complete journalistic sentence, 15-25 words.",
  "description": "1-2 detailed sentences using this FORMULA: (Visual content) + (Main people/objects) + (Headline text) + (Story/Context). Start with 'This dramatic image shows...' or similar."
}}

RULES:
- DO NOT cut words in half.
- Use active language and be specific (names, emotions, recognizable logos).
- If readable text appears, include the most important text naturally in the Title and Description.
- If the editor's scene hint names a specific person/event, use it only if visually verified.
Output ONLY the JSON object. No markdown, no explanation.{scene_hint}"""

            last_err = None
            model_candidates = []
            # Priority: Try OpenAI flagship first if available (per user request for ultra speed & accuracy)
            if self.api_keys.get("openai"):
                model_candidates.append("gpt-4o")
                model_candidates.append("gpt-4o-mini")
            
            # Then Together models
            for model in [
                FAST_IMAGE_SEO_MODEL,
                FAST_IMAGE_SEO_FALLBACK_MODEL,
                VISION_MODEL,
                VISION_FALLBACK_MODEL,
                "moonshotai/Kimi-K2.5",
            ]:
                model = (model or "").strip()
                if model and model not in model_candidates:
                    model_candidates.append(model)
                    
            for model in model_candidates:
                try:
                    self.after(0, lambda m=model: self.set_status(f"AI analysing image with {m.split('/')[-1]}…"))
                    extra = {"reasoning": {"enabled": False}} if "Kimi" in model else {}
                    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_url}}]}]

                    try:
                        # Determine which key to use for this specific model
                        is_openai_model = str(model).lower().startswith("gpt-")
                        active_key = self.api_keys.get("openai" if is_openai_model else "together")
                        
                        if not active_key:
                            continue # Skip if key missing for this provider
                            
                        # ដំឡើង temperature=0.6 ដើម្បីឲ្យវាមានគំនិតច្នៃប្រឌិត និងមិនចេញពាក្យដដែលៗរាល់ដង
                        resp = chat_completion(active_key, model, messages=messages, temperature=0.65, top_p=0.9, response_format={"type": "json_object"} if is_openai_model or "Kimi" in model else None, timeout=FAST_IMAGE_TIMEOUT, max_tokens=FAST_IMAGE_SEO_MAX_TOKENS, **extra)
                        content = extract_content(resp).strip()
                        if not content:
                            raise RuntimeError("empty content")
                    except Exception as e:
                        if "HTTP 404" in str(e) or "HTTP 401" in str(e) or "not found" in str(e).lower():
                            raise e
                        
                        active_key = self.api_keys.get("openai" if is_openai_model else "together")
                        resp = chat_completion(active_key, model, messages=messages, temperature=0.65, top_p=0.9, timeout=FAST_IMAGE_TIMEOUT, max_tokens=FAST_IMAGE_SEO_MAX_TOKENS, **extra)
                        content = extract_content(resp).strip()

                    if not content:
                        alt_text, img_title, caption = self._fallback_image_seo_fields(scene_notes, path)
                        def _done_empty(m=model, a=alt_text, t=img_title, c=caption):
                            self._apply_result(a, t, c, f"✓ WordPress Featured Image SEO generated via smart fallback after {m.split('/')[-1]}")
                            self._set_generating(False)
                        self.after(0, _done_empty)
                        return

                    try:
                        raw_data = parse_json(content)
                    except Exception:
                        alt_text, img_title, caption = self._fallback_image_seo_fields(scene_notes, path)
                        def _done_parse(m=model, a=alt_text, t=img_title, c=caption):
                            self._apply_result(a, t, c, f"✓ WordPress Featured Image SEO generated via smart fallback after {m.split('/')[-1]}")
                            self._set_generating(False)
                        self.after(0, _done_parse)
                        return

                    alt_text = self._clean_field(raw_data.get("alt_text", ""), max_words=20, mode="alt")
                    img_title = self._clean_field(raw_data.get("img_title", ""), max_words=15, mode="title")
                    caption = self._clean_field(raw_data.get("caption", ""), max_words=40, mode="caption")
                    description = self._clean_field(raw_data.get("description", ""), max_words=60, mode="generic")
                    
                    if len(alt_text) < 10 or len(img_title) < 5 or len(caption) < 15:
                        alt_text, img_title, caption, description = self._fallback_image_seo_fields(scene_notes, path)
                        
                    def _done(m=model, a=alt_text, t=img_title, c=caption, d=description):
                        status_msg = f"✓ WordPress Featured Image SEO generated via {m.split('/')[-1]}"
                        self._apply_result(a, t, c, d, status=status_msg)
                        self._set_generating(False)
                    self.after(0, _done)
                    return
                except Exception as e: 
                    last_err = e
                    self.after(0, lambda err=str(e)[:80]: self.set_status(f"Model error: {err} — trying fallback…"))
                    
            alt_text, img_title, caption, description = self._fallback_image_seo_fields(scene_notes, path)
            def _done_last(a=alt_text, t=img_title, c=caption, d=description):
                self._apply_result(a, t, c, d, status="✓ WordPress Featured Image SEO generated via final smart fallback")
                self._set_generating(False)
            self.after(0, _done_last)
            return
            
        except Exception as e:
            msg = str(e).strip() or repr(e)
            alt, title, cap, desc = self._fallback_image_seo_fields(scene_notes, path)
            def _err(a=alt, t=title, c=cap, d=desc, m=msg):
                self._apply_result(a, t, c, d, "✓ WordPress Featured Image SEO generated via emergency fallback")
                self._set_generating(False)
                self.set_status(f"AI fallback used: {m[:100]}")
            self.after(0, _err)

    def _sanitize(self, text, max_len=None, mode="generic"):
        result = self._clean_field(text, max_words=30, mode=mode)
        if max_len and len(result) > max_len:
            # Smart Truncate: កាត់អក្សរកុំឲ្យដាច់ពាក្យកណ្តាលទី
            trimmed = result[:max_len]
            last_space = trimmed.rfind(" ")
            if last_space > (max_len // 2):
                trimmed = trimmed[:last_space]
            result = trimmed.rstrip(" ,;:.-")
            if mode == "caption" and not re.search(r"[.!?]$", result): 
                result += "."
        return result

    def _clean_field(self,text:str,max_words:int=20,mode:str="generic")->str:
        text=str(text or "").strip(); text=html.unescape(text); text=re.sub(r"\s+"," ",text).strip()
        JUNK=[r"\bfeatured image\b",r"\bimage seo\b",r"\bseo\b",r"\bkeyword[s]?\b",r"\boptimiz\w*\b",r"\branking\b",r"\bmetadata\b",r"\balt tag\b",r"\balt text\b",r"\bvisibility\b",r"\bdiscoverability\b",r"\bengagement\b",r"\btraffic\b",r"\bcontent marketing\b",r"\bblog post\b",r"\bnews article\b",r"\bthis image\b",r"\bthe image\b",r"\ba photo of\b",r"\ban image of\b",r"\bpicture of\b",r"\bshowcas\w*\b",r"\bhighlights?\b",r"\bIMG_?\d+\b",r"\bDSC_?\d+\b",r"\b\w+\.(jpg|jpeg|png|webp)\b"]
        for pat in JUNK: text=re.sub(pat,"",text,flags=re.I)
        text=re.sub(r"\s*,\s*,",",",text); text=re.sub(r"^\s*[,;:\-–—]\s*","",text); text=re.sub(r"\s*[,;:\-–—]\s*$","",text); text=re.sub(r"\s+"," ",text).strip()
        if mode=="title":
            text=re.sub(r"[.!?]+$","",text).strip()
            SMALL={"a","an","the","and","or","but","in","on","at","to","for","of","with","by"}
            words=text.split(); text=" ".join(w.capitalize() if (i==0 or w.lower() not in SMALL) else w.lower() for i,w in enumerate(words))
        elif mode=="caption":
            sentences=re.split(r'(?<=[.!?])\s+',text); text=sentences[0].strip() if sentences else text
            text=text.strip(" -,:;")
            if text and not re.search(r"[.!?]$",text): text+="."
        elif mode=="alt":
            text=re.sub(r"[.!?]+$","",text).strip()
            if text and text[0].isupper() and not re.match(r"^[A-Z]{2,}",text): text=text[0].lower()+text[1:]
        words=text.split()
        if len(words)>max_words:
            text=" ".join(words[:max_words]).rstrip(" ,;:-")
            if mode=="caption" and not re.search(r"[.!?]$",text): text+="."
        return re.sub(r"\s+"," ",text).strip()


    def _fallback_image_seo_fields(self, scene_notes: str = "", path: str = ""):
        seed = " ".join([scene_notes or "", os.path.splitext(os.path.basename(path or ""))[0]])
        seed = html.unescape(seed)
        seed = re.sub(r"[_\-]+", " ", seed)
        seed = re.sub(r"\s+", " ", seed).strip()

        # Filter out purely numeric tokens from filename to avoid bad fallbacks
        tokens = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]{2,}", seed)]
        tokens = [t for t in tokens if not re.match(r"^\d+$", t)]
        
        stop = {"image","photo","news","report","article","homepage","banner","webp","jpg","jpeg","png","crop","img"}
        uniq = []
        seen = set()
        for t in tokens:
            tl = t.lower()
            if tl in seen or tl in stop:
                continue
            seen.add(tl)
            uniq.append(t)

        proper = [t for t in uniq if t[:1].isupper() or t.isupper()]
        subject = " ".join(proper[:2]).strip() or " ".join(uniq[:4]).strip() or "news figure"

        alt_text = self._clean_field(f"{subject} speaking in a news photo", max_words=16, mode="alt")
        img_title = self._clean_field(subject or "News Photo", max_words=10, mode="title")
        caption = self._clean_field(f"{subject} is shown speaking in a news image related to the article", max_words=24, mode="caption")
        description = "Generate from image to Full SEO in WordPress"

        if len(alt_text) < 8:
            alt_text = "political figure speaking in a news photo"
        if len(img_title) < 4:
            img_title = "News Photo"
        if len(caption) < 12:
            caption = "Political figure is shown speaking in a news image related to the article."

        return alt_text, img_title, caption, description

    def _sanitize(self,text,max_len=None,mode="generic"):
        result=self._clean_field(text,max_words=30,mode=mode)
        if max_len and len(result)>max_len:
            result=result[:max_len].rsplit(" ",1)[0].rstrip(" ,;:.-")
            if mode=="caption" and not re.search(r"[.!?]$",result): result+="."
        return result

    def _apply_result(self, alt, title, caption, description, status=""):
        alt = self._sanitize(alt, 90, mode="alt")
        title = self._sanitize(title, 90, mode="title")
        caption = self._sanitize(caption, 180, mode="caption")
        description = self._sanitize(description, 300, mode="generic")
        
        self.alt_text.delete(0, "end"); self.alt_text.insert(0, alt)
        self.img_title.delete(0, "end"); self.img_title.insert(0, title)
        self.caption.delete("1.0", "end"); self.caption.insert("1.0", caption)
        self.description.delete("1.0", "end"); self.description.insert("1.0", description)
        if status: self.set_status(status)

    def _clip(self,text,label):
        if not text.strip(): self.set_status(f"No {label} to copy"); return
        root=self.winfo_toplevel(); root.clipboard_clear(); root.clipboard_append(text); root.update()
        self.set_status(f"Copied {label}")

    def copy_alt(self):     self._clip(self.alt_text.get().strip(),"Alt Text")
    def copy_title(self):   self._clip(self.img_title.get().strip(),"Image Title")
    def copy_caption(self): self._clip(self.caption.get("1.0","end").strip(),"Caption")
    def copy_description(self): self._clip(self.description.get("1.0","end").strip(),"Description")
    def copy_all(self):
        alt=self.alt_text.get().strip(); title=self.img_title.get().strip()
        cap=self.caption.get("1.0","end").strip(); desc=self.description.get("1.0","end").strip()
        text = f"Alt Text:\n{alt}\n\nImage Title:\n{title}\n\nCaption:\n{cap}\n\nDescription:\n{desc}"
        self._clip(text,"all image fields")

    def clear_fields(self):
        self.scene_entry.delete(0,"end"); self.alt_text.delete(0,"end")
        self.img_title.delete(0,"end"); self.caption.delete("1.0","end")
        self.description.delete("1.0","end")
        self.image_path=self.original_image=self.tk_canvas_image=self.cropped_image=None
        self._clear_temp(); self.canvas.delete("all"); self.canvas_image_item=None
        self.image_offset_x=self.image_offset_y=0.0
        self.crop_info.configure(text="No image loaded"); self.set_status("Cleared all image SEO fields")

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════
class WordPressSEOStudio(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("WordPress SEO Studio")
        self.update_idletasks()
        sw,sh=self.winfo_screenwidth(),self.winfo_screenheight()
        ww=min(1500,max(1280,int(sw*0.90))); wh=min(920,max(780,int(sh*0.88)))
        self.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{max(0,(sh-wh)//2)}")
        self.minsize(1200,720); self.configure(fg_color=T.APP_BG)
        self.api_keys = {"together": "", "openai": ""}
        self.key_manager = APIKeyManager()
        self._build(); self._update_badge()
        if self.api_keys.get("together") or self.api_keys.get("openai"):
            self.image_tab.init_client()
        
        # Start update check in background
        threading.Thread(target=self._check_updates_background, daemon=True).start()

    def _check_updates_background(self):
        """Checks for updates without freezing the UI."""
        try:
            # Short delay to let the app finish loading
            time.sleep(3)
            # Use a session to avoid repeated connection overhead if needed
            response = requests.get(UPDATE_JSON_URL, timeout=10)
            if response.status_code == 200:
                data = response.json()
                remote_version = str(data.get("version", "1.0"))
                download_url = data.get("url", "")
                
                if remote_version > APP_VERSION and download_url:
                    # Update found! Update UI on main thread
                    self.after(0, lambda: self._show_update_alert(remote_version, download_url))
        except Exception:
            # Silently ignore update check errors (no internet, wrong URL, etc.)
            pass

    def _show_update_alert(self, new_version, download_url):
        """Shows the update button and a status message."""
        if hasattr(self, "update_btn"):
            self.update_btn.pack(side="right", padx=12, pady=9)
            self.update_btn.configure(
                text=f"✨ Update to v{new_version}",
                command=lambda: self._perform_auto_update(download_url)
            )
            self._set_status(f"New Update Available: v{new_version}!")
            
            # Show a popup once
            messagebox.showinfo("Update Available", 
                                f"A new version (v{new_version}) is available!\n\n"
                                "Click the 'Update' button in the top bar to install it automatically.",
                                parent=self)

    def _perform_auto_update(self, download_url):
        """Downloads the new version and restarts the app."""
        if not messagebox.askyesno("Confirm Update", 
                                   "The tool will download the new version and restart.\n\n"
                                   "Do you want to proceed?", parent=self):
            return

        self._set_status("Downloading update...")
        self.update_btn.configure(state="disabled", text="⏳ Updating...")

        def worker():
            try:
                # 1. Download new file content
                r = requests.get(download_url, timeout=30)
                if r.status_code != 200:
                    raise RuntimeError(f"Download failed (HTTP {r.status_code})")
                
                new_content = r.content
                if len(new_content) < 1000: # Safety check: script shouldn't be too small
                    raise RuntimeError("Downloaded file seems too small or invalid.")

                # 2. Get current file path
                current_file = os.path.abspath(__file__)
                
                # 3. Save new content to a temporary file first
                temp_file = current_file + ".new"
                with open(temp_file, "wb") as f:
                    f.write(new_content)
                
                # 4. Create a small batch script to handle replacement and restart
                # This is necessary because we can't easily replace the file while it's in use
                # or ensure the restart happens after we close.
                batch_file = os.path.join(tempfile.gettempdir(), "update_seo_studio.bat")
                with open(batch_file, "w") as f:
                    f.write(f'@echo off\n')
                    f.write(f'title Updating WordPress SEO Studio...\n')
                    f.write(f'echo Waiting for application to close...\n')
                    f.write(f'timeout /t 2 /nobreak > nul\n')
                    f.write(f'echo Replacing file...\n')
                    f.write(f'move /y "{temp_file}" "{current_file}"\n')
                    f.write(f'echo Restarting application...\n')
                    f.write(f'start "" python "{current_file}"\n')
                    f.write(f'echo Update Complete!\n')
                    f.write(f'exit\n')
                
                self.after(0, lambda: self._set_status("Update ready! Restarting..."))
                time.sleep(1)
                
                # Run the batch file and exit the current process
                subprocess.Popen([batch_file], shell=True)
                self.after(0, self.quit)
                
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: messagebox.showerror("Update Error", f"Update failed: {m}", parent=self))
                self.after(0, lambda: self.update_btn.configure(state="normal", text="✨ Update Failed"))
                self.after(0, lambda: self._set_status("Update failed"))

        threading.Thread(target=worker, daemon=True).start()

    def get_api_key(self, provider="together"): 
        if provider is None: return self.api_keys
        return self.api_keys.get(provider, "")

    def _set_status(self,text):
        if hasattr(self,"status_label") and self.status_label.winfo_exists():
            self.status_label.configure(text=f"  {text}")

    def _update_badge(self):
        if not hasattr(self, "badge"): return
        keys = self.key_manager.load()
        has_saved = bool(keys.get("together") or keys.get("openai"))
        together = self.api_keys.get("together")
        openai = self.api_keys.get("openai")
        if (together or openai) and has_saved:
            self.badge.configure(text="●  API keys saved", text_color="#22c55e")
        elif (together or openai):
            self.badge.configure(text="●  Session keys active", text_color="#f59e0b")
        else:
            self.badge.configure(text="○  API not configured", text_color="#4a6380")

    def _apply_api_key(self, together, openai, saved):
        self.api_keys["together"] = (together or "").strip()
        self.api_keys["openai"] = (openai or "").strip()
        if not self.api_keys["together"] and not self.api_keys["openai"]:
            try: self.key_manager.clear()
            except: pass
        self._update_badge(); self.image_tab.init_client()
        self._set_status("API keys updated")

    def _open_api_settings(self):
        APISettingsPopup(self,self.key_manager,self._apply_api_key)

    def _build(self):
        topbar=ctk.CTkFrame(self,fg_color="#020c1a",height=48,corner_radius=0)
        topbar.pack(fill="x",side="top"); topbar.pack_propagate(False)
        ctk.CTkLabel(topbar,text="WordPress SEO Studio",font=ctk.CTkFont("Segoe UI",15,"bold"),text_color="#b8cff8").pack(side="left",padx=16)
        ctk.CTkLabel(topbar,text="SEO Formatter  ·  Image Crop  ·  AI Image SEO  ·  Yoast Fields  ·  AI SEO Fields",font=ctk.CTkFont("Segoe UI",10),text_color="#3d5a7a").pack(side="left",padx=(0,16))
        Btn(topbar,"⚙  API Settings",self._open_api_settings,"cyan",136,30).pack(side="right",padx=12,pady=9)
        
        # New Update Button (hidden by default)
        self.update_btn = Btn(topbar, "✨ Update Available", lambda: None, "yellow", 160, 30)
        self.update_btn.pack_forget() 

        self.badge=ctk.CTkLabel(topbar,text="○  API not configured",font=ctk.CTkFont("Segoe UI",11),text_color="#4a6380")
        self.badge.pack(side="right",padx=(0,4))

        self.tabs=ctk.CTkTabview(self,fg_color=T.APP_BG,segmented_button_fg_color=T.PANEL_BG,segmented_button_selected_color=T.BLUE_BORDER,segmented_button_selected_hover_color=T.BLUE_H,segmented_button_unselected_color=T.PANEL_BG,segmented_button_unselected_hover_color=T.PANEL_BG_2,text_color=T.TEXT_MAIN,text_color_disabled=T.TEXT_SOFT)
        self.tabs.pack(fill="both",expand=True,padx=10,pady=(6,0))
        self.tabs.add("📝  SEO Formatter"); self.tabs.add("🖼  Image SEO")

        seo_frame=self.tabs.tab("📝  SEO Formatter")
        seo_frame.grid_rowconfigure(0,weight=1); seo_frame.grid_columnconfigure(0,weight=1)
        img_frame=self.tabs.tab("🖼  Image SEO")
        img_frame.grid_rowconfigure(0,weight=1); img_frame.grid_columnconfigure(0,weight=1)

        self.seo_tab=SEOFormatterTab(seo_frame,self._set_status,self.get_api_key)
        self.seo_tab.grid(row=0,column=0,sticky="nsew")
        self.image_tab=ImageSEOTab(img_frame,self._set_status,self.get_api_key)
        self.image_tab.grid(row=0,column=0,sticky="nsew")

        self.status_label=ctk.CTkLabel(self,text="  Ready",height=24,corner_radius=0,anchor="w",fg_color="#010810",text_color="#3d5a7a",font=ctk.CTkFont("Segoe UI",11))
        self.status_label.pack(fill="x",side="bottom")


if __name__=="__main__":
    app=WordPressSEOStudio()
    app.mainloop()

