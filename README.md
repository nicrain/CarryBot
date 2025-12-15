CarryBot — 台阶检测（RealSense 深度）
=================================

简介
----
这是一个用于 RealSense 深度相机的台阶检测脚本，面向机器人（CarryBot）平台：
- `detect_stairs.py` 包含检测算法（ROI、去噪、深度突变、连通域过滤、时序平滑等）；
- 支持 headless 验证（保存伪彩色深度帧）、参数化（环境变量/命令行）和实时调参（`config.json` + HTTP API）。

快速开始
--------
1. 安装依赖（示例）:

```bash
pip install numpy opencv-python pyrealsense2
```

2. 本地运行（有显示器）:

```bash
python detect_stairs.py
```

3. Headless（保存一帧图像用于调试）:

```bash
HEADLESS_TEST=1 python detect_stairs.py
```

参数与调参
----------
- 参考 `README_STAIR_PARAMS.md` 了解所有可调参数（环境变量、CLI 以及调参建议）。
- 可通过 `config.json` 热加载，或使用 HTTP API（默认端口 8000）实时设置：
  - GET /params
  - POST /params  (JSON body)

工具脚本
-------
- `tools/set_param.sh`：快速通过 HTTP 更新参数（可用 `SERVER`/`PORT` 覆盖目标地址）。
- `tools/test_server.sh`：测试 HTTP 服务并查看 `config.json`、`param_changes.log`。

调试和测试
---------
- 在无 GUI 环境下使用 `HEADLESS_TEST=1`，脚本会保存 `depth_frame_step2.jpg` 供离线查看。
- 在远程调参时，优先使用 `SERVER=127.0.0.1` 测试本机；在跨主机使用时指定机器人 IP，例如 `SERVER=192.168.10.212`。

文件一览
-------
- `detect_stairs.py` — 主脚本
- `README_STAIR_PARAMS.md` — 参数与调参说明
- `config.json` — 可选配置文件（脚本会读取并热加载）
- `tools/` — 帮助脚本

下一步
------
- 提交更多文档细节（安装/系统依赖、示例图像）
- 在仓库中添加 CI 测试或格式化脚本。
