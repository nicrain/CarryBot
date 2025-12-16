#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =================================================================================================
#            ---          CarryBot - 楼梯检测系统          ---
# =================================================================================================
#
# ## 描述
# 该脚本是 CarryBot 感知系统的核心。它使用 Intel RealSense 摄像头通过分析深度数据流
# 来检测楼梯（上行和下行）和墙壁。
#
# ## 功能特性
# - **楼梯和墙壁检测**：实时分析深度数据流。
# - **多层级配置**：通过命令行参数、环境变量和 `config.json` 文件来管理参数。
# - **用于实时调参的HTTP服务器**：一个轻量级Web服务器，允许在不重启脚本的情况下实时查看和修改算法参数。
# - **配置热重载**：监视 `config.json` 文件的变化并立即应用。
# - **可视化**：在摄像头视频流上通过文本和矩形叠加层显示检测状态。
#
# =================================================================================================


# --- 1. 导入必要的库 ---
# -------------------------------------------------------------------------------------------------
# 每一个库的导入都在程序中扮演着特定的角色。

import argparse  # 用于解析在命令行中传递的参数 (例如: --config config.json)
import os        # 用于与操作系统交互，特别是读取环境变量
import json      # 用于读写 JSON 格式的文件 (我们的配置文件)
import time      # 提供与时间相关的功能, 比如 `sleep`
import threading # 允许在后台运行任务 (HTTP服务器和文件监视器)
import http.server # 用于创建简单Web服务器的模块
import socketserver  # 与 http.server 配合使用以管理网络连接

import cv2       # OpenCV: 用于图像处理的主要库
import numpy as np # NumPy: 对于数值计算，特别是矩阵(图像)运算，不可或缺
import pyrealsense2 as rs # Intel官方用于控制RealSense摄像头的库


# --- 2. 参数管理类 (ParamsHandler) ---
# -------------------------------------------------------------------------------------------------
# 这是一个非常重要的类，它集中管理所有的参数。
# 它实现了一套配置的层级结构：
# 优先级 1: 命令行参数 (例如: --roi_v_start 0.5)
# 优先级 2: 环境变量 (例如: CARRYBOT_ROI_V_START=0.5 python detect_stairs.py)
# 优先级 3: `config.json` 配置文件
# 优先级 4: 硬编码在类中的默认值

class ParamsHandler:
    """
    该类通过一个优先级层级来管理程序配置。
    """
    def __init__(self, default_params_path='config.json'):
        # 指向JSON配置文件的路径
        self.params_path = default_params_path
        
        # 用于存储从文件加载的参数的字典
        self.file_params = {}
        
        # 用于存储从环境变量加载的参数的字典
        self.env_params = {}
        
        # 用于存储从命令行加载的参数的字典
        self.cli_args = {}

        # 默认参数字典。这是在没有提供其他配置时的基础配置。
        self.defaults = {
            "roi_h_start": 0.2,       # 感兴趣区域(ROI)的水平起始位置 (占宽度的百分比)
            "roi_h_stop": 0.8,        # ROI的水平结束位置
            "roi_v_start": 0.3,       # ROI的垂直起始位置 (占高度的百分比)
            "roi_v_stop": 0.7,        # ROI的垂直结束位置
            "median_blur_ksize": 5,   # 中值滤波的核大小 (必须是奇数)
            "min_valid_dist": 0.1,    # 最小有效检测距离 (米) (忽略任何比这更近的物体)
            "max_valid_dist": 5.0,    # 最大有效检测距离 (米) (忽略任何比这更远的物体)
            "wall_dist_th": 0.8,      # 用于检测墙壁的距离阈值 (米)
            "step_height_th": 0.05,   # 用于检测台阶的高度阈值 (米)
            "noise_filtering_area_min_th": 1000 # 噪声过滤的最小面积阈值 (像素)
        }

    def load_from_file(self):
        """从JSON文件加载参数。"""
        try:
            with open(self.params_path, 'r') as f:
                self.file_params = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # 如果文件不存在或已损坏，我们从一个空字典开始
            self.file_params = {}

    def save_to_file(self):
        """将当前参数保存到JSON文件。"""
        # 我们保存一个合并后的参数版本，以确保文件始终是完整的
        merged_params = self.get_all_params()
        with open(self.params_path, 'w') as f:
            json.dump(merged_params, f, indent=4)

    def _load_from_env(self):
        """从环境变量加载参数。"""
        for key in self.defaults:
            # 构建环境变量的名称, 例如: "roi_h_start" -> "CARRYBOT_ROI_H_START"
            env_var = f"CARRYBOT_{key.upper()}"
            if env_var in os.environ:
                value = os.environ[env_var]
                # 尝试将值转换为数字 (float 或 int)
                try:
                    self.env_params[key] = float(value) if '.' in value else int(value)
                except ValueError:
                    # 忽略格式不正确的环境变量
                    pass

    def _load_from_cli_args(self, args):
        """从命令行参数加载参数。"""
        # `vars(args)` 将 argparse 的 `args` 对象转换为字典
        # 我们只保留用户明确提供的参数 (值不为None的)
        self.cli_args = {k: v for k, v in vars(args).items() if v is not None}

    def get(self, key):
        """
        遵循优先级层级来获取一个参数值。
        """
        # 优先级 1: 命令行
        if key in self.cli_args:
            return self.cli_args[key]
        # 优先级 2: 环境变量
        if key in self.env_params:
            return self.env_params[key]
        # 优先级 3: 配置文件
        if key in self.file_params:
            return self.file_params[key]
        # 优先级 4: 默认值
        return self.defaults.get(key)

    def get_all_params(self):
        """返回一个根据优先级合并后的所有参数的字典。"""
        # 我们从默认值开始，然后用更高优先级的配置层依次覆盖它们。
        all_params = self.defaults.copy()
        all_params.update(self.file_params)
        all_params.update(self.env_params)
        all_params.update(self.cli_args)
        return all_params
        
    def update_and_save(self, new_params):
        """从外部源(如HTTP服务器)更新参数并保存。"""
        # 我们更新'文件'层，因为通过API进行的修改
        # 必须持久化到JSON文件中。
        self.file_params.update(new_params)
        self.save_to_file()


# --- 3. 用于实时调参的HTTP服务器 ---
# -------------------------------------------------------------------------------------------------
# 这些类创建了一个在后台运行的小型Web服务器。
# 这个服务器有两个功能：
# - GET: 返回一个简单的网页 (或JSON格式的参数) 来可视化当前配置。
# - POST: 接受新的参数值以实时更新它们。

class HTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    用于HTTP请求的自定义处理器。
    """
    def __init__(self, *args, params_handler, **kwargs):
        # 我们存储一个对参数管理器的引用
        self.params_handler = params_handler
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """处理GET请求。"""
        if self.path == '/params':
            # 如果URL是/params，我们以JSON格式返回当前参数
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*') # 允许跨域请求
            self.end_headers()
            response = json.dumps(self.params_handler.get_all_params())
            self.wfile.write(response.encode('utf-8'))
        else:
            # 对于任何其他URL，我们返回一个基础的HTML页面
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """
            <html>
                <h1>CarryBot 实时调参</h1>
                <p>使用 GET /params 查看当前配置。</p>
                <p>使用 POST /params 并附带JSON数据来更新配置。</p>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))

    def do_POST(self):
        """处理POST请求。"""
        if self.path == '/params':
            # 读取请求体的大小
            content_length = int(self.headers['Content-Length'])
            # 读取请求体
            post_data = self.rfile.read(content_length)
            
            try:
                # 解码收到的JSON数据
                new_params = json.loads(post_data)
                
                # 将值转换为正确的类型 (int/float)
                for key, value in new_params.items():
                    if isinstance(value, (int, float)):
                       if key in self.params_handler.defaults:
                           original_type = type(self.params_handler.defaults[key])
                           new_params[key] = original_type(value)

                # 更新并保存参数
                self.params_handler.update_and_save(new_params)
                
                # 以成功状态响应
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')

            except (json.JSONDecodeError, ValueError) as e:
                # 处理JSON格式错误
                self.send_response(400) # Bad Request
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                error_msg = f'{{"status": "error", "message": "无效的JSON或值: {e}"}}'
                self.wfile.write(error_msg.encode('utf-8'))
        else:
            self.send_error(404, "File Not Found")
    
    def log_message(self, format, *args):
        """重载以使服务器静默。"""
        # 我们在这里什么都不做，以避免在控制台中显示HTTP日志
        pass

def start_http_server(params_handler, host='0.0.0.0', port=8080):
    """
    在一个单独的线程中启动HTTP服务器。
    """
    # 我们创建一个`handler_factory`函数，它可以将我们的`params_handler`
    # 传递给`HTTPRequestHandler`的构造函数。
    def handler_factory(*args, **kwargs):
        return HTTPRequestHandler(*args, params_handler=params_handler, **kwargs)

    # `with`确保服务器被正确关闭
    with socketserver.TCPServer((host, port), handler_factory) as httpd:
        print(f"实时调参服务器已启动于 http://{host}:{port}")
        # 服务器循环运行，直到主程序结束
        httpd.serve_forever()

def start_config_watcher(params_handler):
    """
    监视配置文件的变化并热重载它。
    在一个单独的线程中运行。
    """
    last_mtime = 0 # 存储文件的最后修改时间
    while True:
        try:
            # 获取当前的修改时间
            mtime = os.path.getmtime(params_handler.params_path)
            # 如果它比上次记录的要新...
            if mtime > last_mtime:
                last_mtime = mtime
                print("检测到 config.json 发生变化, 正在重新加载...")
                # ...我们就从文件中重新加载参数。
                params_handler.load_from_file()
        except FileNotFoundError:
            # 如果文件不存在，我们什么都不做
            last_mtime = 0
        
        # 我们等待一秒钟再重新检查
        time.sleep(1)


# --- 4. 主函数 (main) ---
# -------------------------------------------------------------------------------------------------
# 这里是所有逻辑被编排的地方。

def parse_args():
    """
    配置和解析命令行参数。
    """
    # 创建一个参数解析器
    parser = argparse.ArgumentParser(description="使用RealSense摄像头进行楼梯检测。 সন")
    
    # 添加一个参数来指定配置文件的路径
    parser.add_argument('--config', type=str, help='指向JSON配置文件的路径。')
    
    # 为每个参数添加参数项，允许直接从命令行覆盖它们。
    parser.add_argument('--roi_h_start', type=float)
    parser.add_argument('--roi_h_stop', type=float)
    parser.add_argument('--roi_v_start', type=float)
    parser.add_argument('--roi_v_stop', type=float)
    parser.add_argument('--median_blur_ksize', type=int)
    parser.add_argument('--min_valid_dist', type=float)
    parser.add_argument('--max_valid_dist', type=float)
    parser.add_argument('--wall_dist_th', type=float)
    parser.add_argument('--step_height_th', type=float)
    parser.add_argument('--noise_filtering_area_min_th', type=int)

    # 解析提供的参数并返回它们
    return parser.parse_args()


def main():
    """
    执行检测逻辑的主函数。
    """
    # --- 初始化 ---
    args = parse_args()
    
    # 创建我们的参数管理器实例
    # 如果在命令行中提供了config路径，我们就使用它
    params = ParamsHandler(default_params_path=args.config or 'config.json')

    # 按照正确的优先级顺序从所有来源加载参数
    params.load_from_file()
    params._load_from_env()
    params._load_from_cli_args(args)

    # 在一个后台线程中启动HTTP服务器
    # `daemon=True`意味着如果主程序退出，这个线程将自动停止
    http_thread = threading.Thread(target=start_http_server, args=(params,), daemon=True)
    http_thread.start()

    # 在另一个后台线程中启动配置文件监视器
    watcher_thread = threading.Thread(target=start_config_watcher, args=(params,), daemon=True)
    watcher_thread.start()

    # --- RealSense摄像头配置 ---
    pipeline = rs.pipeline()
    config = rs.config()
    
    # 配置视频流：深度和彩色
    # 注意：代码的其余部分只使用深度流，彩色流是可选的。
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

    print("\n--- 启动 CarryBot 视觉系统 ---")
    print("正在尝试连接 Intel RealSense 摄像头...")
    pipeline.start(config)
    print("连接成功！正在读取数据流...")
    print("(在显示窗口中按 'q' 键退出)\n")

    # --- 主处理循环 ---
    try:
        while True:
            # --- A. 图像采集 ---
            # 等待下一对图像 (深度 + 彩色)
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            color_frame = frames.get_color_frame()

            # 安全检查：如果任一图像缺失，我们跳过这次迭代
            if not depth_frame or not color_frame:
                continue

            # 将图像转换为NumPy数组，以便用OpenCV处理它们
            depth_image = np.asanyarray(depth_frame.get_data())
            color_image = np.asanyarray(color_frame.get_data())
            
            # 对深度图像应用颜色映射，使其对人眼可见
            depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)

            # --- B. 检测算法 ---
            
            # 1. 定义感兴趣区域 (ROI - Region of Interest)
            # 我们只处理图像的一部分，以提高效率并避免边缘噪声。
            h, w = depth_image.shape
            roi_x1 = int(w * params.get('roi_h_start'))
            roi_x2 = int(w * params.get('roi_h_stop'))
            roi_y1 = int(h * params.get('roi_v_start'))
            roi_y2 = int(h * params.get('roi_v_stop'))
            
            # 从深度图像中提取ROI
            roi = depth_image[roi_y1:roi_y2, roi_x1:roi_x2]

            # 2. ROI预处理
            # 应用中值滤波以减少噪声 (随机斑点)
            # 更大的核尺寸会更平滑，但可能会模糊细节。
            ksize = int(params.get('median_blur_ksize'))
            if ksize % 2 == 0: ksize += 1 # 核必须是奇数
            roi_filtered = cv2.medianBlur(roi, ksize)

            # 3. 检测逻辑
            # 我们创建一个有效像素的掩码。我们忽略太近、太远或为0(无测量值)的像素。
            valid_mask = (roi_filtered > params.get('min_valid_dist') * 1000) & \
                (roi_filtered < params.get('max_valid_dist') * 1000)
            
            # 如果少于10%的ROI是有效的，我们认为没有可靠的信息。
            if np.sum(valid_mask) < valid_mask.size * 0.1:
                is_wall = is_stairs_down = is_stairs_up = False
            else:
                # 计算ROI中有效像素的平均距离
                mean_dist_mm = np.mean(roi_filtered[valid_mask])
                
                # 决策 1: 墙壁检测
                # 如果平均距离小于墙壁阈值，我们认为正对着一堵墙。
                is_wall = mean_dist_mm < params.get('wall_dist_th') * 1000

                # 决策 2: 下行楼梯检测 (一个“洞”)
                # 我们寻找像素无效(距离=0)的水平条带。
                # 这可能表示一个洞或一个下行楼梯的开始。
                horizontal_projection = np.sum(valid_mask, axis=1) # 沿行求和
                # 如果一行的有效像素少于10%，我们认为它是“空的”
                empty_lines = np.where(horizontal_projection < roi.shape[1] * 0.1)[0]
                
                # 对“洞”检测进行噪声过滤
                if len(empty_lines) > 0:
                    # 我们创建一个“空”区域的二值图像
                    hole_mask = np.zeros_like(roi, dtype=np.uint8)
                    hole_mask[empty_lines, :] = 255
                    
                    # 我们使用连通组件分析来找到最大的空区域。
                    # 这允许我们忽略可能是噪声的小“洞”。
                    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(hole_mask, 4)
                    
                    if num_labels > 1:
                        # 我们忽略标签0，因为它是背景
                        largest_component_area = np.max(stats[1:, cv2.CC_STAT_AREA])
                        # 如果最大的洞区域是显著的，我们就检测到一个下行楼梯。
                        is_stairs_down = largest_component_area > params.get('noise_filtering_area_min_th')
                    else:
                        is_stairs_down = False
                else:
                    is_stairs_down = False

                # 决策 3: 上行楼梯检测
                # 我们计算ROI上半部分和下半部分的平均高度差
                mid_point = roi.shape[0] // 2
                top_half_mask = valid_mask[:mid_point, :]
                bottom_half_mask = valid_mask[mid_point:, :]

                if np.sum(top_half_mask) > 0 and np.sum(bottom_half_mask) > 0:
                    top_half_mean = np.mean(roi_filtered[:mid_point, :][top_half_mask])
                    bottom_half_mean = np.mean(roi_filtered[mid_point:, :][bottom_half_mask])
                    
                    # 如果下半部分明显比上半部分更近，那就是一个上行台阶。
                    height_diff_m = (top_half_mean - bottom_half_mean) / 1000.0
                    is_stairs_up = height_diff_m > params.get('step_height_th')
                else:
                    is_stairs_up = False

            # --- C. 可视化 ---
            # 我们在图像上绘制结果以进行调试。
            
            # 在彩色图像和深度颜色图上绘制一个矩形来显示ROI
            cv2.rectangle(color_image, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 2)
            cv2.rectangle(depth_colormap, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 2)

            # 准备要显示的文本
            status_text = "OK"
            status_color = (0, 255, 0) # 绿色
            if is_wall:
                status_text = "检测到墙壁"
                status_color = (0, 0, 255) # 红色
            elif is_stairs_down:
                status_text = "检测到下行楼梯"
                status_color = (0, 0, 255) # 红色
            elif is_stairs_up:
                status_text = "检测到上行楼梯"
                status_color = (0, 0, 255) # 红色
            
            # 在两个图像上显示状态
            cv2.putText(color_image, status_text, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, status_color, 2)
            cv2.putText(depth_colormap, status_text, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, status_color, 2)

            # 水平拼接两个图像以在单个窗口中显示它们
            images = np.hstack((color_image, depth_colormap))

            # 显示组合后的图像
            cv2.imshow('CarryBot 视觉 - 彩色 | 深度', images)

            # 等待键盘按键。如果是'q'，我们退出循环。
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

    except Exception as e:
        print(f"\n在主循环中发生错误: {e}")

    finally:
        # --- 清理工作 ---
        print("正在关闭视频流并释放资源...")
        pipeline.stop()
        cv2.destroyAllWindows()
        print("程序已终止。")


# --- 5. 脚本的入口点 ---
# -------------------------------------------------------------------------------------------------
# 这是Python的一个惯例。这个`if`块内的代码只有在文件被直接运行时
# (例如 `python detect_stairs.py`)才会执行, 
# 而在它被作为模块导入到另一个脚本中时则不会执行。
if __name__ == "__main__":
    main()
