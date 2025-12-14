import pyrealsense2 as rs
import time

try:
    # 创建管道
    pipeline = rs.pipeline()
    config = rs.config()

    # 启用深度流 (640x480 分辨率, 30fps)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

    # 开始采集
    print("正在尝试连接相机...")
    pipeline.start(config)
    print("相机连接成功！")

    # 循环读取 10 帧数据
    for i in range(10):
        frames = pipeline.wait_for_frames()
        depth_frame = frames.get_depth_frame()

        if not depth_frame:
            continue

        # 获取画面中心点的距离 (320, 240)
        dist = depth_frame.get_distance(320, 240)
        print(f"第 {i+1} 帧 - 中心点距离: {dist:.3f} 米")
        time.sleep(0.5)

except Exception as e:
    print(f"发生错误: {e}")
finally:
    # 记得关闭管道，否则下次运行可能报错
    print("正在关闭相机...")
    try:
        pipeline.stop()
    except:
        pass
