#include <MeMegaPi.h>
#include <Wire.h>
#include <MeGyro.h>
#include <MeUltrasonicSensor.h>
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

// --- 实体 STOP 按钮 ---
// 适配类似 R16-503 的带灯按钮：
// - 两个“大脚”是开关触点（通常常开 NO）
// - 两个“小脚”标 + / - 是 LED（与 STOP 输入无关）
// 接线建议：开关触点一端接 GND，另一端接 STOP_BTN_PIN；用 INPUT_PULLUP。
// 如果有两个按钮实现同样 STOP：两个按钮的开关触点并联到同一个 STOP_BTN_PIN 与 GND。
// 默认 STOP 引脚；如果板子丝印/映射不一致，可在运行时用串口命令 Bxx 修改。
uint8_t stop_btn_pin = 22; // 默认 22
const unsigned long STOP_DEBOUNCE_MS = 30;
bool stop_btn_stable_pressed = false;
bool stop_btn_last_sample = false;
unsigned long stop_btn_last_change_ms = 0;
bool stop_btn_reported_pressed = false;
unsigned long stop_debug_until_ms = 0;

static inline void apply_stop_all() {
  MotorL.reset();
  MotorR.reset();
  MotorT.reset();
  VerinMotor.setMotorPwm(0);
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

  Serial.print("STOP_BTN_PIN:");
  Serial.println(stop_btn_pin);

  pinMode(stop_btn_pin, INPUT_PULLUP);

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
  VerinMotor.setMotorPwm(0);
}

void loop() {
  // 0. 实体 STOP 按钮（防抖 + 电平触发）
  // INPUT_PULLUP: 未按下=HIGH，按下(短接到GND)=LOW
  bool stop_sample_pressed = (digitalRead(stop_btn_pin) == LOW);

  // 可选调试：在指定时间窗口内，周期性打印当前 STOP 引脚电平
  if (stop_debug_until_ms != 0 && millis() < stop_debug_until_ms) {
    static unsigned long last_dbg = 0;
    if (millis() - last_dbg >= 200) {
      last_dbg = millis();
      Serial.print("STOP_BTN_READ_PIN:");
      Serial.print(stop_btn_pin);
      Serial.print(" VAL:");
      Serial.println(stop_sample_pressed ? 0 : 1);
    }
  }
  // 紧急停：只要检测到 LOW，就立刻停（不等防抖）。
  // 这样即使串口持续有数据（while Serial.available 一直跑），也能立即刹车。
  if (stop_sample_pressed) {
    apply_stop_all();
    t_auto_active = false;
    t_auto_armed = true;
    if (!stop_btn_reported_pressed) {
      Serial.print("STOP_BTN_RAW_LOW_PIN:");
      Serial.println(stop_btn_pin);
      stop_btn_reported_pressed = true;
    }
    return;
  } else {
    stop_btn_reported_pressed = false;
  }

  if (stop_sample_pressed != stop_btn_last_sample) {
    stop_btn_last_sample = stop_sample_pressed;
    stop_btn_last_change_ms = millis();
    Serial.print("STOP_BTN_RAW:");
    Serial.println(stop_sample_pressed ? 1 : 0);
  }
  if (millis() - stop_btn_last_change_ms >= STOP_DEBOUNCE_MS) {
    if (stop_btn_stable_pressed != stop_btn_last_sample) {
      stop_btn_stable_pressed = stop_btn_last_sample;
      if (stop_btn_stable_pressed) {
        apply_stop_all();
        Serial.println("STOP_BTN");
      }
    }
  }
  if (stop_btn_stable_pressed) {
    // 按住期间持续保持停机状态（更安全，等同于反复收到 'S'）
    apply_stop_all();
    t_auto_active = false;
    t_auto_armed = true;
    return;
  }

  // 1. 读取串口指令
  // 限制每轮处理的命令数，避免被串口洪泛“饿死”其他逻辑（例如 STOP 按钮）。
  int cmd_budget = 8;
  while (Serial.available() > 0 && cmd_budget-- > 0) {
    // 串口处理期间也检查紧急停
    if (digitalRead(stop_btn_pin) == LOW) {
      apply_stop_all();
      t_auto_active = false;
      t_auto_armed = true;
      Serial.print("STOP_BTN_RAW_LOW_PIN:");
      Serial.println(stop_btn_pin);
      // 清空缓冲区，避免松开按钮后立刻又被历史命令启动
      while (Serial.available() > 0) (void)Serial.read();
      return;
    }

    char cmd = Serial.read();
    if (cmd > 32 && cmd < 127) { Serial.print("RX:"); Serial.write(cmd); Serial.println(); }

    switch (cmd) {
      case 'B': case 'b': { // 设置 STOP 按钮引脚：B22
        int new_pin = Serial.parseInt();
        if (new_pin >= 2 && new_pin <= 53) {
          stop_btn_pin = (uint8_t)new_pin;
          pinMode(stop_btn_pin, INPUT_PULLUP);
          Serial.print("STOP_BTN_PIN_SET:");
          Serial.println(stop_btn_pin);
        } else {
          Serial.print("STOP_BTN_PIN_INVALID:");
          Serial.println(new_pin);
        }
        break;
      }
      case 'Q': case 'q': { // 打印 5 秒 STOP 引脚读数，用于接线自检
        stop_debug_until_ms = millis() + 5000;
        Serial.print("STOP_BTN_DEBUG_5S_PIN:");
        Serial.println(stop_btn_pin);
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
      case 'T': case 't': { // 爬楼 T20
        float val = Serial.parseFloat();
        if (!t_auto_active) {
          MotorT.setTarget(val);
        }
        Serial.print("SET_TRISTAR:"); Serial.println(val);
        break;
      }
      case 'V': case 'v': { // 推杆控制 V100(伸出) V-100(收回) V0(停止)
        int val = Serial.parseInt();
        val = constrain(val, -255, 255);
        VerinMotor.setMotorPwm(val);
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
