import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "control_worker.py"
SPEC = importlib.util.spec_from_file_location("control_worker", SCRIPT)
control_worker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(control_worker)


class FakeMount:
    def __init__(self):
        self.stops = 0
        self.jogs = []
        self.enabled = 0
        self.disabled = 0

    async def stop(self):
        self.stops += 1

    async def jog(self, azimuth, altitude, azimuth_limit, altitude_limit):
        self.jogs.append((azimuth, altitude))
        return {"Azimuth": azimuth_limit, "Altitude": altitude_limit}

    async def enable(self, axes, move_after_enable):
        self.enabled += 1

    async def disable(self):
        self.disabled += 1


class SlowFakeMount(FakeMount):
    async def jog(self, azimuth, altitude, azimuth_limit, altitude_limit):
        await asyncio.sleep(10)


class FakeWebSocket(asyncio.PriorityQueue):
    @property
    def sent(self):
        return [item[2] for item in sorted(self._queue)]


class FakeSessionSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        try:
            return json.dumps(next(self.messages))
        except StopIteration:
            raise ConnectionError("test session ended")


class ControlWorkerTests(unittest.IsolatedAsyncioTestCase):
    def worker(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with (
            patch.object(control_worker, "SETTINGS_PATH", Path(__file__).resolve().parents[1] / "AppSetting.JSON"),
            patch.object(control_worker, "STATE_PATH", Path(temporary.name) / "state.json"),
        ):
            worker = control_worker.ControlWorker(watchdog_seconds=0.03)
        worker.mount = FakeMount()
        return worker

    async def test_held_jog_starts_without_using_absolute_expiry(self):
        worker = self.worker()
        websocket = FakeWebSocket()
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        await worker.handle_command(websocket, {
            "protocol_version": 1, "station_id": "iriv-production",
            "sequence": 2, "command_type": "jog", "expires_at": expired,
            "command": {"azimuth_direction": 1, "altitude_direction": 0, "hold_id": "hold-2"},
        })
        self.assertEqual(worker.mount.jogs, [(1, 0)])
        self.assertEqual(websocket.sent[-1]["state"], "accepted")

    async def test_old_and_duplicate_sequences_are_ignored(self):
        worker = self.worker()
        websocket = FakeWebSocket()
        base = {"protocol_version": 1, "station_id": "iriv-production", "command_type": "stop", "command": {}}
        await worker.handle_command(websocket, {**base, "sequence": 4})
        await worker.handle_command(websocket, {**base, "sequence": 4})
        await worker.handle_command(websocket, {**base, "sequence": 3})
        self.assertEqual(worker.mount.stops, 1)
        self.assertEqual(len(websocket.sent), 3)

    async def test_monotonic_watchdog_stops_jog(self):
        worker = self.worker()
        websocket = FakeWebSocket()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        await worker.handle_command(websocket, {
            "protocol_version": 1, "station_id": "iriv-production",
            "sequence": 5, "command_type": "jog", "expires_at": expires,
            "command": {"azimuth_direction": -1, "altitude_direction": 1, "hold_id": "hold-5"},
        })
        await asyncio.sleep(0.06)
        self.assertEqual(worker.mount.jogs, [(-1, 1)])
        self.assertEqual(worker.mount.stops, 1)

    async def test_matching_keepalive_renews_without_ack_or_restart(self):
        worker = self.worker()
        websocket = FakeWebSocket()
        await worker.handle_command(websocket, {
            "protocol_version": 1, "station_id": "iriv-production", "sequence": 6,
            "command_type": "jog",
            "command": {"azimuth_direction": 1, "altitude_direction": 0, "hold_id": "held"},
        })
        for _ in range(8):
            await asyncio.sleep(0.01)
            worker.renew_jog_watchdog({
                "type": "jog_keepalive", "protocol_version": 1, "sequence": 6, "hold_id": "held"
            })
        self.assertEqual(worker.mount.stops, 0)
        self.assertEqual(len(websocket.sent), 1)
        worker.renew_jog_watchdog({
            "type": "jog_keepalive", "protocol_version": 1, "sequence": 999, "hold_id": "wrong"
        })
        await asyncio.sleep(0.05)
        self.assertEqual(worker.mount.stops, 1)

    async def test_enable_and_disable_ack_completed(self):
        worker = self.worker()
        websocket = FakeWebSocket()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        base = {"protocol_version": 1, "station_id": "iriv-production", "expires_at": expires}
        await worker.handle_command(websocket, {
            **base, "sequence": 10, "command_type": "enable",
            "command": {"axes": ["azimuth", "altitude"], "move_after_enable": False},
        })
        await worker.handle_command(websocket, {
            "protocol_version": 1, "station_id": "iriv-production",
            "sequence": 11, "command_type": "disable", "command": {"axes": ["azimuth", "altitude"]},
        })
        self.assertEqual(worker.mount.enabled, 1)
        self.assertEqual(worker.mount.disabled, 1)
        self.assertEqual([item["state"] for item in websocket.sent], ["completed", "completed"])

    async def test_safe_stop_always_bypasses_sequence(self):
        worker = self.worker()
        worker.last_sequence = 99
        await worker.safe_stop("reconnect")
        self.assertEqual(worker.mount.stops, 1)

    async def test_failed_unauthenticated_session_does_not_stop_motion(self):
        worker = self.worker()
        socket = FakeSessionSocket([])
        with patch.object(control_worker.websockets, "connect", return_value=socket):
            with self.assertRaises(ConnectionError):
                await worker.session()
        self.assertEqual(worker.mount.stops, 0)

    async def test_authenticated_session_loss_stops_exactly_once(self):
        worker = self.worker()
        socket = FakeSessionSocket([
            {"type": "authenticated"},
            {"type": "safe_stop", "reason": "connection_established"},
        ])
        with patch.object(control_worker.websockets, "connect", return_value=socket):
            with self.assertRaises(ConnectionError):
                await worker.session()
        self.assertEqual(worker.mount.stops, 1)

    async def test_region_sensor_does_not_block_enable(self):
        settings = json.loads((Path(__file__).resolve().parents[1] / "AppSetting.JSON").read_text())
        mount = control_worker.LocalMount(settings, motion_enabled=False)
        base = {
            "connected": True, "health": "ready", "has_bus_power": True,
            "azimuth_sensors": {"cw_sensor": True, "ccw_sensor": False},
            "axes": [
                {"label": "Azimuth", "available": True, "is_armed": False, "active_errors": 0, "disarm_reason": 0},
                {"label": "Altitude", "available": True, "is_armed": False, "active_errors": 0, "disarm_reason": 0},
            ],
        }
        armed = {**base, "axes": [{**axis, "is_armed": True} for axis in base["axes"]]}
        mount.status = AsyncMock(side_effect=[base, armed])
        with patch.object(mount, "request", return_value={"ok": True}):
            await mount.enable(["azimuth", "altitude"], False)

    async def test_local_jog_uses_sequenced_deadman_heartbeats(self):
        settings = json.loads((Path(__file__).resolve().parents[1] / "AppSetting.JSON").read_text())
        mount = control_worker.LocalMount(settings, motion_enabled=True)
        mount.preflight = AsyncMock(return_value={
            "connected": True,
            "health": "ready",
            "has_bus_power": True,
            "axes": [
                {"label": "Azimuth", "velocity_limit": 20.0},
                {"label": "Altitude", "velocity_limit": 20.0},
            ],
        })
        mount.request = MagicMock(return_value={"ok": True})

        await mount.jog(1, 0, 5.0, 5.0)
        await asyncio.sleep(0.23)
        await mount.stop()

        jog_calls = [
            call for call in mount.request.call_args_list
            if len(call.args) >= 2 and call.args[1] == "/api/motors/velocity-command"
        ]
        self.assertGreaterEqual(len(jog_calls), 2)
        sequences = [int(call.args[3]["X-Motion-Command-Sequence"]) for call in jog_calls]
        client_ids = {call.args[3]["X-Motion-Client-ID"] for call in jog_calls}
        self.assertEqual(sequences[:2], [1, 2])
        self.assertEqual(len(client_ids), 1)

    async def test_stop_bypasses_blocked_motor_executor(self):
        worker = self.worker()
        worker.mount = SlowFakeMount()
        commands = asyncio.PriorityQueue()
        acknowledgements = FakeWebSocket()
        executor = asyncio.create_task(worker.motor_executor(commands, acknowledgements))
        await commands.put((10, 1, {
            "type": "mount_command", "protocol_version": 1, "station_id": "iriv-production",
            "sequence": 20, "command_type": "jog",
            "command": {"azimuth_direction": 1, "altitude_direction": 0, "hold_id": "slow"},
        }))
        await asyncio.sleep(0.01)
        await asyncio.wait_for(worker.urgent_stop(acknowledgements, {
            "sequence": 21, "command_type": "stop"
        }, "test_stop"), timeout=0.1)
        self.assertEqual(worker.mount.stops, 1)
        self.assertEqual(acknowledgements.sent[0]["state"], "stopped")
        executor.cancel()
        await asyncio.gather(executor, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
