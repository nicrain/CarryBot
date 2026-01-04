# CarryBot Project Context

## Overview
CarryBot is a perception and control system designed for a mobile robot (likely using a Raspberry Pi and Makeblock MegaPi). Its primary function is to detect environmental hazards like stairs (up/down) and walls using an Intel RealSense depth camera and navigate accordingly.

## Key Components

### 1. Vision System (`detect_stairs.py`)
- **Language:** Python 3
- **Hardware:** Intel RealSense D435 Depth Camera.
- **Libraries:** `pyrealsense2`, `opencv-python`, `numpy`.
- **Functionality:**
    - Captures depth and color frames.
    - Processes depth data to detect walls, stairs (up/down), and obstacles.
    - Supports line following (reflective tape) for semi-autonomous navigation.
    - **Web Interface:** Runs a built-in HTTP server on port `8080` for MJPEG stream and parameter tuning.

### 2. Motor Control & Stabilization (`motor_control/`)
- **Connection:** Raspberry Pi $\leftrightarrow$ MegaPi via **USB Serial** (115200 baud).
- **Architecture:**
    - **Arduino:** `motor_control.ino` (Command Parser) + `MotorController.h` (PID Logic & Stall Protection).
    - **Python:** `motor_driver.py` (Threaded Driver). Handles handshake, RPM clamping, and unit conversion.
- **Hardware Specs:**
    - **Wheels:** Diameter **68.5mm**.
    - **Gear Ratio:** Internal 1:46 + External 8:56 ($\approx$ 1:7). Total reduction $\approx$ 1:322.
    - **Max Speed:** ~185 RPM (Motor Shaft) $\approx$ **9.5 cm/s** (Linear).
    - **Tristar:** 1:75 Internal ratio. Max 86 RPM.
- **Safety:**
    - **Stall Protection:** Auto-stop if error > 20 for 2 seconds.
    - **RPM Limiting:** Software clamp at $\pm$185 (Wheels) and $\pm$86 (Tristar).
    - **Dead Zone:** Auto-silence motors when target is 0.

## Project Structure

```text
/
├── detect_stairs.py       # Main vision application
├── config/                # Configuration files
├── web/                   # Web interface templates
├── motor_control/         # Motor System
│   ├── motor_control.ino  # Main Arduino Sketch
│   ├── MotorController.h  # Header-only PID & Logic class
│   └── motor_driver.py    # Python Driver (PC/Pi side)
├── docs/                  # Documentation
├── tests/                 # Python tests
│   └── test_move.py       # Motor movement test script
└── tools/                 # Utility scripts
```

## Key Requirements (from CDC)
- **Payload:** Up to 2kg.
- **Stair Climbing:** Capable of overcoming small steps (up to 4cm) using the Tri-Star system.
- **Safety:** Physical emergency stop button + software-triggered stop.
- **Interface:** Simplified Android app with pictograms for accessibility (PMR/Elderly).

## Setup & Usage

### Vision System (Raspberry Pi)
The system is designed to run in headless mode (CLI).

1.  **Install Dependencies:** `pip install -r requirements.txt`
2.  **Run:** `python detect_stairs.py` (Recommended: Run inside `tmux` or `screen`).
3.  **Monitor:** Access `http://<device-ip>:8080` from a browser to view the stream and tune parameters.

### Motor Control
- Flash `MeMegaPiDCMotorTest.ino` to the MegaPi board using Arduino IDE.

## Development Notes
- **Parameter Tuning:** The `config.json` file is the source of truth. It can be updated via the web UI or manually. The Python script watches this file for changes.
- **Testing:**
    - `tests/test_camera.py`: Basic camera availability test.
    - `tests/test_smoke.py`: Smoke tests for the application.
