# คู่มืออ้างอิง ODrive, Motion และการแก้ Jitter

อัปเดตล่าสุด: 24 สิงหาคม 2026
สถานีต้นแบบ: NARIT#1
ขอบเขต: ODrive Pro, มอเตอร์ Azimuth/Altitude, absolute SPI encoder 14-bit และ Python control server

เอกสารนี้เป็น baseline สำหรับเครื่องปัจจุบันและใช้เป็นลำดับตรวจสอบเครื่องถัดไป ห้ามคัดลอกผล calibration ที่ผูกกับชุดมอเตอร์ สาย และ encoder ข้ามแกนหรือข้ามเครื่องโดยไม่ทำ calibration ใหม่

## สถานะหลังบันทึกล่าสุด

- บันทึก configuration ปัจจุบันลง flash ของ Drive ทั้งสองตัวแล้ว
- `save_configuration()` ทำให้ Drive reboot และได้ตรวจ readback หลัง reboot แล้ว
- Azimuth และ Altitude อยู่ `IDLE`, ไม่ armed, `active_errors=0`, `disarm_reason=0`
- Python services กลับมา `active` ทั้ง `fire-detector.service` และ `fire-detector-control.service`
- ระบบทำงานใน hardware mode (`simulation_mode=false`)
- Altitude แก้ `motor_model_l_dq_valid` จาก `true` เป็น `false` แล้ว ค่าอื่นใน backup ก่อน/หลังเหมือนเดิม

## Serial mapping

| แกน | Serial decimal | Serial ที่ใช้กับ odrivetool |
|---|---:|---|
| Azimuth | `59898476770354` | `367A336E3432` |
| Altitude | `59812575523890` | `366633513432` |

ต้องยืนยัน mapping นี้ก่อนเขียนค่าเสมอ การสลับ Drive จะทำให้ direction, position mapping และ commutation offset ผิดชุด

## Final hardware baseline

| Parameter | Azimuth | Altitude | หมายเหตุ |
|---|---:|---:|---|
| Encoder resolution | 14-bit | 14-bit | encoder รุ่นเดียวกัน |
| SPI baud rate | 1,000,000 | 1,000,000 | ค่าที่ใช้งานได้เสถียร |
| SPI mode / NCS GPIO | `1` / `17` | `1` / `17` | เหมือนกัน |
| Encoder bandwidth | `50 1/s` | `50 1/s` | ไม่ควรใช้แทนการแก้ SPI error |
| Pole pairs | `20` | `20` | เหมือนกัน |
| Torque constant | `0.29 Nm/A` | `0.29 Nm/A` | เหมือนกัน |
| Motor direction | `-1` | `+1` | ต่างกันตามการติดตั้ง ห้าม copy |
| Commutation scale | `-20` | `+20` | ต้องสอดคล้องกับ direction |
| Commutation offset | `-8.99467945098877` | `10.525343894958496` | ผลเฉพาะชุด ห้าม copy |
| Phase resistance | `0.0696004 Ω` | `0.0834530 Ω` | ผลวัดของแต่ละ assembly |
| Phase inductance | `99.599 µH` | `103.726 µH` | ผลวัดของแต่ละ assembly |
| R/L valid | true / true | true / true | อ่านกลับหลัง reboot แล้ว |
| `motor_model_l_d/q` | `0 / 0` | `0 / 0` | ไม่ได้ใช้ D/Q model |
| `motor_model_l_dq_valid` | false | false | ต้อง false เมื่อ Ld/Lq เป็นศูนย์ |
| Current-control bandwidth | `1000 1/s` | `1000 1/s` | เหมือนกัน |
| ODrive position gain | `8` | `20` | ค่าจริงใน Drive |
| ODrive velocity gain | `90` | `60` | ค่าที่ผู้ใช้ปรับและ flash ล่าสุด |
| ODrive velocity I gain | `1200` | `900` | ค่าที่ผู้ใช้ปรับและ flash ล่าสุด |
| Input-filter bandwidth | `50 1/s` | `50 1/s` | ค่าปัจจุบัน |
| Inertia | `0.12` | `0.12` | ค่าปัจจุบัน |
| Circular position mapper | true | false | Azimuth wrap; Altitude มีขอบเขต |

หน้า UI แสดง `Position Gain = 1.0` จาก software position algorithm ใน `AppSetting.JSON` ไม่ใช่ `controller.config.pos_gain` ใน ODrive ค่า ODrive จริงคือ Azimuth `8` และ Altitude `20` ตามตาราง ดังนั้นห้ามใช้ค่าหน้า UI ช่องนี้เป็นหลักฐานว่าค่า position loop ใน Drive เท่ากับ 1

## สิ่งที่พิสูจน์แล้วว่ามีผลจริง

### 1. SPI encoder clock

Azimuth เคยมี jitter ระหว่าง motion และหายหลังลด SPI clock จากประมาณ `1.6875 MHz` เป็น `1 MHz` โดยทดสอบ Jog ทั้งสองทิศแล้วเรียบขึ้นชัดเจน จึงใช้ `1 MHz` เป็น baseline ของ encoder รุ่นนี้ทั้งสองแกน

Altitude ที่ทดลอง `750 kHz` เกิด encoder errors จำนวนมากทันที จึง rollback กลับ `1 MHz` ห้ามสรุปว่า clock ยิ่งต่ำยิ่งดี ต้องดู error counter และคุณภาพ waveform ของแต่ละค่า

### 2. Encoder resolution ต้องตรงกับอุปกรณ์

encoder ทั้งสองแกนเป็น absolute 14-bit ค่า Altitude เคยอยู่ที่ 18-bit และถูกแก้เป็น 14-bit แล้ว หลังเปลี่ยนจำนวนบิตต้องทำ commutation/encoder offset calibration ของแกนนั้นใหม่ เพราะ mapping เดิมอ้างอิงสเกลผิด

### 3. Commutation offset เป็นค่าประจำ installation

Altitude ทำ commutation calibration ที่ `20 A` และทดสอบ motion ระยะประมาณ `+10°/-10°` แล้วออกตัวนุ่มและหยุดได้ ค่า firmware ที่ได้ต้องตรวจ branch ของเฟสก่อนใช้ ไม่ใช่ยอมรับทุก offset ที่ procedure คืนมา

ค่าที่ใช้งานจริงของ Altitude คือ `10.525343894958496` ซึ่งรวมการแก้ phase branch `+0.5 electrical turn` จากค่าดิบของรอบ calibration ล่าสุด ห้ามนำ offset ของ Azimuth มาใช้กับ Altitude

### 4. `motor_model_l_dq_valid` ของ Altitude เคยถูกเปิดผิด

วันที่ 21 สิงหาคมมีสคริปต์ทดลองตั้ง `motor_model_l_dq_valid=true` จากความเข้าใจผิดว่าเป็น aggregate validity ของ phase R/L แต่ flag นี้หมายถึง D/Q inductance model ในขณะที่ `motor_model_l_d=0` และ `motor_model_l_q=0`

แก้เป็น `false` และ save/readback แล้วเมื่อ 24 สิงหาคม Feed-forward (`wL`, `bEMF`, `dI/dt`) และ field weakening ปิดอยู่ทั้งหมด จึงยังไม่ควรอ้างว่า flag นี้เป็นสาเหตุเดียวของ jitter แต่ configuration เดิมผิดและจะมีความเสี่ยงทันทีหากเปิด feature ที่ใช้ D/Q model

### 5. Single-owner hardware I/O และ command arbitration

ทุก transport ได้แก่ Web UI, REST/API, local IPC และ remote control ต้องเข้าทาง `MotionCommandManager` และ `HardwareIOQueue` เท่านั้น

- คำสั่งปกติเรียง FIFO
- Stop/Disable ใช้ safety priority และ invalidates คำสั่งเก่าที่รออยู่
- control setpoint ที่ใหม่กว่าสามารถ supersede setpoint เก่าที่ยังค้างใน queue
- มี thread เดียวเป็นเจ้าของ USB/ODrive I/O
- telemetry ถูก poll จาก owner loop ครั้งเดียว แล้ว UI, report และ motion algorithm อ่าน snapshot กลาง
- command acknowledgement ไม่อ่าน hardware เต็มชุดซ้ำ

การออกแบบนี้ตัด lock contention และ USB read ซ้ำที่เคยทำให้ UI กับ control loop สะดุดพร้อมกัน

### 6. Jog release และ dead-man

Web Jog ใช้ client ID, sequence ต่อหน้า และ lease ownership คำสั่ง release ที่ใหม่กว่าจะไม่ถูกคำสั่ง start เก่าซึ่งมาถึงช้าทับกลับ หาก browser หายหรือไม่ได้ heartbeat ระบบสั่งศูนย์เมื่อ lease หมดอายุประมาณ `0.6 s`

## Current/torque protection

ค่าป้องกันใน Python server:

| รายการ | ค่า |
|---|---:|
| Continuous current | `20 A` |
| Peak current | `40 A` |
| Hard current | `48 A` |
| Peak duration | `2.0 s` |
| Smooth derating duration | `0.75 s` |
| Recovery threshold | `16 A` |
| Recovery duration | `30 s` |
| Torque constant | `0.29 Nm/A` |
| Continuous torque | `5.8 Nm` |
| Peak torque | `11.6 Nm` |

เมื่อใช้ peak ครบเวลา ระบบค่อย ๆ ลด allowed current จาก `40 A` ไป `20 A` ภายใน `0.75 s` ไม่ตัด velocity/setpoint เป็นศูนย์ทันที จึงหลีกเลี่ยง motion spike จาก hard stop

ค่า torque soft limit ที่ flash ใน Drive เป็น `±11.6 Nm` แต่เมื่อ Python server เริ่มทำงาน current envelope จะเริ่มแบบ conservative ที่ continuous torque แล้วปล่อย peak ตาม state ของ envelope ดังนั้นอย่าวิเคราะห์จากค่า flash เพียงอย่างเดียว ต้องดู runtime envelope ด้วย

ไม่มี thermistor ต่ออยู่ จึงห้ามเพิ่ม continuous/peak time จากการคาดเดา ต้องใช้ข้อจำกัด `20/40/48 A` นี้จนกว่าจะมี thermal feedback และผลทดสอบอุณหภูมิจริง

## สิ่งที่ทดลองแล้วแต่ไม่ใช่คำอธิบายหลัก

- ลดหรือเพิ่ม tuning gain แล้วยังเกิด jitter ได้ จึงไม่ควรไล่ gain อย่างเดียว
- เปลี่ยน Altitude encoder bandwidth จาก `70` เป็น `50 1/s` แล้วยังเคยพบ velocity spike จึงไม่ใช่ root fix เพียงตัวเดียว
- พบ jitter จาก Jog ภายในระบบโดยไม่ผ่าน external API จึงไม่ใช่ API transport เพียงอย่างเดียว
- Phase R ของ Altitude สูงกว่า Azimuth ประมาณ 20% แต่ผลวัด Altitude หลายรอบอยู่ใกล้ `0.081–0.083 Ω` จึงไม่ควร copy ค่า R/L ของ Azimuth ไปทับ ค่าสาย ขั้วต่อ และอุณหภูมิเป็นส่วนหนึ่งของผลวัด
- การทำ commutation ซ้ำอย่างเดียวไม่แก้ motor R/L หากต้องตรวจ R/L ต้องใช้ `MOTOR_CALIBRATION` แล้วจึงทำ `ENCODER_OFFSET_CALIBRATION`

## ลำดับมาตรฐานสำหรับเครื่องใหม่หรือการ recovery

1. ยืนยัน serial mapping และ firmware version
2. ตั้งชนิดมอเตอร์, `pole_pairs=20`, `torque_constant=0.29`, current limits และ SPI encoder 14-bit/1 MHz
3. ตั้ง direction และ mapper sign จากการติดตั้งจริง ห้าม copy sign โดยไม่ตรวจ
4. Disable แกนและสำรอง configuration ก่อน calibration
5. ทำ `MOTOR_CALIBRATION` ที่ `20 A` เพื่อวัด phase R/L ตรวจว่า valid และค่าซ้ำได้
6. ทำ `ENCODER_OFFSET_CALIBRATION`/commutation ที่ `20 A`
7. ตรวจทิศ, phase branch, offset validity และ encoder error counter
8. ทดสอบ Jog ช้าในสองทิศ แล้วทดสอบ `+10°/-10°` ภายในพื้นที่ปลอดภัย
9. ตรวจ overshoot, velocity spike, current reversal, error/disarm และการหยุดเมื่อปล่อย Jog
10. Apply tuning ผ่าน UI ก่อน แล้วกด Save to Drive; ตรวจ reconnect และ readback หลัง reboot
11. สร้าง backup final แยกแต่ละ serial

ห้ามใช้ `odrivetool` หรือ Python ต่อ USB โดยตรงขณะที่ services ทำงาน เพราะจะสร้าง hardware owner ซ้อน ต้อง Stop/Disable motion แล้วหยุด `fire-detector-control.service` และ `fire-detector.service` ก่อน และเปิดกลับหลังเสร็จ

## Backup ที่เป็น reference

- `data/odrive_backups/azimuth_user_tuning_saved_pre_alt_dq_fix_20260824.json` — Azimuth หลัง flash tuning ปัจจุบัน
- `data/odrive_backups/altitude_user_tuning_saved_pre_dq_fix_20260824.json` — Altitude หลัง flash tuning แต่ก่อนแก้ D/Q flag
- `data/odrive_backups/altitude_final_user_tuning_dq_model_fixed_20260824.json` — Altitude final หลังแก้ flag และ reboot/readback
- `data/odrive_backups/azimuth_spi1m_after_jog_verify_20260824.json` — หลักฐาน baseline Azimuth หลังปรับ SPI 1 MHz
- `data/odrive_backups/altitude_final_20a_commutation_10deg_verified_20260824.json` — Altitude หลัง commutation 20 A และทดสอบ 10°

Restore เฉพาะ backup ที่ serial และ installation ตรงกัน หลัง restore ต้องตรวจ direction, position และ current โดยไม่ assume ว่าปลอดภัยทันที

## Checklist หลังการแก้ครั้งนี้

- [x] Flash tuning ปัจจุบันของ Azimuth
- [x] Flash tuning ปัจจุบันของ Altitude
- [x] แก้ Altitude `motor_model_l_dq_valid=false`
- [x] Reboot และ persistent readback
- [x] ตรวจว่า R/L, gains, encoder bandwidth, SPI baud และ commutation offset ไม่เปลี่ยน
- [x] Drive ทั้งสอง IDLE และ error เป็นศูนย์
- [x] Services กลับมา active
- [ ] ผู้ใช้ทดสอบ Altitude Jog หลายตำแหน่งหลังแก้ flag
- [ ] บันทึก telemetry หากยังพบ jitter เพื่อเทียบ setpoint, encoder raw/error, velocity และ current ใน timestamp เดียวกัน

Azimuth ถือเป็น baseline ที่ผ่านการทดสอบ smooth แล้ว ส่วน Altitude ยังต้องทดสอบภายใต้ motion จริงหลังการแก้ D/Q flag ก่อนประกาศว่า jitter ถูกแก้สมบูรณ์
