# CarryBot 台阶检测参数指南

本文档详细介绍了 `detect_stairs.py` 脚本所使用的所有配置参数。

## 参数配置层级

程序按照以下优先级（由高到低）加载参数：
1. **命令行参数** (例如: `python detect_stairs.py --roi_h_start 0.5`)
2. **环境变量** (例如: `CARRYBOT_ROI_H_START=0.5 python detect_stairs.py`)
3. **配置文件** (`config.json`)
4. **默认值** (代码中硬编码的值)

## 参数列表

| 参数名 | 类型 | 默认值 | 描述 |
| :--- | :--- | :--- | :--- |
| **ROI (感兴趣区域) 设置** |
| `roi_h_start` | float | 0.2 | 水平方向 ROI 起始位置 (0.0 - 1.0)，占图像宽度的百分比。 |
| `roi_h_stop` | float | 0.8 | 水平方向 ROI 结束位置 (0.0 - 1.0)。 |
| `roi_v_start` | float | 0.3 | 垂直方向 ROI 起始位置 (0.0 - 1.0)，占图像高度的百分比。 |
| `roi_v_stop` | float | 0.7 | 垂直方向 ROI 结束位置 (0.0 - 1.0)。 |
| **图像预处理** |
| `median_blur_ksize` | int | 5 | 中值滤波核大小，必须是奇数。用于去除椒盐噪声。 |
| **距离过滤** |
| `min_valid_dist` | float | 0.1 | 最小有效距离 (米)。小于此距离的像素将被忽略。 |
| `max_valid_dist` | float | 5.0 | 最大有效距离 (米)。大于此距离的像素将被忽略。 |
| **检测阈值** |
| `wall_dist_th` | float | 0.8 | 墙壁检测阈值 (米)。如果 ROI 平均距离小于此值，则判定为墙壁。 |
| `step_height_th` | float | 0.05 | 台阶高度阈值 (米)。如果 ROI 上下半部分的平均高度差大于此值，判定为上行楼梯。 |
| `noise_filtering_area_min_th` | int | 1000 | 噪声过滤面积阈值 (像素数)。用于下行楼梯（空洞）检测，小于此面积的空洞被视为噪声。 |

## 实时调参 (HTTP API)

脚本启动了一个 HTTP 服务器（默认端口 **8080**），支持实时查看和修改参数。

### 查看当前参数
**GET** `/params`

```bash
curl http://localhost:8080/params
```

### 修改参数
**POST** `/params`
发送一个包含需要修改参数的 JSON 对象。修改后的参数会自动保存到 `config.json`。

```bash
curl -X POST -H "Content-Type: application/json" -d '{"roi_h_start": 0.3, "wall_dist_th": 1.0}' http://localhost:8080/params
```
