import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
LOG_PATH = os.path.join(DATA_DIR, "app.log")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_env():
    candidate = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(candidate):
        return
    with open(candidate, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def env(name, default=None):
    load_env()
    value = os.getenv(name)
    if not value:
        return default
    return value


def env_required(name):
    value = env(name)
    if not value:
        raise ValueError(f"Missing env var: {name}")
    return value


def app_timezone():
    timezone_name = env("APP_TIMEZONE") or env("TZ", "Europe/Kiev")
    aliases = {
        "Europe/Kiev": "Europe/Kyiv",
    }
    candidates = [timezone_name]
    if timezone_name in aliases:
        candidates.append(aliases[timezone_name])
    candidates.append("UTC")
    for candidate in candidates:
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    return ZoneInfo("UTC")


def local_now():
    return datetime.now(app_timezone())


def format_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp, app_timezone()).strftime("%Y-%m-%d %H:%M:%S")


def default_settings():
    return {
        "automation_enabled": False,
        "schedule_enabled": False,
        "active_from": "08:00",
        "active_to": "20:00",
        "charger_phases": int(env("CHARGER_PHASES", 1)),
        "charger_voltage": float(env("CHARGER_VOLTAGE", 230)),
        "charger_min_amps": int(env("CHARGER_MIN_AMPS", 6)),
        "charger_max_amps": int(env("CHARGER_MAX_AMPS", 16)),
        "charger_reserve_watts": float(env("CHARGER_RESERVE_WATTS", 250)),
        "update_interval_seconds": int(env("UPDATE_INTERVAL_SECONDS", 300)),
    }


def load_settings():
    ensure_data_dir()
    if not os.path.exists(SETTINGS_PATH):
        settings = default_settings()
        save_settings(settings)
        return settings
    with open(SETTINGS_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def save_settings(settings):
    ensure_data_dir()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2)


def log(message):
    ensure_data_dir()
    timestamp = local_now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as file:
        file.write(line + "\n")


def tail_logs():
    ensure_data_dir()
    if not os.path.exists(LOG_PATH):
        return ""
    with open(LOG_PATH, "r", encoding="utf-8") as file:
        lines = file.readlines()
    return "".join(reversed(lines[-200:]))


def now_text():
    return local_now().strftime("%Y-%m-%d %H:%M:%S")
