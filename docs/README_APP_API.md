# CarryBot App 对接接口（视频流 + 运动控制）

> 目的：App 负责人可把本文直接交给 AI agent，实现“看视频 + 控制前后左右上下停止”。
>
> 约定：用 `<ROBOT_IP>` 表示树莓派/主控机在局域网内的 IP。

---

## 0. 网络与端口

- 手机/平板与机器人需在同一局域网（或能路由到机器人 IP）。
- 视觉视频流服务：`http://<ROBOT_IP>:8080`
- 电机控制服务：`http://<ROBOT_IP>:8090`

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

## 2. 控制：电机 HTTP API（Flask）

> 本服务把 HTTP JSON 请求转换为串口指令，再由 Arduino/控制板执行。

### 2.1 CORS / OPTIONS

- 服务端对所有响应添加：
  - `Access-Control-Allow-Origin: *`
  - `Access-Control-Allow-Headers: Content-Type`
  - `Access-Control-Allow-Methods: GET,POST,OPTIONS`
- 控制接口均支持 `OPTIONS` 预检（返回 `204`）。

### 2.2 健康检查

- **GET** `/health`
- **URL**：`http://<ROBOT_IP>:8090/health`
- **返回**：`{"ok": true|false}`
  - `ok=true`：串口已打开（电机板在线）

### 2.3 停止（急停）

- **POST** `/stop`
- **URL**：`http://<ROBOT_IP>:8090/stop`
- **请求体**：无要求（可不带 body）
- **返回**：`{"status":"ok"}`

### 2.4 前/后/左/右/停止（推荐：统一驾驶接口）

- **POST** `/drive`
- **URL**：`http://<ROBOT_IP>:8090/drive`
- **Content-Type**：`application/json`

请求 JSON（App 侧可极简，只传 action）：
- `action`：字符串（不区分大小写）
- `speed`：数值（可选；不传则服务端默认 `60`）

支持的 action：
- 前进：`forward` / `f`
- 后退：`backward` / `back` / `b`
- 左转（原地）：`left` / `l`
- 右转（原地）：`right` / `r`
- 停止：`stop` / `s`

返回：
- 成功：`200` + `{"status":"ok", ...}`
- action 不认识：`400` + `{"status":"error","message":"Unknown action: ..."}`

curl 示例：
```bash
curl -X POST http://<ROBOT_IP>:8090/drive \
  -H 'Content-Type: application/json' \
  -d '{"action":"forward"}'

curl -X POST http://<ROBOT_IP>:8090/drive \
  -H 'Content-Type: application/json' \
  -d '{"action":"left"}'

curl -X POST http://<ROBOT_IP>:8090/stop
```

### 2.5 上/下（爬楼机构：Tristar）

> App 里的“上/下”映射为 **三星轮机构转动方向**（不是 verin）。

推荐用同一个 `/drive` 接口实现上/下（App 不需要传 rpm，服务端默认 `20`）：

- 上：`POST /drive` `{"action":"up"}`
- 下：`POST /drive` `{"action":"down"}`
- 停止：`POST /stop`

如果需要直接控制 tristar（可选，不推荐给 MVP）：

- **POST** `/tristar`
- **URL**：`http://<ROBOT_IP>:8090/tristar`
- **请求 JSON**：`{"rpm": <number>}`（可选；不传则服务端默认 `20`）
- **返回**：`{"status":"ok","rpm":<rpm>}`

重要约束：
- tristar RPM 会被限幅到 **±86**（超过会被 clamp 到极限）。

curl 示例：
```bash
# 上（默认 20）
curl -X POST http://<ROBOT_IP>:8090/drive \
  -H 'Content-Type: application/json' \
  -d '{"action":"up"}'

# 下（默认 20）
curl -X POST http://<ROBOT_IP>:8090/drive \
  -H 'Content-Type: application/json' \
  -d '{"action":"down"}'

# 停止
curl -X POST http://<ROBOT_IP>:8090/stop
```

### 2.6 （可选）更底层的轮子控制

如果 App 需要更细粒度控制（例如弧线/差速），可用 `/wheels`：

- **POST** `/wheels`
- **URL**：`http://<ROBOT_IP>:8090/wheels`

两种请求格式：
1) 两轮同速：`{"rpm": 80}`
2) 左右独立：`{"left": -60, "right": 60}`

重要约束：
- 轮子 RPM 会被限幅到 **±185**。

---

## 3. 建议的 App 控制映射（MVP）

- 前：`POST /drive` `{"action":"forward"}`
- 后：`POST /drive` `{"action":"backward"}`
- 左：`POST /drive` `{"action":"left"}`
- 右：`POST /drive` `{"action":"right"}`
- 上：`POST /drive` `{"action":"up"}`
- 下：`POST /drive` `{"action":"down"}`
- 停止：`POST /stop`

默认速度（App 无需控制）：
- 行走：默认 `60`
- tristar：默认 `20`

---

## 4. 机器人端启动命令（部署用）

### 4.1 启动视频流（8080）

```bash
python detect_stairs.py
```

### 4.2 启动电机控制 API（8090）

```bash
python3 -m motor_control.motor_http_api --port 8090 --serial /dev/ttyUSB0
```

备注：
- 若不传 `--serial`，服务会尝试自动扫描串口；找不到会进入 simulation（不会真正控制电机）。
