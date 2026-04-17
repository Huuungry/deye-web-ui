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


def list_stations(token=None):
    if token is None:
        token = get_token()
    data = api_post("/station/v1.0/list", {"page": 1, "size": 100}, token=token)
    station_list = data.get("stationList", [])
    stations = []
    for station in station_list:
        station_id = station.get("id")
        if station_id is None:
            continue
        stations.append(
            {
                "id": int(station_id),
                "name": station.get("stationName")
                or station.get("name")
                or station.get("stationTitle")
                or f"Station {station_id}",
            }
        )
    return stations


def get_first_station(token):
    stations = list_stations(token)
    if not stations:
        raise RuntimeError("No stations found")
    return stations[0]


def get_station(token):
    station_id = env("SOLARMAN_STATION_ID")
    if not station_id:
        return get_first_station(token), None
    try:
        parsed_id = int(station_id)
    except ValueError:
        station = get_first_station(token)
        return station, f"Configured station id '{station_id}' is invalid, using {station['id']}"
    return {"id": parsed_id, "name": f"Station {parsed_id}"}, None


def get_station_realtime(token, station_id):
    return api_post("/station/v1.0/realTime", {"stationId": station_id}, token=token)


def get_current_state():
    token = get_token()
    station, warning = get_station(token)
    try:
        data = get_station_realtime(token, station["id"])
    except Exception as exc:
        if env("SOLARMAN_STATION_ID"):
            fallback_station = get_first_station(token)
            warning = (
                f"Configured station id {station['id']} failed, using {fallback_station['id']}: {exc}"
            )
            station = fallback_station
            data = get_station_realtime(token, station["id"])
        else:
            raise

    return {
        "station_id": station["id"],
        "station_name": station["name"],
        "station_warning": warning,
        "production": float(data.get("generationPower") or 0),
        "consumption": float(data.get("usePower") or 0),
        "charging": abs(float(data.get("chargePower") or 0)),
        "discharging": float(data.get("dischargePower") or 0),
        "battery_soc": float(data.get("batterySoc") or 0),
    }
