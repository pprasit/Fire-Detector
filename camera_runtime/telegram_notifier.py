"""
Telegram Notifier Module for Wildfire & Hotspot Detection
Sends instant text alerts and dual snapshots (Thermal + Visible) to Telegram chat/group.
"""

import os
import io
import json
import time
import logging
import threading
from typing import Optional, List, Dict, Any, Tuple
import urllib.request
import urllib.parse
import cv2
import numpy as np

logger = logging.getLogger("TelegramNotifier")


class TelegramNotifier:
    """Handles sending real-time hotspot detection alerts and dual snapshots to Telegram."""

    def __init__(
        self,
        bot_token: str = "",
        chat_id: Optional[str] = None,
        enabled: bool = True,
        send_photos: bool = True,
        cooldown_sec: float = 30.0,
        suppress_false_alarm: bool = True
    ):
        self.bot_token = bot_token.strip()
        self.chat_id = str(chat_id).strip() if chat_id else ""
        self.enabled = bool(enabled and self.bot_token)
        self.send_photos = send_photos
        self.cooldown_sec = max(5.0, float(cooldown_sec))
        self.suppress_false_alarm = bool(suppress_false_alarm)

        self.last_sent_timestamp: Dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def api_base(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"

    def update_config(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None, enabled: Optional[bool] = None, suppress_false_alarm: Optional[bool] = None):
        with self._lock:
            if bot_token is not None:
                self.bot_token = bot_token.strip()
            if chat_id is not None:
                self.chat_id = str(chat_id).strip()
            if enabled is not None:
                self.enabled = bool(enabled and self.bot_token)
            if suppress_false_alarm is not None:
                self.suppress_false_alarm = bool(suppress_false_alarm)

    def fetch_latest_chat_id(self) -> Optional[str]:
        """Queries getUpdates to find the chat_id of the latest user/group that interacted with the bot."""
        if not self.bot_token:
            return None
        url = f"{self.api_base}/getUpdates"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WildfireDetector/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok"):
                    results = data.get("result", [])
                    for item in reversed(results):
                        msg = item.get("message") or item.get("channel_post") or item.get("my_chat_member", {}).get("chat")
                        if msg:
                            chat = msg.get("chat", {}) if "chat" in msg else msg
                            c_id = str(chat.get("id", ""))
                            if c_id:
                                logger.info(f"✅ Discovered Telegram Chat ID: {c_id} ({chat.get('title') or chat.get('username') or chat.get('first_name')})")
                                self.chat_id = c_id
                                return c_id
        except Exception as e:
            logger.warning(f"Error fetching Telegram getUpdates: {e}")
        return None

    def send_message_async(self, text: str, chat_id: Optional[str] = None):
        """Dispatches text notification asynchronously."""
        if not self.enabled:
            return
        t = threading.Thread(target=self.send_message, args=(text, chat_id), daemon=True)
        t.start()

    def send_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        """Sends a text message using Telegram Bot API."""
        target_chat = chat_id or self.chat_id
        if not target_chat:
            target_chat = self.fetch_latest_chat_id()
        if not target_chat or not self.enabled:
            logger.warning("Cannot send Telegram message: chat_id not set or notifier disabled.")
            return False

        url = f"{self.api_base}/sendMessage"
        payload = json.dumps({
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json",
                "User-Agent": "WildfireDetector/1.0"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                res = json.loads(resp.read().decode())
                return bool(res.get("ok"))
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_incident_alert_async(
        self,
        incident_rec: Dict[str, Any],
        thermal_frame: Optional[np.ndarray] = None,
        visible_frame: Optional[np.ndarray] = None,
        chat_id: Optional[str] = None
    ):
        """Asynchronously dispatches formatted fire incident alert with dual photos."""
        if not self.enabled:
            return
        t = threading.Thread(
            target=self.send_incident_alert,
            args=(incident_rec, thermal_frame, visible_frame, chat_id),
            daemon=True
        )
        t.start()

    def send_incident_alert(
        self,
        incident_rec: Dict[str, Any],
        thermal_frame: Optional[np.ndarray] = None,
        visible_frame: Optional[np.ndarray] = None,
        chat_id: Optional[str] = None
    ) -> bool:
        """
        Sends formatted Hotspot / Fire alert with Dual Snapshots (Thermal + Visible).
        Enforces cooldown per coordinate to prevent flood.
        """
        inc_id = incident_rec.get("id", "UNKNOWN")
        az = incident_rec.get("current_azimuth", incident_rec.get("azimuth", 0.0))
        alt = incident_rec.get("current_altitude", incident_rec.get("altitude", 0.0))
        coord_key = f"{round(az, 1)}_{round(alt, 1)}"

        now = time.time()
        with self._lock:
            last_t = self.last_sent_timestamp.get(coord_key, 0.0)
            if now - last_t < self.cooldown_sec:
                logger.info(f"[TelegramNotifier] Skipping alert for {coord_key} (Cooldown active: {now - last_t:.1f}s / {self.cooldown_sec}s)")
                return False
            self.last_sent_timestamp[coord_key] = now

        target_chat = chat_id or self.chat_id
        if not target_chat:
            target_chat = self.fetch_latest_chat_id()
        if not target_chat or not self.enabled:
            logger.warning("[TelegramNotifier] No valid chat_id found for alert.")
            return False

        # Format Caption
        conf = float(incident_rec.get("current_confidence", incident_rec.get("confidence", 0.95))) * 100.0
        trend_label = incident_rec.get("growth_trend_label", incident_rec.get("growth_trend", "ACTIVE"))
        time_str = incident_rec.get("last_updated", incident_rec.get("first_detected", time.strftime("%Y-%m-%d %H:%M:%S")))

        # Extract zoom info with fallback to latest history entry and nested thermal dict
        zoom_info = incident_rec.get("zoom_info") or {}
        if not zoom_info and incident_rec.get("history"):
            zoom_info = incident_rec["history"][-1].get("zoom_info") or {}
        thm_zoom = zoom_info.get("thermal") if isinstance(zoom_info.get("thermal"), dict) else zoom_info
        focal_mm = float(thm_zoom.get("focal_mm", zoom_info.get("focal_mm", 0.0)))
        zoom_x = float(thm_zoom.get("zoom_x", zoom_info.get("zoom_x", (focal_mm / 31.0) if focal_mm > 0 else 0.0)))
        area_px = incident_rec.get("current_area_px", incident_rec.get("area_px", 0))

        zoom_text = f"<code>{focal_mm:.1f} mm ({zoom_x:.1f}x)</code>" if focal_mm > 0 else "<code>N/A</code>"

        # Format LLM Verification Block if available
        llm_block = ""
        llm_ver = incident_rec.get("llm_verification")
        if llm_ver and isinstance(llm_ver, dict):
            risk = str(llm_ver.get("risk_level", "UNKNOWN")).upper()
            if risk == "FALSE_ALARM" and self.suppress_false_alarm:
                logger.info(f"🟢 [TelegramNotifier] Incident [{inc_id}] assessed as FALSE_ALARM by LLM. Suppressing Telegram alert.")
                return False

            risk_labels = {
                "HIGH": "🔴 <b>อันตรายสูง (HIGH RISK / ยืนยันไฟป่า)</b>",
                "MEDIUM": "🟠 <b>เฝ้าระวัง (MEDIUM RISK)</b>",
                "LOW": "🟡 <b>ความเสี่ยงต่ำ (LOW RISK)</b>",
                "FALSE_ALARM": "🟢 <b>สัญญาณลวง (FALSE ALARM / แดดสะท้อน)</b>"
            }
            risk_badge = risk_labels.get(risk, f"⚪ <b>{risk}</b>")
            reason_text = llm_ver.get("reason", "-")
            rec_text = llm_ver.get("recommendation", "")

            # Guard against Telegram 1024-character caption limit for media
            if len(reason_text) > 280:
                reason_text = reason_text[:277] + "..."
            if rec_text and len(rec_text) > 140:
                rec_text = rec_text[:137] + "..."

            rec_line = f"\n📋 <b>คำแนะนำ:</b> {rec_text}" if rec_text else ""
            llm_block = (
                f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 <b>ผลวิเคราะห์ AI (LLM Verification):</b>\n"
                f"• <b>การประเมิน:</b> {risk_badge}\n"
                f"• <b>เหตุผล:</b> {reason_text}"
                f"{rec_line}"
            )

        caption = (
            f"🔥 <b>ตรวจพบจุดความร้อน / เปลวไฟ! (Hotspot Alert)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>พิกัดมุมกล้อง:</b> <code>Azimuth {az:+.1f}°</code> | <code>Altitude {alt:+.1f}°</code>\n"
            f"🎯 <b>ความมั่นใจ:</b> <b>{conf:.1f}%</b> (สถานะ: <b>{trend_label}</b>)\n"
            f"📏 <b>ขนาดความร้อน:</b> <code>{area_px} px</code>\n"
            f"🔭 <b>ระยะซูมเลนส์:</b> {zoom_text}\n"
            f"🕒 <b>เวลาบันทึก:</b> <code>{time_str}</code>\n"
            f"🆔 <b>รหัสเหตุการณ์:</b> <code>{inc_id}</code>"
            f"{llm_block}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>สถานีตรวจจับไฟป่าอัตโนมัติ (Wildlife & Wildfire AI Sentry)</i>"
        )

        # Prepare Images
        th_bytes = self._encode_frame_to_jpeg(thermal_frame)
        vis_bytes = self._encode_frame_to_jpeg(visible_frame)

        if not self.send_photos or (not th_bytes and not vis_bytes):
            return self.send_message(caption, target_chat)

        if th_bytes and vis_bytes:
            return self._send_media_group(target_chat, caption, [
                ("thermal_hotspot.jpg", th_bytes),
                ("visible_context.jpg", vis_bytes)
            ])
        elif th_bytes:
            return self._send_single_photo(target_chat, caption, "thermal_hotspot.jpg", th_bytes)
        else:
            return self._send_single_photo(target_chat, caption, "visible_context.jpg", vis_bytes)

    def send_extinguished_alert_async(
        self,
        incident_rec: Dict[str, Any],
        thermal_frame: Optional[np.ndarray] = None,
        visible_frame: Optional[np.ndarray] = None,
        chat_id: Optional[str] = None
    ):
        """Asynchronously sends notification confirming hotspot has been extinguished."""
        if not self.enabled:
            return
        t = threading.Thread(
            target=self.send_extinguished_alert,
            args=(incident_rec, thermal_frame, visible_frame, chat_id),
            daemon=True
        )
        t.start()

    def send_extinguished_alert(
        self,
        incident_rec: Dict[str, Any],
        thermal_frame: Optional[np.ndarray] = None,
        visible_frame: Optional[np.ndarray] = None,
        chat_id: Optional[str] = None
    ) -> bool:
        """Sends notification confirming hotspot has been extinguished (verified clean across rounds)."""
        inc_id = incident_rec.get("id", "UNKNOWN")
        az = incident_rec.get("current_azimuth", incident_rec.get("azimuth", 0.0))
        alt = incident_rec.get("current_altitude", incident_rec.get("altitude", 0.0))
        time_str = incident_rec.get("extinguished_time", time.strftime("%Y-%m-%d %H:%M:%S"))

        target_chat = chat_id or self.chat_id
        if not target_chat:
            target_chat = self.fetch_latest_chat_id()
        if not target_chat or not self.enabled:
            return False

        caption = (
            f"✅ <b>ยืนยัน: จุดความร้อนดับสนิทแล้ว (Fire Extinguished)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>พิกัดมุมกล้อง:</b> <code>Azimuth {az:+.1f}°</code> | <code>Altitude {alt:+.1f}°</code>\n"
            f"🔍 <b>การตรวจสอบซ้ำ:</b> ซูมตรวจลึกไม่พบความร้อนต่อเนื่อง 2 รอบสแกน\n"
            f"🕒 <b>เวลายืนยันดับ:</b> <code>{time_str}</code>\n"
            f"🆔 <b>รหัสเหตุการณ์:</b> <code>{inc_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>สถานีตรวจจับไฟป่าอัตโนมัติ (Wildlife & Wildfire AI Sentry)</i>"
        )

        th_bytes = self._encode_frame_to_jpeg(thermal_frame)
        vis_bytes = self._encode_frame_to_jpeg(visible_frame)

        if not self.send_photos or (not th_bytes and not vis_bytes):
            return self.send_message(caption, target_chat)

        if th_bytes and vis_bytes:
            return self._send_media_group(target_chat, caption, [
                ("thermal_extinguished.jpg", th_bytes),
                ("visible_extinguished.jpg", vis_bytes)
            ])
        elif th_bytes:
            return self._send_single_photo(target_chat, caption, "thermal_extinguished.jpg", th_bytes)
        else:
            return self._send_single_photo(target_chat, caption, "visible_extinguished.jpg", vis_bytes)

    def _encode_frame_to_jpeg(self, frame: Optional[np.ndarray]) -> Optional[bytes]:
        if frame is None:
            return None
        try:
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if ok:
                return buf.tobytes()
        except Exception as e:
            logger.error(f"Error encoding frame to JPEG: {e}")
        return None

    def _send_single_photo(self, chat_id: str, caption: str, filename: str, image_bytes: bytes) -> bool:
        url = f"{self.api_base}/sendPhoto"
        boundary = "----WebKitFormBoundary" + os.urandom(16).hex()

        body = io.BytesIO()
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode())
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n".encode())
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{filename}\"\r\nContent-Type: image/jpeg\r\n\r\n".encode())
        body.write(image_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())

        try:
            req = urllib.request.Request(
                url,
                data=body.getvalue(),
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "WildfireDetector/1.0"
                }
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                res = json.loads(resp.read().decode())
                return bool(res.get("ok"))
        except Exception as e:
            logger.error(f"Error sending Telegram single photo: {e}")
            return False

    def _send_media_group(self, chat_id: str, caption: str, files: List[Tuple[str, bytes]]) -> bool:
        url = f"{self.api_base}/sendMediaGroup"
        boundary = "----WebKitFormBoundary" + os.urandom(16).hex()

        media_meta = []
        for idx, (fname, _) in enumerate(files):
            attach_name = f"photo_{idx}"
            item = {
                "type": "photo",
                "media": f"attach://{attach_name}"
            }
            if idx == 0:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media_meta.append(item)

        body = io.BytesIO()
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode())
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"\r\n\r\n{json.dumps(media_meta)}\r\n".encode())

        for idx, (fname, img_bytes) in enumerate(files):
            attach_name = f"photo_{idx}"
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{attach_name}\"; filename=\"{fname}\"\r\nContent-Type: image/jpeg\r\n\r\n".encode())
            body.write(img_bytes)
            body.write(b"\r\n")

        body.write(f"--{boundary}--\r\n".encode())

        try:
            req = urllib.request.Request(
                url,
                data=body.getvalue(),
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "WildfireDetector/1.0"
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode())
                return bool(res.get("ok"))
        except Exception as e:
            logger.error(f"Error sending Telegram media group: {e}")
            if files:
                return self._send_single_photo(chat_id, caption, files[0][0], files[0][1])
            return False
