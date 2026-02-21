# Copilot Instructions for CarryBot (Stair Detection)

## 一句话概览
轻量、实时的楼梯/墙体检测脚本（`detect_stairs.py`），基于 Intel RealSense 深度相机，带有参数热加载和 HTTP 实时调参能力。

## 关键组件与数据流 🔧
- `detect_stairs.py`：主流程（RealSense pipeline → 获取深度/彩色帧 → ROI 提取 → 中值滤波/掩码 → 连通域/高度差决策 → 可视化/保存）。
- `ParamsHandler`：集中管理参数并实现优先级：**CLI > 环境变量 > config.json > defaults**。常用默认参数（在 `ParamsHandler.defaults` 内）：
  - `roi_h_start`: 0.2
  - `roi_h_stop`: 0.8
  - `roi_v_start`: 0.5
  - `roi_v_stop`: 1.0
  - `median_blur_ksize`: 5
  - `min_valid_dist`: 0.1
  - `max_valid_dist`: 5.0
  - `wall_dist_th`: 0.8
  - `step_height_th`: 0.05
  - `noise_filtering_area_min_th`: 1000
- HTTP 调参服务（`HTTPRequestHandler`）：GET/POST `/params`，默认端口 **8080**，POST 会调用 `ParamsHandler.update_and_save()` 持久化到 `config.json`。
- 配置热重载：`start_config_watcher()` 每秒检查 `config.json` 的修改时间并自动 `load_from_file()`。

## 运行、测试与 CI（短指引）
- 安装：`pip install -r requirements.txt -r requirements-dev.txt`（CI 使用 Python 3.11）。
- 本地运行：`python detect_stairs.py`（显示）
- 测试：`pytest -q`（关键测试在 `tests/test_config_and_api.py`、`tests/test_smoke.py`）。
- CI：`.github/workflows/ci.yml` 会运行 `black --check`, `flake8`, `pytest`。

## 项目约定 / 开发细节（重要）
- 环境变量：以 `CARRYBOT_` 为前缀（例如 `CARRYBOT_ROI_H_START`）；`ParamsHandler._load_from_env()` 将尝试解析为 int 或 float（基于是否包含小数点）。
- 配置文件：`config.json`（仓库根）现在使用与 `ParamsHandler.defaults` 匹配的小写键；`update_and_save()` 会保存合并后的参数到该文件。
- HTTP 服务静默：`HTTPRequestHandler.log_message` 被重写为空函数以避免控制台日志。
- 算法注意：README 中提到的一些参数（`EDGE_THRESH`, `SMOOTH_WINDOW`）在当前检测主流程中并未被引用——在修改或重新引入时请先核实用途。

## 如何为本项目写测试（要点）
- 单元测试偏向参数管理（不需要 RealSense 硬件）：参见 `tests/test_config_and_api.py`，它覆盖了文件加载、环境变量和 CLI 的优先级顺序。
- 集成测试建议：在一个线程中启动 HTTP 服务器（或直接调用 `HTTPRequestHandler`），对 `/params` 发 POST，然后断言 `config.json` 内容被正确写入。注意使用临时目录（`tmp_path`）以避免修改仓库根文件。

## 贡献流程（精确步骤）
1. 新参数：在 `ParamsHandler.defaults` 添加小写键并设置默认值。
2. CLI：在 `parse_args()` 中添加 `--<param-name>`（类型应与默认匹配）。
3. 文档：更新 `README_STAIR_PARAMS.md` 和 `README.md`（必要时同步端口说明）。
4. 测试：为新参数添加单元测试（覆盖 file/env/CLI 优先级及 `update_and_save()`）。
5. PR：保持格式化（`black`/`flake8`）并确保 CI 通过。