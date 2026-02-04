#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import select
import sys
import threading
import time

import serial
import serial.tools.list_ports


def _auto_pick_port() -> str | None:
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        dev = (p.device or "").lower()
        desc = (p.description or "").lower()
        if "ttyusb" in dev or "usb" in dev or "arduino" in desc or "megapi" in desc or "makeblock" in desc:
            return p.device
    return ports[0].device if ports else None


def _reader(ser: serial.Serial, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            line = ser.readline()
            if not line:
                continue
            text = line.decode("utf-8", errors="ignore").rstrip("\r\n")
            if text:
                sys.stdout.write(f"\r[Arduino] {text}\n")
                sys.stdout.flush()
        except Exception:
            time.sleep(0.05)


def _send(ser: serial.Serial, cmd: str) -> None:
    cmd = cmd.strip()
    if not cmd:
        return
    if not cmd.endswith("\n"):
        cmd += "\n"
    ser.write(cmd.encode("utf-8", errors="ignore"))
    ser.flush()


def _interactive_raw(ser: serial.Serial) -> None:
    # Raw-key interactive console: type commands, Enter to send.
    # If buffer is empty, pressing 's' (or space) sends STOP immediately.
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    stop_event = threading.Event()

    reader_thread = threading.Thread(target=_reader, args=(ser, stop_event), daemon=True)
    reader_thread.start()

    buffer: list[str] = []

    def redraw_prompt() -> None:
        sys.stdout.write("\r> " + "".join(buffer) + "\x1b[K")
        sys.stdout.flush()

    try:
        tty.setraw(fd)
        sys.stdout.write("Type command then Enter (e.g. v100, m20).\n")
        sys.stdout.write("Quick STOP: press 's' or Space when input is empty. Quit: 'q'.\n")
        redraw_prompt()

        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not r:
                continue

            ch = sys.stdin.read(1)
            if not ch:
                continue

            # Quit
            if ch in ("q", "Q") and not buffer:
                _send(ser, "S")
                sys.stdout.write("\n[Local] Quit (sent STOP)\n")
                break

            # Ctrl+C
            if ch == "\x03":
                _send(ser, "S")
                sys.stdout.write("\n[Local] Ctrl+C (sent STOP)\n")
                break

            # Backspace
            if ch in ("\x7f", "\b"):
                if buffer:
                    buffer.pop()
                redraw_prompt()
                continue

            # Enter
            if ch in ("\r", "\n"):
                cmd = "".join(buffer)
                buffer.clear()
                sys.stdout.write("\n")
                sys.stdout.flush()
                _send(ser, cmd)
                redraw_prompt()
                continue

            # Quick STOP when nothing typed
            if not buffer and ch in ("s", "S", " "):
                _send(ser, "S")
                sys.stdout.write("\n[Local] STOP\n")
                redraw_prompt()
                continue

            # Printable characters
            if 32 <= ord(ch) <= 126:
                buffer.append(ch)
                redraw_prompt()

    finally:
        stop_event.set()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main() -> int:
    ap = argparse.ArgumentParser(description="Simple serial console for CarryBot motor controller")
    ap.add_argument("--port", default=None, help="Serial port (e.g. /dev/ttyUSB0). Auto-detect if omitted.")
    ap.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    args = ap.parse_args()

    port = args.port or _auto_pick_port()
    if not port:
        print("No serial port found.")
        return 2

    try:
        ser = serial.Serial(port, args.baud, timeout=0.2)
    except Exception as e:
        print(f"Failed to open {port}: {e}")
        print("Tip: ensure permissions (dialout group) and no other program is using the port.")
        return 1

    print(f"Connected: {port} @ {args.baud}")
    try:
        _interactive_raw(ser)
    finally:
        try:
            ser.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
