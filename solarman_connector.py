import hashlib

import requests

from web_config import env, env_required


def api_post(path, body, token=None):
    base_url = env("SOLARMAN_BASE_URL", "https://globalapi.solarmanpv.com")
    app_id = env_required("SOLARMAN_APP_ID")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"bearer {token}"
    response = requests.post(
        f"{base_url}{path}",
        params={"appId": app_id, "language": "en"},
        headers=headers,
        json=body,
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("success") is False:
        raise RuntimeError(f"Solarman API error {data.get('code')}: {data.get('msg')}")
    return data


def get_token():
    email = env_required("SOLARMAN_EMAIL")
    password = env_required("SOLARMAN_PASSWORD")
    app_secret = env_required("SOLARMAN_APP_SECRET")
    password_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
    data = api_post(
        "/account/v1.0/token",
        {"email": email, "password": password_sha256, "appSecret": app_secret},
    )
    return data["access_token"]


def get_station_id(token):
    station_id = env("SOLARMAN_STATION_ID")
    if station_id:
        return int(station_id)
    data = api_post("/station/v1.0/list", {"page": 1, "size": 1}, token=token)
    station_list = data.get("stationList", [])
    if not station_list:
        raise RuntimeError("No stations found")
    return int(station_list[0]["id"])


def get_current_state():
    token = get_token()
    station_id = get_station_id(token)
    data = api_post("/station/v1.0/realTime", {"stationId": station_id}, token=token)
    return {
        "production": float(data.get("generationPower") or 0),
        "consumption": float(data.get("usePower") or 0),
        "charging": abs(float(data.get("chargePower") or 0)),
        "discharging": float(data.get("dischargePower") or 0),
        "battery_soc": float(data.get("batterySoc") or 0),
    }
