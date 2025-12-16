CarryBot — 台阶检测（RealSense 深度）
=================================

简介
----
这是一个用于 RealSense 深度相机的台阶检测脚本，面向机器人（CarryBot）平台：
- `detect_stairs.py` 包含检测算法（ROI、中值滤波、深度阈值判断、连通域过滤）；
- 支持参数化（环境变量/命令行）和实时调参（`config.json` + HTTP API）。

快速开始
--------
1. 安装依赖（示例）:

```bash
pip install numpy opencv-python pyrealsense2
```

2. 运行脚本:

```bash
python detect_stairs.py
```

参数与调参
----------
- 参考 `README_STAIR_PARAMS.md` 了解所有可调参数（环境变量、CLI 以及调参建议）。
- 可通过 `config.json` 热加载，或使用 HTTP API（默认端口 8080）实时设置：
  - GET /params
  - POST /params  (JSON body)

工具脚本
-------
- `tools/set_param.sh`：快速通过 HTTP 更新参数。
- `tools/test_server.sh`：测试 HTTP 服务。

调试和测试
---------
- 脚本运行时会开启 HTTP 服务器（默认端口 8080），可用于实时调整参数。
- 配置文件 `config.json` 支持热重载，修改文件后脚本会自动应用新参数。

文件一览
-------
- `detect_stairs.py` — 主脚本
- `README_STAIR_PARAMS.md` — 参数与调参说明
- `config.json` — 配置文件
- `tools/` — 帮助脚本