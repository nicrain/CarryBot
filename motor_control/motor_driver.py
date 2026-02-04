import serial
import serial.tools.list_ports
import time
import threading

class MotorDriver:
    def __init__(self, port=None, baudrate=115200, timeout=1):
        self.ser = None
        self.running = True
        self.arduino_ready = threading.Event() # 握手信号
        target_port = port
        
        # 自动搜索端口
        if target_port is None:
            ports = list(serial.tools.list_ports.comports())
            print(f"[MotorDriver] Scanning {len(ports)} ports...")
            for p in ports:
                print(f"  - Found: {p.device} | {p.description}")
                # 兼容性：Mac 通常是 cu.usbserial, Linux 是 ttyUSB
                if "usb" in p.device.lower() or "arduino" in p.description.lower() or "usb" in p.description.lower():
                    target_port = p.device
                    print(f"[MotorDriver] Selected port: {target_port}")
                    break
        
        if target_port is None:
            print("[MotorDriver] Warning: No serial port found. Running in simulation mode.")
            return

        try:
            self.ser = serial.Serial(target_port, baudrate, timeout=timeout)
            # 强制复位 Arduino
            self.ser.dtr = False
            time.sleep(0.1)
            self.ser.dtr = True
            
            print(f"[MotorDriver] Connected to {target_port}. Waiting for Arduino reset...")

            self.read_thread = threading.Thread(target=self._read_serial_loop)
            self.read_thread.daemon = True
            self.read_thread.start()
            
            # 等待 Arduino 发送 "Ready" 信号
            if self.arduino_ready.wait(timeout=5.0):
                print("[MotorDriver] Arduino is READY.")
            else:
                print("[MotorDriver] Warning: Handshake timed out. Arduino might not have reset.")
            
        except Exception as e:
            print(f"[MotorDriver] ERROR: Could not open port {target_port}: {e}")
            print("[MotorDriver] Make sure Arduino IDE Serial Monitor is CLOSED.")
            self.ser = None
            exit(1) # Exit since we can't do anything without the motor

    def _read_serial_loop(self):
        while self.running and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    # 读取一行，忽略解码错误
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"[Arduino] {line}")
                        # 握手检测关键词
                        if "Ready" in line:
                            self.arduino_ready.set()
            except Exception:
                pass
            time.sleep(0.01)

    def _send_command(self, cmd):
        if self.ser and self.ser.is_open:
            try:
                # 加上 \n 换行符，确保 Arduino 知道这是一条完整指令
                self.ser.write(f"{cmd}\n".encode('utf-8'))
                self.ser.flush() # 强制立刻发送
            except Exception as e:
                print(f"[MotorDriver] Send error: {e}")
        else:
            print(f"[Simulation] Motor Command: {cmd}")

    def _clamp_rpm(self, rpm, limit):
        """限制 RPM 在指定的物理极限范围内"""
        if abs(rpm) > limit:
            old_rpm = rpm
            rpm = limit if rpm > 0 else -limit
            print(f"[MotorDriver] Warning: RPM clamped {old_rpm} -> {rpm} (Limit: {limit})")
        return rpm

    def move_wheels(self, rpm):
        """直接设置轮子电机轴转速 (RPM)，极限 185"""
        rpm = self._clamp_rpm(rpm, 185)
        self._send_command(f"M{rpm:.2f}")

    def move_wheels_cmps(self, speed_cmps):
        """
        设置小车线速度 (cm/s)。
        转换公式: RPM = speed_cmps * 19.52
        基于: 轮径6.85cm, 外部减速比 1:7 (8:56)
        """
        rpm = speed_cmps * 19.52
        rpm = self._clamp_rpm(rpm, 185)
        self._send_command(f"M{rpm:.2f}")

    def move_tristar(self, rpm):
        """设置三星轮电机轴转速 (RPM)，极限 86"""
        rpm = self._clamp_rpm(rpm, 86)
        self._send_command(f"T{rpm:.2f}")

    def move_verin_pwm(self, pwm):
        """设置推杆/执行器 PWM（-255 ~ 255），对应固件命令 V<val>"""
        try:
            pwm_int = int(pwm)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid pwm value: {pwm}")

        if pwm_int < -255:
            pwm_int = -255
        elif pwm_int > 255:
            pwm_int = 255

        self._send_command(f"V{pwm_int}")

    def stop(self):
        self._send_command("S")

    def close(self):
        self.running = False
        if self.ser:
            self.stop()
            time.sleep(0.1)
            self.ser.close()

if __name__ == "__main__":
    driver = MotorDriver()
    
    try:
        # 此时 Arduino 应该已经 Ready 了
        print(">>> 3..2..1.. GO! (Testing Wheels M40)")
        time.sleep(1)
        driver.move_wheels(40)
        
        time.sleep(3) 
        
        print(">>> STOP")
        driver.stop()
        time.sleep(1)
        
        print(">>> Testing Tristar (T30)")
        driver.move_tristar(30)
        time.sleep(3)
        
        print(">>> DONE")
        driver.stop()
        
    except KeyboardInterrupt:
        driver.stop()
    finally:
        driver.close()