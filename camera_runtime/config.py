"""
Configuration for Integrated Fire Detection & Automated PTZ Surveillance System
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ==============================================================================
# 1. Dual Camera Settings (Thermal & Visible)
# ==============================================================================
CAMERAS = {
    "thermal": {
        "id": "thermal",
        "name": "Thermal Camera (กล้องความร้อน)",
        "ip": "",
        "onvif_port": 8080,
        "username": "admin",
        "password": "",
        # Substream for AI & Live Stream
        "rtsp_url": "",
        "main_rtsp_url": "",
        "target_fps": 15.0,
        "min_focal_mm": 31.0,
        "max_focal_mm": 155.0,
        # FOV specs: 31mm -> 14.2° x 11.4°, 155mm -> 2.8° x 2.3°
        "wide_h_fov_deg": 14.2,
        "wide_v_fov_deg": 11.4,
        "tele_h_fov_deg": 2.8,
        "tele_v_fov_deg": 2.3,
        "color_theme": "#f97316"
    },
    "visible": {
        "id": "visible",
        "name": "Visible Camera (กล้องแสงปกติ)",
        "ip": "",
        "onvif_port": 80,
        "username": "admin",
        "password": "",
        "rtsp_url": "",
        "main_rtsp_url": "",
        "target_fps": 15.0,
        "min_focal_mm": 5.1,
        "max_focal_mm": 102.0,
        "optical_zoom_x": 20.0,
        "default_focal_mm": 15.1,
        "default_zoom_x": 3.0,
        "default_h_fov_deg": 18.59,
        "default_v_fov_deg": 10.20,
        # FOV specs: 5.1mm -> 51.69° x 29.58° (59.56° D), 102mm -> 3.12° x 1.75° (3.58° D)
        "wide_h_fov_deg": 51.69,
        "wide_v_fov_deg": 29.58,
        "wide_d_fov_deg": 59.56,
        "tele_h_fov_deg": 3.12,
        "tele_v_fov_deg": 1.75,
        "tele_d_fov_deg": 3.58,
        "color_theme": "#06b6d4"
    }
}

# ==============================================================================
# 1.1 Thermal Graphic & Auto-Brightness Settings
# ==============================================================================
THERMAL_IMAGING = {
    "auto_mode": "SCHEDULE",          # "OFF" (Manual), "SCHEDULE" (Day/Night Schedule), "DYNAMIC" (Luminance feedback)
    "current_brightness": 64,         # Live brightness level (0 - 255)
    "current_contrast": 128,          # Live contrast level (0 - 255)
    "day_brightness": 46,             # Brightness during daytime (cuts solar clutter on roofs/trees)
    "day_contrast": 135,              # Contrast during daytime
    "night_brightness": 64,           # Brightness during nighttime (sensor standard)
    "night_contrast": 128,            # Contrast during nighttime
    "schedule_day_start": "07:30",    # Time to engage daytime profile (HH:MM)
    "schedule_night_start": "17:30",  # Time to engage nighttime profile (HH:MM)
    "dynamic_target_luma": 35.0,      # Target 75th percentile luma for dynamic controller
    "dynamic_min_brightness": 38,     # Minimum clamp for dynamic controller
    "dynamic_max_brightness": 64,     # Maximum clamp for dynamic controller
    "dynamic_check_interval_sec": 20.0# Evaluation interval (seconds)
}
CAMERAS["thermal"]["imaging"] = THERMAL_IMAGING

# ==============================================================================
# 2. PTZ & Mount Agent Connection Settings
# ==============================================================================
MOUNT = {
    "unix_socket_path": "/run/fire-detector/mount-agent.sock",
    "tcp_host": "127.0.0.1",
    "tcp_port": 8000,
    "default_scan_speed": 1.0,      # Continuous sweep speed 1 deg/sec
    "max_goto_speed": 10.0,         # Fast slew speed
    "az_min": -300.0,
    "az_max": 300.0,
    "alt_min": -25.0,
    "alt_max": 45.0,
    "use_simulator_fallback": False  # Auto-fallback to simulator if real mount agent unreachable
}

# ==============================================================================
# 3. AI & Verification Engine Settings
# ==============================================================================
AI_CONFIG = {
    "model_param": str(BASE_DIR / "models" / "model.ncnn.param"),
    "model_bin": str(BASE_DIR / "models" / "model.ncnn.bin"),
    "detector_engine": "CLASSIC_THERMAL", # "CLASSIC_THERMAL" (Fast computer vision hotspot), "AI_NCNN" (YOLO), or "HYBRID"
    "hotspot_threshold": 225,       # Grayscale luminance threshold (0-255) for classic thermal detection
    "min_hotspot_area": 15,         # Minimum area in px^2 to reject sensor noise
    "max_hotspot_area": 40000,      # Maximum area in px^2 to reject full-screen saturation
    "morph_kernel_size": 5,         # Kernel size (px) for morphological operations
    "dilate_iterations": 2,         # Dilation iterations to merge adjacent fragments
    "blur_ksize": 3,                # Gaussian blur kernel size to smooth sensor noise
    "use_tophat": True,             # Method 1: White Top-Hat Transform for AGC/background invariance
    "tophat_ksize": 15,             # Kernel size for Top-Hat filter (px)
    "tophat_threshold": 35,         # Contrast threshold for hotspot peak over background
    "use_adaptive": True,           # Method 2: Dynamic Saliency Thresholding (Mean + k*Std)
    "adaptive_k": 3.0,              # Standard deviation multiplier above scene mean
    "adaptive_min_threshold": 170,  # Minimum luminance floor to prevent false alarms in dark scenes
    "zoom_aware": True,             # Method 4: Automatically scale area & criteria with optical zoom
    "use_clutter_suppression": True,# Method 3: Suppress multi-target canopy/foliage glare clutter storms
    "clutter_threshold": 8,         # Trigger clutter mode if >= N candidate hotspots in a single frame
    "clutter_min_core_ratio": 0.035,# Require strict core density (ratio of hot pixels) during clutter storm
    "conf_threshold": 0.25,
    "nms_threshold": 0.45,
    "infer_interval_sec": 0.2,      # Detection interval: Every 0.2s (200ms / 5 Hz)
    "capture_az_step": 5.0,         # Trigger detection every 5.0 degrees (if in AZ_STEP mode)
    "trigger_mode": "FIXED_INTERVAL", # "FIXED_INTERVAL" (Every 200ms continuous) or "AZ_STEP" (Angle step trigger)
    "min_verification_hits": 5,     # Require 5 consecutive detections to confirm fire
    "alarm_hold_cycles": 20,        # Keep confirmed alarm state for ~2s during momentary drop
    "iou_match_threshold": 0.15,    # IoU threshold for Kalman tracking during pan
    "thermal_core_min_val": 190,    # Pixel luminance threshold for high-heat core
    "min_core_ratio": 0.02,
    "latency_floor_ms": 100.0       # Minimum display latency reporting
}

# ==============================================================================
# 4. Mission Controller (Autonomous Sentry Workflow)
# ==============================================================================
MISSION_CONFIG = {
    "auto_sentry_enabled": False,   # Start in Stop / Hold (IDLE) mode by default
    "scan_mode": "CONTINUOUS",      # "CONTINUOUS" (Smooth pan sweep) or "STEP_SWEEP" (Step & stare)
    "scan_az_start": -90.0,
    "scan_az_end": 90.0,
    "scan_alt": 0.0,
    "scan_alt_start": -15.0,
    "scan_alt_end": 5.0,
    "scan_alt_step": 5.0,
    "sweep_speed_deg_s": 1.0,       # Continuous pan scan speed (°/s)
    "scan_focal_length_mm": 31.0,   # Thermal camera focal length (mm) for FOV calculation (31.0 - 155.0)
    "visible_sync_scan_zoom": True, # Synchronize visible camera zoom during scan
    "visible_fov_multiplier": 2.0,  # Ratio of visible FOV to thermal FOV (e.g. 2.0 = Visible is 2x wider than Thermal)
    "scan_fov_overlap_pct": 20.0,   # % Overlap between sweeps / FOV steps
    "max_goto_speed": 10.0,         # Fast slew speed between layers / waypoints (°/s)
    "settle_sec": 0.5,              # Settle / stabilization time (s)
    "capture_az_step": 5.0,         # Fallback AI Trigger step (degrees)
    "step_calc_mode": "FOV_AUTO",   # "DEGREE" or "FOV_AUTO"
    "step_az_deg": 12.0,            # Step angle in degrees (if in manual DEGREE mode)
    "step_overlap_pct": 20.0,       # % Overlap for FOV-based step calculation
    "step_dwell_sec": 1.5,          # Dwell / settle time at each waypoint (s)
    "step_goto_speed": 10.0,        # PTZ slew speed between waypoints (°/s)
    "zoom_verify_focal_mm": 100.0,  # Target optical zoom focal length for verification
    "zoom_settle_wait_sec": 2.0,    # Wait time for zoom lens movement to complete
    "focus_settle_sec": 3.5,        # Wait time (seconds) for thermal/visible autofocus to stabilize before processing
    "min_focus_blur_laplacian": 40.0, # Image sharpness threshold to verify camera is in-focus
    "alarm_cooldown_sec": 60.0,     # Time before resuming scan after confirmed fire alert
    "pre_zoom_check_enabled": False, # Pre-zoom stationary check to reject transient solar glints
    "pre_zoom_stare_sec": 0.8,      # Stare duration while stationary before zooming
    "false_alarm_cooldown_hours": 2.0 # Cooldown to suppress re-triggering on confirmed false alarm locations
}

# ==============================================================================
# 5. Remote Frame Ingest Publisher Settings
# ==============================================================================
FRAME_PUBLISHER = {
    "enabled": False,                  # Disabled by default until configured
    "server_url": "http://127.0.0.1:8000", # Mount Agent / Ingest Server URL
    "target_fps": 15.0,               # Maximum publish cadence per camera
    "adaptive": True,                 # Follow the Station RTSP queue policy
    "policy_url": "http://127.0.0.1:8000/api/stream/policy",
    "policy_poll_sec": 2.0,
    "min_fps": 3.0,
    "source": "live",                 # Stream source identifier
    "cameras": ["thermal", "visible"], # Cameras to push
    "annotate_thermal": False         # Clean thermal image (bounding boxes sent via Metadata)
}

# ==============================================================================
# 6. Web Video Streaming & Bandwidth Settings (Tailscale / 4G VPN Optimization)
# ==============================================================================
STREAMING_CONFIG = {
    "bandwidth_mode": "4G_SAVER",      # "LAN_HIGH", "BALANCED", "4G_SAVER", "EXTREME_SAVER", "CUSTOM"
    "stream_fps": 6.0,                 # Streaming FPS for web client (6.0 FPS is smooth & low bandwidth)
    "jpeg_quality": 50,                # 40-75 (50 gives excellent quality while reducing bandwidth by ~65%)
    "visible_max_width": 640,          # Downscale visible camera width for web view (0 = original resolution)
    "thermal_max_width": 640           # Max width for thermal camera web view
}

# ==============================================================================
# 7. Incident Archive & Matching Settings
# ==============================================================================
INCIDENT_CONFIG = {
    "match_tolerance_deg": 1.0,        # Angular proximity threshold (degrees) to consider same fire
    "max_inactive_gap_hours": 2.0,     # Max inactive duration (hours) before closing incident and starting new one
    "hotspot_recheck_enabled": True,   # Automatically re-check remembered hotspots on subsequent scan passes
    "max_misses_to_extinguish": 2      # Consecutive clean re-checks required before marking hotspot as extinguished
}

# ==============================================================================
# 8. Real-time Mobile Notification Settings (Telegram Bot)
# ==============================================================================
TELEGRAM_CONFIG = {
    "enabled": False,
    "bot_token": "",
    "chat_id": "7235888789",
    "send_photos": True,
    "cooldown_sec": 30.0,
    "suppress_false_alarm": True    # Suppress Telegram alert if LLM marks incident as FALSE_ALARM
}

# ==============================================================================
# 9. LLM Multimodal Fire Verification Settings
# ==============================================================================
LLM_CONFIG = {
    "enabled": False,
    "api_key": "",
    "base_url": "https://lllm.narit.or.th/v1",
    "model": "OpenAI-NARIT-Local-AI-01",
    "max_tokens": 2048,
    "temperature": 0.1,
    "timeout_sec": 45
}

# ==============================================================================
# 10. Web Server Configuration
# ==============================================================================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5005

CONFIG_FILE = Path(os.environ.get("FIRE_CAMERA_SETTINGS", str(BASE_DIR / "system_settings.json")))

def load_config_from_file():
    """Loads configuration from JSON file if it exists."""
    import json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if "cameras" in saved:
                    for cam_id, params in saved["cameras"].items():
                        if cam_id in CAMERAS:
                            CAMERAS[cam_id].update(params)
                if "mount" in saved:
                    MOUNT.update(saved["mount"])
                if "ai" in saved:
                    AI_CONFIG.update(saved["ai"])
                if "mission" in saved:
                    MISSION_CONFIG.update(saved["mission"])
                if "frame_publisher" in saved:
                    FRAME_PUBLISHER.update(saved["frame_publisher"])
                if "streaming" in saved:
                    STREAMING_CONFIG.update(saved["streaming"])
                if "incident" in saved:
                    INCIDENT_CONFIG.update(saved["incident"])
                if "telegram" in saved:
                    TELEGRAM_CONFIG.update(saved["telegram"])
                if "llm" in saved:
                    LLM_CONFIG.update(saved["llm"])
                if "thermal_imaging" in saved:
                    THERMAL_IMAGING.update(saved["thermal_imaging"])
                    if "thermal" in CAMERAS:
                        CAMERAS["thermal"]["imaging"] = THERMAL_IMAGING
            print(f"✅ Loaded system settings from {CONFIG_FILE}")
        except Exception as e:
            print(f"⚠️ Error loading settings from {CONFIG_FILE}: {e}")

# Automatically load persisted settings on import
load_config_from_file()

def get_all_config() -> dict:
    return {
        "cameras": CAMERAS,
        "mount": MOUNT,
        "ai": AI_CONFIG,
        "mission": MISSION_CONFIG,
        "frame_publisher": FRAME_PUBLISHER,
        "streaming": STREAMING_CONFIG,
        "incident": INCIDENT_CONFIG,
        "telegram": TELEGRAM_CONFIG,
        "llm": LLM_CONFIG,
        "thermal_imaging": THERMAL_IMAGING
    }

def update_and_save_config(new_cfg: dict) -> bool:
    import json
    try:
        if "cameras" in new_cfg:
            for cam_id, params in new_cfg["cameras"].items():
                if cam_id in CAMERAS:
                    CAMERAS[cam_id].update(params)
        if "mount" in new_cfg:
            MOUNT.update(new_cfg["mount"])
        if "ai" in new_cfg:
            AI_CONFIG.update(new_cfg["ai"])
        if "mission" in new_cfg:
            MISSION_CONFIG.update(new_cfg["mission"])
        if "frame_publisher" in new_cfg:
            FRAME_PUBLISHER.update(new_cfg["frame_publisher"])
        if "streaming" in new_cfg:
            STREAMING_CONFIG.update(new_cfg["streaming"])
        if "incident" in new_cfg:
            INCIDENT_CONFIG.update(new_cfg["incident"])
        if "telegram" in new_cfg:
            TELEGRAM_CONFIG.update(new_cfg["telegram"])
        if "llm" in new_cfg:
            LLM_CONFIG.update(new_cfg["llm"])
        if "thermal_imaging" in new_cfg:
            THERMAL_IMAGING.update(new_cfg["thermal_imaging"])
            if "thermal" in CAMERAS:
                CAMERAS["thermal"]["imaging"] = THERMAL_IMAGING

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(get_all_config(), f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False
