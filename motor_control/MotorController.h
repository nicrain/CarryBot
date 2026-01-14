#ifndef MOTOR_CONTROLLER_H
#define MOTOR_CONTROLLER_H

#include <Arduino.h>
#include <MeMegaPi.h>

class MotorController {
  public:
    MeEncoderOnBoard* encoder;
    float Kp, Ki, Kd, F;
    float integralLimit;
    bool reversed;
    
    // 状态变量
    float targetSpeed;
    float currentSpeed; // 平滑后的速度
    float integral;
    float lastError;
    
    // 堵转保护
    unsigned long stallStartTime;
    bool isStalled;

    // 构造函数
    MotorController(MeEncoderOnBoard* enc, float kp, float ki, float kd, float f, bool rev = false) {
      encoder = enc;
      Kp = kp; Ki = ki; Kd = kd; F = f;
      reversed = rev;
      integralLimit = 200.0;
      reset();
    }

    void reset() {
      targetSpeed = 0;
      currentSpeed = 0;
      resetPID();
      isStalled = false;
      stallStartTime = 0;
      encoder->setMotorPwm(0);
    }

    void setTarget(float t) {
      targetSpeed = t;
      if (t == 0) isStalled = false;
    }

    void writePWM(float pwm) {
      float output = reversed ? -pwm : pwm;
      encoder->setMotorPwm(constrain(output, -255, 255));
    }

    float computePWM() {
      // 1. 读取并平滑速度
      float rawSpeed = encoder->getCurrentSpeed();
      if (reversed) rawSpeed = -rawSpeed;
      currentSpeed = (currentSpeed * 0.7) + (rawSpeed * 0.3);

      // 2. 静止死区控制
      if (targetSpeed == 0 && abs(currentSpeed) < 2.0) {
         resetPID();
         return 0;
      }
      
      float error = targetSpeed - currentSpeed;

      // 3. 堵转保护
      if (abs(error) > 20.0 && abs(targetSpeed) > 5.0) {
          if (stallStartTime == 0) stallStartTime = millis();
          else if (millis() - stallStartTime > 2000) isStalled = true;
      } else {
          stallStartTime = 0;
      }

      if (isStalled) return 0;

      // 4. PID 计算
      integral = constrain(integral + error, -integralLimit, integralLimit);
      
      float ff = 0;
      if (abs(targetSpeed) > 1.0) {
          ff = (targetSpeed > 0) ? F : -F;
      }

      float output = ff + (Kp * error) + (Ki * integral) + (Kd * (error - lastError));
      lastError = error;
      
      return output;
    }

  private:
    void resetPID() {
      integral = 0;
      lastError = 0;
    }
};

#endif