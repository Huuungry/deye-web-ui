import base64
import os
import socket
import ssl
import struct
import time

import requests

from web_config import env, env_required, log


AMP_TO_INDEX = {
    32: 0,
    30: 1,
    28: 2,
    26: 3,
    24: 4,
    22: 5,
    20: 6,
    18: 7,
    16: 8,
    14: 9,
    12: 10,
    10: 11,
    8: 12,
    6: 13,
}
SUPPORTED_AMPS = sorted(AMP_TO_INDEX)
STATUS_TEXT = {
    "0": "waiting_for_vehicle",
    "1": "vehicle_connected_idle",
    "2": "charging",
    "3": "charging_fault",
    "4": "charging_blocked",
    "5": "mains_voltage_low",
    "6": "charger_communication_fault",
    "7": "offline",
    "16": "leakage_current_fault",
}


def normalize_amps(amps):
    if amps <= 0:
        return 0
    supported = [value for value in SUPPORTED_AMPS if value <= amps]
    if not supported:
        return 0
    return max(supported)


def login_charger():
    session = requests.Session()
    base_url = env("CHARGER_BASE_URL", "https://electros.org.ua/auth/")
    login_name = env_required("CHARGER_LOGIN")
    password = env_required("CHARGER_PASSWORD")
    session.get(base_url + "main.php", timeout=30, verify=False)
    response = session.post(
        base_url + "login.php",
        data={"username": login_name, "password": password},
        timeout=30,
        verify=False,
        allow_redirects=True,
    )
    response.raise_for_status()
    return session


def recv_http(sock):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def send_ws_text(sock, text):
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    mask = os.urandom(4)
    header.extend(mask)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    sock.sendall(header + masked)


def recv_ws_frame(sock):
    first = sock.recv(2)
    if len(first) < 2:
        raise RuntimeError("No websocket frame received")
    byte1, byte2 = first
    opcode = byte1 & 0x0F
    length = byte2 & 0x7F
    masked = (byte2 & 0x80) != 0
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    mask = sock.recv(4) if masked else b""
    payload = b""
    while len(payload) < length:
        payload += sock.recv(length - len(payload))
    if masked:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return opcode, payload.decode("utf-8", errors="replace")


def open_socket(session):
    host = env("CHARGER_WS_HOST", "electros.org.ua")
    path = env("CHARGER_WS_PATH", "/ws/")
    origin = env("CHARGER_WS_ORIGIN", "https://electros.org.ua")
    protocol = env("CHARGER_WS_PROTOCOL", "example-protocol")
    cookie_header = "; ".join(f"{cookie.name}={cookie.value}" for cookie in session.cookies)
    raw = socket.create_connection((host, 443), timeout=10)
    context = ssl._create_unverified_context()
    sock = context.wrap_socket(raw, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {protocol}\r\n"
        f"Origin: {origin}\r\n"
        f"Cookie: {cookie_header}\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("utf-8"))
    response = recv_http(sock)
    if b"101 Switching Protocols" not in response:
        raise RuntimeError(response.decode("utf-8", errors="replace"))
    return sock


def parse_charger_state(message):
    parts = message.split("\n")
    current_amps = int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else None
    status_code = parts[8] if len(parts) > 8 else None
    measured_current = int(parts[9]) / 10 if len(parts) > 9 and parts[9].isdigit() else None
    mains_voltage = None
    if len(parts) > 16 and parts[16].isdigit():
        mains_voltage = int(parts[16])
    elif len(parts) > 10 and parts[10].isdigit():
        mains_voltage = int(parts[10])
    charging_power_w = None
    if measured_current is not None and mains_voltage is not None:
        charging_power_w = round(measured_current * mains_voltage, 1)
    return {
        "online": status_code != "7",
        "status_code": status_code,
        "status_text": STATUS_TEXT.get(status_code, "unknown"),
        "current_amps": current_amps,
        "measured_current": measured_current,
        "mains_voltage": mains_voltage,
        "charging_power_w": charging_power_w,
    }


def get_charger_state():
    try:
        session = login_charger()
        sock = open_socket(session)
        device = env_required("CHARGER_LOGIN")
        send_ws_text(sock, f"site {device}")
        opcode, message = recv_ws_frame(sock)
        sock.close()
        if opcode != 1:
            return {
                "online": False,
                "status_code": None,
                "status_text": "invalid_response",
                "current_amps": None,
                "measured_current": None,
                "mains_voltage": None,
                "charging_power_w": None,
            }
        return parse_charger_state(message)
    except Exception as exc:
        return {
            "online": False,
            "status_code": None,
            "status_text": f"offline: {exc}",
            "current_amps": None,
            "measured_current": None,
            "mains_voltage": None,
            "charging_power_w": None,
        }


def stop_charging_now():
    session = login_charger()
    sock = open_socket(session)
    device = env_required("CHARGER_LOGIN")
    send_ws_text(sock, f"site {device}\nstop")
    time.sleep(1)
    sock.close()
    log("Sent stop command")


def set_amps(amps):
    amps = normalize_amps(amps)
    if amps <= 0:
        stop_charging_now()
        return
    session = login_charger()
    sock = open_socket(session)
    device = env_required("CHARGER_LOGIN")
    index = AMP_TO_INDEX[amps]
    send_ws_text(sock, f"site {device}\nstart\n{index}\n0\n")
    time.sleep(1)
    sock.close()
    log(f"Sent start command with {amps}A")
