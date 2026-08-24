# Mount Agent API

Mount Agent มีสองช่องทางที่ใช้ JSON โครงสร้างเดียวกัน:

- Local Control Interface: NDJSON ผ่าน Unix socket `/run/fire-detector/mount-agent.sock`
- Remote Device Protocol: Mount เป็นฝ่ายเชื่อม TCP/TLS ออกไปยัง Socket Receiver จึงไม่เปิดพอร์ตรับคำสั่งจาก LAN/Internet

ทุกข้อความจบด้วย newline (`\n`) ขนาดไม่เกิน 64 KiB และใช้ protocol version `1.0`

## Transport และ latency

- Client บนเครื่อง Mount ควรใช้ Unix domain socket แบบ persistent เป็นช่องทาง control ที่เร็วที่สุดและไม่เปิด network port
- งานระยะไกลใช้ persistent TCP/TLS connection ที่ Mount เชื่อมออกไปหา Receiver จึงไม่ handshake ใหม่ทุกคำสั่งและใช้ได้หลัง router/CGNAT
- Local subscription ตั้ง `interval_ms` ได้ 100–60,000 ms (สูงสุด 10 Hz); Remote telemetry ตั้ง `telemetry_sec` ได้ต่ำสุด 0.1 วินาที
- WebSocket `/ws/status` ของ dashboard เป็น read-only status stream ไม่ใช่ Mount Agent control transport

TCP เป็น byte stream: client ต้องสะสมข้อมูลจนพบ newline ห้ามสมมติว่า `recv()` หนึ่งครั้งคือ JSON หนึ่ง message และควรใช้ connection เดิมตลอด lease/control session

## รูปแบบคำสั่ง

```json
{
  "version": "1.0",
  "type": "command",
  "message_id": "ค่าที่ไม่ซ้ำกัน",
  "action": "mount.get_status",
  "params": {}
}
```

คำตอบมี `correlation_id` ตรงกับ `message_id`, ค่า `ok` และ `result` หรือ `error`

## Control lease

คำสั่งที่ทำให้ Mount เคลื่อนที่หรือเปลี่ยน configuration ต้องขอสิทธิ์ควบคุมก่อน:

1. `control.acquire` พร้อม `{"lease_ms":5000}`
2. ส่ง `lease_id` ที่ได้ใน `control_lease_id`
3. เรียก `control.renew` ก่อนหมดเวลา
4. จบงานด้วย `control.release`

คำสั่งหยุดและ disable ไม่ต้องมี lease เพื่อให้ระบบความปลอดภัยหยุด Mount ได้เสมอ คำสั่งความเร็วที่ไม่เป็นศูนย์ต้องมี `command_timeout_ms` ระหว่าง 100–5000 ms; หากไม่มีคำสั่งใหม่ ระบบจะสั่งความเร็วเป็นศูนย์อัตโนมัติ

## คำสั่ง

- System: `system.hello`, `system.ping`, `system.get_info`, `system.get_health`, `system.get_capabilities`
- Mount: `mount.get_status`, `mount.enable`, `mount.disable`, `mount.stop`, `mount.goto`, `mount.set_velocity`
- Axis: `axis.enable`, `axis.disable`, `axis.stop`, `axis.goto`, `axis.set_velocity`
- Pointing: `pointing.goto_altaz`
- Calibration: `calibration.start`, `calibration.stop`, `calibration.get_status`
- Tuning: `tuning.apply`, `tuning.save`
- Telemetry: `subscribe`, `unsubscribe`

ตัวอย่าง Goto:

```json
{"version":"1.0","type":"command","message_id":"cmd-2","action":"mount.goto","control_lease_id":"LEASE","params":{"azimuth_deg":30,"altitude_deg":15,"max_velocity_deg_per_sec":10}}
```

ตัวอย่าง Velocity:

```json
{"version":"1.0","type":"command","message_id":"cmd-3","action":"axis.set_velocity","control_lease_id":"LEASE","params":{"axis":"azimuth","velocity_deg_per_sec":2,"command_timeout_ms":500}}
```

Telemetry topics ได้แก่ `mount.status`, `axis.telemetry`, `sensor.status`, `drive.status`, `fault` และ `calibration.status`

## Camera Frame Ingest API

ระบบหลักไม่เชื่อมต่อกล้อง Thermal/Visible โดยตรง โมดูลกล้องภายนอกเป็นผู้เชื่อมต่อกล้องทั้งสองและส่งภาพ encoded เข้ามาทาง HTTP API:

### วิธีแนะนำสำหรับ 60 FPS: Binary WebSocket

ห้ามส่ง byte array เป็น JSON array ของตัวเลขและไม่ควรใช้ Base64 สำหรับสตรีมความถี่สูง ให้เปิด connection เดียวไปที่:

```text
ws://192.168.1.105:8000/ws/camera-stream?role=producer&source=live
```

หนึ่ง binary WebSocket message ต่อหนึ่งเฟรมมีโครงสร้าง:

```text
[uint32 big-endian: ความยาว JSON header]
[JSON header แบบ UTF-8]
[JPEG/PNG bytes ที่เหลือทั้งหมด]
```

JSON header มี `camera`, `mime_type`, `metadata` และ `sha256` (แนะนำ) แต่ byte ของภาพอยู่นอก JSON ตัวอย่างพร้อมใช้คือ `API-Doc/examples/04_publish_camera_binary_ws.py`:

```bash
.venv/bin/python API-Doc/examples/04_publish_camera_binary_ws.py \
  --camera thermal --frame thermal-frame.jpg --fps 60
```

WebSocket/TCP รักษาลำดับและส่งข้อมูลแบบ reliable ส่วน `producer_sequence` ใช้ตรวจเฟรมที่หายจากต้นทาง และ `sha256` ใช้ยืนยัน payload ระดับ application

ต้องปิด WebSocket per-message compression (`compression=None` ใน Python) เพราะ JPEG/PNG บีบอัดมาแล้ว การบีบอัดซ้ำเปลือง CPU และทำให้อัตราเฟรมลดลงได้มาก

### วิธี HTTP สำหรับ compatibility/ทดสอบ

```text
POST http://192.168.1.105:8000/api/camera-stream/frame/thermal?source=live
POST http://192.168.1.105:8000/api/camera-stream/frame/visible?source=live
Content-Type: image/jpeg หรือ image/png
X-Camera-Metadata: JSON object (ไม่บังคับ)
Body: raw JPEG/PNG bytes
```

ตัวอย่าง `curl`:

```bash
curl -X POST "http://192.168.1.105:8000/api/camera-stream/frame/thermal?source=live" \
  -H "Content-Type: image/jpeg" \
  -H 'X-Camera-Metadata: {"captured_at":"2026-08-11T10:30:00.000Z","width":640,"height":512,"producer_sequence":1}' \
  --data-binary @thermal-frame.jpg
```

เมื่อรับสำเร็จ API ตอบ HTTP `202 Accepted`:

```json
{"ok":true,"camera":"thermal","source":"live","sequence":1234}
```

ข้อกำหนดสำคัญ:

- `camera` ต้องเป็น `thermal` หรือ `visible`
- ขนาดแต่ละเฟรมไม่เกิน 16 MiB
- ระบบเก็บเฉพาะเฟรมล่าสุดของแต่ละกล้องเพื่อไม่ให้คิวและ latency สะสม
- ตรวจ receiver ได้จาก `GET /api/camera-stream`
- ดูภาพได้จาก `/api/camera-mjpeg/live/thermal` และ `/api/camera-mjpeg/live/visible`
- ตัวอย่าง HTTP: `API-Doc/examples/03_publish_camera_frames.py`
- สำหรับประมาณ 60 FPS ให้ใช้ภาพที่ encode เป็น JPEG/PNG แล้วและเชื่อมต่อผ่าน LAN ที่เสถียร ห้ามส่ง raw sensor array มายัง endpoint นี้

รันตัวอย่าง:

```bash
.venv/bin/python API-Doc/examples/03_publish_camera_frames.py \
  --host 192.168.1.105 --camera thermal --frame thermal-frame.jpg --fps 60
```

## ทดลอง Local Interface

คำสั่งนี้อ่านสถานะเท่านั้นและไม่ทำให้ Mount เคลื่อนที่:

```bash
.venv/bin/python scripts/mount_agent_client.py mount.get_status
```

Local socket ตรวจ UID ของ process และอนุญาตเฉพาะ root หรือ UID เดียวกับ service พร้อมจำกัด 20 คำสั่งต่อวินาที

## Remote security และ configuration

Remote ปิดไว้โดยค่าเริ่มต้น กำหนด `mount_agent.remote` ใน `AppSetting.JSON` แล้วจึงเปิด `enabled` โดยต้องระบุ `host`, `port`, `device_id` และ secret ผ่านไฟล์ที่จำกัด permission หรือ environment variable เท่านั้น ห้ามเก็บ secret ตรงใน JSON

การเชื่อมต่อใช้ TLS 1.2 ขึ้นไป ตรวจ CA และ hostname รองรับ client certificate จากนั้นยืนยัน Device ID ด้วย HMAC-SHA256 challenge/nonce มี heartbeat, reconnect แบบ exponential backoff, command allowlist, message expiry, rate limit, duplicate ID protection และ control lease

ค่าเริ่มต้นของ Remote allowlist ไม่อนุญาต calibration/tuning การเปิดคำสั่งเหล่านี้ควรทำเฉพาะระบบส่วนกลางที่มี authorization และ audit log เพิ่มเติม

## สถานะการ verify (4 สิงหาคม 2026)

Automated integration test ครอบคลุม Unix socket จริง, response correlation, duplicate protection, control lease และ telemetry subscription โดยไม่สั่ง hardware รันซ้ำได้ด้วย:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

ก่อน production ยังต้องทำ supervised hardware acceptance test เพื่อตรวจทิศทางแกน, software/physical limits, emergency stop, velocity watchdog และ Receiver reconnection
