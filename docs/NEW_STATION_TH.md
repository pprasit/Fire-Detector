# ติดตั้ง Fire Detector บน Raspberry Pi เครื่องใหม่

ชุดนี้รวม dashboard/ODrive และระบบกล้อง Thermal + Visible, ตรวจจับไฟ,
โมเดล NCNN, Mission และ Panorama อยู่ใน repository เดียวกันแล้ว
รองรับการติดตั้งบน Raspberry Pi OS Bookworm 64-bit สำหรับ IRIV PiControl
CM4/CM5 ตามตัวติดตั้งเดิม ส่วน Raspberry Pi บอร์ดปกติให้ใช้ `--skip-iriv-support`

## 1. ดึงซอร์สและติดตั้งระบบพื้นฐาน

ตั้ง username `pi` ตอนลง OS แล้วต่ออินเทอร์เน็ต จากนั้น:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone --depth 1 --branch main https://github.com/pprasit/Fire-Detector.git /home/pi/Public/Fire-Detector
cd /home/pi/Public/Fire-Detector
sudo bash scripts/bootstrap_iriv.sh --hostname fire-station-02 --skip-codex --skip-tailscale --disable-updater
sudo reboot
```

หากต้องการ Tailscale ให้เอา `--skip-tailscale` ออกและ login อุปกรณ์ใหม่
hostname ของแต่ละเครื่องต้องไม่ซ้ำกัน ตัวติดตั้งจะสร้าง `AppSetting.JSON`
จากตัวอย่างสำหรับเครื่องใหม่ โดยยังอยู่ใน simulation และไม่เชื่อม Receiver
อัตโนมัติ เปิด dashboard ที่ `http://fire-station-02.local:8000`

## 2. ตรวจและกำหนดอุปกรณ์จริง

ต่อ ODrive ทั้งสองตัวผ่าน USB และจ่ายไฟมอเตอร์ ต่อกล้องเข้าวง LAN เดียวกัน:

```bash
cd /home/pi/Public/Fire-Detector
.venv/bin/python scripts/station_doctor.py --probe-odrive --discover-cameras
```

คำสั่งอ่านข้อมูลเท่านั้น ไม่สั่งหมุนหรือ calibrate มอเตอร์ แสดง USB, serial ports,
video devices, serial ของ ODrive ในรูปเลขฐานสิบ และ IP ของกล้อง ONVIF
กล้องที่ปิด discovery หรืออยู่คนละ subnet อาจไม่ตอบ ให้ใส่ IP เองได้
exit code 1 หมายถึงยังมีรายการต้องตั้งค่า ไม่ได้แปลว่าติดตั้งเสียเสมอไป

ในหน้า Settings ระบุ `drive_serials.azimuth_serial` และ
`drive_serials.altitude_serial` ตามแกนจริง โดยใช้ `serial_decimal` จากผลตรวจ
ห้ามใช้ลำดับ USB เพื่อเดาว่าเป็นแกนใด ตรวจตำแหน่งศูนย์ อัตราทด ทิศทาง
กระแสสูงสุด ขอบเขตการเคลื่อนที่ และ limit switch ให้ตรงกับชุดประกอบใหม่
แล้วจึงปิด simulation การ calibrate และเริ่มหมุนต้องทำกับฮาร์ดแวร์จริงทีละแกน
ตัวติดตั้งไม่คัดลอกค่าชดเชยมอเตอร์จากเครื่องต้นแบบ

## 3. ตั้งค่ากล้องและติดตั้งระบบตรวจจับ

```bash
cd /home/pi/Public/Fire-Detector
cp -n camera_runtime/system_settings.example.json camera_runtime/system_settings.json
chmod 600 camera_runtime/system_settings.json
nano camera_runtime/system_settings.json
```

กรอก `ip`, `onvif_port`, `username`, `password`, `rtsp_url` และ
`main_rtsp_url` ของกล้องแต่ละตัวตามคู่มือกล้อง ถ้ารหัสผ่านอยู่ใน RTSP URL
ต้อง percent-encode อักขระพิเศษ thermal ใช้ ONVIF port 8080 และ visible
ใช้ port 80 เป็นค่าเริ่มต้น เปลี่ยนได้ในไฟล์นี้
คง `mission.auto_sentry_enabled=false` ระหว่างตรวจรับ
ปรับ mount limits ใน `mount` ให้สอดคล้องกับ dashboard ด้วย

```bash
sudo bash scripts/install_camera_runtime.sh
systemctl is-active fire-detector.service fire-detector-camera.service
.venv/bin/python scripts/station_doctor.py --probe-odrive
```

ตัวติดตั้งติดตั้ง FFmpeg และ Python dependencies พร้อมเปิดระบบกล้องตอนบูต
หน้า camera runtime อยู่ที่ `http://fire-station-02.local:5005`
ภาพจะถูกส่งเข้า dashboard port 8000 ผ่าน loopback ในเครื่องเดียวกัน
Telegram และ LLM ถูกปิดไว้จนกว่าจะตั้ง credentials ของเครื่องใหม่
ไฟล์ settings ทั้งสองไฟล์มีข้อมูลเฉพาะสถานีและถูก ignore จาก Git

## 4. ตรวจรับก่อนเริ่มงานจริง

- ต้องแสดงภาพสดจริงทั้ง Thermal และ Visible และสถานะเชื่อมต่อถูกต้อง
- Dashboard ต้องเห็น ODrive ทั้งสองแกน มี DC bus power และไม่มี drive error
- ตรวจ limit switch, ทิศทาง, ศูนย์, ขอบเขต และการหยุด ก่อนทดลอง scan
- ตั้งชื่อสถานี พิกัดจริง ความสูง และ north offset; DEM ที่แถมมาเป็นพื้นที่
  เครื่องต้นแบบ หากย้ายพื้นที่ให้เตรียม DEM ใหม่ด้วย `scripts/build_station_dem.py --help`
- ทดสอบโหมดตรวจจับด้วยเป้าความร้อนที่ควบคุมได้ ก่อนเปิด autonomous sentry
- การเชื่อม Receiver ต้องมี device ID ไม่ซ้ำและ enroll ใหม่ตาม
  [STATION_ONBOARDING.md](STATION_ONBOARDING.md) ห้ามคัดลอก shared secret เครื่องเดิม
- บริการส่ง RTSP และ remote control เป็นตัวเลือกหลัง enrollment:
  ใช้ runbook ดังกล่าว ไม่เปิด simulator และ remote motion โดยอัตโนมัติ

`station_doctor` ช่วยตรวจการตั้งค่าและการพบอุปกรณ์ ไม่ใช่การรับรองภาพสด
หรือการ calibrate ฮาร์ดแวร์ เครื่องใหม่ยังต้องผ่านรายการตรวจรับข้างต้น

## อัปเดตเครื่องที่ติดตั้งแล้ว

สำหรับเครื่องที่ใช้รุ่นนี้แล้ว:

```bash
cd /home/pi/Public/Fire-Detector
git pull --ff-only origin main
.venv/bin/python -m pip install -r camera_runtime/requirements.txt
```

ก่อน restart ให้หยุด scan/sentry และสั่ง stop จากหน้าควบคุมให้เรียบร้อย
แล้วจึง restart `fire-detector.service` และ `fire-detector-camera.service`
การ pull ไม่ restart ระบบที่กำลังทำงานให้อัตโนมัติ

**ย้ายจากรุ่นเก่าที่ track settings/data:** ก่อน pull ให้สำรอง `AppSetting.JSON`
และ `data/` นอก checkout เพราะรุ่นนี้เลิก track ไฟล์ประจำเครื่อง
Git อาจลบไฟล์ที่เคย track ระหว่างอัปเดต หลัง pull ให้นำข้อมูลที่สำรองกลับมา
อย่า reset หรือ clean เพื่อฝืนผ่าน local changes
เครื่องต้นแบบที่ยังรัน `wildlife-detection-runtime.service` จาก Desktop
ยังใช้ตำแหน่งเดิมได้ การติดตั้งชุดใหม่นี้ไม่ได้ย้ายหรือ restart เครื่องต้นแบบ
เมื่อต้องการย้าย ให้หยุด scan/sentry และ stop ก่อนหยุดบริการเก่า
คัดลอก settings เฉพาะเครื่องอย่างปลอดภัย แล้วใช้ตัวติดตั้งระบบกล้องข้างต้น

## ทดสอบซอฟต์แวร์

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q
node --test tests/test_mission_terrain.mjs
```

Node ใช้ทดสอบคณิตศาสตร์ของหน้าจอเท่านั้น ไม่จำเป็นสำหรับรันระบบบน Pi
ชุดทดสอบกล้องบางไฟล์เป็น integration กับกล้อง/เครือข่ายจริง
เลือกเฉพาะ unit tests เมื่อต้องการทดสอบแบบ offline
