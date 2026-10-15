"""Render a station-centred DEM panorama with Pointing Model imagery."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter


EARTH_RADIUS_M = 6_371_000.0
REFRACTION_COEFFICIENT = 0.13


def _bilinear(array: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    row0 = np.floor(rows).astype(np.int32)
    col0 = np.floor(cols).astype(np.int32)
    row1 = np.clip(row0 + 1, 0, array.shape[0] - 1)
    col1 = np.clip(col0 + 1, 0, array.shape[1] - 1)
    row0 = np.clip(row0, 0, array.shape[0] - 1)
    col0 = np.clip(col0, 0, array.shape[1] - 1)
    row_fraction = rows - row0
    col_fraction = cols - col0
    return (
        array[row0, col0] * (1 - row_fraction) * (1 - col_fraction)
        + array[row0, col1] * (1 - row_fraction) * col_fraction
        + array[row1, col0] * row_fraction * (1 - col_fraction)
        + array[row1, col1] * row_fraction * col_fraction
    )


def _bilinear_rgb(array: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    row0 = np.floor(rows).astype(np.int32)
    col0 = np.floor(cols).astype(np.int32)
    row1 = np.clip(row0 + 1, 0, array.shape[0] - 1)
    col1 = np.clip(col0 + 1, 0, array.shape[1] - 1)
    row0 = np.clip(row0, 0, array.shape[0] - 1)
    col0 = np.clip(col0, 0, array.shape[1] - 1)
    row_fraction = (rows - row0)[:, None]
    col_fraction = (cols - col0)[:, None]
    return (
        array[row0, col0] * (1 - row_fraction) * (1 - col_fraction)
        + array[row0, col1] * (1 - row_fraction) * col_fraction
        + array[row1, col0] * row_fraction * (1 - col_fraction)
        + array[row1, col1] * row_fraction * col_fraction
    )


def _bilinear_rgb_wrapped(array: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Sample an equirectangular image with horizontal 0/360-degree wrapping."""
    row0 = np.floor(rows).astype(np.int32)
    col0 = np.floor(cols).astype(np.int32)
    row1 = np.clip(row0 + 1, 0, array.shape[0] - 1)
    col1 = (col0 + 1) % array.shape[1]
    row0 = np.clip(row0, 0, array.shape[0] - 1)
    col0 %= array.shape[1]
    row_fraction = (rows - row0)[:, None]
    col_fraction = (cols - np.floor(cols))[:, None]
    return (
        array[row0, col0] * (1 - row_fraction) * (1 - col_fraction)
        + array[row0, col1] * (1 - row_fraction) * col_fraction
        + array[row1, col0] * row_fraction * (1 - col_fraction)
        + array[row1, col1] * row_fraction * col_fraction
    )


def _mount_row_to_geographic(
    mount_azimuth_deg: np.ndarray,
    mount_altitude_deg: float,
    *,
    pointing_model: dict[str, Any] | None,
    azimuth_north_offset_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Map one mount-coordinate image row to true geographic sightlines."""
    model = pointing_model if isinstance(pointing_model, dict) else {}
    if model.get("active") is True and model.get("mode") == "single_point_offset":
        device_azimuth = mount_azimuth_deg - float(model.get("azimuth_offset_deg", 0.0))
        device_altitude = np.full_like(
            mount_azimuth_deg,
            mount_altitude_deg - float(model.get("altitude_offset_deg", 0.0)),
        )
    elif model.get("active") is True and isinstance(model.get("rotation_matrix"), list):
        matrix = np.asarray(model["rotation_matrix"], dtype=np.float64)
        if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
            raise ValueError("Pointing Model rotation matrix is invalid.")
        azimuth = np.radians(mount_azimuth_deg)
        altitude = math.radians(mount_altitude_deg)
        horizontal = math.cos(altitude)
        mount = np.stack((
            horizontal * np.sin(azimuth),
            horizontal * np.cos(azimuth),
            np.full_like(azimuth, math.sin(altitude)),
        ))
        device = matrix @ mount
        device /= np.linalg.norm(device, axis=0, keepdims=True)
        device_azimuth = np.degrees(np.arctan2(device[0], device[1]))
        device_altitude = np.degrees(np.arcsin(np.clip(device[2], -1.0, 1.0)))
    else:
        device_azimuth = mount_azimuth_deg
        device_altitude = np.full_like(mount_azimuth_deg, mount_altitude_deg)
    return (
        np.mod(device_azimuth - azimuth_north_offset_deg, 360.0),
        device_altitude,
    )


def _load_imagery(paths: dict[str, Path]) -> dict[str, np.ndarray]:
    imagery: dict[str, np.ndarray] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Pointing Model imagery is missing: {path.name}")
        with Image.open(path) as source:
            sharpened = source.convert("RGB").filter(
                ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=2)
            )
            imagery[name] = np.asarray(sharpened, dtype=np.uint8)
    return imagery


def _sample_imagery(
    imagery: dict[str, np.ndarray],
    east: np.ndarray,
    north: np.ndarray,
    *,
    overview_radius_m: float,
    detail_radius_m: float,
    precision_radius_m: float,
) -> np.ndarray:
    result = np.empty((len(east), 3), dtype=np.float32)
    distance = np.hypot(east, north)
    for name, radius, mask in (
        ("overview", overview_radius_m, np.ones(len(east), dtype=bool)),
        ("detail", detail_radius_m, distance <= detail_radius_m),
        ("precision", precision_radius_m, distance <= precision_radius_m),
    ):
        if not np.any(mask):
            continue
        texture = imagery[name]
        cols = (east[mask] / (2 * radius) + 0.5) * (texture.shape[1] - 1)
        rows = (0.5 - north[mask] / (2 * radius)) * (texture.shape[0] - 1)
        result[mask] = _bilinear_rgb(
            texture,
            np.clip(rows, 0, texture.shape[0] - 1),
            np.clip(cols, 0, texture.shape[1] - 1),
        )
    return result


def render_dem_panorama(
    *,
    dem_path: Path,
    metadata_path: Path,
    imagery_paths: dict[str, Path],
    output_path: Path,
    width: int = 7200,
    height: int = 500,
    altitude_top_deg: float = 10.0,
    altitude_bottom_deg: float = -15.0,
    max_distance_m: float = 20_000.0,
    radial_step_m: float = 15.0,
    pointing_model: dict[str, Any] | None = None,
    azimuth_north_offset_deg: float = 0.0,
) -> dict[str, Any]:
    """Render a DEM panorama reprojected into the mount coordinate frame."""
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    station = metadata["station"]
    imagery_info = metadata.get("imagery") or {}
    with Image.open(dem_path) as source:
        elevation = np.asarray(source, dtype=np.float32).copy()
        pixel_scale = tuple(float(value) for value in source.tag_v2[33550])
        tiepoint = tuple(float(value) for value in source.tag_v2[33922])
    imagery = _load_imagery(imagery_paths)

    station_lat = float(station["latitude"])
    station_lon = float(station["longitude"])
    camera_agl_m = float(station.get("elevation_above_ground_m") or 0.0)
    scale_lon, scale_lat, _ = pixel_scale
    _, _, _, west, north_edge, _ = tiepoint
    station_col = (station_lon - west) / scale_lon
    station_row = (north_edge - station_lat) / scale_lat
    ground_elevation_m = float(
        _bilinear(elevation, np.array([station_row]), np.array([station_col]))[0]
    )
    observer_elevation_m = ground_elevation_m + camera_agl_m
    metres_per_col = scale_lon * 111_320.0 * math.cos(math.radians(station_lat))
    metres_per_row = scale_lat * 111_320.0

    distances = np.arange(radial_step_m, max_distance_m + 0.001, radial_step_m, dtype=np.float32)
    curvature = distances * distances / (2.0 * EARTH_RADIUS_M) * (1.0 - REFRACTION_COEFFICIENT)
    mount_azimuths = np.arange(width, dtype=np.float64) * 360.0 / width
    mount_altitudes = np.linspace(altitude_top_deg, altitude_bottom_deg, height, dtype=np.float64)
    mapped_altitude_min = 90.0
    mapped_altitude_max = -90.0
    for mount_altitude in mount_altitudes:
        _, true_altitudes = _mount_row_to_geographic(
            mount_azimuths,
            float(mount_altitude),
            pointing_model=pointing_model,
            azimuth_north_offset_deg=azimuth_north_offset_deg,
        )
        mapped_altitude_min = min(mapped_altitude_min, float(np.min(true_altitudes)))
        mapped_altitude_max = max(mapped_altitude_max, float(np.max(true_altitudes)))
    degrees_per_pixel = (altitude_top_deg - altitude_bottom_deg) / max(1, height - 1)
    source_altitude_top = min(90.0, mapped_altitude_max + degrees_per_pixel)
    source_altitude_bottom = max(-90.0, mapped_altitude_min - degrees_per_pixel)
    source_height = max(
        height,
        int(math.ceil((source_altitude_top - source_altitude_bottom) / degrees_per_pixel)) + 1,
    )
    ray_altitudes = np.linspace(
        source_altitude_top,
        source_altitude_bottom,
        source_height,
        dtype=np.float32,
    )
    sky_top = np.array([102, 157, 198], dtype=np.float32)
    sky_bottom = np.array([190, 211, 220], dtype=np.float32)
    sky_mix = np.linspace(0.0, 1.0, source_height, dtype=np.float32)[:, None]
    sky_column = sky_top * (1.0 - sky_mix) + sky_bottom * sky_mix
    geographic_panorama = np.repeat(sky_column[:, None, :], width, axis=1)
    hit_count = 0

    overview_radius_m = float(metadata.get("radius_km") or 20.0) * 1000.0
    detail_radius_m = float(imagery_info.get("detail_radius_m") or 5000.0)
    precision_radius_m = float(imagery_info.get("precision_radius_m") or 1000.0)
    for column in range(width):
        bearing = math.radians(column * 360.0 / width)
        east = np.sin(bearing) * distances
        north = np.cos(bearing) * distances
        sample_cols = station_col + east / metres_per_col
        sample_rows = station_row - north / metres_per_row
        valid = (
            (sample_cols >= 0)
            & (sample_cols <= elevation.shape[1] - 1)
            & (sample_rows >= 0)
            & (sample_rows <= elevation.shape[0] - 1)
        )
        profile = _bilinear(elevation, sample_rows, sample_cols)
        terrain_angle = np.degrees(
            np.arctan2(profile - observer_elevation_m - curvature, distances)
        ).astype(np.float32)
        terrain_angle[~valid] = -np.inf
        envelope = np.maximum.accumulate(terrain_angle)
        hit_indices = np.searchsorted(envelope, ray_altitudes, side="left")
        hits = hit_indices < len(distances)
        if not np.any(hits):
            continue

        hit_index = hit_indices[hits]
        target_angle = ray_altitudes[hits]
        current_angle = envelope[hit_index]
        previous_index = np.maximum(hit_index - 1, 0)
        previous_angle = envelope[previous_index]
        denominator = current_angle - previous_angle
        fraction = np.divide(
            target_angle - previous_angle,
            denominator,
            out=np.ones_like(target_angle),
            where=np.abs(denominator) > 1e-6,
        )
        fraction[hit_index == 0] = 1.0
        fraction = np.clip(fraction, 0.0, 1.0)
        previous_distance = np.where(hit_index > 0, distances[previous_index], 0.0)
        hit_distances = previous_distance + fraction * (distances[hit_index] - previous_distance)
        east_hit = np.sin(bearing) * hit_distances
        north_hit = np.cos(bearing) * hit_distances
        colors = _sample_imagery(
            imagery,
            east_hit,
            north_hit,
            overview_radius_m=overview_radius_m,
            detail_radius_m=detail_radius_m,
            precision_radius_m=precision_radius_m,
        )
        haze = np.clip((hit_distances - 9000.0) / 70_000.0, 0.0, 0.16)[:, None]
        colors = colors * (1.0 - haze) + np.array([154, 181, 190]) * haze
        geographic_panorama[hits, column] = np.clip(colors * 1.06 + 2.0, 0, 255)
        hit_count += int(np.count_nonzero(hits))

    panorama = np.empty((height, width, 3), dtype=np.float32)
    source_altitude_span = source_altitude_top - source_altitude_bottom
    for row, mount_altitude in enumerate(mount_altitudes):
        true_azimuths, true_altitudes = _mount_row_to_geographic(
            mount_azimuths,
            float(mount_altitude),
            pointing_model=pointing_model,
            azimuth_north_offset_deg=azimuth_north_offset_deg,
        )
        source_cols = true_azimuths / 360.0 * width
        source_rows = (
            (source_altitude_top - true_altitudes)
            / source_altitude_span
            * (source_height - 1)
        )
        panorama[row] = _bilinear_rgb_wrapped(
            geographic_panorama,
            np.clip(source_rows, 0, source_height - 1),
            source_cols,
        )

    output = Image.fromarray(np.rint(panorama).astype(np.uint8), mode="RGB").filter(
        ImageFilter.UnsharpMask(radius=0.6, percent=55, threshold=2)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    output.save(temporary_path, format="PNG", optimize=True)
    temporary_path.replace(output_path)
    return {
        "width": width,
        "height": height,
        "azimuth_min_deg": 0.0,
        "azimuth_max_deg": 360.0,
        "altitude_min_deg": altitude_bottom_deg,
        "altitude_max_deg": altitude_top_deg,
        "camera_height_agl_m": camera_agl_m,
        "ground_elevation_amsl_m": round(ground_elevation_m, 3),
        "observer_elevation_amsl_m": round(observer_elevation_m, 3),
        "terrain_pixel_fraction": round(hit_count / (width * source_height), 6),
        "coordinate_frame": "mount",
        "azimuth_north_offset_deg": round(float(azimuth_north_offset_deg), 6),
        "pointing_model_applied": bool(
            isinstance(pointing_model, dict) and pointing_model.get("active") is True
        ),
        "pointing_model_mode": (
            str(pointing_model.get("mode") or "rigid_rotation")
            if isinstance(pointing_model, dict) and pointing_model.get("active") is True
            else "inactive"
        ),
    }
