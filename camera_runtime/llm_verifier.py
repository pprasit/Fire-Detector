"""
LLM Verifier Module for Wildfire & Hotspot Detection
Connects to NARIT Multimodal LLM (OpenAI-compatible) to analyze dual camera snapshots
(Thermal Heatmap + Optical Context) and verify whether a detected hotspot is a real fire or false alarm.
"""

import os
import json
import time
import base64
import logging
import threading
from typing import Optional, Dict, Any, Tuple
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("LLMVerifier")

try:
    from config import CAMERAS
except ImportError:
    CAMERAS = {}

DEFAULT_API_URL = "https://lllm.narit.or.th/v1"
DEFAULT_MODEL = "OpenAI-NARIT-Local-AI-01"


class LLMVerifier:
    """Manages AI verification of fire incidents via multimodal LLM."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_API_URL,
        model: str = DEFAULT_MODEL,
        enabled: bool = True,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        timeout_sec: int = 45
    ):
        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip()
        self.enabled = bool(enabled and self.api_key)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout_sec = timeout_sec
        self._lock = threading.Lock()

    def update_config(self, cfg: Dict[str, Any]):
        """Live update configuration parameters."""
        with self._lock:
            if "api_key" in cfg:
                self.api_key = str(cfg["api_key"]).strip()
            if "base_url" in cfg:
                self.base_url = str(cfg["base_url"]).strip().rstrip("/")
            if "model" in cfg:
                self.model = str(cfg["model"]).strip()
            if "enabled" in cfg:
                self.enabled = bool(cfg["enabled"] and self.api_key)
            if "max_tokens" in cfg:
                self.max_tokens = int(cfg["max_tokens"])
            if "temperature" in cfg:
                self.temperature = float(cfg["temperature"])
            if "timeout_sec" in cfg:
                self.timeout_sec = int(cfg["timeout_sec"])
            logger.info(f"LLMVerifier config updated: enabled={self.enabled}, model={self.model}")

    def test_connection(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> Dict[str, Any]:
        """Tests connectivity and authentication with LLM models endpoint."""
        key = (api_key if api_key is not None else self.api_key).strip()
        url = (base_url if base_url is not None else self.base_url).strip().rstrip("/")

        models_endpoint = f"{url}/models"
        headers = {
            "Authorization": f"Bearer {key}",
            "User-Agent": "WildfireDetector/1.0"
        }

        try:
            res = requests.get(models_endpoint, headers=headers, timeout=10, verify=False)
            if res.status_code == 200:
                data = res.json()
                models = [m.get("id") for m in data.get("data", []) if "id" in m]
                return {
                    "ok": True,
                    "models": models,
                    "message": f"Connected successfully! Found {len(models)} model(s)."
                }
            else:
                return {
                    "ok": False,
                    "models": [],
                    "message": f"HTTP {res.status_code}: {res.text[:200]}"
                }
        except Exception as e:
            return {
                "ok": False,
                "models": [],
                "message": f"Connection failed: {str(e)}"
            }

    @staticmethod
    def _encode_image_to_base64(filepath: str) -> Optional[str]:
        """Encodes an image file to Base64 string."""
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to read image for LLM: {filepath} ({e})")
            return None

    @staticmethod
    def _azimuth_to_cardinal(az_deg: float) -> str:
        """Converts azimuth degrees to compass cardinal direction."""
        az = float(az_deg) % 360.0
        directions = [
            ("ทิศเหนือ (N)", 0.0, 22.5),
            ("ทิศตะวันออกเฉียงเหนือ (NE)", 22.5, 67.5),
            ("ทิศตะวันออก (E)", 67.5, 112.5),
            ("ทิศตะวันออกเฉียงใต้ (SE)", 112.5, 157.5),
            ("ทิศใต้ (S)", 157.5, 202.5),
            ("ทิศตะวันตกเฉียงใต้ (SW)", 202.5, 247.5),
            ("ทิศตะวันตก (W)", 247.5, 292.5),
            ("ทิศตะวันตกเฉียงเหนือ (NW)", 292.5, 337.5),
            ("ทิศเหนือ (N)", 337.5, 360.0),
        ]
        for name, start, end in directions:
            if start <= az < end:
                return name
        return "ทิศเหนือ (N)"

    def verify_incident(
        self,
        incident_rec: Dict[str, Any],
        vis_path: str,
        thm_path: str,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Sends dual snapshots and spatial/temporal context to LLM for fire verification.
        Returns parsed verification dict.
        """
        if not self.enabled:
            return {
                "status": "disabled",
                "message": "LLM Verification is disabled in settings."
            }

        vis_b64 = self._encode_image_to_base64(vis_path)
        thm_b64 = self._encode_image_to_base64(thm_path)

        if not vis_b64 or not thm_b64:
            return {
                "status": "error",
                "message": f"Missing image files (Visible: {bool(vis_b64)}, Thermal: {bool(thm_b64)})"
            }

        # Determine exact snapshot timestamp from filename or last_updated
        snapshot_time = incident_rec.get("last_updated") or incident_rec.get("first_detected") or time.strftime("%Y-%m-%d %H:%M:%S")
        thm_fname = os.path.basename(thm_path)
        if thm_fname.startswith("fire_") and len(thm_fname) >= 20:
            try:
                # fire_YYYYMMDD_HHMMSS_th.jpg -> YYYY-MM-DD HH:MM:SS
                dt_part = thm_fname[5:20]
                snapshot_time = f"{dt_part[0:4]}-{dt_part[4:6]}-{dt_part[6:8]} {dt_part[9:11]}:{dt_part[11:13]}:{dt_part[13:15]}"
            except Exception:
                pass

        first_detected = incident_rec.get("first_detected", snapshot_time)
        total_rounds = incident_rec.get("scan_rounds") or incident_rec.get("total_rounds") or 1
        rounds_info = ""
        if total_rounds > 1 and first_detected != snapshot_time:
            rounds_info = f"\n- ประวัติการตรวจพบ: ตรวจพบครั้งแรกเมื่อ {first_detected} (สแกนตรวจพบซ้ำเป็นรอบที่ {total_rounds})"

        az = incident_rec.get("current_azimuth", incident_rec.get("azimuth", 0.0))
        alt = incident_rec.get("current_altitude", incident_rec.get("altitude", 0.0))
        inc_id = incident_rec.get("id", "UNKNOWN")
        heat_px = incident_rec.get("current_area_px", incident_rec.get("area_px", 0))

        zoom_info = incident_rec.get("zoom_info")
        if not zoom_info and incident_rec.get("history"):
            zoom_info = incident_rec["history"][-1].get("zoom_info")
        zoom_info = zoom_info or {}

        # Extract Thermal Camera Optics
        thm_cfg = CAMERAS.get("thermal", {})
        thm_zoom_data = zoom_info.get("thermal") if isinstance(zoom_info.get("thermal"), dict) else zoom_info
        thm_min_focal = float(thm_cfg.get("min_focal_mm", 31.0))
        thm_max_focal = float(thm_cfg.get("max_focal_mm", 155.0))
        thm_focal = float(thm_zoom_data.get("focal_mm") or thm_max_focal)
        thm_zoom_x = float(thm_zoom_data.get("zoom_x") or (thm_focal / thm_min_focal if thm_min_focal > 0 else 5.0))
        thm_fov_h = float(thm_zoom_data.get("fov_h") or (thm_cfg.get("tele_h_fov_deg", 2.8) if thm_focal >= 140 else thm_cfg.get("wide_h_fov_deg", 14.2)))
        thm_fov_v = float(thm_zoom_data.get("fov_v") or (thm_cfg.get("tele_v_fov_deg", 2.3) if thm_focal >= 140 else thm_cfg.get("wide_v_fov_deg", 11.4)))

        # Extract Visible Camera Optics
        vis_cfg = CAMERAS.get("visible", {})
        vis_zoom_data = zoom_info.get("visible") if isinstance(zoom_info.get("visible"), dict) else {}
        vis_min_focal = float(vis_cfg.get("min_focal_mm", 5.1))
        vis_max_focal = float(vis_cfg.get("max_focal_mm", 102.0))
        vis_default_focal = float(vis_cfg.get("default_focal_mm", 15.1))
        vis_focal = float(vis_zoom_data.get("focal_mm") or vis_default_focal)
        vis_zoom_x = float(vis_zoom_data.get("zoom_x") or (vis_focal / vis_min_focal if vis_min_focal > 0 else 3.0))
        vis_fov_h = float(vis_zoom_data.get("fov_h") or (18.59 if abs(vis_focal - 15.1) < 2.0 else (vis_cfg.get("wide_h_fov_deg", 51.69) if vis_focal <= 10 else vis_cfg.get("tele_h_fov_deg", 3.12))))
        vis_fov_v = float(vis_zoom_data.get("fov_v") or (10.20 if abs(vis_focal - 15.1) < 2.0 else (vis_cfg.get("wide_v_fov_deg", 29.58) if vis_focal <= 10 else vis_cfg.get("tele_v_fov_deg", 1.75))))

        # Calculate FOV ratio
        fov_ratio = round(vis_fov_h / thm_fov_h, 1) if thm_fov_h > 0 else 6.5

        cardinal_dir = self._azimuth_to_cardinal(az)
        tilt_desc = f"ก้มลง {abs(alt):.1f}° (ส่องแนวพื้นดิน/แนวเขา)" if alt < 0 else (f"เงยขึ้น {alt:.1f}°" if alt > 0 else "ระดับสายตา 0.0°")

        system_prompt = (
            "คุณเป็น AI ผู้เชี่ยวชาญด้านการวิเคราะห์อัคคีภัยและไฟป่าผ่านภาพถ่ายตรวจการณ์ (Wildfire Verification Agent)\n"
            "หน้าที่ของคุณคือเปรียบเทียบภาพ 2 ภาพที่บันทึกพร้อมกันจากระบบกล้องคู่ PTZ:\n"
            "- ภาพที่ 1: กล้อง Visible (RGB แสงปกติ) มุมกว้าง สำหรับตรวจหาควันไฟ เปลวไฟ และบริบทภูมิประเทศ\n"
            "- ภาพที่ 2: กล้อง Thermal (Colormap ความร้อน) ซูมระยะไกลเจาะเฉพาะจุด สำหรับตรวจหาจุดกำเนิดความร้อนสูง (Thermal Hotspot)\n\n"
            "หลักเกณฑ์สำคัญในการวิเคราะห์ด้านออปติกและมุมมอง (Optical & FOV Principles):\n"
            "1. กล้อง Visible มีมุมมอง (FOV) กว้างกว่ากล้อง Thermal มาก ภาพ Thermal คือภาพซูมเจาะเข้าไปยังตำแหน่งกึ่งกลางของภาพ Visible\n"
            "2. หากเป็นไฟป่าระยะไกล ควันไฟในภาพ Visible อาจมองเห็นเป็นเพียงกลุ่มควันสีขาว/เทาขนาดเล็กหรือจางๆ ในขณะที่ภาพ Thermal จะเห็นจุดความร้อนขนาดใหญ่ชัดเจนเนื่องจากเป็นเลนส์เทเลโฟโต้กำลังซูมสูง\n"
            "3. หาก Thermal มีความร้อนสูง แต่ใน Visible ไม่พบควันไฟหรือเปลวไฟเลย และเป็นเวลากลางวันแดดจัด ให้สงสัยว่าเป็น 'FALSE_ALARM' (แดดสะท้อนหิน, ผิวดินแห้ง หรือหลังคา)\n"
            "4. หาก Thermal มีความร้อนสูง และใน Visible พบควันไฟลอยขึ้นอย่างสอดคล้องกับพิกัดความร้อน ให้ประเมินเป็น 'HIGH' (ยืนยันไฟป่า)\n"
            "5. หากมีความร้อนสูงแต่ภาพ Visible ถูกบดบังด้วยหมอก/เมฆ หรือไม่แน่ใจเรื่องควัน ให้ประเมินเป็น 'MEDIUM' หรือ 'LOW' เพื่อเฝ้าระวัง\n"
            "6. คิดและวิเคราะห์อย่างกระชับตรงประเด็น และตอบกลับเป็น JSON เท่านั้น ไม่ต้องมีข้อความเกริ่นนำ"
        )

        user_prompt = f"""ข้อมูลการตรวจการณ์และสเปคกล้อง (Surveillance & Camera Context):
1. ข้อมูลเหตุการณ์และพิกัดเล็ง (PTZ Mount):
   - รหัสเหตุการณ์: {inc_id}
   - วันเวลาที่บันทึกภาพชุดนี้: {snapshot_time}{rounds_info}
   - ทิศทางมุมกล้อง: Azimuth {az:+.1f}° ({cardinal_dir}), Altitude {alt:+.1f}° ({tilt_desc})

2. ข้อมูลสเปคกล้องและเลนส์ตรวจการณ์ (Camera Specifications):
   - ภาพที่ 1: กล้อง Visible (RGB แสงปกติ)
     * ความละเอียดเซนเซอร์: Color CMOS HD/Full HD (อัตราส่วน 16:9)
     * ระยะโฟกัสเลนส์ (Focal Length): {vis_focal:.1f} mm ({vis_zoom_x:.1f}x) [ช่วงเลนส์ 5.1 - 102.0 mm, ซูมออปติคอล 20x]
     * องศามุมมองภาพ (FOV): แนวนอน {vis_fov_h:.1f}° x แนวตั้ง {vis_fov_v:.1f}° (มุมกว้างครอบคลุมบริบทภูมิประเทศ)
   - ภาพที่ 2: กล้อง Thermal (Colormap ความร้อน)
     * ความละเอียดเซนเซอร์: 640x512 VOx Uncooled Microbolometer คลื่นความร้อน LWIR (8-14 µm)
     * ระยะโฟกัสเลนส์ (Focal Length): {thm_focal:.1f} mm ({thm_zoom_x:.1f}x) [ช่วงเลนส์ 31.0 - 155.0 mm, ซูมออปติคอล 5x]
     * องศามุมมองภาพ (FOV): แนวนอน {thm_fov_h:.2f}° x แนวตั้ง {thm_fov_v:.2f}° (มุมแคบ ซูมเทเลเจาะลึก)
     * ขนาดจุดความร้อนที่ตรวจจับได้: {heat_px} พิกเซล (บนพื้นที่ภาพความร้อน 640x512)

3. ความสัมพันธ์เชิงพื้นที่ระหว่างสองกล้อง (Spatial & Optical Relation):
   - ทั้ง 2 กล้องติดตั้งขนานกันบนแท่นหมุน PTZ เดียวกัน เล็งไปยังพิกัดเป้าหมายเดียวกัน
   - กล้อง Visible มีมุมมองกว้างกว่ากล้อง Thermal ถึง ~{fov_ratio:.1f} เท่าในแนวนอน (ภาพความร้อนเทียบเท่ากับการซูมเจาะเข้าไปยังส่วนเล็กๆ ตรงกลางของภาพ Visible)

คำถาม: จากการวิเคราะห์เปรียบเทียบทั้ง 2 ภาพประกอบกับสเปคกล้องและมุมมอง FOV ข้างต้น ทั้ง 2 ภาพนี้สัมพันธ์กันและมีโอกาสเกิดไฟป่าจริงหรือไม่? หรือเป็นเพียง False Alarm (แดดสะท้อนหิน/ผิวดินแห้ง/หลังคา)?
ให้ตอบเป็น JSON โครงสร้างนี้เท่านั้น:
{{
  "fire_detected": true/false,
  "risk_level": "HIGH" / "MEDIUM" / "LOW" / "FALSE_ALARM",
  "thermal_detail": "สรุปจุดความร้อนที่พบใน Thermal และขนาดเมื่อเทียบกับ FOV เลนส์",
  "visible_detail": "สรุปสิ่งที่พบใน Visible เช่น ควัน เปลวไฟ หรือแดดสะท้อน ในขอบเขตพื้นที่ที่ตรงกับภาพความร้อน",
  "reason": "คำอธิบายสรุปเหตุผลความเชื่อมโยงของทั้งสองภาพและการวิเคราะห์โดยอ้างอิงสเปคกล้อง/FOV",
  "recommendation": "คำแนะนำการปฏิบัติการ (เช่น สั่งทีมดับเพลิงเข้าพื้นที่ / ให้เฝ้าระวังต่อ / ไม่ต้องระดมกำลัง)"
}}"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{vis_b64}"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{thm_b64}"}}
                    ]
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        endpoint = f"{self.base_url}/chat/completions"
        timeout_val = timeout or self.timeout_sec

        try:
            start_t = time.time()
            res = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_val, verify=False)
            latency = round(time.time() - start_t, 2)

            if res.status_code != 200:
                logger.error(f"LLM API returned error {res.status_code}: {res.text[:300]}")
                return {
                    "status": "error",
                    "error_code": res.status_code,
                    "message": f"API Error {res.status_code}: {res.text[:200]}"
                }

            data = res.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            raw_content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""

            # Attempt JSON parsing
            parsed = self._extract_json(raw_content)

            # Fallback if content was empty due to excessive reasoning
            if not parsed and reasoning:
                parsed = {
                    "fire_detected": "FALSE_ALARM" not in reasoning.upper(),
                    "risk_level": "FALSE_ALARM" if "FALSE_ALARM" in reasoning.upper() else "LOW",
                    "reason": reasoning[-300:] if len(reasoning) > 300 else reasoning
                }

            if not parsed:
                parsed = {
                    "fire_detected": False,
                    "risk_level": "UNKNOWN",
                    "reason": raw_content if raw_content else "No valid JSON output received from model."
                }

            parsed["status"] = "success"
            parsed["latency_sec"] = latency
            parsed["model"] = self.model
            parsed["analyzed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            return parsed

        except requests.exceptions.Timeout:
            logger.warning(f"LLM API request timed out ({timeout_val}s)")
            return {
                "status": "timeout",
                "message": f"LLM verification timed out after {timeout_val} seconds."
            }
        except Exception as e:
            logger.error(f"Error during LLM verification: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    def verify_incident_async(
        self,
        incident_rec: Dict[str, Any],
        vis_path: str,
        thm_path: str,
        callback=None
    ):
        """Dispatches verification in a background thread and calls callback(result)."""
        def _worker():
            res = self.verify_incident(incident_rec, vis_path, thm_path)
            if callback:
                try:
                    callback(res)
                except Exception as cb_err:
                    logger.error(f"Error in LLM verify callback: {cb_err}")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Parses JSON from model output, handling markdown code fences."""
        if not text:
            return None
        text_clean = text.strip()

        # Handle ```json ... ``` or ``` ... ```
        if "```" in text_clean:
            parts = text_clean.split("```")
            for p in parts:
                p_trim = p.strip()
                if p_trim.startswith("json"):
                    p_trim = p_trim[4:].strip()
                try:
                    return json.loads(p_trim)
                except Exception:
                    continue

        # Try direct JSON parsing
        try:
            return json.loads(text_clean)
        except Exception:
            pass

        # Try finding outermost { ... }
        start = text_clean.find("{")
        end = text_clean.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text_clean[start:end + 1])
            except Exception:
                pass

        return None
