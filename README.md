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

性能优化建议
-----------
本系统专为**无头模式 (Headless Mode)** 设计。
为了获得最佳性能（更高的帧率、更低的延迟），建议将 Raspberry Pi 设置为 **CLI 启动模式**（不加载桌面环境）。

**设置方法：**
`sudo raspi-config` -> `System Options` -> `Boot / Auto Login` -> `Console Autologin`.

参数与调参
----------
- 所有参数的详细说明请参考 [README_STAIR_PARAMS.md](README_STAIR_PARAMS.md)。
- 推荐直接在 Web 控制台进行调参，修改会自动保存到 `config.json`。

文件一览
-------
- `detect_stairs.py`: 主程序（Web 服务器 + 检测算法）。
- `index.html`: Web 控制台的前端模板。
- `config.json`: 配置文件。
- `README_STAIR_PARAMS.md`: 参数详解文档。
- `tools/`: 辅助脚本目录。