# PTZ Camera & Surveillance System Integration Specification
**Specification Version:** 1.3 | **Updated:** 2026-09-10
**Target:** ทีมพัฒนาฝั่งกล้อง PTZ, Mount Agent และ Central Station Integrator

---

## 1. รายการ Endpoints (API Overview)

| Endpoint | Method | ทิศทาง | หน้าที่ |
| :--- | :--- | :--- | :--- |
| `/api/camera-stream/frame/<camera_id>?source=live` | `POST` | ระบบส่ง $\rightarrow$ PTZ | ส่งเฟรมภาพ JPEG พร้อม Metadata ใน Header |
| `/api/camera/zoom` | `POST` | PTZ สั่ง $\rightarrow$ ระบบ | สั่งซูมกล้อง พร้อม Limit Check / Clamping อัตโนมัติ |
| `/api/camera/focus` | `POST` | PTZ สั่ง $\rightarrow$ ระบบ | สั่งโฟกัสกล้อง (`auto`, `near`, `far`) พร้อม Clamp ความเร็วและเวลา |
| `/api/sweep/control` | `POST` | PTZ สั่ง $\rightarrow$ ระบบ | สั่ง Sweep กวาดตรวจ (`start`, `pause`, `resume`, `stop`) |
| `/api/sweep/status` | `GET` | PTZ ดึง $\rightarrow$ ระบบ | ดึงสถานะการสแกนและผลคำนวณ Trajectory ปัจจุบัน |
| `/api/detector/config` | `GET` / `POST` | PTZ สั่ง/ดึง $\rightarrow$ ระบบ | ปรับ Hotspot Threshold / สลับ Dynamic Saliency แบบเรียลไทม์ |
| `/api/telemetry` | `GET` | PTZ ดึง $\rightarrow$ ระบบ | ดึงข้อมูล Telemetry รวมทุกกล้องและสถานะแท่นกล้อง |

---

## 2. การรับภาพและสถานะกล้อง (Frame & Metadata Ingest)

### `POST /api/camera-stream/frame/<camera_id>?source=live`
* **URL Param:** `camera_id` = `thermal` หรือ `visible`
* **Headers:**
  * `Content-Type`: `image/jpeg`
  * `X-Camera-Metadata`: `<JSON String>`
* **Body:** Binary JPEG Image Bytes (ภาพ Thermal ดั้งเดิมแบบไม่มี Bounding Box วาดทับ)
* **Expected Response:** `202 Accepted`

### ตัวอย่าง Header `X-Camera-Metadata`:
```json
{
  "captured_at": "2026-09-10T11:15:00.120Z",
  "camera_id": "thermal",
  "width": 640,
  "height": 512,
  "capture_sequence": 14502,
  "focal_length_mm": 31.0,
  "zoom_ratio": 0.0,
  "zoom_pct": 0.0,
  "zoom_x": 1.0,
  "fov_h_deg": 14.2,
  "fov_v_deg": 11.4,
  "is_zooming": false,
  "azimuth_deg": 45.2,
  "altitude_deg": -5.0,
  "mission_state": "SEARCH_SWEEP",
  "scan_mode": "CONTINUOUS",
  "is_paused": false,
  "current_waypoint": 5,
  "total_waypoints": 30,
  "current_layer": 1,
  "total_layers": 3,
  "fire_detected": true,
  "annotated": false,
  "detections": [
    {
      "box": [280, 190, 360, 270],
      "score": 0.942,
      "state": "CONFIRMED_FIRE"
    }
  ]
}
```

### Data Dictionary & Range:
| ฟิลด์ข้อมูล | ชนิด | ช่วงค่าที่รองรับ | คำอธิบาย |
| :--- | :--- | :--- | :--- |
| `focal_length_mm` | Float | Thermal: `31.0 - 155.0` \| Visible: `5.1 - 102.0` | ความยาวโฟกัสจริงของเลนส์ (mm) |
| `zoom_pct` / `zoom_x` | Float | `0.0 - 100.0%` \| `1.0x - 20.0x` | เปอร์เซ็นต์ซูม / กำลังขยายออปติคอล |
| `fov_h_deg` / `fov_v_deg` | Float | Thermal Wide: `14.2°×11.4°` $\rightarrow$ Tele: `2.8°×2.3°`<br>Visible Wide: `51.7°×29.6°` $\rightarrow$ Tele: `3.1°×1.8°` | มุมมองภาพแนวนอนและแนวตั้ง (FOV) คำนวณตามระยะซูมจริง |
| `is_zooming` | Bool | `true` / `false` | เลนส์กำลังขับมอเตอร์ซูมอยู่หรือไม่ |
| `azimuth_deg` / `altitude_deg` | Float | Az: `-300°..+300°` \| Alt: `-10°..+45°` | พิกัดองศาแท่นกล้องปัจจุบัน |
| `mission_state` | String | *ดูตาราง State Machine ด้านล่าง* | สถานะการทำงานของระบบตรวจจับ |
| `fire_detected` | Bool | `true` / `false` | ตรวจพบเป้าหมายความร้อน/ไฟในขณะนี้หรือไม่ |
| `annotated` | Bool | `true` / `false` | ระบุว่าภาพถูกวาด Bounding Box ทับหรือไม่ (ค่าเริ่มต้น `false` ส่งภาพ Clean) |
| `detections` | Array | `[{"box": [x1, y1, x2, y2], "score": float, "state": str}]` | รายการพิกัด Bounding Box และคะแนนความมั่นใจ |

### Mission State Reference:
| `mission_state` | ความหมาย | คำแนะนำสำหรับแท่นกล้อง PTZ |
| :--- | :--- | :--- |
| `IDLE` / `PAUSED` | หยุดนิ่ง / พักการสแกน | PTZ ควบคุมแบบ Manual ได้อิสระ |
| `SEARCH_SWEEP` | กำลังกวาดตรวจต่อเนื่อง | ระบบส่งคำสั่ง Pan อัตโนมัติ |
| `STEP_MOVING` / `STEP_DWELLING` | สเต็ปไปจุดถัดไป / หยุดนิ่งวิเคราะห์ AI | ห้ามแทรกแซงมุมกล้อง |
| `TARGET_CENTERING` | ปรับตำแหน่งเป้าหมายเข้ากึ่งกลางภาพ | ระบบกำลังหมุน Fine Centering |
| `ZOOMING_IN` / `VERIFYING_FOCUS` | ซูมเลนส์เข้า / รอกล้องโฟกัสนิ่ง | ห้ามขยับ PTZ เพื่อไม่ให้ภาพหลุดโฟกัส |
| `DEEP_CONFIRMATION` / `ALARM_ACTIVE` | ยืนยันไฟที่ระยะซูม / กำลังแจ้งเตือน | ห้ามขยับ PTZ ระบบกำลังบันทึกภาพหลักฐาน |
| `ZOOMING_OUT` | ซูมเลนส์กลับสู่มุมกว้าง | เลนส์กำลังขยายออกเพื่อกลับไปสแกนต่อ |

---

## 3. สั่งซูมและโฟกัสกล้อง (Zoom & Focus Control)

### 3.1 สั่งซูมกล้อง (`POST /api/camera/zoom`)
* **Endpoint:** `POST http://<SERVER_IP>:5005/api/camera/zoom`
* **Parameters (JSON):**
  * `camera`: `"thermal"` (default) | `"visible"` | `"all"`
  * เลือกระบุ 1 รูปแบบ:
    * `"zoom_pct"`: `0.0` ถึง `100.0`
    * `"focal_mm"`: Thermal clamp `31.0 - 155.0`, Visible clamp `5.1 - 102.0`
    * `"zoom_x"`: Thermal clamp `1.0 - 5.0x`, Visible clamp `1.0 - 20.0x`

#### ตัวอย่าง Request:
```json
{
  "camera": "thermal",
  "zoom_pct": 50.0
}
```

#### ตัวอย่าง Response:
```json
{
  "status": "ok",
  "camera": "thermal",
  "applied_mode": "zoom_pct",
  "requested_value": 50.0,
  "clamped": false,
  "zoom_info": {
    "focal_mm": 93.0,
    "zoom_pct": 50.0,
    "zoom_x": 3.0,
    "fov_h": 4.73,
    "fov_v": 3.8
  },
  "limits": {
    "min_focal_mm": 31.0,
    "max_focal_mm": 155.0,
    "max_zoom_x": 5.0
  }
}
```

---

### 3.2 สั่งโฟกัสกล้อง (`POST /api/camera/focus`)
* **Endpoint:** `POST http://<SERVER_IP>:5005/api/camera/focus`
* **Parameters (JSON):**
  * `camera`: `"thermal"` (default) | `"visible"` | `"all"`
  * `action`: `"auto"` | `"near"` | `"far"`
  * `speed`: `0.05` ถึง `1.0` (default: `0.5`)
  * `duration_sec`: `0.05` ถึง `5.0` วินาที (default: `0.5`)

#### ตัวอย่าง Request:
```json
{
  "camera": "thermal",
  "action": "auto"
}
```

#### ตัวอย่าง Response:
```json
{
  "status": "ok",
  "camera": "thermal",
  "action": "auto",
  "speed": 0.5,
  "duration_sec": 0.5,
  "clamped": false,
  "results": {
    "focus_mode": "auto",
    "sharpness_score": 348.5
  }
}
```

---

## 4. สั่งการกวาดตรวจ (`POST /api/sweep/control`)

* **Endpoint:** `POST http://<SERVER_IP>:5005/api/sweep/control`
* **Parameters (JSON):**
  * `action`: `"start"` | `"pause"` | `"resume"` | `"stop"` | `"status"`
  * *(เฉพาะ action="start" - Optional):*
    * `az_start`, `az_end`: ช่วงมุมกวาดแนวนอน (องศา เช่น `-90.0`, `90.0`)
    * `alt_start`, `alt_end`: ช่วงมุมก้ม-เงย (องศา เช่น `-10.0`, `0.0`) หรือส่ง `alt` ค่าเดี่ยว
    * `speed`: ความเร็วกวาด (องศา/วินาที เช่น `1.0`)
    * `focal_length_mm` (หรือ `zoom_pct`): ระยะเลนส์กล้อง Thermal ที่ใช้กวาดตรวจ (มม.)

#### ตัวอย่าง Request (`start`):
```json
{
  "action": "start",
  "az_start": -90.0,
  "az_end": 90.0,
  "alt_start": -10.0,
  "alt_end": 0.0,
  "speed": 1.0,
  "focal_length_mm": 60.0
}
```

#### ตัวอย่าง Response:
```json
{
  "status": "ok",
  "action": "start",
  "mission_state": "SEARCH_SWEEP",
  "is_paused": false,
  "current_position": {
    "azimuth_deg": 45.2,
    "altitude_deg": -5.0
  },
  "active_parameters": {
    "az_start": -90.0,
    "az_end": 90.0,
    "alt_start": -10.0,
    "alt_end": 0.0,
    "speed_deg_s": 1.0,
    "focal_length_mm": 60.0
  },
  "trajectory": {
    "layers_count": 4,
    "alt_layers": [-10.0, -6.67, -3.33, 0.0],
    "alt_step_deg": 4.72,
    "az_step_deg": 5.89,
    "fov": {
      "h_deg": 7.36,
      "v_deg": 5.9
    },
    "est_total_sec": 1421,
    "est_total_min": 23.7
  }
}
```

---

## 5. ตั้งค่าการตรวจจับแบบเรียลไทม์ (`/api/detector/config`)

ใช้สำหรับปรับค่าความไวความร้อน (Hotspot Threshold) และสลับเปิด/ปิด Dynamic (Adaptive) Saliency Thresholding ระหว่างการสแกนหรือตรวจจับ โดยระบบจะปรับใช้ในหน่วยความจำทันทีในเฟรมถัดไป

* **Endpoint:** `/api/detector/config`
* **Methods:** `GET`, `POST`
* **Parameters (JSON Body สำหรับ POST):**
  * `hotspot_threshold` *(Integer, 50 - 255)*: ค่าเกณฑ์ความสว่างความร้อน (Luminance)
  * `use_adaptive` *(Boolean)*: เปิด (`true`) หรือปิด (`false`) Dynamic / Adaptive Saliency
  * `adaptive_k` *(Float, 1.0 - 6.0, Optional)*: ตัวคูณส่วนเบี่ยงเบนมาตรฐาน (Std Dev Multiplier)
  * `adaptive_min_threshold` *(Integer, 50 - 255, Optional)*: ค่าเกณฑ์ขั้นต่ำของการคำนวณ Adaptive

#### ตัวอย่าง Request (`POST`):
```json
{
  "hotspot_threshold": 170,
  "use_adaptive": true
}
```

#### ตัวอย่าง Response (`200 OK` ทั้ง `GET` และ `POST`):
```json
{
  "status": "ok",
  "saved_to_disk": false,
  "detector_config": {
    "hotspot_threshold": 170,
    "use_adaptive": true,
    "adaptive_k": 3.0,
    "adaptive_min_threshold": 150
  }
}
```

---

## 6. Python Reference Code

### 6.1 Ingest Receiver (FastAPI)
```python
import json
from fastapi import FastAPI, Request, Response, status

app = FastAPI(title="PTZ Receiver")

@app.post("/api/camera-stream/frame/{camera_id}")
async def receive_camera_frame(camera_id: str, request: Request):
    meta = json.loads(request.headers.get("X-Camera-Metadata", "{}"))
    focal_mm = meta.get("focal_length_mm", 0.0)
    state = meta.get("mission_state", "IDLE")
    az = meta.get("azimuth_deg", 0.0)
    jpeg_bytes = await request.body()

    is_locked = state in ("TARGET_CENTERING", "ZOOMING_IN", "VERIFYING_FOCUS", "DEEP_CONFIRMATION")
    speed_scale = 31.0 / max(31.0, focal_mm) if focal_mm > 0 else 1.0

    return Response(status_code=status.HTTP_202_ACCEPTED)
```

### 6.2 Control Client
```python
import requests

SERVER = "http://192.168.0.50:5005"

class PTZClient:
    @staticmethod
    def set_zoom(camera="thermal", percent=None, focal_mm=None, zoom_x=None):
        payload = {"camera": camera}
        if percent is not None: payload["zoom_pct"] = percent
        elif focal_mm is not None: payload["focal_mm"] = focal_mm
        elif zoom_x is not None: payload["zoom_x"] = zoom_x
        return requests.post(f"{SERVER}/api/camera/zoom", json=payload, timeout=3.0).json()

    @staticmethod
    def set_focus(camera="thermal", action="auto", speed=0.5, duration_sec=0.5):
        payload = {"camera": camera, "action": action, "speed": speed, "duration_sec": duration_sec}
        return requests.post(f"{SERVER}/api/camera/focus", json=payload, timeout=3.0).json()

    @staticmethod
    def sweep(action="start", az_start=-90.0, az_end=90.0, alt_start=-10.0, alt_end=0.0, speed=1.0, focal_mm=60.0):
        payload = {"action": action}
        if action == "start":
            payload.update({
                "az_start": az_start, "az_end": az_end,
                "alt_start": alt_start, "alt_end": alt_end,
                "speed": speed, "focal_length_mm": focal_mm
            })
        return requests.post(f"{SERVER}/api/sweep/control", json=payload, timeout=4.0).json()

    @staticmethod
    def set_detector(hotspot_threshold=None, use_adaptive=None, adaptive_k=None):
        payload = {}
        if hotspot_threshold is not None: payload["hotspot_threshold"] = hotspot_threshold
        if use_adaptive is not None: payload["use_adaptive"] = use_adaptive
        if adaptive_k is not None: payload["adaptive_k"] = adaptive_k
        return requests.post(f"{SERVER}/api/detector/config", json=payload, timeout=3.0).json()

    @staticmethod
    def get_detector():
        return requests.get(f"{SERVER}/api/detector/config", timeout=3.0).json()

if __name__ == "__main__":
    print(PTZClient.set_zoom(camera="thermal", percent=50.0))
    print(PTZClient.set_focus(camera="thermal", action="auto"))
    print(PTZClient.set_detector(hotspot_threshold=175, use_adaptive=True))
    res = PTZClient.sweep("start", az_start=-90, az_end=90, alt_start=-10, alt_end=0, speed=1.0, focal_mm=60.0)
    traj = res.get("trajectory", {})
    print(f"Sweep Started: {traj.get('layers_count')} Layers | Time: {traj.get('est_total_min')} min/pass")
```
