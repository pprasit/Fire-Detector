"""Burn camera telemetry into frames before display or upload."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")


def format_elapsed(seconds: float) -> str:
    tenths = max(0, round(seconds * 10))
    hours, remainder = divmod(tenths, 36_000)
    minutes, remainder = divmod(remainder, 600)
    whole_seconds, decimal = divmod(remainder, 10)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{decimal}"


def burn_camera_overlay(
    frame: Image.Image,
    *,
    captured_at: datetime,
    elapsed_sec: float,
    zoom_x: float,
) -> Image.Image:
    """Return an RGB frame with a legible, top-left telemetry overlay."""
    rendered = frame.convert("RGB")
    draw = ImageDraw.Draw(rendered, "RGBA")
    width, height = rendered.size
    font_size = max(10, min(17, round(width / 76)))
    font = ImageFont.truetype(str(FONT_PATH), font_size) if FONT_PATH.is_file() else ImageFont.load_default()
    captured_utc = captured_at.astimezone(timezone.utc)
    lines = (
        f"ELAPSED {format_elapsed(elapsed_sec)}",
        f"UTC {captured_utc:%Y-%m-%d %H:%M:%S.%f}"[:-3],
        f"ZOOM {zoom_x:.2f}x",
        f"RES {width}x{height}",
    )
    padding = max(5, round(font_size * 0.45))
    spacing = max(2, round(font_size * 0.18))
    boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=1) for line in lines]
    text_width = max(box[2] - box[0] for box in boxes)
    line_height = max(box[3] - box[1] for box in boxes)
    box_width = min(width, text_width + padding * 2)
    box_height = min(height, line_height * len(lines) + spacing * (len(lines) - 1) + padding * 2)
    draw.rounded_rectangle((6, 6, 6 + box_width, 6 + box_height), radius=4, fill=(0, 0, 0, 92))
    y = 6 + padding
    for line in lines:
        draw.text(
            (6 + padding, y), line, font=font, fill=(255, 255, 255, 255),
            stroke_width=1, stroke_fill=(0, 0, 0, 255),
        )
        y += line_height + spacing
    return rendered
