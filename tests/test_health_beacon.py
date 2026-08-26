import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "health_beacon.py"
SPEC = importlib.util.spec_from_file_location("health_beacon", MODULE_PATH)
health_beacon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health_beacon)


def healthy_status():
    return {
        "run_mode": "hardware", "simulation_mode": False, "connected": True,
        "health": "ready", "has_bus_power": True,
        "axes": [
            {"label": "Azimuth", "available": True, "active_errors": 0},
            {"label": "Altitude", "available": True, "active_errors": 0},
        ],
        "azimuth_sensors": {"cw_pin": 13, "cw_error": None, "ccw_pin": 17, "ccw_error": None},
    }


def healthy_cameras():
    return {"sources": {"live": {"connected": True, "cameras": {
        "thermal": {"connected": True}, "visible": {"connected": True},
    }}}}


def test_all_required_hardware_is_healthy():
    assert health_beacon.health_reason(healthy_status(), healthy_cameras()) is None
    assert health_beacon.pattern_output(health_beacon.MODE_HEALTHY, 0.0) is True
    assert health_beacon.pattern_output(health_beacon.MODE_HEALTHY, 0.19) is True
    assert health_beacon.pattern_output(health_beacon.MODE_HEALTHY, 0.2) is False
    assert health_beacon.pattern_output(health_beacon.MODE_HEALTHY, 2.19) is False
    assert health_beacon.pattern_output(health_beacon.MODE_HEALTHY, 2.2) is True


def test_missing_drive_turns_beacon_off():
    status = healthy_status()
    status["axes"] = status["axes"][:1]
    mode, reason = health_beacon.beacon_state(status, healthy_cameras())
    assert mode == health_beacon.MODE_ALTITUDE_ERROR
    assert "altitude" in reason


def test_missing_camera_turns_beacon_off():
    cameras = healthy_cameras()
    cameras["sources"]["live"]["cameras"]["visible"]["connected"] = False
    mode, reason = health_beacon.beacon_state(healthy_status(), cameras)
    assert mode == health_beacon.MODE_VISIBLE_MISSING
    assert "visible" in reason


def test_thermal_missing_visible_healthy_uses_double_flash():
    cameras = healthy_cameras()
    cameras["sources"]["live"]["cameras"]["thermal"]["connected"] = False
    mode, _ = health_beacon.beacon_state(healthy_status(), cameras)
    assert mode == health_beacon.MODE_THERMAL_MISSING
    assert [health_beacon.pattern_output(mode, value) for value in (0.0, 0.5, 1.0, 1.5, 3.49, 3.5)] == [
        True, False, True, False, False, True,
    ]


def test_visible_missing_thermal_healthy_uses_triple_flash():
    cameras = healthy_cameras()
    cameras["sources"]["live"]["cameras"]["visible"]["connected"] = False
    mode, _ = health_beacon.beacon_state(healthy_status(), cameras)
    assert mode == health_beacon.MODE_VISIBLE_MISSING
    assert [health_beacon.pattern_output(mode, value) for value in (
        0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 4.49, 4.5,
    )] == [True, False, True, False, True, False, False, True]


def assert_flash_count(mode, count):
    samples = [health_beacon.pattern_output(mode, index / 10) for index in range(int((count + 1.5) * 10))]
    starts = sum(value and (index == 0 or not samples[index - 1]) for index, value in enumerate(samples))
    assert starts == count
    assert all(not value for value in samples[count * 10 - 5:])


def test_general_not_ready_state_flashes_once_instead_of_looking_dead():
    status = healthy_status()
    status["connected"] = False
    mode, _ = health_beacon.beacon_state(status, healthy_cameras())
    assert mode == health_beacon.MODE_OFF
    assert_flash_count(mode, 1)


def test_both_cameras_missing_flashes_general_not_ready_code():
    cameras = healthy_cameras()
    cameras["sources"]["live"]["connected"] = False
    cameras["sources"]["live"]["cameras"]["thermal"]["connected"] = False
    cameras["sources"]["live"]["cameras"]["visible"]["connected"] = False
    mode, reason = health_beacon.beacon_state(healthy_status(), cameras)
    assert mode == health_beacon.MODE_OFF
    assert reason == "both camera streams are missing"
    assert health_beacon.beacon_label(mode, reason) == "BOTH CAMERAS OFFLINE"
    assert_flash_count(mode, 1)


def test_axis_and_internet_patterns():
    status = healthy_status()
    status["axes"][0]["active_errors"] = 1
    assert health_beacon.beacon_state(status, healthy_cameras())[0] == health_beacon.MODE_AZIMUTH_ERROR
    assert_flash_count(health_beacon.MODE_AZIMUTH_ERROR, 4)

    status = healthy_status()
    status["axes"][1]["available"] = False
    assert health_beacon.beacon_state(status, healthy_cameras())[0] == health_beacon.MODE_ALTITUDE_ERROR
    assert_flash_count(health_beacon.MODE_ALTITUDE_ERROR, 5)

    mode, _ = health_beacon.beacon_state(healthy_status(), healthy_cameras(), telemetry_connected=False)
    assert mode == health_beacon.MODE_INTERNET_ERROR
    assert_flash_count(mode, 6)


def test_disconnected_internet_uses_rapid_100ms_pattern():
    mode, reason = health_beacon.beacon_state(
        healthy_status(), healthy_cameras(), internet_connected=False
    )
    assert mode == health_beacon.MODE_NETWORK_DISCONNECTED
    assert "internet" in reason
    assert [health_beacon.pattern_output(mode, value) for value in (
        0.0, 0.099, 0.1, 0.199, 0.2, 0.299,
    )] == [True, True, False, False, True, True]
