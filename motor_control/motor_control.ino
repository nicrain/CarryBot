#include <MeMegaPi.h>
#include <MeGyro.h>
#include "MotorController.h"

// --- 硬件对象定义 ---
MeEncoderOnBoard Encoder_L(SLOT1);
MeEncoderOnBoard Encoder_R(SLOT2);
MeEncoderOnBoard Encoder_T(SLOT3);
MeEncoderOnBoard VerinMotor(SLOT4); // 推杆/执行器 (PWM)
MeGyro Gyro(PORT_5);

// --- 控制器实例 (PID 参数在这里调) ---
// 格式: MotorController(&Encoder, Kp, Ki, Kd, FeedForward, Reversed)
MotorController MotorL(&Encoder_L, 1.2, 0.6, 2.0, 30.0, false);
MotorController MotorR(&Encoder_R, 1.2, 0.6, 2.0, 30.0, true);
MotorController MotorT(&Encoder_T, 1.5, 0.5, 1.0, 40.0, false);

// --- 全局参数 ---
float K_sync = 1.0;          // 左右轮同步系数
const int PID_INTERVAL = 20; // 控制周期 ms
const int IMU_INTERVAL = 50; // IMU output interval (ms)
unsigned long lastTime = 0;
unsigned long lastImuTime = 0;

// --- 中断函数 (必须写在这里) ---
void isr_L() { if(digitalRead(Encoder_L.getPortB()) == 0) Encoder_L.pulsePosMinus(); else Encoder_L.pulsePosPlus(); }
void isr_R() { if(digitalRead(Encoder_R.getPortB()) == 0) Encoder_R.pulsePosMinus(); else Encoder_R.pulsePosPlus(); }
void isr_T() { if(digitalRead(Encoder_T.getPortB()) == 0) Encoder_T.pulsePosMinus(); else Encoder_T.pulsePosPlus(); }

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  Serial.println("CarryBot Motor Ctrl Ready");

  Gyro.begin();

  // 绑定中断
  attachInterrupt(Encoder_L.getIntNum(), isr_L, RISING);
  attachInterrupt(Encoder_R.getIntNum(), isr_R, RISING);
  attachInterrupt(Encoder_T.getIntNum(), isr_T, RISING);

  // 设置减速比和脉冲数
  Encoder_L.setPulse(7); Encoder_L.setRatio(46);
  Encoder_R.setPulse(7); Encoder_R.setRatio(46);
  Encoder_T.setPulse(7); Encoder_T.setRatio(75);
  // 推杆通常没有编码器反馈，这里只需要确保 PWM 输出可用
  VerinMotor.setPulse(7);
  VerinMotor.setRatio(46);
  
  // 初始停止
  MotorL.reset(); MotorR.reset(); MotorT.reset();
  VerinMotor.setMotorPwm(0);
}

void loop() {
  // 1. 读取串口指令
  while (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd > 32 && cmd < 127) { Serial.print("RX:"); Serial.write(cmd); Serial.println(); }

    switch (cmd) {
      case 'M': case 'm': { // 轮子移动 M30
        float val = Serial.parseFloat();
        MotorL.setTarget(val);
        MotorR.setTarget(val);
        Serial.print("SET_WHEELS:"); Serial.println(val);
        break;
      }
      case 'T': case 't': { // 爬楼 T20
        float val = Serial.parseFloat();
        MotorT.setTarget(val);
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
        MotorL.reset(); MotorR.reset(); MotorT.reset();
        VerinMotor.setMotorPwm(0);
        Serial.println("STOP");
        break;
      }
    }
  }

  // 2. 刷新编码器状态
  Encoder_L.loop(); Encoder_R.loop(); Encoder_T.loop();
  VerinMotor.loop();
  Gyro.update();

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
