#include <MeMegaPi.h>
#include <Wire.h>
#include <MeGyro.h>
#include <MeUltrasonicSensor.h>
#include <ctype.h>
#include <math.h>
#include "MotorController.h"

// SLOT4 固定为第二个爬坡电机（Tristar2）
#define SLOT4_AS_TRISTAR2 1

// --- 外接 L293D 控制 verin（推杆/执行器）---
// 接线方案（单路 H-bridge）：
// - L293D Vcc1(pin16) -> MegaPi 5V
// - L293D Vcc2(pin8)  -> MegaPi V+
// - L293D GND(p4,p5,p12,p13) -> MegaPi GND（必须共地）
// - L293D OUT1(pin3) / OUT2(pin6) -> verin 两根线
// - L293D IN1(pin2) -> D23, IN2(pin7) -> D24, EN1,2(pin1) -> D25
// 说明：推杆不做 PWM 调速，只做方向全速开/关。
const uint8_t VERIN_IN1_PIN = 23;
const uint8_t VERIN_IN2_PIN = 24;
const uint8_t VERIN_EN_PIN  = 25;

static inline void verin_l293d_stop() {
  // Disable output (coast)
  digitalWrite(VERIN_EN_PIN, LOW);
  digitalWrite(VERIN_IN1_PIN, LOW);
  digitalWrite(VERIN_IN2_PIN, LOW);
}

static inline void verin_l293d_run_dir(int dir) {
  // dir: -1 / +1
  if (dir >= 0) {
    digitalWrite(VERIN_IN1_PIN, HIGH);
    digitalWrite(VERIN_IN2_PIN, LOW);
  } else {
    digitalWrite(VERIN_IN1_PIN, LOW);
    digitalWrite(VERIN_IN2_PIN, HIGH);
  }

  // Full speed enable (EN high)
  digitalWrite(VERIN_EN_PIN, HIGH);
}

// --- 硬件对象定义 ---
MeEncoderOnBoard Encoder_L(SLOT1);
MeEncoderOnBoard Encoder_R(SLOT2);
MeEncoderOnBoard Encoder_T(SLOT3);
MeEncoderOnBoard Encoder_T2(SLOT4);
MeGyro Gyro(PORT_6);
MeUltrasonicSensor Ultrasonic(PORT_7);

// --- 控制器实例 (PID 参数在这里调) ---
// 格式: MotorController(&Encoder, Kp, Ki, Kd, FeedForward, Reversed)
MotorController MotorL(&Encoder_L, 1.2, 0.6, 2.0, 30.0, false);
MotorController MotorR(&Encoder_R, 1.2, 0.6, 2.0, 30.0, true);
MotorController MotorT(&Encoder_T, 1.5, 0.5, 1.0, 40.0, false);

// 注意：你的安装方向导致 SLOT4 与 SLOT3 电机“机械方向相反”。
// 这里将 SLOT4 设为 reversed=true，让同一个目标 RPM 下两台电机最终“机械方向一致”。
MotorController MotorT2(&Encoder_T2, 1.5, 0.5, 1.0, 40.0, true);

// --- 全局参数 ---
float K_sync = 1.0;          // 左右轮同步系数
const int PID_INTERVAL = 20; // 控制周期 ms
const int IMU_INTERVAL = 500; // IMU output interval (ms)
const int ULTRA_INTERVAL = 100; // Ultrasonic interval (ms)
unsigned long lastTime = 0;
unsigned long lastImuTime = 0;
unsigned long lastUltraTime = 0;

// --- 推杆自动调平（外接 L293D，非 PWM）---
// 读取 Gyro 角度（deg），超出 deadband 时持续纠偏；回到 deadband 时停止。
// 注意：如果推杆物理方向与约定相反，用 verin_hw_reversed 统一反转。
bool verin_hw_reversed = false;
bool verin_level_enabled = true;
char verin_level_axis = 'x';
float verin_level_deadband_deg = 2.0; // deg
bool verin_level_reversed = false;
const int VERIN_LEVEL_INTERVAL = 500; // ms (2 Hz)
unsigned long lastVerinLevelTime = 0;

static inline int apply_verin_hw_dir(int dir) {
  return verin_hw_reversed ? -dir : dir;
}

static inline float get_gyro_axis_deg(char axis) {
  switch (axis) {
    case 'x': case 'X': return Gyro.getAngleX();
    case 'y': case 'Y': return Gyro.getAngleY();
    case 'z': case 'Z': return Gyro.getAngleZ();
    default: return Gyro.getAngleX();
  }
}

static inline void verin_output_stop() {
  verin_l293d_stop();
}

static inline void verin_output_set_manual_dir(int dir) {
  dir = (dir >= 0) ? 1 : -1;
  dir = apply_verin_hw_dir(dir);
  verin_l293d_run_dir(dir);
}

static inline void verin_output_set_autolevel_dir(int dir) {
  dir = (dir >= 0) ? 1 : -1;
  dir = apply_verin_hw_dir(dir);
  verin_l293d_run_dir(dir);
}

static inline void verin_level_stop() {
  verin_level_enabled = false;
  verin_output_stop();
}

// --- 实体 STOP 按钮 ---
// 适配类似 R16-503 的带灯按钮：
// - 两个“大脚”是开关触点（通常常开 NO）
// - 两个“小脚”标 + / - 是 LED（与 STOP 输入无关）
// 接线建议：开关触点一端接 GND，另一端接 STOP_BTN_PIN；用 INPUT_PULLUP。
// 如果有两个按钮实现同样 STOP：两个按钮的开关触点并联到同一个 STOP_BTN_PIN 与 GND。
const uint8_t STOP_BTN_PIN = 22;
bool stop_btn_reported_pressed = false;

// --- 上台阶步进辅助时序 ---
// 需求：爬坡时，前轴每转动 1/3（对应电机约 3 圈），
// 停止爬坡并让底盘前进 1 秒（m80），然后继续爬坡。
// 这里复用 T_TARGET_PULSES 作为“1/3”阈值。
bool t_seq_active = false;
bool t_rear_started = false;
long t_seq_start_pulse = 0;
float t_seq_target_rpm = 0;
bool t2_freewheel_mode = false;
bool t_step_assist_active = false;
unsigned long t_step_assist_start_ms = 0;

const float T_STEP_FORWARD_REQ_RPM = 80.0; // 等效串口指令 m80
const unsigned long T_STEP_FORWARD_MS = 1000;

static inline void clear_tristar_step_assist() {
  t_step_assist_active = false;
  t_step_assist_start_ms = 0;
}

static inline void apply_stop_all() {
  MotorL.reset();
  MotorR.reset();
  MotorT.reset();
  MotorT2.reset();
  t_seq_active = false;
  t_rear_started = false;
  t_seq_start_pulse = 0;
  t_seq_target_rpm = 0;
  clear_tristar_step_assist();

  verin_output_stop();
  verin_level_enabled = false;
}

static inline void apply_motion_stop() {
  // 停止底盘/爬坡电机，但不改变推杆自动调平开关状态。
  MotorL.reset();
  MotorR.reset();
  MotorT.reset();
  MotorT2.reset();
  t_seq_active = false;
  t_rear_started = false;
  t_seq_start_pulse = 0;
  t_seq_target_rpm = 0;
  clear_tristar_step_assist();
}

static inline void set_tristar2_freewheel_mode(bool enabled) {
  t2_freewheel_mode = enabled;
  if (enabled) {
    MotorT2.setTarget(0);
    MotorT2.writePWM(0);
    t_seq_active = false;
    t_rear_started = false;
    t_seq_start_pulse = 0;
    t_seq_target_rpm = 0;
    clear_tristar_step_assist();
  }
}

// --- T 电机自动触发参数 ---
const int T_PULSE_PER_REV = 8; // Encoder_T.setPulse
const int T_RATIO = 75;        // Encoder_T.setRatio (电机轴参数 / param moteur)
const float T_GEAR_RATIO = 9.0; // 8T:72T => 1:9 (motor:wheel)
const long T_TARGET_PULSES = (long)((T_PULSE_PER_REV * T_RATIO * T_GEAR_RATIO) / 3.0); // 轮轴 1/3 圈

// --- 中断函数 (必须写在这里) ---
void isr_L() { if(digitalRead(Encoder_L.getPortB()) == 0) Encoder_L.pulsePosMinus(); else Encoder_L.pulsePosPlus(); }
void isr_R() { if(digitalRead(Encoder_R.getPortB()) == 0) Encoder_R.pulsePosMinus(); else Encoder_R.pulsePosPlus(); }
void isr_T() { if(digitalRead(Encoder_T.getPortB()) == 0) Encoder_T.pulsePosMinus(); else Encoder_T.pulsePosPlus(); }
void isr_T2() { if(digitalRead(Encoder_T2.getPortB()) == 0) Encoder_T2.pulsePosMinus(); else Encoder_T2.pulsePosPlus(); }

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  Serial.println("CarryBot Motor Ctrl Ready");

  pinMode(VERIN_IN1_PIN, OUTPUT);
  pinMode(VERIN_IN2_PIN, OUTPUT);
  pinMode(VERIN_EN_PIN, OUTPUT);
  verin_l293d_stop();

  pinMode(STOP_BTN_PIN, INPUT_PULLUP);

  Gyro.begin();

  // 绑定中断
  attachInterrupt(Encoder_L.getIntNum(), isr_L, RISING);
  attachInterrupt(Encoder_R.getIntNum(), isr_R, RISING);
  attachInterrupt(Encoder_T.getIntNum(), isr_T, RISING);
  attachInterrupt(Encoder_T2.getIntNum(), isr_T2, RISING);

  // 设置减速比和脉冲数
  Encoder_L.setPulse(7); Encoder_L.setRatio(46);
  Encoder_R.setPulse(7); Encoder_R.setRatio(46);
  Encoder_T.setPulse(T_PULSE_PER_REV); Encoder_T.setRatio(T_RATIO);
  Encoder_T2.setPulse(T_PULSE_PER_REV); Encoder_T2.setRatio(T_RATIO);
  
  // 初始停止
  MotorL.reset(); MotorR.reset(); MotorT.reset();
  MotorT2.reset();
  verin_output_stop();
}

void loop() {
  // 0. 实体 STOP 按钮（防抖 + 电平触发）
  // INPUT_PULLUP: 未按下=HIGH，按下(短接到GND)=LOW
  bool stop_sample_pressed = (digitalRead(STOP_BTN_PIN) == LOW);

  // 紧急停：只要检测到 LOW，就立刻停（不等防抖）。
  // 这样即使串口持续有数据（while Serial.available 一直跑），也能立即刹车。
  if (stop_sample_pressed) {
    apply_stop_all();
    if (!stop_btn_reported_pressed) {
      Serial.println("STOP_BTN");
      stop_btn_reported_pressed = true;
    }
    return;
  } else {
    stop_btn_reported_pressed = false;
  }

  // 1. 读取串口指令
  // 限制每轮处理的命令数，避免被串口洪泛“饿死”其他逻辑（例如 STOP 按钮）。
  int cmd_budget = 8;
  while (Serial.available() > 0 && cmd_budget-- > 0) {
    // 串口处理期间也检查紧急停
    if (digitalRead(STOP_BTN_PIN) == LOW) {
      apply_stop_all();
      Serial.println("STOP_BTN");
      // 清空缓冲区，避免松开按钮后立刻又被历史命令启动
      while (Serial.available() > 0) (void)Serial.read();
      return;
    }

    char cmd = Serial.read();
    if (cmd > 32 && cmd < 127) { Serial.print("RX:"); Serial.write(cmd); Serial.println(); }

    switch (cmd) {
      case 'L': case 'l': { // 推杆自动调平开关: L1 开 / L0 关
        int en = Serial.parseInt();
        verin_level_enabled = (en != 0);
        if (!verin_level_enabled) {
          verin_output_stop();
        }
        Serial.print("VERIN_LEVEL:");
        Serial.println(verin_level_enabled ? 1 : 0);
        break;
      }
      case 'A': case 'a': { // 选择轴: Ax / Ay / Az
        char ax = 0;
        // 跳过可能的空白
        while (Serial.peek() == ' ' || Serial.peek() == '\t') (void)Serial.read();
        ax = (char)Serial.read();
        if (ax == 'x' || ax == 'X' || ax == 'y' || ax == 'Y' || ax == 'z' || ax == 'Z') {
          verin_level_axis = (char)tolower(ax);
          Serial.print("VERIN_AXIS:");
          Serial.println(verin_level_axis);
        } else {
          Serial.print("VERIN_AXIS_INVALID:");
          Serial.println((int)ax);
        }
        break;
      }
      case 'D': case 'd': { // deadband (deg): D3.0
        float v = Serial.parseFloat();
        if (v < 0) v = -v;
        verin_level_deadband_deg = v;
        Serial.print("VERIN_DEADBAND:");
        Serial.println(verin_level_deadband_deg);
        break;
      }
      case 'I': case 'i': { // 调平方向: I0 NORMAL / I1 REVERSED
        int v = Serial.parseInt();
        verin_level_reversed = (v != 0);
        Serial.print("VERIN_MODE:");
        Serial.println(verin_level_reversed ? "REVERSED" : "NORMAL");
        break;
      }
      case 'M': case 'm': { // 轮子移动 M30
        float req = Serial.parseFloat();
        // 约定：串口输入的正值表示“小车向前”。
        // 但在当前硬件接线/安装方向下，MegaPi 的正 PWM 对应小车后退，
        // 所以这里做一次全局符号翻转，保证 m100=前进，m-100=后退。
        float val = -req;
        MotorL.setTarget(val);
        MotorR.setTarget(val);
        clear_tristar_step_assist();
        Serial.print("SET_WHEELS_REQ:"); Serial.println(req);
        Serial.print("SET_WHEELS_APPLIED:"); Serial.println(val);
        break;
      }
      case 'B': case 'b': { // 左右轮分别控制: B<left_rpm> <right_rpm>
        float left_req = Serial.parseFloat();
        float right_req = Serial.parseFloat();
        // 同样约定：正值=前进；硬件层面需要全局符号翻转
        float left_val = -left_req;
        float right_val = -right_req;
        MotorL.setTarget(left_val);
        MotorR.setTarget(right_val);
        clear_tristar_step_assist();
        Serial.print("SET_WHEELS_LR_REQ:");
        Serial.print(left_req);
        Serial.print(",");
        Serial.println(right_req);
        Serial.print("SET_WHEELS_LR_APPLIED:");
        Serial.print(left_val);
        Serial.print(",");
        Serial.println(right_val);
        break;
      }
      case 'T': case 't': { // 爬楼 T20
        float val = Serial.parseFloat();
        set_tristar2_freewheel_mode(false);
        MotorT.setTarget(val);
        // 时序：启动时先前轴单独转 1/3，再启动后轴；之后进入步进辅助循环。
        if (val == 0) {
          MotorT2.setTarget(0);
          t_seq_active = false;
          t_rear_started = false;
          t_seq_start_pulse = 0;
          t_seq_target_rpm = 0;
          clear_tristar_step_assist();
        } else {
          t_seq_target_rpm = val;
          clear_tristar_step_assist();
          if (!t_seq_active) {
            t_seq_active = true;
            t_rear_started = false;
            t_seq_start_pulse = Encoder_T.getPulsePos();
            MotorT2.setTarget(0);
            Serial.println("TRI_SEQ_START_FRONT");
          } else {
            MotorT2.setTarget(t_rear_started ? val : 0);
          }
        }
        Serial.print("SET_TRISTAR:"); Serial.println(val);
        break;
      }

      case 'F': case 'f': { // 前轴爬坡电机（SLOT3）单独控制: F20
        float val = Serial.parseFloat();
        MotorT.setTarget(val);
        // 独立控制时关闭双电机时序
        t_seq_active = false;
        t_rear_started = false;
        t_seq_start_pulse = 0;
        t_seq_target_rpm = 0;
        clear_tristar_step_assist();
        Serial.print("SET_TRISTAR_FRONT:"); Serial.println(val);
        break;
      }

      case 'R': case 'r': { // 后轴爬坡电机（SLOT4）单独控制: R20
        float val = Serial.parseFloat();
        set_tristar2_freewheel_mode(false);
        MotorT2.setTarget(val);
        // 独立控制时关闭双电机时序
        t_seq_active = false;
        t_rear_started = false;
        t_seq_start_pulse = 0;
        t_seq_target_rpm = 0;
        clear_tristar_step_assist();
        Serial.print("SET_TRISTAR_REAR:"); Serial.println(val);
        break;
      }
      case 'Y': case 'y': { // Tristar2 freewheel mode: Y1/Y0
        int en = Serial.parseInt();
        set_tristar2_freewheel_mode(en != 0);
        Serial.print("TRI2_FREEWHEEL:");
        Serial.println(t2_freewheel_mode ? 1 : 0);
        break;
      }
      case 'V': case 'v': {
        // 推杆控制（外接 L293D）：V>0 一个方向 / V<0 另一个方向 / V0 停止（不做 PWM）
        // 手动推杆优先：收到 V 指令就关闭自动调平
        verin_level_enabled = false;
        int val = Serial.parseInt();
        if (val == 0) {
          verin_output_stop();
        } else {
          verin_output_set_manual_dir(val > 0 ? 1 : -1);
        }
        Serial.print("SET_VERIN:"); Serial.println(val);
        break;
      }
      case 'S': case 's': { // 停止 S
        apply_motion_stop();
        Serial.println("STOP");
        break;
      }
    }
  }

  // 1.5 推杆自动调平（外接 L293D，持续纠偏）
  if (verin_level_enabled && (millis() - lastVerinLevelTime > VERIN_LEVEL_INTERVAL)) {
    lastVerinLevelTime = millis();
    float angle = get_gyro_axis_deg(verin_level_axis);
    if (abs(angle) > verin_level_deadband_deg) {
      // NORMAL: 角度为正时用 +1 方向纠偏；REVERSED 反过来。
      int dir = (angle > 0) ? 1 : -1;
      if (verin_level_reversed) dir = -dir;
      verin_output_set_autolevel_dir(dir);
    } else {
      verin_output_stop();
    }
  }

  // 2. 刷新编码器状态
  Encoder_L.loop(); Encoder_R.loop(); Encoder_T.loop();
  Encoder_T2.loop();
  Gyro.update();

  // 2.5 超声波测距上报（仅遥测，不再自动触发电机动作）
  if (millis() - lastUltraTime > ULTRA_INTERVAL) {
    lastUltraTime = millis();
    double dist_cm = Ultrasonic.distanceCm();
    if (dist_cm > 0 && dist_cm < 400) {
      Serial.print("ULTRA:");
      Serial.println(dist_cm);
    }
  }

  // 2.8 上台阶时序：首次前轴 1/3 后启动后轴；随后每 1/3 进行一次步进辅助
  if (t_seq_active && !t2_freewheel_mode && t_seq_target_rpm != 0) {
    long delta_pulse = labs(Encoder_T.getPulsePos() - t_seq_start_pulse);

    // 阶段1：刚开始上台阶，前轴先转 1/3，再启动后轴
    if (!t_rear_started) {
      if (delta_pulse >= T_TARGET_PULSES) {
        MotorT2.setTarget(t_seq_target_rpm);
        t_rear_started = true;
        t_seq_start_pulse = Encoder_T.getPulsePos();
        Serial.println("TRI_SEQ_START_REAR");
      }
    }

    // 阶段2：后轴已启动后，执行“1/3 -> 前进1秒 -> 恢复爬坡”循环
    if (t_rear_started && !t_step_assist_active && delta_pulse >= T_TARGET_PULSES) {
      // 停止爬坡轴
      MotorT.setTarget(0);
      MotorT2.setTarget(0);

      // 轮子前进 1 秒：等效 m80（M 命令内部会做符号翻转）
      MotorL.setTarget(-T_STEP_FORWARD_REQ_RPM);
      MotorR.setTarget(-T_STEP_FORWARD_REQ_RPM);

      t_step_assist_active = true;
      t_step_assist_start_ms = millis();
      Serial.println("TRI_STEP_ASSIST_FORWARD");
    }

    if (t_step_assist_active && (millis() - t_step_assist_start_ms >= T_STEP_FORWARD_MS)) {
      // 结束前进脉冲并恢复爬坡
      MotorL.setTarget(0);
      MotorR.setTarget(0);
      MotorT.setTarget(t_seq_target_rpm);
      MotorT2.setTarget(t_seq_target_rpm);
      t_seq_start_pulse = Encoder_T.getPulsePos();
      clear_tristar_step_assist();
      Serial.println("TRI_STEP_ASSIST_RESUME");
    }
  }

  // 3. 定时 PID 计算
  if (millis() - lastTime > PID_INTERVAL) {
    lastTime = millis();

    // 计算基础 PWM
    float pwmL = MotorL.computePWM();
    float pwmR = MotorR.computePWM();
    float pwmT = MotorT.computePWM();
    float pwmT2 = MotorT2.computePWM();

    // 左右轮同步纠偏 (仅在直线行驶时)
    if (abs(MotorL.targetSpeed) > 5.0 && MotorL.targetSpeed == MotorR.targetSpeed) {
        float speedDiff = MotorL.currentSpeed - MotorR.currentSpeed;
        pwmL -= speedDiff * K_sync;
        pwmR += speedDiff * K_sync;
    }

    // 写入电机
    MotorL.writePWM(pwmL);
    MotorR.writePWM(pwmR);
    MotorT.writePWM(pwmT);
    if (t2_freewheel_mode) {
      MotorT2.writePWM(0);
    } else {
      MotorT2.writePWM(pwmT2);
    }

    // 4. 定期发送调试信息 (每 100ms 一次)
    static int debugCount = 0;
    if (debugCount++ > 5) {
      debugCount = 0;
      Serial.print("T:"); Serial.print(MotorL.targetSpeed);
      Serial.print(" L:"); Serial.print(MotorL.currentSpeed);
      Serial.print(" R:"); Serial.print(MotorR.currentSpeed);
      Serial.print(" Tri:"); Serial.print(MotorT.currentSpeed);
      Serial.print(" Tri2:"); Serial.print(MotorT2.currentSpeed);
      
      if (MotorL.isStalled || MotorR.isStalled || MotorT.isStalled
          || MotorT2.isStalled
      ) {
        Serial.print(" !!STALLED!!");
      }
      Serial.println();
    }
  }

  // 5. IMU output (roll/pitch/yaw angles)
  if (millis() - lastImuTime > IMU_INTERVAL) {
    lastImuTime = millis();
    Serial.print("IMU:");
    Serial.print(Gyro.getAngleX());
    Serial.print(",");
    Serial.print(Gyro.getAngleY());
    Serial.print(",");
    Serial.println(Gyro.getAngleZ());
  }
}
