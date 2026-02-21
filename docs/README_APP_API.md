# CarryBot App 对接接口（视频流 + 运动控制）

> 目的：App 负责人可把本文直接交给 AI agent，实现“看视频 + 控制前后左右上下停止”。
>
> 约定：用 `<ROBOT_IP>` 表示树莓派/主控机在局域网内的 IP。

---

## 0. 网络与端口

- 手机/平板与机器人需在同一局域网（或能路由到机器人 IP）。
- 当前统一服务（视频 + 参数 + 电机控制）都在：`http://<ROBOT_IP>:8080`

---

## 1. 视觉：视频流（MJPEG）

### 1.1 获取视频流

- **GET** `/video_feed`
- **URL**：`http://<ROBOT_IP>:8080/video_feed`
- **响应类型**：`multipart/x-mixed-replace; boundary=frame`
- **每帧内容**：JPEG（`Content-Type: image/jpeg`）

备注：
- 当前实现的画面通常是“拼接帧”（彩色 + 深度伪彩并排）。如果 App 只需要彩色，可在客户端裁剪左半边显示。

---

## 2. 控制：HTTP API（集成在 detect_stairs）

### 2.1 CORS / OPTIONS

- 服务端对所有响应添加：
  - `Access-Control-Allow-Origin: *`
  - `Access-Control-Allow-Headers: Content-Type`
  - `Access-Control-Allow-Methods: GET,POST,OPTIONS`
- 控制接口均支持 `OPTIONS` 预检（返回 `204`）。

### 2.2 健康检查

- **GET** `/health`
- **URL**：`http://<ROBOT_IP>:8080/health`

### 2.3 停止（急停）

- **POST** `/stop`
- **URL**：`http://<ROBOT_IP>:8080/stop`
- **请求体**：无要求（可不带 body）
- **返回**：`{"status":"ok"}`

### 2.4 统一驾驶接口

- **POST** `/drive`
- **URL**：`http://<ROBOT_IP>:8080/drive`
- **Content-Type**：`application/json`

请求 JSON（App 侧可极简，只传 action）：
- `action`：字符串（不区分大小写）
- `speed`：数值（可选；不传则服务端默认 `60`）
- `rpm`：数值（可选；爬坡相关动作不传则默认 `20`）

常用 action：
- 前进：`forward` / `f`
- 后退：`backward` / `back` / `b`
- 左转：`left` / `l`
- 右转：`right` / `r`
- 停止：`stop` / `s`
- 爬坡上：`up` / `u`
- 台阶下：`down` / `d`

返回：
- 成功：`200` + `{"status":"ok", ...}`
- 错误：`4xx` + `{"status":"error"|"blocked", ...}`

curl 示例：
```bash
curl -X POST http://<ROBOT_IP>:8080/drive \
  -H 'Content-Type: application/json' \
  -d '{"action":"forward"}'

curl -X POST http://<ROBOT_IP>:8080/drive \
  -H 'Content-Type: application/json' \
  -d '{"action":"up"}'

curl -X POST http://<ROBOT_IP>:8080/stop
```

### 2.5 （可选）更底层轮子接口

- **POST** `/wheels`
- **URL**：`http://<ROBOT_IP>:8080/wheels`

两种请求格式：
1) 两轮同速：`{"rpm": 80}`
2) 左右独立：`{"left": -60, "right": 60}`

---

## 3. 机器人端启动命令（部署用）

```bash
python detect_stairs.py
```

备注：
- 电机 API 已集成在 `detect_stairs.py` 中，不再需要单独启动 `motor_http_api.py`。
