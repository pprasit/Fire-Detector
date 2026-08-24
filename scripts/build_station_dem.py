#!/usr/bin/env python3
"""Build a station-centred 30 m GeoTIFF from public AWS Terrain Tiles."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
import urllib.request

from PIL import Image, TiffImagePlugin


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
OUTPUT_PATH = PROJECT_ROOT / "data" / "dem" / "output_hh.tif"
TILE_CACHE = PROJECT_ROOT / "data" / "dem" / "tiles"
SAMPLES_PER_DEGREE = 3600
TILE_PIXELS = 3601
AWS_SKADI_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi"


def tile_name(latitude: int, longitude: int) -> str:
    return f"{'N' if latitude >= 0 else 'S'}{abs(latitude):02d}{'E' if longitude >= 0 else 'W'}{abs(longitude):03d}"


def download_tile(latitude: int, longitude: int) -> Path:
    name = tile_name(latitude, longitude)
    path = TILE_CACHE / f"{name}.hgt.gz"
    if path.is_file() and path.stat().st_size > 1024:
        return path
    TILE_CACHE.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".gz.tmp")
    url = f"{AWS_SKADI_URL}/{name[:3]}/{name}.hgt.gz"
    request = urllib.request.Request(url, headers={"User-Agent": "FireDetector/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def open_hgt(path: Path) -> Image.Image:
    with gzip.open(path, "rb") as source:
        payload = source.read()
    expected = TILE_PIXELS * TILE_PIXELS * 2
    if len(payload) != expected:
        raise ValueError(f"{path.name} has {len(payload)} bytes; expected {expected}.")
    return Image.frombytes("I;16B", (TILE_PIXELS, TILE_PIXELS), payload)


def build_dem(latitude: float, longitude: float, radius_km: float, output: Path) -> dict[str, object]:
    north_south_deg = radius_km / 111.32
    east_west_deg = radius_km / (111.32 * math.cos(math.radians(latitude)))
    requested = {
        "south": latitude - north_south_deg,
        "north": latitude + north_south_deg,
        "west": longitude - east_west_deg,
        "east": longitude + east_west_deg,
    }
    west_index = math.floor(requested["west"] * SAMPLES_PER_DEGREE)
    east_index = math.ceil(requested["east"] * SAMPLES_PER_DEGREE)
    south_index = math.floor(requested["south"] * SAMPLES_PER_DEGREE)
    north_index = math.ceil(requested["north"] * SAMPLES_PER_DEGREE)
    width = east_index - west_index
    height = north_index - south_index
    mosaic = Image.new("I", (width, height))

    for tile_lat in range(math.floor(requested["south"]), math.floor(requested["north"]) + 1):
        for tile_lon in range(math.floor(requested["west"]), math.floor(requested["east"]) + 1):
            tile_west = tile_lon * SAMPLES_PER_DEGREE
            tile_east = (tile_lon + 1) * SAMPLES_PER_DEGREE
            tile_south = tile_lat * SAMPLES_PER_DEGREE
            tile_north = (tile_lat + 1) * SAMPLES_PER_DEGREE
            overlap_west = max(west_index, tile_west)
            overlap_east = min(east_index, tile_east)
            overlap_south = max(south_index, tile_south)
            overlap_north = min(north_index, tile_north)
            if overlap_west >= overlap_east or overlap_south >= overlap_north:
                continue
            source = open_hgt(download_tile(tile_lat, tile_lon))
            source_left = overlap_west - tile_west
            source_right = overlap_east - tile_west
            source_top = tile_north - overlap_north
            source_bottom = tile_north - overlap_south
            region = source.crop((source_left, source_top, source_right, source_bottom))
            destination_x = overlap_west - west_index
            destination_y = north_index - overlap_north
            mosaic.paste(region, (destination_x, destination_y))
            source.close()
            region.close()

    west = west_index / SAMPLES_PER_DEGREE
    north = north_index / SAMPLES_PER_DEGREE
    scale = 1.0 / SAMPLES_PER_DEGREE
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[33550] = (scale, scale, 0.0)
    tags[33922] = (0.0, 0.0, 0.0, west, north, 0.0)
    tags[34735] = (1, 1, 0, 3, 1024, 0, 1, 2, 2048, 0, 1, 4326, 2054, 0, 1, 9102)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tif.tmp")
    mosaic.save(temporary, format="TIFF", compression="tiff_deflate", tiffinfo=tags)
    mosaic.close()
    temporary.replace(output)
    return {
        "path": str(output),
        "width": width,
        "height": height,
        "bounds": {
            "west": west,
            "south": south_index / SAMPLES_PER_DEGREE,
            "east": east_index / SAMPLES_PER_DEGREE,
            "north": north,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--radius-km", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    station = settings["station"]
    result = build_dem(float(station["latitude"]), float(station["longitude"]), args.radius_km, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
