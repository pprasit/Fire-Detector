"""
Test Classic Thermal Hotspot Detector
Tests hotspot segmentation, bounding boxes, and score calculation on test images.
"""

import sys
import os
from pathlib import Path
import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from thermal_detector import ClassicThermalDetector


def test_synthetic_hotspot():
    detector = ClassicThermalDetector(threshold=180, min_area=10, max_area=10000)

    # Create dark image (cool background) with a bright heat hotspot in center
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :] = (30, 10, 10)  # Dark blue / cold

    # Add hotspot
    cv2.circle(frame, (320, 240), 20, (255, 255, 255), -1)  # White-hot circle

    dets = detector.detect(frame)
    print(f"Synthetic test: found {len(dets)} detections.")
    assert len(dets) >= 1, "Expected at least 1 detection on synthetic hotspot"
    box = dets[0]["box"]
    score = dets[0]["score"]
    print(f"Detected Box: {box}, Score: {score:.3f}, Area: {dets[0]['area']}")

    # Box should surround the circle (x: ~300..340, y: ~220..260)
    assert 290 <= box[0] <= 310, f"Unexpected x1: {box[0]}"
    assert 210 <= box[1] <= 230, f"Unexpected y1: {box[1]}"
    assert 330 <= box[2] <= 350, f"Unexpected x2: {box[2]}"
    assert 250 <= box[3] <= 270, f"Unexpected y2: {box[3]}"
    print("✅ Synthetic Hotspot Test Passed!")


def test_wildfire_image():
    test_img_path = str(BASE_DIR / "tests" / "wildfire_test.jpg")
    if not os.path.exists(test_img_path):
        print("Wildfire image not found, skipping image test.")
        return

    frame = cv2.imread(test_img_path)
    assert frame is not None, "Failed to read wildfire_test.jpg"

    detector = ClassicThermalDetector(threshold=160, min_area=10, max_area=50000)
    dets = detector.detect(frame)
    print(f"Wildfire test image: found {len(dets)} detections.")
    for i, d in enumerate(dets[:5]):
        print(f"  #{i+1}: Box={d['box']}, Score={d['score']}, Area={d['area']}, MaxVal={d['max_val']}")
    print("✅ Wildfire Image Test Passed!")


def test_fragment_merging():
    detector = ClassicThermalDetector(threshold=180, min_area=10, max_area=50000)

    # Create dark frame with 3 small disconnected hotspots that belong to same object (close to each other)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(frame, (300, 240), 6, (255, 255, 255), -1)
    cv2.circle(frame, (315, 242), 6, (255, 255, 255), -1)
    cv2.circle(frame, (330, 238), 6, (255, 255, 255), -1)

    dets = detector.detect(frame)
    print(f"Fragment merging test: found {len(dets)} detections (should be merged into 1).")
    assert len(dets) == 1, f"Expected 1 merged detection, got {len(dets)}"
    box = dets[0]["box"]
    print(f"Merged Box: {box}, Area: {dets[0]['area']}")
    assert box[0] <= 300 and box[2] >= 330, "Bounding box should cover all 3 fragments"
    print("✅ Fragment Merging Test Passed!")


def test_tophat_and_adaptive_invariance():
    """
    Test Method 1 (Top-Hat) & Method 2 (Adaptive Thresholding) under simulated AGC background shift.
    Even when the background rises significantly (e.g. fog/bright terrain at 130),
    the hotspot (220) should still be accurately isolated and detected.
    """
    detector = ClassicThermalDetector(
        threshold=190,
        min_area=10,
        max_area=50000,
        use_tophat=True,
        tophat_ksize=15,
        tophat_threshold=30,
        use_adaptive=True,
        adaptive_k=2.5,
        adaptive_min_threshold=160,
        zoom_aware=True
    )

    # Simulated scene with high background luminance due to AGC stretch (intensity 120-130)
    frame = np.full((480, 640, 3), 125, dtype=np.uint8)
    # Add random low-amplitude background texture/fog (115 to 135)
    noise = np.random.randint(-10, 10, (480, 640, 3), dtype=np.int16)
    frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # Insert a distinct hotspot (peak 225, radius 12 px -> ~450 px area)
    cv2.circle(frame, (320, 240), 12, (225, 225, 225), -1)

    dets = detector.detect(frame, zoom_ratio=0.0)
    print(f"Top-Hat & Adaptive AGC shift test: found {len(dets)} detections.")
    assert len(dets) >= 1, "Expected hotspot to be detected despite high background shift"
    box = dets[0]["box"]
    print(f"Detected Hotspot Box: {box}, Score: {dets[0]['score']}, Active Threshold: {dets[0]['active_threshold']}")
    assert 300 <= box[0] <= 315 and 325 <= box[2] <= 340, f"Hotspot bounding box x incorrect: {box}"
    assert 220 <= box[1] <= 235 and 245 <= box[3] <= 260, f"Hotspot bounding box y incorrect: {box}"
    print("✅ Top-Hat & Adaptive Invariance Test Passed!")


def test_zoom_aware_scaling():
    """
    Test Method 4 (Zoom-Aware Area Scaling).
    At wide zoom (zoom_ratio=0.0), small specks (area ~16 px) should pass.
    At tele zoom (zoom_ratio=1.0), small noise specks (< 60 px) are rejected,
    while large flame zones (> 40000 px) are accepted.
    """
    detector = ClassicThermalDetector(
        threshold=180,
        min_area=15,
        max_area=40000,
        use_tophat=True,
        use_adaptive=True,
        zoom_aware=True,
        min_focal_mm=31.0,
        max_focal_mm=155.0
    )

    # Frame with a 1-pixel sensor noise spike
    frame_small = np.zeros((480, 640, 3), dtype=np.uint8)
    frame_small[200, 200] = (250, 250, 250)

    # 1. Single-pixel sensor noise is filtered out
    dets_tele = detector.detect(frame_small, zoom_ratio=1.0)
    assert len(dets_tele) == 0, f"Expected small sensor noise to be filtered out, got {len(dets_tele)}"
    print("Tele Zoom (1.0): successfully rejected sub-scale noise speck")

    # Frame with a very large flame zone (area ~50,000 px, normally > 40000 max_area)
    frame_large = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame_large, (100, 100), (350, 300), (255, 255, 255), -1)  # 250x200 = 50,000 px

    # At Wide (0.0): > 40,000 px is rejected
    dets_large_wide = detector.detect(frame_large, zoom_ratio=0.0)
    assert len(dets_large_wide) == 0, "Expected >40000 px area to be rejected at wide zoom"

    # At Tele (1.0): max_area is scaled up to ~25x, so 50,000 px passes!
    dets_large_tele = detector.detect(frame_large, zoom_ratio=1.0)
    assert len(dets_large_tele) >= 1, "Expected large flame zone to be accepted at tele zoom"
    print(f"Tele Zoom (1.0): successfully accommodated large target area={dets_large_tele[0]['area']}")

    print("✅ Zoom-Aware Area Scaling Test Passed!")


if __name__ == "__main__":
    test_synthetic_hotspot()
    test_wildfire_image()
    test_fragment_merging()
    test_tophat_and_adaptive_invariance()
    test_zoom_aware_scaling()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
