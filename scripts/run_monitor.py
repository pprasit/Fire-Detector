#!/usr/bin/env python3
"""Run the Fire Detector monitor web server."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from fire_detector.web_server import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Fire Detector monitor web server.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address.")
    parser.add_argument("--port", default=8000, type=int, help="Bind port.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
