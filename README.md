CarryBot — 台阶检测系统 (Web 控制台版)
=====================================

简介
----
CarryBot 是一个用于 RealSense 深度相机的智能感知系统。
核心脚本 `detect_stairs.py` 能够实时检测：
- **上行楼梯** (Stairs Up)
- **下行楼梯/空洞** (Stairs Down)
- **墙壁** (Walls)

**主要特性：**
- **Web 视频流**: 无需本地显示器，直接通过浏览器监控实时画面（MJPEG流）。
- **交互式控制台**: 视频下方集成控制面板，可实时调整算法参数。
- **纯后台运行**: 设计为 Headless 模式，完美适配 Raspberry Pi CLI 环境。
- **配置热重载**: 支持 `config.json` 自动重载。

快速开始
--------
1. **安装依赖**:
   ```bash
   pip install -r requirements.txt
   ```

2. **运行系统**:
   ```bash
   python detect_stairs.py
   ```
   *建议在 `tmux` 或 `screen` 中运行，以便断开 SSH 后保持后台运行。*

3. **访问控制台**:
   打开浏览器访问：`http://<树莓派IP>:8080`

电机指令快速发送（Pi 上类似 Arduino 串口监视器）
---------------------------------------------

如果你想在树莓派上像 Arduino IDE Serial Monitor 一样手动发送 `v100` / `m20` / `s` 指令，可以用：

```bash
python3 tools/serial_console.py --port /dev/ttyUSB0
```

- 输入命令后按回车发送（例如 `v100`、`m20`）
- 输入为空时按 `s` 或空格可立即 Stop
- 默认会隐藏固件周期性的遥测刷屏（如 `T:... L:...`）；需要时加 `--show-telemetry` 或 `--all`

性能优化建议
-----------
本系统专为**无头模式 (Headless Mode)** 设计。
为了获得最佳性能（更高的帧率、更低的延迟），建议将 Raspberry Pi 设置为 **CLI 启动模式**（不加载桌面环境）。

**设置方法：**
`sudo raspi-config` -> `System Options` -> `Boot / Auto Login` -> `Console Autologin`.

参数与调参
----------
- 所有参数的详细说明请参考 [README_STAIR_PARAMS.md](docs/README_STAIR_PARAMS.md)。
- 推荐直接在 Web 控制台进行调参，修改会自动保存到 `config/config.json`。

文件一览

-------

- `detect_stairs.py`: 主程序（Web 服务器 + 检测算法）。

- `web/`: Web 资源（包含前端模板 `index.html`）。

- `config/`: 配置文件目录。

- `docs/`: 文档目录（参数说明等）。

- `motor_control/`: 电机控制核心。

  - `motor_control.ino`: Arduino 固件。

  - `motor_driver.py`: Python 驱动（支持 cm/s 速度控制）。

- `tests/`: 测试脚本（运行 `python tests/test_move.py` 测试电机）。

- `tools/`: 辅助脚本目录。



电机控制 (Motor Control)

------------------------

系统采用 **上位机 (Python) + 下位机 (Arduino)** 架构：

1.  **Arduino**: 运行 PID 闭环控制、堵转保护和同步纠偏。

2.  **Python**: 通过 `MotorDriver` 类发送指令。支持 **直观模式 (cm/s)** 和 **专家模式 (RPM)**。




- **轮式移动 (Slot 1 & 2)**: 负责平地移动与转向。
  - 电机：25mm DC Encoder Motor, 185rpm, 减速比 1:46。
- **三星轮机构 (Slot 3)**: 负责爬楼梯。
  - 电机：25mm DC Encoder Motor, 86rpm, 减速比 1:75 (提供更大扭矩)。
- **平台调平 (Stabilization)**: 使用 12V 线性编码电缸（通过 L293N 驱动）实时调整托盘倾角。
- **感知反馈**: 
  - **IMU**: 监测机器人姿态，用于托盘自动调平。
  - **超声波传感器**: 4路超声波用于近距离避障。
- **控制逻辑**: 基于 PID 的速度闭环控制，并包含左右轮同步纠偏算法。
