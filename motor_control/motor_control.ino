#include <MeMegaPi.h>
#include <Wire.h>
#include <MeGyro.h>
#include <MeUltrasonicSensor.h>
#include <ctype.h>
#include <math.h>
#include "MotorController.h"

// --- 硬件对象定义 ---
MeEncoderOnBoard Encoder_L(SLOT1);
MeEncoderOnBoard Encoder_R(SLOT2);
MeEncoderOnBoard Encoder_T(SLOT3);
MeEncoderOnBoard VerinMotor(SLOT4); // 推杆/执行器 (PWM)
MeGyro Gyro(PORT_6);
MeUltrasonicSensor Ultrasonic(PORT_7);

// --- 控制器实例 (PID 参数在这里调) ---
// 格式: MotorController(&Encoder, Kp, Ki, Kd, FeedForward, Reversed)
MotorController MotorL(&Encoder_L, 1.2, 0.6, 2.0, 30.0, false);
MotorController MotorR(&Encoder_R, 1.2, 0.6, 2.0, 30.0, true);
MotorController MotorT(&Encoder_T, 1.5, 0.5, 1.0, 40.0, false);

// --- 全局参数 ---
float K_sync = 1.0;          // 左右轮同步系数
const int PID_INTERVAL = 20; // 控制周期 ms
const int IMU_INTERVAL = 500; // IMU output interval (ms)
const int ULTRA_INTERVAL = 100; // Ultrasonic interval (ms)
unsigned long lastTime = 0;
unsigned long lastImuTime = 0;
unsigned long lastUltraTime = 0;

// --- 推杆自动调平（板上闭环）---
// 基于 Gyro.getAngleX/Y/Z（单位：deg），输出 VerinMotor PWM（-255~255）。
// 注意：如果推杆物理方向与约定相反（V100 变成收回），用 verin_hw_reversed 统一反转。
bool verin_hw_reversed = false;
bool verin_level_enabled = true;
char verin_level_axis = 'x';
float verin_level_deadband_deg = 2.0; // deg
float verin_level_kp = 20.0;          // PWM per deg
int verin_level_pwm_max = 150;        // PWM limit
int verin_level_pwm_step = 5;         // 最小 PWM 变化才重发
// 调平方向：默认 NORMAL（与当前机械/安装方向匹配）。
// 如需反向，可切换到 REVERSED。
bool verin_level_reversed = false;
const int VERIN_LEVEL_INTERVAL = 500; // ms (2 Hz)
unsigned long lastVerinLevelTime = 0;
int last_verin_pwm_sent = 0;

static inline int apply_verin_hw_dir(int pwm_cmd) {
  return verin_hw_reversed ? -pwm_cmd : pwm_cmd;
}

static inline void write_verin_pwm_cmd(int pwm_cmd) {
  pwm_cmd = constrain(pwm_cmd, -255, 255);
  VerinMotor.setMotorPwm(apply_verin_hw_dir(pwm_cmd));
  last_verin_pwm_sent = pwm_cmd;
}

static inline float get_gyro_axis_deg(char axis) {
  switch (axis) {
    case 'x': case 'X': return Gyro.getAngleX();
    case 'y': case 'Y': return Gyro.getAngleY();
    case 'z': case 'Z': return Gyro.getAngleZ();
    default: return Gyro.getAngleX();
  }
}

static inline void verin_level_stop() {
  verin_level_enabled = false;
  write_verin_pwm_cmd(0);
}

// --- 实体 STOP 按钮 ---
// 适配类似 R16-503 的带灯按钮：
// - 两个“大脚”是开关触点（通常常开 NO）
// - 两个“小脚”标 + / - 是 LED（与 STOP 输入无关）
// 接线建议：开关触点一端接 GND，另一端接 STOP_BTN_PIN；用 INPUT_PULLUP。
// 如果有两个按钮实现同样 STOP：两个按钮的开关触点并联到同一个 STOP_BTN_PIN 与 GND。
const uint8_t STOP_BTN_PIN = 22;
bool stop_btn_reported_pressed = false;

static inline void apply_stop_all() {
  MotorL.reset();
  MotorR.reset();
  MotorT.reset();
  write_verin_pwm_cmd(0);
  verin_level_enabled = false;
}

// --- T 电机自动触发参数 ---
const int T_PULSE_PER_REV = 8; // Encoder_T.setPulse
const int T_RATIO = 75;        // Encoder_T.setRatio (电机轴参数 / param moteur)
const float T_GEAR_RATIO = 9.0; // 8T:72T => 1:9 (motor:wheel)
const long T_TARGET_PULSES = (long)((T_PULSE_PER_REV * T_RATIO * T_GEAR_RATIO) / 3.0); // 轮轴 1/3 圈
const float T_AUTO_RPM = 20.0; // 自动触发速度
const double ULTRA_TRIGGER_CM = 5.0;
const double ULTRA_RESET_CM = 6.0; // 简单迟滞，防止抖动
bool t_auto_active = false;
bool t_auto_armed = true;
long t_start_pulse = 0;

// --- 中断函数 (必须写在这里) ---
void isr_L() { if(digitalRead(Encoder_L.getPortB()) == 0) Encoder_L.pulsePosMinus(); else Encoder_L.pulsePosPlus(); }
void isr_R() { if(digitalRead(Encoder_R.getPortB()) == 0) Encoder_R.pulsePosMinus(); else Encoder_R.pulsePosPlus(); }
void isr_T() { if(digitalRead(Encoder_T.getPortB()) == 0) Encoder_T.pulsePosMinus(); else Encoder_T.pulsePosPlus(); }

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  Serial.println("CarryBot Motor Ctrl Ready");

  pinMode(STOP_BTN_PIN, INPUT_PULLUP);

  Gyro.begin();

  // 绑定中断
  attachInterrupt(Encoder_L.getIntNum(), isr_L, RISING);
  attachInterrupt(Encoder_R.getIntNum(), isr_R, RISING);
  attachInterrupt(Encoder_T.getIntNum(), isr_T, RISING);

  // 设置减速比和脉冲数
  Encoder_L.setPulse(7); Encoder_L.setRatio(46);
  Encoder_R.setPulse(7); Encoder_R.setRatio(46);
  Encoder_T.setPulse(T_PULSE_PER_REV); Encoder_T.setRatio(T_RATIO);
  // 推杆通常没有编码器反馈，这里只需要确保 PWM 输出可用
  VerinMotor.setPulse(7);
  VerinMotor.setRatio(46);
  
  // 初始停止
  MotorL.reset(); MotorR.reset(); MotorT.reset();
  write_verin_pwm_cmd(0);
}

void loop() {
  // 0. 实体 STOP 按钮（防抖 + 电平触发）
  // INPUT_PULLUP: 未按下=HIGH，按下(短接到GND)=LOW
  bool stop_sample_pressed = (digitalRead(STOP_BTN_PIN) == LOW);

  // 紧急停：只要检测到 LOW，就立刻停（不等防抖）。
  // 这样即使串口持续有数据（while Serial.available 一直跑），也能立即刹车。
  if (stop_sample_pressed) {
    apply_stop_all();
    t_auto_active = false;
    t_auto_armed = true;
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
      t_auto_active = false;
      t_auto_armed = true;
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
          write_verin_pwm_cmd(0);
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
      case 'K': case 'k': { // Kp (PWM/deg): K20
        float v = Serial.parseFloat();
        verin_level_kp = v;
        Serial.print("VERIN_KP:");
        Serial.println(verin_level_kp);
        break;
      }
      case 'W': case 'w': { // PWM max: W120
        int v = Serial.parseInt();
        verin_level_pwm_max = constrain(abs(v), 0, 255);
        Serial.print("VERIN_PWM_MAX:");
        Serial.println(verin_level_pwm_max);
        break;
      }
      case 'I': case 'i': { // 调平方向: I0 NORMAL / I1 REVERSED
        int v = Serial.parseInt();
        verin_level_reversed = (v != 0);
        Serial.print("VERIN_MODE:");
        Serial.println(verin_level_reversed ? "REVERSED" : "NORMAL");
        break;
      }
      case 'E': case 'e': { // pwm step: E5
        int v = Serial.parseInt();
        verin_level_pwm_step = constrain(abs(v), 0, 50);
        Serial.print("VERIN_PWM_STEP:");
        Serial.println(verin_level_pwm_step);
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
        if (!t_auto_active) {
          MotorT.setTarget(val);
        }
        Serial.print("SET_TRISTAR:"); Serial.println(val);
        break;
      }
      case 'V': case 'v': { // 推杆控制 V100(伸出) V-100(收回) V0(停止)
        // 手动推杆优先：收到 V 指令就关闭自动调平
        verin_level_enabled = false;
        int val = Serial.parseInt();
        write_verin_pwm_cmd(val);
        Serial.print("SET_VERIN:"); Serial.println(val);
        break;
      }
      case 'S': case 's': { // 停止 S
        apply_stop_all();
        Serial.println("STOP");
        break;
      }
    }
  }

  // 1.5 推杆自动调平（板上闭环）
  if (verin_level_enabled && (millis() - lastVerinLevelTime > VERIN_LEVEL_INTERVAL)) {
    lastVerinLevelTime = millis();
    float angle = get_gyro_axis_deg(verin_level_axis);
    int pwm = 0;
    if (abs(angle) > verin_level_deadband_deg) {
      // 以 NORMAL 为基准：这里用 -kp*angle。
      // 如需反向（REVERSED），则改为 +kp*angle。
      float p = verin_level_reversed ? (verin_level_kp * angle) : (-verin_level_kp * angle);
      p = constrain(p, (float)-verin_level_pwm_max, (float)verin_level_pwm_max);
      pwm = (int)round(p);
    }

    if (abs(pwm - last_verin_pwm_sent) >= verin_level_pwm_step) {
      write_verin_pwm_cmd(pwm);
    }
  }

  // 2. 刷新编码器状态
  Encoder_L.loop(); Encoder_R.loop(); Encoder_T.loop();
  VerinMotor.loop();
  Gyro.update();

  // 2.5 超声波触发检测 (接近台阶)
  if (millis() - lastUltraTime > ULTRA_INTERVAL) {
    lastUltraTime = millis();
    double dist_cm = Ultrasonic.distanceCm();
    if (dist_cm > 0 && dist_cm < 400) {
      if (!t_auto_active && t_auto_armed && dist_cm <= ULTRA_TRIGGER_CM) {
        t_auto_active = true;
        t_auto_armed = false;
        t_start_pulse = Encoder_T.getPulsePos();
        MotorT.setTarget(T_AUTO_RPM);
        Serial.print("AUTO_T_START_CM:"); Serial.println(dist_cm);
      } else if (!t_auto_active && !t_auto_armed && dist_cm >= ULTRA_RESET_CM) {
        t_auto_armed = true;
      }
    }
  }

  // 3. 定时 PID 计算
  if (millis() - lastTime > PID_INTERVAL) {
    lastTime = millis();

    // 计算基础 PWM
    float pwmL = MotorL.computePWM();
    float pwmR = MotorR.computePWM();
    float pwmT = MotorT.computePWM();

    // 左右轮同步纠偏 (仅在直线行驶时)
    if (abs(MotorL.targetSpeed) > 5.0 && MotorL.targetSpeed == MotorR.targetSpeed) {
        float speedDiff = MotorL.currentSpeed - MotorR.currentSpeed;
        pwmL -= speedDiff * K_sync;
        pwmR += speedDiff * K_sync;
    }

    // 写入电机
    MotorL.writePWM(pwmL);
    MotorR.writePWM(pwmR);
    // 自动触发运行完成检测
    if (t_auto_active) {
      long delta_pulse = labs(Encoder_T.getPulsePos() - t_start_pulse);
      if (delta_pulse >= T_TARGET_PULSES) {
        MotorT.setTarget(0);
        t_auto_active = false;
        t_auto_armed = true;
        Serial.println("AUTO_T_DONE");
      }
    }

    MotorT.writePWM(pwmT);

    // 4. 定期发送调试信息 (每 100ms 一次)
    static int debugCount = 0;
    if (debugCount++ > 5) {
      debugCount = 0;
      Serial.print("T:"); Serial.print(MotorL.targetSpeed);
      Serial.print(" L:"); Serial.print(MotorL.currentSpeed);
      Serial.print(" R:"); Serial.print(MotorR.currentSpeed);
      Serial.print(" Tri:"); Serial.print(MotorT.currentSpeed);
      
      if (MotorL.isStalled || MotorR.isStalled || MotorT.isStalled) {
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
