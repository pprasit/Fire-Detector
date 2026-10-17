"""
Test Frame Ingest Publisher
Tests sending frames to a mock HTTP server adhering to Mount Agent Ingest API specifications.
"""

import time
import json
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import numpy as np
import cv2
from datetime import datetime, timezone

from frame_publisher import FramePublisher


class MockIngestHandler(BaseHTTPRequestHandler):
    received_frames = []

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        metadata_header = self.headers.get('X-Camera-Metadata')
        content_type = self.headers.get('Content-Type')
        body = self.rfile.read(content_length)

        MockIngestHandler.received_frames.append({
            "path": self.path,
            "content_type": content_type,
            "metadata": json.loads(metadata_header) if metadata_header else None,
            "size": len(body)
        })

        self.send_response(202)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "path": self.path}).encode('utf-8'))

    def log_message(self, format, *args):
        pass  # Quiet logger during testing


class MockCamera:
    def __init__(self, name):
        self.name = name
        # Create a blank 640x512 image
        img = np.zeros((512, 640, 3), dtype=np.uint8)
        _, self.jpeg = cv2.imencode(".jpg", img)
        self.bgr = img
        self.sequence = 0
        self.target_fps = 60

    def get_latest_frame(self):
        return self.bgr, self.jpeg.tobytes()

    def get_latest_encoded_frame(self):
        self.sequence += 1
        return {
            "jpeg": self.jpeg.tobytes(),
            "width": 640,
            "height": 512,
            "sequence": self.sequence,
            "captured_at": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z"),
            "source": "live",
            "simulated": False,
            "source_verified": True,
        }


class StaticMockCamera(MockCamera):
    def get_latest_encoded_frame(self):
        return {
            "jpeg": self.jpeg.tobytes(),
            "width": 640,
            "height": 512,
            "sequence": 1,
            "captured_at": "2026-08-27T00:00:00.000Z",
            "source": "live",
            "simulated": False,
            "source_verified": True,
        }


class EventMockCamera(MockCamera):
    def wait_for_encoded_frame(self, _after_sequence, timeout=1.0):
        time.sleep(min(0.02, timeout))
        return self.get_latest_encoded_frame()


class MatchedEventMockCamera(MockCamera):
    def __init__(self, name):
        super().__init__(name)
        self.target_fps = 15

    def wait_for_encoded_frame(self, _after_sequence, timeout=1.0):
        time.sleep(min(1.0 / self.target_fps, timeout))
        return self.get_latest_encoded_frame()


class MockCameraManager:
    def __init__(self):
        self.cameras = {
            "thermal": MockCamera("thermal"),
            "visible": MockCamera("visible")
        }

    def get_camera(self, cam_id):
        return self.cameras.get(cam_id)


class TestFramePublisher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MockIngestHandler.received_frames = []
        cls.server = HTTPServer(('127.0.0.1', 18888), MockIngestHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_publisher_flow(self):
        MockIngestHandler.received_frames = []
        mock_cam_mgr = MockCameraManager()
        cfg = {
            "enabled": True,
            "server_url": "http://127.0.0.1:18888",
            "target_fps": 15,
            "source": "live",
            "cameras": ["thermal", "visible"]
        }

        pub = FramePublisher(mock_cam_mgr, cfg)
        pub.start()

        time.sleep(0.45)
        pub.stop()

        status = pub.get_status()
        self.assertEqual(status["target_fps"], 15)
        self.assertTrue(status["stats"]["thermal"]["sent"] >= 5)
        self.assertTrue(status["stats"]["visible"]["sent"] >= 5)

        # Verify received payloads in mock server
        self.assertTrue(len(MockIngestHandler.received_frames) >= 4)
        first_frame = MockIngestHandler.received_frames[0]
        self.assertEqual(first_frame["content_type"], "image/jpeg")
        self.assertIn("producer_sequence", first_frame["metadata"])
        self.assertIn("capture_sequence", first_frame["metadata"])
        self.assertEqual(first_frame["metadata"]["width"], 640)
        self.assertEqual(first_frame["metadata"]["height"], 512)
        print("\n✅ Test passed! Received frames verification successful.")

    def test_stale_camera_frame_is_not_republished(self):
        MockIngestHandler.received_frames = []
        manager = MockCameraManager()
        manager.cameras = {"thermal": StaticMockCamera("thermal")}
        pub = FramePublisher(manager, {
            "enabled": True,
            "server_url": "http://127.0.0.1:18888",
            "target_fps": 15,
            "source": "live",
            "cameras": ["thermal"],
        })
        pub.start()
        time.sleep(0.25)
        pub.stop()

        self.assertEqual(pub.get_status()["stats"]["thermal"]["sent"], 1)
        self.assertGreaterEqual(pub.get_status()["stats"]["thermal"]["stale"], 2)

    def test_event_driven_camera_is_capped_at_target_fps(self):
        MockIngestHandler.received_frames = []
        manager = MockCameraManager()
        manager.cameras = {"thermal": EventMockCamera("thermal")}
        pub = FramePublisher(manager, {
            "enabled": True,
            "server_url": "http://127.0.0.1:18888",
            "target_fps": 10,
            "source": "live",
            "cameras": ["thermal"],
        })
        pub.start()
        time.sleep(0.55)
        pub.stop()

        status = pub.get_status()["stats"]["thermal"]
        self.assertGreaterEqual(status["sent"], 5)
        self.assertLessEqual(status["sent"], 7)
        self.assertGreater(status["skipped"], 0)

    def test_matching_camera_and_publisher_rates_do_not_alias(self):
        MockIngestHandler.received_frames = []
        manager = MockCameraManager()
        manager.cameras = {"visible": MatchedEventMockCamera("visible")}
        pub = FramePublisher(manager, {
            "enabled": True,
            "server_url": "http://127.0.0.1:18888",
            "target_fps": 15,
            "source": "live",
            "cameras": ["visible"],
        })
        pub.start()
        time.sleep(0.55)
        pub.stop()

        status = pub.get_status()["stats"]["visible"]
        self.assertGreaterEqual(status["sent"], 4)
        self.assertLessEqual(status["sent"], 10)
        self.assertEqual(status["skipped"], 0)

    def test_adaptive_policy_is_bounded_by_minimum_and_configured_cap(self):
        pub = FramePublisher(MockCameraManager(), {
            "enabled": True,
            "server_url": "http://127.0.0.1:18888",
            "target_fps": 15,
            "adaptive": True,
            "min_fps": 3,
        })

        self.assertEqual(pub._apply_adaptive_target(10), 10)
        self.assertEqual(pub._apply_adaptive_target(30), 15)
        self.assertEqual(pub._apply_adaptive_target(1), 3)

    def test_camera_view_metadata_uses_latest_frame_without_publisher(self):
        pub = FramePublisher(MockCameraManager(), {
            "enabled": False,
            "target_fps": 15,
        })

        metadata = pub.get_camera_metadata("thermal")

        self.assertEqual(metadata["camera_id"], "thermal")
        self.assertEqual(metadata["width"], 640)
        self.assertEqual(metadata["height"], 512)
        self.assertEqual(metadata["producer_sequence"], metadata["capture_sequence"])
        self.assertEqual(metadata["focal_length_mm"], 31.0)
        self.assertIn("mission_state", metadata)
        self.assertIn("fire_detected", metadata)
        self.assertIsNone(pub.get_camera_metadata("unknown"))

    def test_annotated_thermal_frame_publishing(self):
        """Verify that when detections exist, thermal frame is overlaid and metadata contains detections."""
        overlay_called = []
        sample_dets = [{"box": [100, 100, 200, 200], "score": 0.95, "state": "CONFIRMED_FIRE"}]

        def dummy_overlay(frame, dets):
            overlay_called.append(len(dets))
            out = frame.copy()
            cv2.circle(out, (150, 150), 20, (0, 0, 255), -1)
            return out

        pub = FramePublisher(
            MockCameraManager(),
            {
                "enabled": True,
                "server_url": "http://127.0.0.1:18888",
                "interval_sec": 0.05,
                "target_fps": 20,
                "cameras": ["thermal"],
                "annotate_thermal": True,
            },
            get_detections_fn=lambda: sample_dets,
            overlay_fn=dummy_overlay,
        )
        pub.start()
        time.sleep(0.15)
        pub.stop()

        self.assertGreater(len(overlay_called), 0)
        thermal_frames = [f for f in MockIngestHandler.received_frames if "thermal" in f["path"]]
        self.assertGreater(len(thermal_frames), 0)
        latest_meta = thermal_frames[-1]["metadata"]
        self.assertTrue(latest_meta["fire_detected"])
        self.assertTrue(latest_meta["annotated"])
        self.assertEqual(len(latest_meta["detections"]), 1)
        self.assertEqual(latest_meta["detections"][0]["box"], [100, 100, 200, 200])

    def test_clean_thermal_frame_with_metadata_detections(self):
        """Verify that when annotate_thermal=False, frame is clean (no overlay) but metadata has detections."""
        overlay_called = []
        sample_dets = [{"box": [50, 60, 120, 180], "score": 0.88, "state": "CONFIRMED_FIRE"}]

        def dummy_overlay(frame, dets):
            overlay_called.append(len(dets))
            return frame

        pub = FramePublisher(
            MockCameraManager(),
            {
                "enabled": True,
                "server_url": "http://127.0.0.1:18888",
                "interval_sec": 0.05,
                "target_fps": 20,
                "cameras": ["thermal"],
                "annotate_thermal": False,  # Clean frame
            },
            get_detections_fn=lambda: sample_dets,
            overlay_fn=dummy_overlay,
        )
        pub.start()
        time.sleep(0.15)
        pub.stop()

        # overlay_fn must NOT be called when annotate_thermal is False
        self.assertEqual(len(overlay_called), 0)
        thermal_frames = [f for f in MockIngestHandler.received_frames if "thermal" in f["path"]]
        self.assertGreater(len(thermal_frames), 0)
        latest_meta = thermal_frames[-1]["metadata"]
        self.assertTrue(latest_meta["fire_detected"])
        self.assertFalse(latest_meta["annotated"])
        self.assertEqual(len(latest_meta["detections"]), 1)
        self.assertEqual(latest_meta["detections"][0]["box"], [50, 60, 120, 180])
        self.assertEqual(latest_meta["detections"][0]["score"], 0.88)


if __name__ == '__main__':
    unittest.main()
