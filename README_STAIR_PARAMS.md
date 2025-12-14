detect_stairs 参数说明

概述

这个项目包含一个用于 RealSense 深度摄像头的台阶检测脚本 `detect_stairs.py`。脚本运行时会处理深度图、检测深度突变并判定上/下台阶或墙体。为便于实地调参，关键参数可以通过环境变量或命令行参数覆盖。

参数（可调）

- ROI_WIDTH / ROI_HEIGHT (env) 或 `--roi-width` / `--roi-height` (CLI)
  - 中心感兴趣矩形的宽度和高度（像素）。默认：120

- EDGE_THRESH (env) 或 `--edge-thresh` (CLI)
  - 行梯度判定阈值（毫米）。检测深度突变时用到。默认：200

- ROW_NORM_THRESH (env) 或 `--row-norm-thresh` (CLI)
  - 行归一化阈值（0-1），用于从行突变中筛选显著行。默认：0.3

- MIN_COMPONENT_AREA / MIN_COMPONENT_HEIGHT (env) 或 `--min-area` / `--min-height` (CLI)
  - 连通域过滤最小面积/高度阈值，用于排除小噪点。默认：50, 2

- SMOOTH_WINDOW (env) 或 `--smooth-window` (CLI)
  - 时序平滑（滑动窗口）的窗口长度（帧数）。默认：5

- HEADLESS 测试模式：
  - 在无显示器环境下（如 SSH、Docker），设置 `HEADLESS_TEST=1` 或传 `--headless` 参数，脚本会保存一个调试图像（`depth_frame_step2.jpg`）并退出，便于离线查看。

快速使用示例

保存验证图像（headless）：

```bash
HEADLESS_TEST=1 python detect_stairs.py --roi-width 160 --smooth-window 3 --edge-thresh 150
```

在有显示器的本地运行（显示窗口）：

```bash
python detect_stairs.py
```

调参建议

1. 首先在多个典型场景（平地、上台阶、下台阶、靠墙）下用 `HEADLESS_TEST=1` 采集几帧图像并查看 `Front` 数值与高亮边缘。
2. 调整 `EDGE_THRESH` 和 `ROW_NORM_THRESH`，以获得稳定的边缘检测结果；调低阈值会更灵敏但噪声更多。
3. 根据机器人高度和摄像头安装角度调整 `ROI_WIDTH/HEIGHT` 与 `SMOOTH_WINDOW`，增加 `SMOOTH_WINDOW` 可减小瞬时抖动但会增加响应延迟。

支持的运行时调参方法

- 配置文件 `config.json`（示例见仓库根目录）
  - 脚本会在启动时读取 `config.json`（若存在），并在运行时监测该文件的修改，自动热加载参数。

- HTTP 实时调参
  - 启动时会自动尝试打开 HTTP 参数服务器（默认端口 `8000`）。
  - 获取当前参数：`GET http://<robot-ip>:8000/params`
  - 更新参数并持久化：`POST http://<robot-ip>:8000/params`，Body 为 JSON，例如：
    - `{ "EDGE_THRESH": 150, "ROI_WIDTH": 160 }`

示例命令（启动 HTTP 服务并测试）：

```bash
# 启动仅服务（不打开摄像头）以便调试
python detect_stairs.py --server-only

# 通过 curl 更新参数
curl -X POST http://192.168.10.212:8000/params -H 'Content-Type: application/json' -d '{"EDGE_THRESH":150}'

# 使用 helper 脚本（默认指向 192.168.10.212）
./tools/set_param.sh '{"EDGE_THRESH":150}'
```

便捷脚本

- `tools/set_param.sh`：封装 curl 的小脚本，方便快速调整参数，例如：

```bash
./tools/set_param.sh '{"EDGE_THRESH":150}'
```

参数变更日志

- 所有通过 HTTP 接口更新的参数会写入仓库根目录的 `param_changes.log`，包含时间戳和变更详情，便于审计和回溯。

如需我继续把 `config.json` 的示例加入仓库并写一段快速测试脚本，我可以接着做。