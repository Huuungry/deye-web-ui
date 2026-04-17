import threading
import time

from flask import Flask, jsonify, redirect, render_template, request

from charger_connector import get_charger_state, normalize_amps, set_amps, stop_charging_now
from solarman_connector import get_current_state
from web_config import (
    LOG_PATH,
    ensure_data_dir,
    format_timestamp,
    load_settings,
    local_now,
    log,
    now_text,
    save_settings,
    tail_logs,
)


app = Flask(__name__)

runtime = {
    "worker_running": False,
    "last_run_at": None,
    "next_run_at": None,
    "next_run_ts": None,
    "last_action": None,
    "inverter_state": None,
    "charger_state": None,
    "available_power_w": None,
    "potential_amps": None,
    "target_amps": None,
}
runtime_lock = threading.Lock()
flash_messages = []
worker_started = False
run_now_requested = False


def calculate_target_amps(inverter_state, charger_state, settings):
    active_car_charging_power = 0
    if charger_state["status_text"] == "charging" and charger_state["charging_power_w"]:
        active_car_charging_power = charger_state["charging_power_w"]
    non_charger_consumption = inverter_state["consumption"] - active_car_charging_power
    if non_charger_consumption < 0:
        non_charger_consumption = 0
    available_power = (
        inverter_state["production"]
        - non_charger_consumption
        - settings["charger_reserve_watts"]
    )
    watts_per_amp = settings["charger_voltage"] * settings["charger_phases"]
    potential_amps = int(available_power // watts_per_amp)
    target_amps = potential_amps
    if target_amps < settings["charger_min_amps"]:
        target_amps = 0
    if target_amps > settings["charger_max_amps"]:
        target_amps = settings["charger_max_amps"]
    return target_amps, potential_amps, round(available_power, 1)


def should_stop_charging(target_amps, charger_state):
    if target_amps > 0:
        return False
    if not charger_state["online"]:
        return False
    return charger_state["status_text"] == "charging" or charger_state["current_amps"]


def should_start_or_update(target_amps, charger_state):
    if target_amps <= 0:
        return False
    if charger_state["status_text"] != "charging":
        return True
    return charger_state["current_amps"] != target_amps


def scheduler_window_active(settings):
    if not settings["schedule_enabled"]:
        return False
    now = local_now().strftime("%H:%M")
    start = settings["active_from"]
    stop = settings["active_to"]
    if start <= stop:
        return start <= now <= stop
    return now >= start or now <= stop


def scheduler_allows_run(settings):
    if not settings["schedule_enabled"]:
        return True
    return scheduler_window_active(settings)


def scheduler_status_text(settings):
    if not settings["schedule_enabled"]:
        return "disabled"
    if scheduler_window_active(settings):
        return "active window"
    return "outside window"


def update_runtime(**values):
    with runtime_lock:
        runtime.update(values)


def refresh_live_state():
    settings = load_settings()
    inverter_state = get_current_state()
    charger_state = get_charger_state()
    target_amps, potential_amps, available_power = calculate_target_amps(
        inverter_state, charger_state, settings
    )
    update_runtime(
        inverter_state=inverter_state,
        charger_state=charger_state,
        available_power_w=available_power,
        potential_amps=potential_amps,
        target_amps=target_amps,
    )
    return inverter_state, charger_state, available_power, potential_amps, target_amps


def run_automation_cycle():
    inverter_state, charger_state, available_power, potential_amps, target_amps = refresh_live_state()
    update_runtime(last_run_at=now_text())
    log(f"Inverter state: {inverter_state}")
    log(f"Charger state: {charger_state}")
    log(f"Available power for charging: {available_power} W")
    log(f"Potential amps: {potential_amps}")
    log(f"Target amps: {target_amps}")
    if not charger_state["online"]:
        log("Charger is offline, nothing to do")
        update_runtime(last_action="charger offline")
        return
    if should_stop_charging(target_amps, charger_state):
        log("Not enough power, stopping charge")
        set_amps(0)
        update_runtime(last_action="stop charging")
        return
    if should_start_or_update(target_amps, charger_state):
        log("Enough power available, starting or updating charger")
        set_amps(target_amps)
        update_runtime(last_action=f"set amps to {normalize_amps(target_amps)}")
        return
    if target_amps > 0:
        log("Charger is already charging with correct amps")
        update_runtime(last_action="already correct")
    else:
        log("Not enough power to start charging")
        update_runtime(last_action="not enough power")


def worker_loop():
    global run_now_requested
    update_runtime(worker_running=True)
    while True:
        try:
            settings = load_settings()
            active = scheduler_allows_run(settings)
            with runtime_lock:
                next_run_ts = runtime["next_run_ts"]
            now_ts = time.time()
            run_now = run_now_requested
            if run_now_requested:
                run_now_requested = False

            if run_now:
                run_automation_cycle()
                if settings["automation_enabled"] and active:
                    next_run_ts = now_ts + settings["update_interval_seconds"]
                    update_runtime(
                        next_run_ts=next_run_ts,
                        next_run_at=format_timestamp(next_run_ts),
                    )
                else:
                    update_runtime(next_run_at=None, next_run_ts=None)
            elif settings["automation_enabled"] and active:
                if next_run_ts is None or now_ts >= next_run_ts:
                    run_automation_cycle()
                    next_run_ts = now_ts + settings["update_interval_seconds"]
                    update_runtime(
                        next_run_ts=next_run_ts,
                        next_run_at=format_timestamp(next_run_ts),
                    )
            else:
                update_runtime(next_run_at=None, next_run_ts=None)
        except Exception as exc:
            log(f"Worker error: {exc}")
            update_runtime(last_action=f"error: {exc}")
        time.sleep(1)


def start_worker():
    global worker_started
    if worker_started:
        return
    worker_started = True
    thread = threading.Thread(target=worker_loop, daemon=True)
    thread.start()


def initialize_app():
    ensure_data_dir()
    settings = load_settings()
    if settings["automation_enabled"]:
        settings["automation_enabled"] = False
        save_settings(settings)
    update_runtime(
        worker_running=False,
        next_run_at=None,
        next_run_ts=None,
        last_action="automation stopped",
    )


def pop_messages():
    global flash_messages
    messages = flash_messages[:]
    flash_messages = []
    return messages


def push_message(message):
    flash_messages.append(message)


@app.route("/")
def index():
    settings = load_settings()
    with runtime_lock:
        status = {
            "automation_enabled": settings["automation_enabled"],
            "scheduler_enabled": settings["schedule_enabled"],
            "scheduler_status": scheduler_status_text(settings),
            "worker_running": runtime["worker_running"],
            "last_run_at": runtime["last_run_at"],
            "next_run_at": runtime["next_run_at"],
            "last_action": runtime["last_action"],
        }
        runtime_view = {
            "inverter_state": runtime["inverter_state"],
            "charger_state": runtime["charger_state"],
            "available_power_w": runtime["available_power_w"],
            "potential_amps": runtime["potential_amps"],
            "target_amps": runtime["target_amps"],
        }
    return render_template(
        "index.html",
        settings=settings,
        status=status,
        runtime=runtime_view,
        logs=tail_logs(),
        messages=pop_messages(),
    )


@app.get("/api/status")
def api_status():
    settings = load_settings()
    with runtime_lock:
        payload = {
            "status": {
                "automation_enabled": settings["automation_enabled"],
                "scheduler_enabled": settings["schedule_enabled"],
                "scheduler_status": scheduler_status_text(settings),
                "worker_running": runtime["worker_running"],
                "last_run_at": runtime["last_run_at"],
                "next_run_at": runtime["next_run_at"],
                "last_action": runtime["last_action"],
            },
            "runtime": {
                "inverter_state": runtime["inverter_state"],
                "charger_state": runtime["charger_state"],
                "available_power_w": runtime["available_power_w"],
                "potential_amps": runtime["potential_amps"],
                "target_amps": runtime["target_amps"],
            },
        }
    return jsonify(payload)


@app.get("/api/logs")
def api_logs():
    return jsonify({"logs": tail_logs()})


@app.post("/settings")
def update_settings():
    settings = load_settings()
    settings["charger_min_amps"] = int(request.form["charger_min_amps"])
    settings["charger_max_amps"] = int(request.form["charger_max_amps"])
    settings["charger_voltage"] = float(request.form["charger_voltage"])
    settings["charger_phases"] = int(request.form["charger_phases"])
    settings["charger_reserve_watts"] = float(request.form["charger_reserve_watts"])
    settings["update_interval_seconds"] = int(request.form["update_interval_seconds"])
    settings["schedule_enabled"] = request.form["schedule_enabled"].strip().lower() == "true"
    settings["automation_enabled"] = request.form["automation_enabled"].strip().lower() == "true"
    settings["active_from"] = request.form["active_from"]
    settings["active_to"] = request.form["active_to"]
    save_settings(settings)
    push_message("Settings saved")
    with runtime_lock:
        runtime["next_run_at"] = None
        runtime["next_run_ts"] = None
    return redirect("/")


@app.post("/action/start")
def action_start():
    settings = load_settings()
    settings["automation_enabled"] = True
    save_settings(settings)
    start_worker()
    with runtime_lock:
        runtime["next_run_at"] = None
        runtime["next_run_ts"] = None
    push_message("Automation started")
    return redirect("/")


@app.post("/action/stop")
def action_stop():
    settings = load_settings()
    settings["automation_enabled"] = False
    save_settings(settings)
    update_runtime(last_action="automation stopped")
    push_message("Automation stopped")
    return redirect("/")


@app.post("/action/run-now")
def action_run_now():
    global run_now_requested
    start_worker()
    run_now_requested = True
    with runtime_lock:
        runtime["next_run_at"] = None
        runtime["next_run_ts"] = None
    push_message("Run requested")
    return redirect("/")


@app.post("/action/refresh-state")
def action_refresh_state():
    try:
        refresh_live_state()
        update_runtime(last_action="state refreshed")
        push_message("State refreshed")
    except Exception as exc:
        push_message(f"State refresh failed: {exc}")
        log(f"State refresh failed: {exc}")
    return redirect("/")


@app.post("/action/stop-charging")
def action_stop_charging():
    try:
        stop_charging_now()
        update_runtime(last_action="manual stop charging")
        push_message("Stop charging command sent")
    except Exception as exc:
        push_message(f"Stop charging failed: {exc}")
        log(f"Manual stop charging failed: {exc}")
    return redirect("/")


@app.post("/action/clear-logs")
def action_clear_logs():
    ensure_data_dir()
    with open(LOG_PATH, "w", encoding="utf-8") as file:
        file.write("")
    push_message("Logs cleared")
    return redirect("/")


initialize_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
