#!/usr/bin/env python3
"""Generate the authoritative Station simulation and publish it to local viewers."""

from __future__ import annotations

import argparse
import base64
import json
import logging
from pathlib import Path
import sys
import time

from websockets.sync.client import connect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from upload_simulated_thermal_frame import DEFAULT_FRAMES, simulated_zoom_frame  # noqa: E402

LOGGER = logging.getLogger("local-camera-simulation")
STREAM_URL = "ws://127.0.0.1:8000/ws/camera-stream?role=producer&source=simulation"


def frame_payload(camera: str, phase_seconds: float, sequence: int) -> dict[str, object]:
    image, width, height, zoom = simulated_zoom_frame(
        DEFAULT_FRAMES[camera], camera, phase_seconds,
    )
    return {
        "type": "frame",
        "camera": camera,
        "image": {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(image).decode("ascii"),
        },
        "metadata": {
            "simulated": True,
            "source": "station",
            "sequence": sequence,
            "width": width,
            "height": height,
            "zoom_x": round(zoom, 3),
        },
    }


def publish(frame_rate: float) -> None:
    interval = 1.0 / frame_rate
    sequence = 0
    while True:
        try:
            with connect(STREAM_URL, open_timeout=5, close_timeout=2, max_size=None) as socket:
                LOGGER.info("Station simulation connected to local camera relay at %.1f fps", frame_rate)
                while True:
                    started = time.monotonic()
                    phase = time.time()
                    sequence += 1
                    frames = [frame_payload(camera, phase, sequence) for camera in ("thermal", "visible")]
                    socket.send(json.dumps({"type": "frame_batch", "frames": frames}, separators=(",", ":")))
                    time.sleep(max(0.0, interval - (time.monotonic() - started)))
        except Exception as exc:
            LOGGER.warning("Local camera relay unavailable; retrying: %s", exc)
            time.sleep(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-rate", type=float, default=5.0)
    args = parser.parse_args()
    if not 1.0 <= args.frame_rate <= 10.0:
        parser.error("--frame-rate must be between 1 and 10")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    publish(args.frame_rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
