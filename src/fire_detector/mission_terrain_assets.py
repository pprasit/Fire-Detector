"""Build full-resolution, 16-bit elevation textures without changing the DEM."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image


def build_terrain_assets(dem_path: Path, model: dict, cache_dir: Path) -> dict:
    digest = str(model['cache_key'])
    if not digest or any(char not in '0123456789abcdef' for char in digest):
        raise ValueError('Invalid terrain cache key')
    stem = f'pointing_{digest}_height_hq_v1'
    manifest_path = cache_dir / f'{stem}.json'
    image_path = cache_dir / f'{stem}.png'
    if manifest_path.is_file() and image_path.is_file():
        return json.loads(manifest_path.read_text())
    station = model['station']
    width_m = float(model['raster']['width_m'])
    depth_m = float(model['raster']['depth_m'])
    spacing = max(20.0, float(model['grid_resolution_m']))
    width = min(2049, int(math.ceil(width_m / spacing)) + 1)
    height = min(2049, int(math.ceil(depth_m / spacing)) + 1)
    east, north = np.meshgrid(np.linspace(-width_m / 2, width_m / 2, width),
                              np.linspace(depth_m / 2, -depth_m / 2, height))
    lat = float(station['latitude']) + north / 111_320.0
    lon = float(station['longitude']) + east / (111_320.0 * math.cos(math.radians(float(station['latitude']))))
    with Image.open(dem_path) as source:
        scale = source.tag_v2[33550]
        tie = source.tag_v2[33922]
        west = float(tie[3]) - float(tie[0]) * float(scale[0])
        top = float(tie[4]) + float(tie[1]) * float(scale[1])
        raw = np.asarray(source, dtype=np.float32)
        cols = (lon - west) / float(scale[0])
        rows = (top - lat) / float(scale[1])
        valid = ((cols >= 0) & (cols <= raw.shape[1]-1) &
                 (rows >= 0) & (rows <= raw.shape[0]-1) &
                 (np.hypot(east,north) <= float(model['radius_km'])*1000))
        x = np.clip(cols,0,raw.shape[1]-1)
        y = np.clip(rows,0,raw.shape[0]-1)
        x0,y0 = np.floor(x).astype(int),np.floor(y).astype(int)
        x1,y1 = np.minimum(x0+1,raw.shape[1]-1),np.minimum(y0+1,raw.shape[0]-1)
        samples = [raw[y0,x0],raw[y0,x1],raw[y1,x0],raw[y1,x1]]
        for sample in samples:
            valid &= np.isfinite(sample) & (sample > -10000) & (sample < 10000)
        elevation = (samples[0]*(1-(x-x0)) + samples[1]*(x-x0))*(1-(y-y0)) + (samples[2]*(1-(x-x0)) + samples[3]*(x-x0))*(y-y0)
    if not valid.any():
        raise ValueError('Station footprint does not overlap valid DEM data')
    minimum,maximum = float(np.min(elevation[valid])),float(np.max(elevation[valid]))
    span = max(.001,maximum-minimum)
    encoded = np.rint(np.clip((np.where(valid,elevation,minimum)-minimum)/span,0,1)*65535).astype(np.uint16)
    rgba = np.zeros((height,width,4),dtype=np.uint8)
    rgba[:,:,0] = encoded >> 8
    rgba[:,:,1] = encoded & 255
    rgba[:,:,3] = valid*255
    manifest = {'version':1,'encoding':'rg16','width':width,'height':height,
        'elevation_min_m':minimum,'elevation_max_m':maximum,
        'elevation_quantization_m':span/65535,'grid_spacing_m':width_m/(width-1),
        'src':f'/api/pointing/cache/{image_path.name}'}
    cache_dir.mkdir(parents=True,exist_ok=True)
    def publish(path: Path, writer):
        handle,name = tempfile.mkstemp(prefix=f'.{path.name}.',suffix='.tmp',dir=cache_dir)
        try:
            with os.fdopen(handle,'wb') as stream:
                writer(stream)
            os.replace(name,path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    publish(image_path,lambda stream:Image.fromarray(rgba).save(stream,format='PNG'))
    publish(manifest_path,lambda stream:stream.write(json.dumps(manifest,indent=2).encode()))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dem',type=Path,required=True)
    parser.add_argument('--metadata',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(build_terrain_assets(args.dem,json.loads(args.metadata.read_text()),args.metadata.parent),indent=2))
