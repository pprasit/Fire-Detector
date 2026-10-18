#!/usr/bin/env python3
"""Exercise a release in the isolated offline environment, without hardware."""
import compileall
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'camera_runtime')]


def main():
    # These binary imports catch missing ARM wheels and OS libraries.
    import av
    import cv2
    import ncnn
    import numpy
    import onvif
    import flask
    import pytest
    if not all(compileall.compile_dir(str(ROOT / folder), quiet=1) for folder in ('src', 'scripts', 'camera_runtime')):
        return 1
    return pytest.main(['-q', 'tests', 'camera_runtime/tests/test_camera_cadence.py',
                        'camera_runtime/tests/test_classic_detector.py',
                        'camera_runtime/tests/test_frame_publisher.py'])


if __name__ == '__main__':
    raise SystemExit(main())
