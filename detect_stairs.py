#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =================================================================================================
#            ---          CarryBot - 楼梯检测系统 (Web Stream版 - 带控制面板)          ---
#            ---   Système de Détection d'Escaliers CarryBot (Stream Web + Panneau)   ---
# =================================================================================================
#
# ## 描述 / Description
# 该脚本是 CarryBot 感知系统的核心。它使用 Intel RealSense 摄像头通过分析深度数据流
# 来检测楼梯（上行和下行）和墙壁。
# Ce script est le cœur du système de perception de CarryBot. Il utilise une caméra de profondeur
# Intel RealSense pour détecter les escaliers (montants/descendants) et les murs.
#
# ## 架构变更 / Architecture
# - 视频流地址 / Flux vidéo: http://<IP>:8080/video_feed
# - 调参 API / API Paramètres: http://<IP>:8080/params
# - Web 控制面板 / Panneau Web: http://<IP>:8080/
#
# =================================================================================================

import argparse
import os
import json
import time
import threading
import http.server
import socketserver
from typing import Optional, Tuple

# Heavy runtime deps (camera/vision). Keep imports optional so unit tests that
# only exercise ParamsHandler / HTTP routes can run without RealSense/OpenCV.
try:
    import cv2  # type: ignore
except Exception:
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:
    np = None

try:
    import pyrealsense2 as rs  # type: ignore
except Exception:
    rs = None

try:
    from motor_control.motor_driver import (
        MotorDriver,
        GROUND_ACTIONS,
        STAIR_ACTIONS,
        preempt_for,
    )
except Exception:
    MotorDriver = None
    GROUND_ACTIONS = set()
    STAIR_ACTIONS = set()

    def preempt_for(driver, target):
        return None

# --- 全局变量用于线程间通信 ---
output_frame = None
frame_lock = threading.Lock()

# --- Motor control (optional) ---
motor_driver = None
motor_lock = threading.Lock()

# --- Depth OSD smoothing (helps reduce jumpy distance readout) ---
dist_display_ema_m = None

# --- Navigation safety state shared by camera loop and HTTP API ---
nav_state_lock = threading.Lock()
nav_state = {
    "is_wall": False,
    "is_stairs_up": False,
    "is_stairs_down": False,
    "ultra_cm": None,
    "stair_approach_active": False,
    "forward_lock_latched": False,
    "forward_locked": False,
    "forward_lock_reason": "",
    "manual_reverse_until": 0.0,
}


def _get_nav_state_snapshot() -> dict:
    with nav_state_lock:
        return dict(nav_state)


def _set_nav_state(**kwargs) -> dict:
    with nav_state_lock:
        nav_state.update(kwargs)
        return dict(nav_state)


def _recompute_forward_lock(*, is_wall: bool, lock_latched: bool) -> Tuple[bool, str]:
    if lock_latched:
        return True, "stair_ultrasonic"
    if is_wall:
        return True, "wall"
    return False, ""


def _is_drive_action_forward_like(action: str) -> bool:
    return action in ("forward", "f", "left", "l", "right", "r")


def _is_wheels_forward_like(payload: dict) -> bool:
    if "left" in payload or "right" in payload:
        left = float(payload.get("left", 0.0))
        right = float(payload.get("right", 0.0))
        return left > 0 or right > 0
    rpm = float(payload.get("rpm", 0.0))
    return rpm > 0


def _is_wheels_backward_like(payload: dict) -> bool:
    if "left" in payload or "right" in payload:
        left = float(payload.get("left", 0.0))
        right = float(payload.get("right", 0.0))
        return left < 0 or right < 0
    rpm = float(payload.get("rpm", 0.0))
    return rpm < 0


def _arm_manual_reverse_override(seconds: float) -> None:
    until_ts = time.time() + max(0.0, float(seconds))
    with nav_state_lock:
        nav_state["manual_reverse_until"] = until_ts


def _clear_forward_latch() -> dict:
    with nav_state_lock:
        nav_state["forward_lock_latched"] = False
        forward_locked, lock_reason = _recompute_forward_lock(
            is_wall=bool(nav_state.get("is_wall", False)),
            lock_latched=False,
        )
        nav_state["forward_locked"] = forward_locked
        nav_state["forward_lock_reason"] = lock_reason
        return dict(nav_state)

# --- 2. 参数管理类 (ParamsHandler) ---
class ParamsHandler:
    """参数加载与优先级管理 / Gestion des params et priorites."""
    def __init__(self, default_params_path='config/config.json'):
        self.params_path = default_params_path
        self.file_params = {}
        self.env_params = {}
        self.cli_args = {}
        self.defaults = {
            "roi_h_start": 0.2,
            "roi_h_stop": 0.8,
            "roi_v_start": 0.3,
            "roi_v_stop": 0.7,
            "median_blur_ksize": 5,
            "min_valid_dist": 0.1,
            "max_valid_dist": 5.0,
            "wall_dist_th": 0.3,
            "wall_iqr_th": 0.05,
            "step_height_th": 0.05,
            "noise_filtering_area_min_th": 1000,
            "fps": 15,
            "stair_approach_speed_rpm": 45.0,
            "stair_ultra_trigger_cm": 6.0,
            "manual_reverse_override_s": 1.5,
        }

    def load_from_file(self):
        try:
            with open(self.params_path, 'r') as f:
                self.file_params = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.file_params = {}

    def save_to_file(self):
        merged_params = self.get_all_params()
        with open(self.params_path, 'w') as f:
            json.dump(merged_params, f, indent=4)

    def _load_from_env(self):
        for key in self.defaults:
            env_var = f"CARRYBOT_{key.upper()}"
            if env_var in os.environ:
                value = os.environ[env_var]
                try:
                    self.env_params[key] = float(value) if '.' in value else int(value)
                except ValueError:
                    pass

    def _load_from_cli_args(self, args):
        # Only treat known param keys as tunables. CLI args like --config or
        # --motor-serial should not pollute the params dict.
        self.cli_args = {
            k: v for k, v in vars(args).items() if v is not None and k in self.defaults
        }

    def get(self, key):
        if key in self.cli_args: return self.cli_args[key]
        if key in self.env_params: return self.env_params[key]
        if key in self.file_params: return self.file_params[key]
        return self.defaults.get(key)

    def get_all_params(self):
        all_params = self.defaults.copy()
        all_params.update(self.file_params)
        all_params.update(self.env_params)
        all_params.update(self.cli_args)
        return all_params
        
    def update_and_save(self, new_params):
        self.file_params.update(new_params)
        self.save_to_file()


# --- 3. 支持 MJPEG 流的 HTTP 服务器 ---
# -------------------------------------------------------------------------------------------------

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """支持多线程的 HTTP 服务器，防止视频流阻塞调参请求。"""
    daemon_threads = True

class StreamingHandler(http.server.BaseHTTPRequestHandler):
    """Web 端点与视频流处理 / Gestion des endpoints web et du flux video."""
    def __init__(self, *args, params_handler=None, motor_driver=None, motor_lock=None, **kwargs):
        self.params_handler = params_handler
        self.motor_driver = motor_driver
        self.motor_lock = motor_lock
        super().__init__(*args, **kwargs)

    def _send_json(self, status_code: int, payload: dict, *, cors: bool = False):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _motor_available(self) -> bool:
        return self.motor_driver is not None and getattr(self.motor_driver, "ser", None) is not None

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            # 动态生成参数表单
            params_form_html = ""
            current_params = self.params_handler.get_all_params()
            for key, default_val in self.params_handler.defaults.items():
                current_val = current_params.get(key, default_val)
                input_type = "number" if isinstance(default_val, (int, float)) else "text"
                step_val = "0.01" if isinstance(default_val, float) else "1"
                
                params_form_html += f"""
                <div class="param-group">
                    <label for="{key}">{key}</label>
                    {"<select id='fps' name='fps'>" + ''.join([f"<option value='{val}'{(' selected' if int(current_val) == val else '')}>{val}</option>" for val in [6, 15, 30, 60]]) + "</select>" if key == 'fps' else f"<input type='{input_type}' id='{key}' name='{key}' value='{current_val}' step='{step_val}'>"}
                </div>
                """

            # 读取外部 HTML 模板
            try:
                # 尝试从当前目录读取 index.html
                with open('web/templates/index.html', 'r', encoding='utf-8') as f:
                    html_template = f.read()
            except FileNotFoundError:
                # 如果找不到文件，尝试在脚本所在目录查找
                script_dir = os.path.dirname(os.path.abspath(__file__))
                try:
                    with open(os.path.join(script_dir, 'web/templates/index.html'), 'r', encoding='utf-8') as f:
                        html_template = f.read()
                except FileNotFoundError:
                    html_template = "<html><body><h1>Error: index.html not found! / Fichier index.html introuvable!</h1></body></html>"
            
            # 插入表单
            html = html_template.replace("<!-- FORM_PLACEHOLDER -->", params_form_html)
            self.wfile.write(html.encode('utf-8'))

        elif self.path == '/health':
            ok = self._motor_available()
            snap = _get_nav_state_snapshot()
            self._send_json(
                200,
                {
                    "ok": True,
                    "motor_ok": ok,
                    "forward_locked": snap["forward_locked"],
                    "forward_lock_reason": snap["forward_lock_reason"],
                    "stair_approach_active": snap["stair_approach_active"],
                    "ultra_cm": snap["ultra_cm"],
                },
                cors=True,
            )
            
        elif self.path == '/video_feed':
            if cv2 is None:
                self.send_error(503, "OpenCV (cv2) not available")
                return
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        if output_frame is None:
                            continue
                        (flag, encodedImage) = cv2.imencode(".jpg", output_frame)
                        if not flag:
                            continue
                        byte_data = encodedImage.tobytes()

                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(byte_data)))
                    self.end_headers()
                    self.wfile.write(byte_data)
                    self.wfile.write(b'\r\n')
                    time.sleep(0.05)
            except Exception as e:
                pass

        elif self.path == '/params':
            self._send_json(200, self.params_handler.get_all_params(), cors=True)

        elif self.path == '/nav_state':
            self._send_json(200, _get_nav_state_snapshot(), cors=True)
            
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/params':
            try:
                new_params = self._read_json_body()
                for key, value in new_params.items():
                    if isinstance(value, (int, float)):
                       if key in self.params_handler.defaults:
                           original_type = type(self.params_handler.defaults[key])
                           new_params[key] = original_type(value)
                
                self.params_handler.update_and_save(new_params)
                self._send_json(200, {"status": "success"}, cors=True)
            except Exception as e:
                self._send_json(400, {"status": "error", "message": str(e)}, cors=True)
            return

        # --- Motor control API (merged from motor_http_api.py) ---
        if self.path in ("/stop", "/wheels", "/tristar", "/drive"):
            if self.motor_driver is None:
                self._send_json(503, {"status": "error", "message": "Motor driver not available"}, cors=True)
                return

            payload = self._read_json_body()

            def _with_lock(fn):
                lock = self.motor_lock
                if lock is None:
                    return fn()
                with lock:
                    return fn()

            def _preempt_for(target: str):
                _with_lock(lambda: preempt_for(self.motor_driver, target))

            if self.path == "/stop":
                _with_lock(self.motor_driver.stop)
                self._send_json(200, {"status": "ok"}, cors=True)
                return

            if self.path == "/wheels":
                snap = _get_nav_state_snapshot()
                if snap["forward_locked"] and _is_wheels_forward_like(payload):
                    _with_lock(self.motor_driver.stop)
                    self._send_json(
                        423,
                        {
                            "status": "blocked",
                            "message": "Forward motion locked",
                            "reason": snap["forward_lock_reason"],
                        },
                        cors=True,
                    )
                    return

                _preempt_for("ground")

                if _is_wheels_backward_like(payload):
                    _arm_manual_reverse_override(float(self.params_handler.get("manual_reverse_override_s")))

                # Option A: independent wheels
                if "left" in payload or "right" in payload:
                    left = float(payload.get("left", 0))
                    right = float(payload.get("right", 0))
                    _with_lock(lambda: self.motor_driver.move_wheels_lr(left, right))
                    self._send_json(200, {"status": "ok", "left": left, "right": right}, cors=True)
                    return

                rpm = float(payload.get("rpm", 0))
                _with_lock(lambda: self.motor_driver.move_wheels(rpm))
                self._send_json(200, {"status": "ok", "rpm": rpm}, cors=True)
                return

            if self.path == "/tristar":
                rpm = float(payload.get("rpm", 20.0))
                _preempt_for("stair")
                if hasattr(self.motor_driver, "set_tristar2_freewheel"):
                    _with_lock(lambda: self.motor_driver.set_tristar2_freewheel(False))
                _with_lock(lambda: self.motor_driver.move_tristar(rpm))
                self._send_json(200, {"status": "ok", "rpm": rpm}, cors=True)
                return

            if self.path == "/drive":
                action = str(payload.get("action", "")).strip().lower()
                speed = float(payload.get("speed", 60.0))
                rpm = float(payload.get("rpm", 20.0))

                if action in ("unlock_forward", "unlock", "uf"):
                    snap = _clear_forward_latch()
                    self._send_json(
                        200,
                        {
                            "status": "ok",
                            "action": "unlock_forward",
                            "forward_locked": snap["forward_locked"],
                            "forward_lock_reason": snap["forward_lock_reason"],
                        },
                        cors=True,
                    )
                    return

                snap = _get_nav_state_snapshot()
                if snap["forward_locked"] and _is_drive_action_forward_like(action):
                    _with_lock(self.motor_driver.stop)
                    self._send_json(
                        423,
                        {
                            "status": "blocked",
                            "message": "Forward motion locked",
                            "reason": snap["forward_lock_reason"],
                        },
                        cors=True,
                    )
                    return

                if action in GROUND_ACTIONS:
                    _preempt_for("ground")
                elif action in STAIR_ACTIONS:
                    _preempt_for("stair")

                if action in ("stop", "s"):
                    _with_lock(self.motor_driver.stop)
                    self._send_json(200, {"status": "ok", "action": "stop"}, cors=True)
                    return

                if action in ("forward", "f"):
                    _with_lock(lambda: self.motor_driver.move_wheels_lr(speed, speed))
                    self._send_json(200, {"status": "ok", "action": "forward", "speed": speed}, cors=True)
                    return

                if action in ("backward", "back", "b"):
                    _arm_manual_reverse_override(float(self.params_handler.get("manual_reverse_override_s")))
                    _with_lock(lambda: self.motor_driver.move_wheels_lr(-speed, -speed))
                    self._send_json(200, {"status": "ok", "action": "backward", "speed": speed}, cors=True)
                    return

                if action in ("left", "l"):
                    # Pivot turn: stop left wheel, drive right wheel forward
                    _with_lock(lambda: self.motor_driver.move_wheels_lr(0.0, speed))
                    self._send_json(200, {"status": "ok", "action": "left", "speed": speed}, cors=True)
                    return

                if action in ("right", "r"):
                    # Pivot turn: drive left wheel forward, stop right wheel
                    _with_lock(lambda: self.motor_driver.move_wheels_lr(speed, 0.0))
                    self._send_json(200, {"status": "ok", "action": "right", "speed": speed}, cors=True)
                    return

                # Stair mechanism (tristar)
                if action in ("up", "u"):
                    if hasattr(self.motor_driver, "set_tristar2_freewheel"):
                        _with_lock(lambda: self.motor_driver.set_tristar2_freewheel(False))
                    _with_lock(lambda: self.motor_driver.move_tristar(abs(rpm)))
                    self._send_json(200, {"status": "ok", "action": "up", "rpm": abs(rpm)}, cors=True)
                    return

                if action in ("down", "d"):
                    if hasattr(self.motor_driver, "move_tristar_front"):
                        if hasattr(self.motor_driver, "move_tristar_rear"):
                            _with_lock(lambda: self.motor_driver.move_tristar_rear(0.0))
                        _with_lock(lambda: self.motor_driver.move_tristar_front(abs(rpm)))
                        self._send_json(200, {"status": "ok", "action": "down", "rpm": abs(rpm), "rear_control": "stopped"}, cors=True)
                    else:
                        _with_lock(lambda: self.motor_driver.move_tristar(abs(rpm)))
                        self._send_json(200, {"status": "ok", "action": "down", "rpm": abs(rpm), "rear_control": "n/a"}, cors=True)
                    return

                # Independent climb motors (firmware: F/R)
                if action in ("front_up", "fu"):
                    if hasattr(self.motor_driver, "move_tristar_front"):
                        _with_lock(lambda: self.motor_driver.move_tristar_front(abs(rpm)))
                        self._send_json(200, {"status": "ok", "action": "front_up", "rpm": abs(rpm)}, cors=True)
                    else:
                        self._send_json(400, {"status": "error", "message": "Firmware/driver lacks front motor command"}, cors=True)
                    return

                if action in ("front_down", "fd"):
                    if hasattr(self.motor_driver, "move_tristar_front"):
                        _with_lock(lambda: self.motor_driver.move_tristar_front(-abs(rpm)))
                        self._send_json(200, {"status": "ok", "action": "front_down", "rpm": -abs(rpm)}, cors=True)
                    else:
                        self._send_json(400, {"status": "error", "message": "Firmware/driver lacks front motor command"}, cors=True)
                    return

                if action in ("rear_up", "ru"):
                    if hasattr(self.motor_driver, "move_tristar_rear"):
                        if hasattr(self.motor_driver, "set_tristar2_freewheel"):
                            _with_lock(lambda: self.motor_driver.set_tristar2_freewheel(False))
                        _with_lock(lambda: self.motor_driver.move_tristar_rear(abs(rpm)))
                        self._send_json(200, {"status": "ok", "action": "rear_up", "rpm": abs(rpm)}, cors=True)
                    else:
                        self._send_json(400, {"status": "error", "message": "Firmware/driver lacks rear motor command"}, cors=True)
                    return

                if action in ("rear_down", "rd"):
                    if hasattr(self.motor_driver, "move_tristar_rear"):
                        if hasattr(self.motor_driver, "set_tristar2_freewheel"):
                            _with_lock(lambda: self.motor_driver.set_tristar2_freewheel(False))
                        _with_lock(lambda: self.motor_driver.move_tristar_rear(-abs(rpm)))
                        self._send_json(200, {"status": "ok", "action": "rear_down", "rpm": -abs(rpm)}, cors=True)
                    else:
                        self._send_json(400, {"status": "error", "message": "Firmware/driver lacks rear motor command"}, cors=True)
                    return

                self._send_json(400, {"status": "error", "message": f"Unknown action: {action}"}, cors=True)
                return

        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def log_message(self, format, *args):
        # `args` may contain non-strings (e.g., `404` from `send_error`), so don't
        # inspect `args[0]` for filtering. Filter by request path instead.
        path = getattr(self, "path", "")
        if isinstance(path, str) and path.startswith("/video_feed"):
            return

        super().log_message(format, *args)

def start_http_server(params_handler, host='0.0.0.0', port=8080):
    """启动 HTTP 服务线程 / Demarre le serveur HTTP."""
    def handler_factory(*args, **kwargs):
        return StreamingHandler(
            *args,
            params_handler=params_handler,
            motor_driver=motor_driver,
            motor_lock=motor_lock,
            **kwargs,
        )

    with ThreadingHTTPServer((host, port), handler_factory) as httpd:
        print(f"WEB服务器已启动 / Serveur WEB démarré: http://{host}:{port}")
        httpd.serve_forever()

def start_config_watcher(params_handler):
    """监测配置文件变更 / Surveille les changements du fichier config."""
    last_mtime = 0
    while True:
        try:
            mtime = os.path.getmtime(params_handler.params_path)
            if mtime > last_mtime:
                if last_mtime != 0:
                    print("检测到配置变化 / Changement de configuration détecté.")
                last_mtime = mtime
                params_handler.load_from_file()
        except FileNotFoundError:
            pass
        time.sleep(1)


# --- 4. 主函数 (main) ---
# -------------------------------------------------------------------------------------------------

def parse_args(argv=None):
    """解析 CLI 参数 / Analyse des arguments CLI."""
    parser = argparse.ArgumentParser(description="CarryBot Vision (CN/FR)")
    parser.add_argument('--config', type=str, help='Config file path / Chemin du fichier de config')
    parser.add_argument('--motor-serial', type=str, default=None, help='Motor controller serial port (e.g. /dev/ttyUSB0)')
    handler = ParamsHandler()
    for key, val in handler.defaults.items():
        t = type(val)
        parser.add_argument(f'--{key}', type=t)
    return parser.parse_args(argv)


def main():
    """主循环：采集、检测、可视化与流输出 / Boucle principale capture-detect-affichage."""
    global output_frame
    global dist_display_ema_m
    
    # --- 初始化 ---
    args = parse_args()
    params = ParamsHandler(default_params_path=args.config or 'config.json')
    params.load_from_file()
    params._load_from_env()
    params._load_from_cli_args(args)

    if cv2 is None or np is None or rs is None:
        raise RuntimeError(
            "Missing runtime dependencies. Install OpenCV (opencv-python), numpy and pyrealsense2 "
            "to run the camera loop. (Unit tests can run without them.)"
        )

    # Motor driver (optional): merged into the same web server.
    global motor_driver
    if MotorDriver is not None:
        try:
            motor_driver = MotorDriver(port=args.motor_serial)
        except Exception as e:
            print(f"[Motor] init failed: {e}")
            motor_driver = None

    http_thread = threading.Thread(target=start_http_server, args=(params,), daemon=True)
    http_thread.start()
    
    watcher_thread = threading.Thread(target=start_config_watcher, args=(params,), daemon=True)
    watcher_thread.start()

    pipeline = rs.pipeline()
    config = rs.config()
    
    # FPS 配置 (RealSense 通常支持 6, 15, 30, 60)
    fps = int(params.get('fps'))
    
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, fps)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, fps)

    print("\n--- 启动 CarryBot 视觉系统 (Web 控制台模式) ---")
    print("--- Démarrage CarryBot Vision (Mode Console Web) ---")
    print("请访问 / Veuillez visiter: http://<IP>:8080")
    print("按 Ctrl+C 停止 / Appuyez sur Ctrl+C pour arrêter.\n")
    
    pipeline.start(config)

    try:
        frame_count = 0
        while True:
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            color_frame = frames.get_color_frame()
            if not depth_frame or not color_frame: continue

            depth_image = np.asanyarray(depth_frame.get_data())
            color_image = np.asanyarray(color_frame.get_data())
            
            # --- B. 检测算法 ---
            
            # 可视化增强
            depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.08), cv2.COLORMAP_JET)
            
            # ROI 计算
            h, w = depth_image.shape
            roi_x1 = int(w * params.get('roi_h_start'))
            roi_x2 = int(w * params.get('roi_h_stop'))
            roi_y1 = int(h * params.get('roi_v_start'))
            roi_y2 = int(h * params.get('roi_v_stop'))
            
            roi = depth_image[roi_y1:roi_y2, roi_x1:roi_x2]

            # 滤波
            ksize = int(params.get('median_blur_ksize'))
            if ksize % 2 == 0: ksize += 1
            roi_filtered = cv2.medianBlur(roi, ksize)

            # 有效性掩码
            valid_mask = (roi_filtered > params.get('min_valid_dist') * 1000) & \
                         (roi_filtered < params.get('max_valid_dist') * 1000)
            
            # 状态判定
            is_wall = is_stairs_down = is_stairs_up = False
            
            if np.sum(valid_mask) > valid_mask.size * 0.1:
                # 下行 (洞)
                horizontal_projection = np.sum(valid_mask, axis=1)
                empty_lines = np.where(horizontal_projection < roi.shape[1] * 0.1)[0]
                if len(empty_lines) > 0:
                    hole_mask = np.zeros_like(roi, dtype=np.uint8)
                    hole_mask[empty_lines, :] = 255
                    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(hole_mask, 4)
                    if num_labels > 1:
                        largest_area = np.max(stats[1:, cv2.CC_STAT_AREA])
                        is_stairs_down = largest_area > params.get('noise_filtering_area_min_th')

                # 上行 (台阶)
                mid = roi.shape[0] // 2
                top = valid_mask[:mid, :]
                btm = valid_mask[mid:, :]
                if np.sum(top) > 0 and np.sum(btm) > 0:
                    top_m = np.mean(roi_filtered[:mid, :][top])
                    btm_m = np.mean(roi_filtered[mid:, :][btm])
                    diff_m = (top_m - btm_m) / 1000.0
                    is_stairs_up = diff_m > params.get('step_height_th')

                # Wall detection: close + flat surface.
                # IMPORTANT: if stairs are detected, don't classify as WALL.
                mean_dist_mm = np.mean(roi_filtered[valid_mask])
                wall_dist_th_mm = params.get('wall_dist_th') * 1000
                wall_iqr_th_mm = params.get('wall_iqr_th') * 1000

                depth_vals = roi_filtered[valid_mask]
                if depth_vals.size > 0:
                    q25, q75 = np.percentile(depth_vals, [25, 75])
                    iqr_mm = q75 - q25
                else:
                    iqr_mm = float('inf')

                is_wall = (
                    (mean_dist_mm < wall_dist_th_mm)
                    and (iqr_mm < wall_iqr_th_mm)
                    and (not is_stairs_down)
                    and (not is_stairs_up)
                )

            # --- D. Navigation state + safety behavior ---
            ultra_cm: Optional[float] = None
            if motor_driver is not None and hasattr(motor_driver, "get_latest_ultrasonic_cm"):
                try:
                    ultra_cm = motor_driver.get_latest_ultrasonic_cm()
                except Exception:
                    ultra_cm = None

            snap = _get_nav_state_snapshot()
            approach_active = bool(snap["stair_approach_active"])
            lock_latched = bool(snap["forward_lock_latched"])
            reverse_override_active = time.time() < float(snap.get("manual_reverse_until", 0.0))

            # 1) Wall ahead => immediate stop.
            if is_wall and (not reverse_override_active) and motor_driver is not None:
                with motor_lock:
                    motor_driver.stop()
                approach_active = False

            # 2) Stair ahead => auto approach until ultrasonic trigger.
            if (is_stairs_up and (not approach_active) and (not lock_latched) and (not is_wall)):
                if motor_driver is not None:
                    approach_speed = float(params.get("stair_approach_speed_rpm"))
                    with motor_lock:
                        motor_driver.move_wheels_lr(approach_speed, approach_speed)
                approach_active = True

            ultra_trigger_cm = float(params.get("stair_ultra_trigger_cm"))
            ultra_hit = (
                approach_active
                and ultra_cm is not None
                and ultra_cm > 0
                and ultra_cm <= ultra_trigger_cm
            )

            # 3) Ultrasonic trigger reached => stop and latch forward lock.
            if ultra_hit:
                if motor_driver is not None:
                    with motor_lock:
                        motor_driver.stop()
                approach_active = False
                lock_latched = True

            forward_locked, lock_reason = _recompute_forward_lock(
                is_wall=is_wall,
                lock_latched=lock_latched,
            )
            _set_nav_state(
                is_wall=is_wall,
                is_stairs_up=is_stairs_up,
                is_stairs_down=is_stairs_down,
                ultra_cm=ultra_cm,
                stair_approach_active=approach_active,
                forward_lock_latched=lock_latched,
                forward_locked=forward_locked,
                forward_lock_reason=lock_reason,
            )

            # --- C. 绘图与更新 ---
            
            cv2.rectangle(color_image, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 2)
            cv2.rectangle(depth_colormap, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 2)

            # 双语状态文本 (OSD 使用 ASCII)
            status_text = "OK"
            color = (0, 255, 0)
            if is_stairs_down:
                status_text = "DOWN / DESC"
                color = (0, 0, 255)
            elif is_stairs_up:
                status_text = "UP / MONT"
                color = (0, 0, 255)
            elif is_wall:
                status_text = "WALL / MUR"
                color = (0, 0, 255)
            
            cv2.putText(color_image, status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)

            # Depth OSD distance: close range can be unstable (D435i). Use robust stats,
            # require enough valid pixels, and smooth the value.
            max_valid_mm = params.get('max_valid_dist') * 1000
            display_mask = (roi_filtered > 0) & (roi_filtered < max_valid_mm)

            # Treat <15cm as unreliable by default (independent from min_valid_dist)
            too_close_limit_m = max(float(params.get('min_valid_dist')), 0.15)
            too_close_limit_mm = too_close_limit_m * 1000
            close_mask = (roi_filtered > 0) & (roi_filtered < too_close_limit_mm)

            if np.sum(display_mask) > display_mask.size * 0.1:
                depth_vals = roi_filtered[display_mask]

                # Robust distance estimate
                dist_med_m = float(np.median(depth_vals)) / 1000.0

                # Robust stability check (helps avoid 0/holes causing far-pixel jumps)
                q10, q90 = np.percentile(depth_vals, [10, 90])
                spread_m = float(q90 - q10) / 1000.0

                too_close = np.sum(close_mask) > display_mask.size * 0.2
                unstable = spread_m > 0.60

                if too_close:
                    depth_text = f"Too close (<{too_close_limit_m:.2f}m)"
                    dist_display_ema_m = None
                elif unstable:
                    depth_text = "Depth unstable"
                    dist_display_ema_m = None
                else:
                    alpha = 0.30
                    dist_display_ema_m = (
                        dist_med_m
                        if dist_display_ema_m is None
                        else (1 - alpha) * dist_display_ema_m + alpha * dist_med_m
                    )
                    depth_text = f"Dist: {dist_display_ema_m:.2f}m"
            else:
                depth_text = "No Data"
                dist_display_ema_m = None

            cv2.putText(
                depth_colormap,
                depth_text,
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255),
                2,
            )

            # 拼接图像
            combined_img = np.hstack((color_image, depth_colormap))
            
            # --- 安全地更新全局帧 ---
            with frame_lock:
                output_frame = combined_img.copy()
            
            # 日志心跳
            frame_count += 1
            if frame_count % 100 == 0:
                print(f"[Heartbeat] Frame {frame_count}. Status: {status_text}")

    except KeyboardInterrupt:
        print("\nStopped by user (Ctrl+C). / Arrêté par l'utilisateur (Ctrl+C).")
    except Exception as e:
        print(f"Error / Erreur: {e}")
    finally:
        pipeline.stop()

if __name__ == "__main__":
    main()