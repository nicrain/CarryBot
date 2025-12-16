#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =================================================================================================
#            ---          CarryBot - 楼梯检测系统 (Web Stream版)          ---
# =================================================================================================
#
# ## 描述
# 该脚本是 CarryBot 感知系统的核心。它使用 Intel RealSense 摄像头通过分析深度数据流
# 来检测楼梯（上行和下行）和墙壁。
#
# ## 架构变更 (Web Stream)
# - 移除了本地 GUI (cv2.imshow)，改为 MJPEG HTTP 视频流。
# - 视频流地址: http://<IP>:8080/video_feed
# - 调参 API: http://<IP>:8080/params
#
# =================================================================================================

import argparse
import os
import json
import time
import threading
import http.server
import socketserver
import cv2
import numpy as np
import pyrealsense2 as rs

# --- 全局变量用于线程间通信 ---
output_frame = None
frame_lock = threading.Lock()

# --- 2. 参数管理类 (ParamsHandler) ---
# (保持不变)
class ParamsHandler:
    def __init__(self, default_params_path='config.json'):
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
            "wall_dist_th": 0.8,
            "step_height_th": 0.05,
            "noise_filtering_area_min_th": 1000
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
        self.cli_args = {k: v for k, v in vars(args).items() if v is not None}

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
    """
    处理 HTTP 请求：
    - GET /           : 返回包含视频流的网页
    - GET /video_feed : 返回 MJPEG 视频流
    - GET /params     : 返回当前参数 (JSON)
    - POST /params    : 更新参数
    """
    def __init__(self, *args, params_handler=None, **kwargs):
        self.params_handler = params_handler
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            html = """
            <html>
            <head>
                <title>CarryBot 视觉控制台</title>
                <style>
                    body { font-family: sans-serif; text-align: center; background: #222; color: #fff; }
                    img { border: 2px solid #555; max-width: 100%; }
                    .info { margin-top: 10px; color: #aaa; }
                </style>
            </head>
            <body>
                <h1>CarryBot 实时监控</h1>
                <img src="/video_feed" />
                <div class="info">
                    <p>GET /params 查看参数 | POST /params 修改参数</p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))
            
        elif self.path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        if output_frame is None:
                            continue
                        # 将图像编码为 JPEG
                        (flag, encodedImage) = cv2.imencode(".jpg", output_frame)
                        if not flag:
                            continue
                        byte_data = encodedImage.tobytes()

                    # 发送分界符和图像数据
                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(byte_data)))
                    self.end_headers()
                    self.wfile.write(byte_data)
                    self.wfile.write(b'\r\n')
                    # 控制帧率，避免在此处消耗过多带宽
                    time.sleep(0.05)
            except Exception as e:
                # 客户端断开连接
                pass

        elif self.path == '/params':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            response = json.dumps(self.params_handler.get_all_params())
            self.wfile.write(response.encode('utf-8'))
            
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/params':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                new_params = json.loads(post_data)
                # 类型转换
                for key, value in new_params.items():
                    if isinstance(value, (int, float)):
                       if key in self.params_handler.defaults:
                           original_type = type(self.params_handler.defaults[key])
                           new_params[key] = original_type(value)
                
                self.params_handler.update_and_save(new_params)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')
            except Exception as e:
                self.send_response(400)
                self.wfile.write(f'{{"status": "error", "message": "{e}"}}'.encode('utf-8'))
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        # 仅在非视频流请求时打印日志，避免刷屏
        if "video_feed" not in args[0]:
            super().log_message(format, *args)

def start_http_server(params_handler, host='0.0.0.0', port=8080):
    def handler_factory(*args, **kwargs):
        return StreamingHandler(*args, params_handler=params_handler, **kwargs)

    # 使用多线程服务器
    with ThreadingHTTPServer((host, port), handler_factory) as httpd:
        print(f"WEB服务器已启动: http://{host}:{port}")
        httpd.serve_forever()

def start_config_watcher(params_handler):
    last_mtime = 0
    while True:
        try:
            mtime = os.path.getmtime(params_handler.params_path)
            if mtime > last_mtime:
                if last_mtime != 0: # 首次启动不打印
                    print("检测到配置变化，已重新加载。")
                last_mtime = mtime
                params_handler.load_from_file()
        except FileNotFoundError:
            pass
        time.sleep(1)


# --- 4. 主函数 (main) ---
# -------------------------------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="CarryBot 视觉系统 (Web Stream 版)")
    parser.add_argument('--config', type=str, help='配置文件路径')
    # 添加所有参数以便 CLI 覆盖
    handler = ParamsHandler()
    for key, val in handler.defaults.items():
        t = type(val)
        parser.add_argument(f'--{key}', type=t)
    return parser.parse_args()


def main():
    global output_frame
    
    # --- 初始化 ---
    args = parse_args()
    params = ParamsHandler(default_params_path=args.config or 'config.json')
    params.load_from_file()
    params._load_from_env()
    params._load_from_cli_args(args)

    # 启动后台服务
    http_thread = threading.Thread(target=start_http_server, args=(params,), daemon=True)
    http_thread.start()
    
    watcher_thread = threading.Thread(target=start_config_watcher, args=(params,), daemon=True)
    watcher_thread.start()

    # --- RealSense 配置 ---
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

    print("\n--- 启动 CarryBot 视觉系统 (Headless Mode) ---")
    print("请在浏览器中访问 http://<树莓派IP>:8080 查看视频流。")
    print("按 Ctrl+C 停止程序。\n")
    
    pipeline.start(config)

    try:
        frame_count = 0
        while True:
            # --- A. 图像采集 ---
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            color_frame = frames.get_color_frame()
            if not depth_frame or not color_frame: continue

            depth_image = np.asanyarray(depth_frame.get_data())
            color_image = np.asanyarray(color_frame.get_data())
            
            # --- B. 检测算法 ---
            # ... (这部分逻辑保持完全一致，为了简洁此处不重复每一行注释，但逻辑不变) ...
            
            # 可视化增强 (针对 Web 显示优化)
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
                mean_dist_mm = np.mean(roi_filtered[valid_mask])
                is_wall = mean_dist_mm < params.get('wall_dist_th') * 1000

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

            # --- C. 绘图与更新 ---
            
            cv2.rectangle(color_image, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 2)
            cv2.rectangle(depth_colormap, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 2)

            status_text = "Status: OK"
            color = (0, 255, 0)
            if is_wall:
                status_text = "WALL DETECTED"
                color = (0, 0, 255)
            elif is_stairs_down:
                status_text = "STAIRS DOWN"
                color = (0, 0, 255)
            elif is_stairs_up:
                status_text = "STAIRS UP"
                color = (0, 0, 255)
            
            cv2.putText(color_image, status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
            cv2.putText(depth_colormap, f"Dist: {np.mean(roi_filtered[valid_mask])/1000:.2f}m" if np.sum(valid_mask)>0 else "No Data", 
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

            # 拼接图像
            combined_img = np.hstack((color_image, depth_colormap))
            
            # 缩放图像以减少网络传输带宽 (可选，此处保持原样或缩小)
            # combined_img = cv2.resize(combined_img, (0,0), fx=0.8, fy=0.8)

            # --- 安全地更新全局帧 ---
            with frame_lock:
                output_frame = combined_img.copy()
            
            # 简单的日志心跳
            frame_count += 1
            if frame_count % 100 == 0:
                print(f"[Heartbeat] Frame {frame_count} processed. Last result: {status_text}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        pipeline.stop()

if __name__ == "__main__":
    main()