# 导入 pyrealsense2 库，这是与 RealSense 摄像头交互的官方 Python 封装
import pyrealsense2 as rs
import time

def main():
    # 1. 创建管道 (pipeline)，它是管理摄像头数据流的核心对象
    pipeline = rs.pipeline()
    config = rs.config()

    # 2. 配置数据流
    # 我们需要深度 (Depth) 数据流
    # 分辨率: 640x480
    # 格式: Z16 (16位无符号整数)，这是深度数据的标准格式
    # 帧率: 30 帧/秒 (fps)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

    try:
        print("--- 启动 CarryBot 视觉系统 ---")
        print("正在尝试连接 Intel RealSense 摄像头...")
        
        # 3. 启动摄像头
        # pipeline.start() 会根据配置打开摄像头并开始传输数据
        pipeline.start(config)
        print("连接成功！正在读取数据流...")
        print("(按 Ctrl+C 结束程序)\n")

        # 4. 进入主循环，持续获取图像
        while True:
            # a. 等待下一组数据帧 (此操作是阻塞性的，直到有新帧为止)
            frames = pipeline.wait_for_frames()
            
            # b. 从数据帧中获取深度图
            depth_frame = frames.get_depth_frame()

            # c. 安全检查：如果深度图不存在，则跳过此次循环
            if not depth_frame:
                continue

            # 5. 测量距离
            # a. 获取图像的宽度和高度
            width = depth_frame.get_width()
            height = depth_frame.get_height()
            
            # b. get_distance(x, y) 函数返回指定像素点离摄像头的真实距离，单位是米 (meters)
            # 我们测量图像中心点 (width // 2, height // 2) 的距离
            dist = depth_frame.get_distance(width // 2, height // 2)

            # 6. 显示结果
            # 如果距离为 0.000，通常意味着物体 "太近" 或 "太远"，超出了摄像头的有效测量范围
            if dist == 0:
                print("中心点距离: 超出有效范围 (或太近)")
            else:
                # 使用 f-string 格式化输出，保留3位小数
                print(f"中心点距离: {dist:.3f} 米")

            # 短暂休眠，让人眼可以看清连续的输出
            time.sleep(0.1)

    except KeyboardInterrupt:
        # 处理用户通过 Ctrl+C 发出的中断请求
        print("\n检测到手动中断。")

    except Exception as e:
        # 处理所有其他预料之外的错误 (例如摄像头被拔出)
        print(f"\n发生未知错误: {e}")

    finally:
        # 7. 至关重要的清理工作
        # 必须停止 pipeline 来释放摄像头资源。
        # 如果不这样做，摄像头会被程序锁定，下次运行时可能需要重新插拔USB才能被识别。
        print("正在关闭数据流并释放资源...")
        try:
            pipeline.stop()
        except:
            # 如果 pipeline 已经因为错误而停止，再次调用 stop() 可能报错，所以这里也用 try...except 包裹
            pass
        print("程序已安全退出。")

# Python 的标准入口点检查
# 确保 main() 函数只在直接运行此脚本时执行
if __name__ == "__main__":
    main()