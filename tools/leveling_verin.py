#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from motor_control.motor_driver import MotorDriver


def parse_args():
    parser = argparse.ArgumentParser(description="Verin leveling controller (IMU-based)")
    parser.add_argument("--axis", choices=["x", "y", "z"], default="x", help="IMU angle axis")
    parser.add_argument("--deadband", type=float, default=3.0, help="Level deadband in deg")
    parser.add_argument("--kp", type=float, default=20.0, help="PWM per deg")
    parser.add_argument("--pwm-max", type=float, default=120.0, help="PWM limit")
    parser.add_argument("--rate", type=float, default=2.0, help="Control rate (Hz)")
    parser.add_argument("--pwm-step", type=float, default=5.0, help="Min PWM change to resend")
    parser.add_argument("--invert", action="store_true", help="Invert control direction")
    parser.add_argument("--imu-timeout", type=float, default=1.0, help="IMU data timeout (s)")
    return parser.parse_args()


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def main():
    args = parse_args()
    driver = MotorDriver()

    axis_index = {"x": 0, "y": 1, "z": 2}[args.axis]
    interval = 1.0 / max(args.rate, 1e-3)

    last_sent_pwm = None

    try:
        while True:
            imu = driver.get_latest_imu()
            if imu is None:
                if last_sent_pwm is None or last_sent_pwm != 0:
                    driver.move_verin_pwm(0)
                    last_sent_pwm = 0
                time.sleep(interval)
                continue

            angle_x, angle_y, angle_z, ts = imu
            age = time.time() - ts
            if age > args.imu_timeout:
                if last_sent_pwm is None or last_sent_pwm != 0:
                    driver.move_verin_pwm(0)
                    last_sent_pwm = 0
                time.sleep(interval)
                continue

            angle = [angle_x, angle_y, angle_z][axis_index]

            if abs(angle) <= args.deadband:
                pwm = 0.0
            else:
                pwm = args.kp * angle

            if args.invert:
                pwm = -pwm

            pwm = clamp(pwm, -args.pwm_max, args.pwm_max)
            pwm_int = int(round(pwm))
            if last_sent_pwm is None or abs(pwm_int - last_sent_pwm) >= int(args.pwm_step):
                driver.move_verin_pwm(pwm_int)
                last_sent_pwm = pwm_int

            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        driver.move_verin_pwm(0)
        driver.close()


if __name__ == "__main__":
    main()
