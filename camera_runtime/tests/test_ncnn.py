#!/usr/bin/env python3
"""
Test NCNN AI Model loading and inference inside Integrated_System
"""

import os
import sys
import time
from pathlib import Path
import cv2
import numpy as np
import ncnn

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import config

def main():
    print("=" * 65)
    print(" 🔥 Testing NCNN AI Model in Integrated_System")
    print("=" * 65)
    print(f"Param Path : {config.AI_CONFIG['model_param']}")
    print(f"Bin Path   : {config.AI_CONFIG['model_bin']}")

    net = ncnn.Net()
    net.opt.use_vulkan_compute = False
    net.opt.num_threads = 4

    assert net.load_param(config.AI_CONFIG["model_param"]) == 0, "Param load failed"
    assert net.load_model(config.AI_CONFIG["model_bin"]) == 0, "Bin load failed"
    print("✅ Model loaded successfully!")

    img_path = str(Path(__file__).resolve().parent / "wildfire_test.jpg")
    img = cv2.imread(img_path)
    assert img is not None, f"Image not found at {img_path}"

    in_mat = ncnn.Mat.from_pixels_resize(
        img,
        ncnn.Mat.PixelType.PIXEL_BGR2RGB,
        img.shape[1], img.shape[0],
        640, 640
    )
    in_mat.substract_mean_normalize([0,0,0], [1/255, 1/255, 1/255])

    t0 = time.perf_counter()
    ex = net.create_extractor()
    ex.input("in0", in_mat)
    _, out_mat = ex.extract("out0")
    lat_ms = (time.perf_counter() - t0) * 1000.0

    print(f"✅ NCNN Inference finished in {lat_ms:.2f} ms ({1000/lat_ms:.1f} FPS)")
    print("=" * 65)

if __name__ == "__main__":
    main()
