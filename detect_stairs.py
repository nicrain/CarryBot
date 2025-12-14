"""
detect_stairs.py

关键参数说明（可通过环境变量或命令行覆盖）

环境变量（优先级低于命令行参数）：
- ROI_WIDTH / ROI_HEIGHT: 中心感兴趣矩形宽高（像素），默认 120
- EDGE_THRESH: 行梯度判定阈值（毫米），默认 200
- ROW_NORM_THRESH: 行归一化阈值（0-1），默认 0.3
- MIN_COMPONENT_AREA: 连通域最小面积，默认 50
- MIN_COMPONENT_HEIGHT: 连通域最小高度，默认 2
- SMOOTH_WINDOW: 平滑窗口长度，默认 5

命令行参数（优先级高于环境变量）：
--roi-width, --roi-height, --edge-thresh, --row-norm-thresh, --min-area, --min-height, --smooth-window, --headless

Headless 使用：在无显示器（如 SSH、Docker）环境下运行，设置环境变量 `HEADLESS_TEST=1` 或使用 `--headless`，脚本会保存调试图像（如 `depth_frame_step2.jpg`）并退出。

快速示例：
```
HEADLESS_TEST=1 python detect_stairs.py --roi-width 160 --smooth-window 3 --edge-thresh 150
```

调试建议：先用 `HEADLESS_TEST=1` 保存帧并查看伪彩色图，观察 `Front` 距离、边缘高亮是否符合预期，再在机器人上打开实时显示（GUI）。
"""

import pyrealsense2 as rs
import numpy as np
import cv2
import os
import argparse
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from collections import deque

# Parameters (tunable) - can be overridden by env vars or CLI args
ROI_WIDTH = int(os.getenv('ROI_WIDTH', '120'))
ROI_HEIGHT = int(os.getenv('ROI_HEIGHT', '120'))
EDGE_THRESH = float(os.getenv('EDGE_THRESH', '200'))
ROW_NORM_THRESH = float(os.getenv('ROW_NORM_THRESH', '0.3'))
MIN_COMPONENT_AREA = int(os.getenv('MIN_COMPONENT_AREA', '50'))
MIN_COMPONENT_HEIGHT = int(os.getenv('MIN_COMPONENT_HEIGHT', '2'))
SMOOTH_WINDOW = int(os.getenv('SMOOTH_WINDOW', '5'))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Detect stairs from RealSense depth')
    parser.add_argument('--roi-width', type=int, help='ROI width in pixels')
    parser.add_argument('--roi-height', type=int, help='ROI height in pixels')
    parser.add_argument('--edge-thresh', type=float, help='Edge gradient threshold (mm)')
    parser.add_argument('--row-norm-thresh', type=float, help='Row normalized threshold (0-1)')
    parser.add_argument('--min-area', type=int, help='Min connected component area')
    parser.add_argument('--min-height', type=int, help='Min connected component height')
    parser.add_argument('--smooth-window', type=int, help='Smoothing window size')
    parser.add_argument('--headless', action='store_true', help='Force headless mode (save frames instead of show)')
    parser.add_argument('--server-only', action='store_true', help='Only start HTTP server and config watcher, no camera processing')
    return parser.parse_args(argv)


def load_config(path='config.json'):
    """Load JSON config if exists."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def write_config(cfg, path='config.json'):
    try:
        with open(path, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False


def start_config_watcher(callback, path='config.json', interval=1.0):
    """Start a background thread that watches config file and calls callback when modified."""
    def watcher():
        last_mtime = None
        while True:
            try:
                if os.path.exists(path):
                    m = os.path.getmtime(path)
                    if last_mtime is None:
                        last_mtime = m
                    elif m != last_mtime:
                        last_mtime = m
                        cfg = load_config(path)
                        callback(cfg)
                time.sleep(interval)
            except Exception:
                time.sleep(interval)

    t = threading.Thread(target=watcher, daemon=True)
    t.start()
    return t


class ParamsHandler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        data = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == '/params':
            params = {
                'ROI_WIDTH': ROI_WIDTH,
                'ROI_HEIGHT': ROI_HEIGHT,
                'EDGE_THRESH': EDGE_THRESH,
                'ROW_NORM_THRESH': ROW_NORM_THRESH,
                'MIN_COMPONENT_AREA': MIN_COMPONENT_AREA,
                'MIN_COMPONENT_HEIGHT': MIN_COMPONENT_HEIGHT,
                'SMOOTH_WINDOW': SMOOTH_WINDOW,
            }
            self._send_json(params)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == '/params':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid json'}, code=400)
                return
            # Update allowed params
            changed = {}
            global ROI_WIDTH, ROI_HEIGHT, EDGE_THRESH, ROW_NORM_THRESH, MIN_COMPONENT_AREA, MIN_COMPONENT_HEIGHT, SMOOTH_WINDOW
            if 'ROI_WIDTH' in data:
                ROI_WIDTH = int(data['ROI_WIDTH'])
                changed['ROI_WIDTH'] = ROI_WIDTH
            if 'ROI_HEIGHT' in data:
                ROI_HEIGHT = int(data['ROI_HEIGHT'])
                changed['ROI_HEIGHT'] = ROI_HEIGHT
            if 'EDGE_THRESH' in data:
                EDGE_THRESH = float(data['EDGE_THRESH'])
                changed['EDGE_THRESH'] = EDGE_THRESH
            if 'ROW_NORM_THRESH' in data:
                ROW_NORM_THRESH = float(data['ROW_NORM_THRESH'])
                changed['ROW_NORM_THRESH'] = ROW_NORM_THRESH
            if 'MIN_COMPONENT_AREA' in data:
                MIN_COMPONENT_AREA = int(data['MIN_COMPONENT_AREA'])
                changed['MIN_COMPONENT_AREA'] = MIN_COMPONENT_AREA
            if 'MIN_COMPONENT_HEIGHT' in data:
                MIN_COMPONENT_HEIGHT = int(data['MIN_COMPONENT_HEIGHT'])
                changed['MIN_COMPONENT_HEIGHT'] = MIN_COMPONENT_HEIGHT
            if 'SMOOTH_WINDOW' in data:
                SMOOTH_WINDOW = int(data['SMOOTH_WINDOW'])
                changed['SMOOTH_WINDOW'] = SMOOTH_WINDOW
            # persist to config
            cfg = {
                'ROI_WIDTH': ROI_WIDTH,
                'ROI_HEIGHT': ROI_HEIGHT,
                'EDGE_THRESH': EDGE_THRESH,
                'ROW_NORM_THRESH': ROW_NORM_THRESH,
                'MIN_COMPONENT_AREA': MIN_COMPONENT_AREA,
                'MIN_COMPONENT_HEIGHT': MIN_COMPONENT_HEIGHT,
                'SMOOTH_WINDOW': SMOOTH_WINDOW,
            }
            write_config(cfg)
            # log changes
            try:
                log_line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} UPDATED {json.dumps(changed)}\n"
                with open('param_changes.log', 'a') as lf:
                    lf.write(log_line)
            except Exception:
                pass
            self._send_json({'updated': changed, 'config': cfg})
        else:
            self.send_response(404)
            self.end_headers()


def start_http_server(port=8000):
    server = HTTPServer(('0.0.0.0', port), ParamsHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, t

def main():
    # parse CLI args and override parameters if provided
    args = parse_args()
    global ROI_WIDTH, ROI_HEIGHT, EDGE_THRESH, ROW_NORM_THRESH, MIN_COMPONENT_AREA, MIN_COMPONENT_HEIGHT, SMOOTH_WINDOW
    if args.roi_width:
        ROI_WIDTH = args.roi_width
    if args.roi_height:
        ROI_HEIGHT = args.roi_height
    if args.edge_thresh:
        EDGE_THRESH = args.edge_thresh
    if args.row_norm_thresh:
        ROW_NORM_THRESH = args.row_norm_thresh
    if args.min_area:
        MIN_COMPONENT_AREA = args.min_area
    if args.min_height:
        MIN_COMPONENT_HEIGHT = args.min_height
    if args.smooth_window:
        SMOOTH_WINDOW = args.smooth_window
    if args.headless:
        os.environ['HEADLESS_TEST'] = '1'
    if args.server_only:
        # Start watcher and HTTP server, then block
        def apply_config_noop(cfg):
            global ROI_WIDTH, ROI_HEIGHT, EDGE_THRESH, ROW_NORM_THRESH, MIN_COMPONENT_AREA, MIN_COMPONENT_HEIGHT, SMOOTH_WINDOW
            if 'ROI_WIDTH' in cfg: ROI_WIDTH = int(cfg['ROI_WIDTH'])
            if 'ROI_HEIGHT' in cfg: ROI_HEIGHT = int(cfg['ROI_HEIGHT'])
            if 'EDGE_THRESH' in cfg: EDGE_THRESH = float(cfg['EDGE_THRESH'])
            if 'ROW_NORM_THRESH' in cfg: ROW_NORM_THRESH = float(cfg['ROW_NORM_THRESH'])
            if 'MIN_COMPONENT_AREA' in cfg: MIN_COMPONENT_AREA = int(cfg['MIN_COMPONENT_AREA'])
            if 'MIN_COMPONENT_HEIGHT' in cfg: MIN_COMPONENT_HEIGHT = int(cfg['MIN_COMPONENT_HEIGHT'])
            if 'SMOOTH_WINDOW' in cfg: SMOOTH_WINDOW = int(cfg['SMOOTH_WINDOW'])
            print('配置文件已热加载:', cfg)

        start_config_watcher(apply_config_noop, 'config.json', interval=1.0)
        try:
            server, srv_thread = start_http_server(port=8000)
            print('HTTP params server 启动于端口 8000 (server-only)')
        except Exception as e:
            print('无法启动HTTP服务器:', e)
        # block until interrupted
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print('Server-only 模式退出')
        return
    # Load config.json if exists and apply
    cfg = load_config('config.json')
    if cfg:
        if 'ROI_WIDTH' in cfg: ROI_WIDTH = int(cfg['ROI_WIDTH'])
        if 'ROI_HEIGHT' in cfg: ROI_HEIGHT = int(cfg['ROI_HEIGHT'])
        if 'EDGE_THRESH' in cfg: EDGE_THRESH = float(cfg['EDGE_THRESH'])
        if 'ROW_NORM_THRESH' in cfg: ROW_NORM_THRESH = float(cfg['ROW_NORM_THRESH'])
        if 'MIN_COMPONENT_AREA' in cfg: MIN_COMPONENT_AREA = int(cfg['MIN_COMPONENT_AREA'])
        if 'MIN_COMPONENT_HEIGHT' in cfg: MIN_COMPONENT_HEIGHT = int(cfg['MIN_COMPONENT_HEIGHT'])
        if 'SMOOTH_WINDOW' in cfg: SMOOTH_WINDOW = int(cfg['SMOOTH_WINDOW'])

    # Start config watcher to hot-reload changes
    def apply_config(new_cfg):
        global ROI_WIDTH, ROI_HEIGHT, EDGE_THRESH, ROW_NORM_THRESH, MIN_COMPONENT_AREA, MIN_COMPONENT_HEIGHT, SMOOTH_WINDOW
        if 'ROI_WIDTH' in new_cfg: ROI_WIDTH = int(new_cfg['ROI_WIDTH'])
        if 'ROI_HEIGHT' in new_cfg: ROI_HEIGHT = int(new_cfg['ROI_HEIGHT'])
        if 'EDGE_THRESH' in new_cfg: EDGE_THRESH = float(new_cfg['EDGE_THRESH'])
        if 'ROW_NORM_THRESH' in new_cfg: ROW_NORM_THRESH = float(new_cfg['ROW_NORM_THRESH'])
        if 'MIN_COMPONENT_AREA' in new_cfg: MIN_COMPONENT_AREA = int(new_cfg['MIN_COMPONENT_AREA'])
        if 'MIN_COMPONENT_HEIGHT' in new_cfg: MIN_COMPONENT_HEIGHT = int(new_cfg['MIN_COMPONENT_HEIGHT'])
        if 'SMOOTH_WINDOW' in new_cfg: SMOOTH_WINDOW = int(new_cfg['SMOOTH_WINDOW'])
        print('配置文件已热加载:', new_cfg)

    start_config_watcher(apply_config, 'config.json', interval=1.0)
    # Start HTTP server for runtime param updates
    try:
        server, srv_thread = start_http_server(port=8000)
        print('HTTP params server 启动于端口 8000')
    except Exception as e:
        print('无法启动HTTP服务器:', e)
    # 1. 配置相机
    pipeline = rs.pipeline()
    config = rs.config()
    # 降低一点分辨率以提高处理速度，640x480 足够了
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    # 如果你也想看彩色画面，把下面这行取消注释
    # config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

    # 启动管道
    pipeline.start(config)

    try:
        while True:
            # 2. 获取数据帧
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            if not depth_frame:
                continue

            # 3. 将深度数据转换为 Numpy 数组
            depth_image = np.asanyarray(depth_frame.get_data())

            # 4. 定义感兴趣区域 (ROI)
            height, width = depth_image.shape
            roi_width = ROI_WIDTH
            roi_height = ROI_HEIGHT
            col_start = width // 2 - roi_width // 2
            col_end = width // 2 + roi_width // 2
            row_start = height // 2 - roi_height // 2
            row_end = height // 2 + roi_height // 2
            center_rect = depth_image[row_start:row_end, col_start:col_end]
            # 去噪（中值滤波）
            try:
                center_rect = cv2.medianBlur(center_rect.astype(np.uint16), 5)
            except Exception:
                pass

            # 5. 核心算法：分割地面区与前方区
            rect_h = center_rect.shape[0]
            ground_zone = center_rect[int(rect_h*0.7):rect_h, :]
            front_zone = center_rect[int(rect_h*0.3):int(rect_h*0.6), :]

            # 统计特征（中位数、标准差）
            valid_ground = ground_zone[ground_zone > 0]
            valid_front = front_zone[front_zone > 0]
            dist_ground = np.median(valid_ground) if len(valid_ground) > 0 else 0
            dist_front = np.median(valid_front) if len(valid_front) > 0 else 0
            std_ground = np.std(valid_ground) if len(valid_ground) > 0 else 0
            std_front = np.std(valid_front) if len(valid_front) > 0 else 0

            # --- 时序平滑（滑动窗口） ---
            if 'dist_front_buf' not in globals():
                # 全局缓冲区，首次创建
                globals()['dist_front_buf'] = deque(maxlen=SMOOTH_WINDOW)
                globals()['dist_ground_buf'] = deque(maxlen=SMOOTH_WINDOW)
                globals()['max_grad_buf'] = deque(maxlen=SMOOTH_WINDOW)
                globals()['edge_flag_buf'] = deque(maxlen=SMOOTH_WINDOW)

            dist_front_buf = globals()['dist_front_buf']
            dist_ground_buf = globals()['dist_ground_buf']
            max_grad_buf = globals()['max_grad_buf']
            edge_flag_buf = globals()['edge_flag_buf']

            dist_front_buf.append(dist_front)
            dist_ground_buf.append(dist_ground)

            # 6. 深度突变检测与连通域过滤
            front_zone_valid = np.where(front_zone > 0, front_zone, np.nan)
            if np.all(np.isnan(front_zone_valid)):
                max_grad = 0
                edge_detected = False
                edge_mask = np.zeros_like(front_zone_valid, dtype=np.uint8)
            else:
                row_grad = np.abs(np.nanmean(np.diff(front_zone_valid, axis=0), axis=1))
                max_grad = np.nanmax(row_grad) if row_grad.size > 0 else 0
                edge_detected = max_grad > EDGE_THRESH
                # 基于行突变生成二值 mask
                if row_grad.size > 0:
                    rg_norm = (row_grad - np.nanmin(row_grad))
                    rg_norm = rg_norm / (np.nanmax(rg_norm) + 1e-6)
                    edge_rows = np.where(rg_norm > ROW_NORM_THRESH)[0]
                    edge_mask = np.zeros_like(front_zone_valid, dtype=np.uint8)
                    for r in edge_rows:
                        if r < edge_mask.shape[0]:
                            edge_mask[r, :] = 255
                    edge_mask = cv2.morphologyEx(edge_mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))
                    edge_mask = cv2.morphologyEx(edge_mask, cv2.MORPH_CLOSE, np.ones((5,5), np.uint8))
                else:
                    edge_mask = np.zeros_like(front_zone_valid, dtype=np.uint8)
                # 连通域过滤
                num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(edge_mask, connectivity=8)
                large_component_found = False
                for i in range(1, num_labels):
                    area = stats[i, cv2.CC_STAT_AREA]
                    h = stats[i, cv2.CC_STAT_HEIGHT]
                    if area > MIN_COMPONENT_AREA and h > MIN_COMPONENT_HEIGHT:
                        large_component_found = True
                        break
                if large_component_found:
                    edge_detected = True

            # 更新缓冲
            max_grad_buf.append(max_grad)
            edge_flag_buf.append(1 if edge_detected else 0)

            # 计算平滑值（使用中位数/多数投票）
            smooth_dist_front = np.median(list(dist_front_buf)) if len(dist_front_buf) > 0 else 0
            smooth_dist_ground = np.median(list(dist_ground_buf)) if len(dist_ground_buf) > 0 else 0
            smooth_max_grad = np.median(list(max_grad_buf)) if len(max_grad_buf) > 0 else 0
            smooth_edge = (1 if sum(edge_flag_buf) > len(edge_flag_buf)/2 else 0)

            # 7. 动态阈值与判定
            status_text = "En Mouvement (Pas d'obstacle)"
            color_status = (0, 255, 0)
            dynamic_thresh = dist_ground * 0.8 if dist_ground > 0 else 800

            obstacle_type = None
            # 使用平滑后的指标来判定
            smooth_dist_front = np.median(list(dist_front_buf)) if len(dist_front_buf) > 0 else dist_front
            smooth_dist_ground = np.median(list(dist_ground_buf)) if len(dist_ground_buf) > 0 else dist_ground
            smooth_max_grad = np.median(list(max_grad_buf)) if len(max_grad_buf) > 0 else max_grad
            smooth_edge = (1 if sum(edge_flag_buf) > len(edge_flag_buf)/2 else 0)

            if (0 < smooth_dist_front < dynamic_thresh) or smooth_edge:
                if dist_ground > 0 and dist_front > 0:
                    diff = dist_ground - dist_front
                    if diff > 100:
                        obstacle_type = "Descente (下台阶)"
                    elif diff < -100:
                        obstacle_type = "Montee (上台阶)"
                    else:
                        if dist_front < 400 and max_grad > 300:
                            obstacle_type = "Mur (墙体)"
                        else:
                            obstacle_type = "Marche (台阶)"
                else:
                    obstacle_type = "Obstacle"
                status_text = f"{obstacle_type} DETECTEE !"
                color_status = (0, 0, 255)
                print(f"警告：前方 {dist_front:.0f}mm 处有{obstacle_type}！(突变: {max_grad:.0f}mm, 阈值: {dynamic_thresh:.0f}mm)")

            # 8. 可视化与 headless 保存
            depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)
            cv2.rectangle(depth_colormap, (col_start, row_start + int(rect_h*0.3)), (col_end, row_start + int(rect_h*0.6)), (255, 255, 255), 2)
            cv2.putText(depth_colormap, f"Front: {dist_front:.0f}mm", (col_start, row_start + int(rect_h*0.3)-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 2)
            cv2.putText(depth_colormap, status_text, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, color_status, 2)

            # 高亮 edge_mask 到图像
            try:
                if 'edge_mask' in locals() and np.any(edge_mask):
                    mask_vis = np.zeros_like(depth_colormap)
                    front_row_start = row_start + int(rect_h*0.3)
                    front_row_end = row_start + int(rect_h*0.6)
                    try:
                        resized_mask = cv2.resize(edge_mask, (col_end-col_start, front_row_end-front_row_start), interpolation=cv2.INTER_NEAREST)
                        mask_vis[front_row_start:front_row_end, col_start:col_end, 2] = resized_mask
                        depth_colormap = cv2.addWeighted(depth_colormap, 1.0, mask_vis, 0.6, 0)
                    except Exception:
                        pass
            except Exception:
                pass

            headless_env = os.getenv('HEADLESS_TEST', '0') == '1' or (not os.getenv('DISPLAY') and not os.getenv('WAYLAND_DISPLAY'))
            if headless_env:
                cv2.imwrite('depth_frame_step2.jpg', depth_colormap)
                print('已保存 depth_frame_step2.jpg 以便验证（headless模式）')
                break
            else:
                cv2.imshow('RealSense CarryBot Vision', depth_colormap)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    finally:
        pipeline.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
