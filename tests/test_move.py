import sys
import os
import time

if __name__ != "__main__":
    try:
        import pytest

        pytest.skip("Hardware motor demo (not a unit test)", allow_module_level=True)
    except Exception:
        pass

# 将项目根目录添加到 Python 路径，确保能找到 motor_control 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_control.motor_driver import MotorDriver

def main():
    # 1. 初始化驱动 (自动搜索串口并握手)
    print("--- 正在初始化 CarryBot 电机驱动 ---")
    driver = MotorDriver()

    try:
        # --- 模式 1: 直观模式 (线速度 cm/s) ---
        # 这种模式下，你会发现车跑得比较慢，因为它考虑了所有减速比和轮径
        print("\n>>> [1/2] 模式：直观模式")
        print(">>> 动作：以 5.0 cm/s 的速度前进 3 秒")
        driver.move_wheels_cmps(5.0) 
        time.sleep(3)

        print(">>> 停止 1 秒")
        driver.stop()
        time.sleep(1)

        # --- 模式 2: 专家模式 (旋转速度 RPM) ---
        # 这种模式下，你直接控制电机输出轴的转速
        # 100 RPM 大约是 5 cm/s 的两倍多
        print("\n>>> [2/2] 模式：专家模式")
        print(">>> 动作：以 100 RPM 的转速前进 3 秒")
        driver.move_wheels(100)
        time.sleep(3)

        print("\n>>> 测试完成！正在归位...")
        driver.stop()
        time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[!] 用户中断测试")
    except Exception as e:
        print(f"\n[!] 发生错误: {e}")
    finally:
        # 彻底关闭串口并释放资源
        driver.close()
        print("--- 驱动已关闭 ---")

if __name__ == "__main__":
    main()
