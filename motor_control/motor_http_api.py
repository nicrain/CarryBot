#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""HTTP API for CarryBot motor control.

Minimal endpoints for an App to drive the robot and control tristar.
This service translates HTTP JSON requests into the existing serial protocol:
- Wheels: M<rpm> (both wheels) or B<left> <right> (independent wheels)
- Tristar: T<rpm>
- Stop: S

Run (on Pi):
  python3 -m motor_control.motor_http_api --port 8090 --serial /dev/ttyUSB0

Example curl:
  curl -X POST http://pi:8090/drive -H 'Content-Type: application/json' -d '{"action":"forward","speed":60}'
  curl -X POST http://pi:8090/tristar -H 'Content-Type: application/json' -d '{"rpm":20}'
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from motor_control.motor_driver import MotorDriver


DEFAULT_WHEEL_SPEED_RPM = 60.0
DEFAULT_TRISTAR_RPM = 20.0


def _corsify(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp


def create_app(driver: MotorDriver) -> Flask:
    app = Flask(__name__)

    @app.after_request
    def _after(resp):
        return _corsify(resp)

    @app.route("/health", methods=["GET"])
    def health():
        ok = driver.ser is not None and driver.ser.is_open
        return jsonify({"ok": ok})

    @app.route("/stop", methods=["POST", "OPTIONS"])
    def stop():
        if request.method == "OPTIONS":
            return ("", 204)
        driver.stop()
        return jsonify({"status": "ok"})

    @app.route("/tristar", methods=["POST", "OPTIONS"])
    def tristar():
        if request.method == "OPTIONS":
            return ("", 204)
        payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        rpm = float(payload.get("rpm", DEFAULT_TRISTAR_RPM))
        driver.move_tristar(rpm)
        return jsonify({"status": "ok", "rpm": rpm})

    @app.route("/wheels", methods=["POST", "OPTIONS"])
    def wheels():
        if request.method == "OPTIONS":
            return ("", 204)
        payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}

        # Option A: independent wheels
        if "left" in payload or "right" in payload:
            left = float(payload.get("left", 0))
            right = float(payload.get("right", 0))
            driver.move_wheels_lr(left, right)
            return jsonify({"status": "ok", "left": left, "right": right})

        # Option B: both wheels same speed
        rpm = float(payload.get("rpm", 0))
        driver.move_wheels(rpm)
        return jsonify({"status": "ok", "rpm": rpm})

    @app.route("/drive", methods=["POST", "OPTIONS"])
    def drive():
        if request.method == "OPTIONS":
            return ("", 204)
        payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}

        action = str(payload.get("action", "")).strip().lower()
        speed = float(payload.get("speed", DEFAULT_WHEEL_SPEED_RPM))

        if action in ("stop", "s"):
            driver.stop()
            return jsonify({"status": "ok", "action": "stop"})

        if action in ("forward", "f"):
            driver.move_wheels_lr(speed, speed)
            return jsonify({"status": "ok", "action": "forward", "speed": speed})

        if action in ("backward", "back", "b"):
            driver.move_wheels_lr(-speed, -speed)
            return jsonify({"status": "ok", "action": "backward", "speed": speed})

        # In-place turns (simple + minimal)
        if action in ("left", "l"):
            driver.move_wheels_lr(-speed, speed)
            return jsonify({"status": "ok", "action": "left", "speed": speed})

        if action in ("right", "r"):
            driver.move_wheels_lr(speed, -speed)
            return jsonify({"status": "ok", "action": "right", "speed": speed})

        # Stair mechanism (tristar): map App's up/down to tristar direction.
        # App can omit rpm; server uses DEFAULT_TRISTAR_RPM.
        if action in ("up", "u"):
            rpm = float(payload.get("rpm", DEFAULT_TRISTAR_RPM))
            driver.move_tristar(abs(rpm))
            return jsonify({"status": "ok", "action": "up", "rpm": abs(rpm)})

        if action in ("down", "d"):
            rpm = float(payload.get("rpm", DEFAULT_TRISTAR_RPM))
            driver.move_tristar(-abs(rpm))
            return jsonify({"status": "ok", "action": "down", "rpm": -abs(rpm)})

        return jsonify({"status": "error", "message": f"Unknown action: {action}"}), 400

    return app


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="CarryBot motor HTTP API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--serial", dest="serial_port", default=None)
    args = parser.parse_args(argv)

    driver = MotorDriver(port=args.serial_port)
    app = create_app(driver)

    # Use Flask built-in server (sufficient for LAN control)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
