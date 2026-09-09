# Station Backup Pull API

เอกสารนี้เป็นสัญญา integration สำหรับ Receiver/Server ที่จะสำรองข้อมูลจาก Fire Detector Station วันละครั้ง โดย Server เป็นฝ่ายเชื่อมเข้าหา Station ผ่าน Tailscale และ Station จะไม่ลบข้อมูลต้นทางจนกว่า Server จะยืนยัน checksum และ durable receipt แล้วเท่านั้น

## หลักประกันด้านข้อมูล

ลำดับสถานะของหนึ่ง backup คือ:

```text
candidate -> ready -> confirmed -> deleted
               |          |
          download ได้   DELETE ได้
```

- `ready`: Station สร้าง immutable snapshot สำเร็จและพร้อมให้ดาวน์โหลด
- `confirmed`: Server ยืนยันว่าไฟล์ที่จัดเก็บมี SHA-256 ตรงกันและมี durable receipt แล้ว แต่ไฟล์และข้อมูลต้นทางยังไม่ถูกลบ
- `deleted`: Station ลบ archive ชั่วคราวและ purge เฉพาะแถวฐานข้อมูลที่เวลาไม่เกิน `coverage_through_ms`
- ข้อมูลใหม่ที่เข้าหลังสร้าง snapshot มี timestamp มากกว่า cutoff และไม่ถูก DELETE
- หากคำขอ confirm มี checksum ไม่ตรง Station จะตอบ `409` และไม่เปลี่ยนสถานะ
- หากยังไม่ confirmed คำสั่ง DELETE จะตอบ `409` และไม่ลบข้อมูลใด ๆ
- API ไม่สั่ง Stop, Disable หรือ Restart ระบบควบคุม Mount

## ข้อมูลใน bundle

ไฟล์ที่ดาวน์โหลดเป็น `tar.gz` และประกอบด้วย:

- `manifest.json`
- SQLite online snapshot ที่ `telemetry/mount_telemetry.sqlite3`
- `configuration/AppSetting.JSON` ซึ่งเก็บเฉพาะ path ของ credential ไม่เก็บ shared secret
- runtime state ขนาดเล็กใน `control`, `mission`, `station_configuration`
- ODrive configuration backups

ไม่รวม shared secret, certificate private key, system journal, terrain/pointing cache และวิดีโอที่มี media workflow แยกอยู่แล้ว

## Network และ identity

- ตัวอย่าง Station ปัจจุบัน: `http://<station-tailscale-ip>:8000`
- ควรอนุญาตพอร์ต 8000 เฉพาะ Receiver ผ่าน Tailscale ACL
- Station ตรวจ source address ซ้ำที่ application layer: Backup API ปฏิเสธ IPv4/IPv6 ที่ไม่ใช่ช่วง Tailscale แม้ dashboard หลักยังเปิดใช้บน LAN
- Tailscale เข้ารหัส transport; ทุก request ยังต้องมี HMAC-SHA256 เพื่อยืนยันตัว Server
- ใช้ `device_id` และ shared secret ชุดเดียวกับ `mount_agent.remote`
- อ่าน secret จาก protected secret store ของ Server ห้ามใส่ใน source code, URL, log หรือ request body
- Station ประกาศ service นี้ใน Remote Device Protocol `hello.payload.services.backup_pull_api` โดยมี `url`/`base_url`, `base_path`, version, authentication และ transport ปัจจุบัน

## Signed request

ทุก endpoint ใต้ `/api/v1/backups` ต้องมี headers:

```text
X-Narit-Device-Id: <device_id>
X-Narit-Timestamp: <Unix seconds>
X-Narit-Nonce: <random URL-safe value 16-128 chars>
X-Narit-Content-SHA256: <lowercase SHA-256 of exact request body bytes>
X-Narit-Signature: <lowercase HMAC-SHA256 hex>
```

สำหรับ GET/DELETE ที่ไม่มี body ค่า content hash คือ SHA-256 ของ empty bytes:

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Canonical input เป็น UTF-8 หกบรรทัดและไม่มี newline ต่อท้าย:

```text
device_id
HTTP_METHOD_UPPERCASE
URL_PATH_WITHOUT_QUERY
timestamp
nonce
content_sha256
```

ตัวอย่าง Python สำหรับสร้าง headers:

```python
import hashlib
import hmac
import secrets
import time

def signed_headers(device_id: str, secret: bytes, method: str, path: str, body: bytes):
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    body_sha256 = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((device_id, method.upper(), path, timestamp, nonce, body_sha256))
    signature = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Narit-Device-Id": device_id,
        "X-Narit-Timestamp": timestamp,
        "X-Narit-Nonce": nonce,
        "X-Narit-Content-SHA256": body_sha256,
        "X-Narit-Signature": signature,
    }
```

Station ยอมรับ clock skew ไม่เกิน 5 นาทีและ nonce ใช้ซ้ำไม่ได้ในช่วง replay window ดังนั้น Server ต้อง sync เวลาและสร้าง nonce ใหม่ทุก request รวมถึงการ retry

## Endpoints

### 1. ตรวจ candidate และรายการ backup

```text
GET /api/v1/backups
```

ตัวอย่าง response:

```json
{
  "ok": true,
  "candidate": {
    "available": true,
    "from_ms": 1787700000000,
    "through_ms": 1787786400000,
    "row_count": 864123,
    "database_bytes": 126550016,
    "tables": {}
  },
  "backups": []
}
```

หาก `candidate.available` เป็น `false` และไม่มี backup สถานะ `ready`/`confirmed` Server จบงานรอบนั้นได้โดยไม่สร้างไฟล์

### 2. ขอสร้าง immutable snapshot

```text
POST /api/v1/backups
Content-Type: application/json

{"request_id":"daily-iriv-production-2026-08-27"}
```

`request_id` ต้องไม่ซ้ำและใช้เป็น idempotency key หาก retry ด้วยค่าเดิมจะได้ `backup_id` เดิม Station อนุญาต active backup ครั้งละหนึ่งชุดเพื่อไม่ให้ archive สะสม

Response `201`:

```json
{
  "ok": true,
  "backup": {
    "backup_id": "20260827T010000Z-a1b2c3d4e5f6",
    "request_id": "daily-iriv-production-2026-08-27",
    "status": "ready",
    "byte_size": 24567890,
    "sha256": "<64 lowercase hex>",
    "coverage_from_ms": 1787700000000,
    "coverage_through_ms": 1787786400000,
    "row_count": 864123
  }
}
```

### 3. ดาวน์โหลด

```text
GET /api/v1/backups/<backup_id>/download
```

Response body เป็น raw `tar.gz` และมี headers:

```text
X-Backup-Id: <backup_id>
X-Backup-SHA256: <sha256>
Cache-Control: private, no-store
```

Server ต้องดาวน์โหลดลง temporary filename, `fsync`, คำนวณ SHA-256 จาก byte ที่ได้รับ และเปรียบเทียบกับทั้ง metadata และ `X-Backup-SHA256` ก่อน atomic rename/upload เข้า durable storage

ห้าม confirm จาก HTTP 200 เพียงอย่างเดียว ต้องตรวจ checksum และยืนยันว่า object store/database ฝั่ง Server commit สำเร็จแล้ว

### 4. ยืนยัน durable storage

```text
POST /api/v1/backups/<backup_id>/confirm
Content-Type: application/json

{
  "sha256":"<sha256 calculated by Server>",
  "receipt_id":"receiver-object-or-transaction-id"
}
```

`receipt_id` ต้องอ้างถึง object/transaction ที่ Server สามารถ audit และ restore ได้ การ confirm ไม่ลบข้อมูล เป็นเพียงการเปิดสิทธิ์ให้ DELETE

### 5. ลบข้อมูล local ที่ยืนยันแล้ว

```text
DELETE /api/v1/backups/<backup_id>
```

Station จะ:

1. ตรวจว่า backup มีสถานะ `confirmed` และมี receipt
2. purge แถวจากทุก telemetry table ถึง `coverage_through_ms`
3. เก็บข้อมูลใหม่หลัง cutoff ไว้
4. ลบไฟล์ bundle local
5. บันทึก audit state เป็น `deleted`

DELETE เป็น idempotent; retry backup ที่ `deleted` จะตอบ record เดิมโดยไม่ลบข้อมูลรอบใหม่

## Daily Server workflow

แนะนำให้ Server ทำทุก 24 ชั่วโมงโดยมี lock ต่อ `device_id`:

1. GET list
2. หากมี `ready` ให้ทำต่อจาก download; หากมี `confirmed` ให้ retry DELETE
3. หากไม่มี active backup และ candidate available ให้ POST create ด้วย request ID รายวัน
4. ดาวน์โหลดไป temporary storage พร้อม stream hash
5. ตรวจ SHA-256, เปิด `tar.gz` เพื่อตรวจ `manifest.json` และใช้ safe extraction ที่ปฏิเสธ absolute path/`..`/symlink
6. commit เข้า durable storage และสร้าง receipt
7. POST confirm
8. DELETE
9. GET list อีกครั้งเพื่อยืนยันว่าสถานะเป็น `deleted` และข้อมูลใหม่ (ถ้ามี) ยังเป็น candidate รอบถัดไป

หากขั้นตอนใดล้มเหลว ห้ามข้ามไป DELETE ให้ retry จากสถานะล่าสุดด้วย nonce ใหม่

## Error codes สำคัญ

| HTTP | Code | การจัดการ |
| --- | --- | --- |
| 403 | `BACKUP_TAILSCALE_REQUIRED` | เชื่อมต่อใหม่ผ่าน Tailnet IP/route ของ Station |
| 401 | `BACKUP_AUTH_FAILED` | ตรวจ secret/device ID/canonical input |
| 401 | `BACKUP_AUTH_EXPIRED` | sync เวลาแล้ว retry ด้วย timestamp/nonce ใหม่ |
| 409 | `BACKUP_REPLAY` | สร้าง nonce ใหม่ |
| 409 | `BACKUP_ALREADY_ACTIVE` | ทำ active backup เดิมให้จบก่อน |
| 409 | `BACKUP_CHECKSUM_MISMATCH` | ดาวน์โหลดใหม่ ห้าม confirm/delete |
| 409 | `BACKUP_NOT_CONFIRMED` | confirm durable receipt ก่อน |
| 410 | `BACKUP_FILE_MISSING` | แจ้ง operator; ห้าม purge source |
| 503 | `BACKUP_STATE_UNAVAILABLE` | หยุด workflow และซ่อม state; API จะ fail closed |

## Retention และ storage policy ฝั่ง Station

- Runtime SQLite/WAL/SHM ถูก ignore จาก Git และไม่ใช้ Git LFS เป็นระบบ backup
- Telemetry ที่ยังไม่ confirmed จะไม่ถูกลบตามเวลาโดยอัตโนมัติ
- หลัง DELETE พื้นที่ว่างภายใน SQLite จะถูกนำกลับมาใช้กับข้อมูลใหม่ แม้ขนาดไฟล์อาจไม่ลดทันที
- Journal ถูกจำกัดที่ 512 MB/7 วัน และ high-rate motion success logs อยู่ระดับ DEBUG; warning/error และ safety stop ยังเก็บตามปกติ
- ควรแจ้งเตือน Server หากไม่ได้ backup สำเร็จเกิน 48 ชั่วโมงหรือ Station storage เกิน 75%

ติดตั้งเพดาน journal โดยไม่ต้อง restart Fire Detector service:

```bash
sudo install -d -o root -g root -m 0755 /etc/systemd/journald.conf.d
sudo install -o root -g root -m 0644 \
  deploy/fire-detector-journald.conf \
  /etc/systemd/journald.conf.d/fire-detector.conf
sudo systemctl restart systemd-journald.service
```

การเปลี่ยนโค้ด API และระดับ motion log จะมีผลเมื่อ Fire Detector service เริ่ม process รุ่นใหม่ใน maintenance window ครั้งถัดไป ส่วนการ restart `systemd-journald` ข้างต้นไม่ restart process ควบคุม Mount

## Acceptance test ฝั่ง Server

ก่อนเปิด schedule จริง ให้ทดสอบอย่างน้อย:

- signature ถูก/ผิด, timestamp หมดอายุ และ replay nonce
- retry create ด้วย request ID เดิม
- download ขาดกลางทางแล้ว resume workflow โดยไม่ confirm
- checksum ผิดต้องไม่ confirm
- DELETE ก่อน confirm ต้องถูกปฏิเสธ
- หลัง confirm + DELETE ข้อมูลใหม่หลัง cutoff ยังอยู่
- restart Station ระหว่าง ready/confirmed แล้ว workflow ดำเนินต่อจาก state เดิมได้
