#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =================================================================================================
#            ---          CarryBot - 楼梯检测系统 (Web Stream版 - 带控制面板)          ---
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
# - 新增: Web 控制面板，可直接在浏览器中查看和修改参数。
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
    - GET /           : 返回包含视频流和控制面板的网页
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
            
            # 动态生成参数表单
            params_form_html = ""
            current_params = self.params_handler.get_all_params()
            for key, default_val in self.params_handler.defaults.items():
                current_val = current_params.get(key, default_val)
                input_type = "number" if isinstance(default_val, (int, float)) else "text"
                step_val = "0.01" if isinstance(default_val, float) else "1"
                
                params_form_html += f"""
                <div class="param-group">
                    <label for="{key}">{key}:</label>
                    <input type="{input_type}" id="{key}" name="{key}" value="{current_val}" step="{step_val}">
                </div>
                """

            html = f"""
            <html>
            <head>
                <title>CarryBot 视觉控制台</title>
                <style>
                    body {{ font-family: sans-serif; text-align: center; background: #222; color: #fff; display: flex; flex-direction: column; align-items: center; }}
                    #container {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; max-width: 1200px; margin: 20px auto; }}
                    #video-panel {{ flex: 2; min-width: 640px; }}
                    #control-panel {{ flex: 1; min-width: 300px; background: #333; padding: 20px; border-radius: 8px; text-align: left; }}
                    img {{ border: 2px solid #555; max-width: 100%; height: auto; }}
                    h1 {{ color: #0f0; }}
                    h2 {{ color: #0f0; margin-top: 0; }}
                    .param-group {{ margin-bottom: 10px; }}
                    label {{ display: block; margin-bottom: 5px; color: #aaa; }}
                    input[type="number"], input[type="text"] {{
                        width: calc(100% - 22px); padding: 8px; border: 1px solid #555; border-radius: 4px; background: #444; color: #fff;
                    }}
                    button {{
                        background: #0f0; color: #000; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; margin-top: 10px;
                    }}
                    button:hover {{ background: #0c0; }}
                    #status-message {{ margin-top: 10px; font-weight: bold; }}
                    .success {{ color: #0f0; }}
                    .error {{ color: #f00; }}
                </style>
            </head>
            <body>
                <h1>CarryBot 实时监控与控制</h1>
                <div id="container">
                    <div id="video-panel">
                        <img src="/video_feed" />
                    </div>
                    <div id="control-panel">
                        <h2>参数控制</h2>
                        <form id="params-form">
                            {params_form_html}
                            <button type="submit">更新参数</button>
                            <div id="status-message"></div>
                        </form>
                    </div>
                </div>

                <script>
                    document.getElementById('params-form').addEventListener('submit', async function(event) {{
                        event.preventDefault();
                        const formData = new FormData(event.target);
                        const params = {{}};
                        for (let [key, value] of formData.entries()) {{
                            // 尝试将值转换为数字，如果失败则保留字符串
                            if (!isNaN(parseFloat(value)) && isFinite(value)) {{
                                params[key] = parseFloat(value);
                            }} else {{
                                params[key] = value;
                            }}
                        }}

                        const statusMessage = document.getElementById('status-message');
                        statusMessage.className = '';
                        statusMessage.textContent = '正在更新...';

                        try {{
                            const response = await fetch('/params', {{
                                method: 'POST',
                                headers: {{
                                    'Content-Type': 'application/json'
                                }},
                                body: JSON.stringify(params)
                            }});
                            const data = await response.json();
                            if (response.ok) {{
                                statusMessage.textContent = '更新成功！';
                                statusMessage.className = 'success';
                            }} else {{
                                statusMessage.textContent = '更新失败: ' + (data.message || '未知错误');
                                statusMessage.className = 'error';
                            }}
                        }} catch (error) {{
                            statusMessage.textContent = '请求失败: ' + error.message;
                            statusMessage.className = 'error';
                        }}
                    }});

                    // 自动刷新参数值 (可选，如果想要页面显示最新值)
                    // setInterval(async () => {{
                    //     try {{
                    //         const response = await fetch('/params');
                    //         if (response.ok) {{
                    //             const currentParams = await response.json();
                    //             for (const key in currentParams) {{
                    //                 const input = document.getElementById(key);
                    //                 if (input && document.activeElement !== input) {{ // 避免刷新正在编辑的输入框
                    //                     input.value = currentParams[key];
                    //                 }}
                    //             }}
                    //         }}
                    //     }} catch (error) {{
                    //         console.error('Failed to fetch latest params:', error);
                    //     }}
                    // }}, 2000); // 每2秒刷新一次
                </script>
            </body>
            </html>
            