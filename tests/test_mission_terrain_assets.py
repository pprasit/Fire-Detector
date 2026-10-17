from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
from PIL import Image, TiffImagePlugin

from fire_detector.mission_terrain_assets import build_terrain_assets


class MissionTerrainAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dem = self.root / 'dem.tif'
        self.model = {'cache_key':'a'*20,'grid_resolution_m':30,'radius_km':.15,
                      'station':{'latitude':0,'longitude':0},
                      'raster':{'width_m':300,'depth_m':300}}

    def write_dem(self, values):
        tags = TiffImagePlugin.ImageFileDirectory_v2()
        tags.tagtype[33550] = 12
        tags.tagtype[33922] = 12
        tags[33550] = (30/111320,30/111320,0)
        tags[33922] = (0,0,0,-150/111320,150/111320,0)
        Image.fromarray(values.astype(np.float32)).save(self.dem,tiffinfo=tags)

    def test_preserves_submetre_heights_at_native_grid_spacing(self):
        row,col = np.mgrid[:11,:11]
        heights = 100 + row*.24 + col*.13
        self.write_dem(heights)
        manifest = build_terrain_assets(self.dem,self.model,self.root)
        self.assertEqual(manifest['width'],11)
        self.assertEqual(manifest['grid_spacing_m'],30)
        self.assertLess(manifest['elevation_quantization_m'],.001)
        with Image.open(self.root / Path(manifest['src']).name) as image:
            pixels = np.array(image)
        for r,c in [(5,5),(3,5),(5,7)]:
            encoded = int(pixels[r,c,0])*256+int(pixels[r,c,1])
            actual = manifest['elevation_min_m'] + encoded/65535*(manifest['elevation_max_m']-manifest['elevation_min_m'])
            self.assertAlmostEqual(actual,float(heights[r,c]),delta=.001)
            self.assertEqual(pixels[r,c,3],255)
        self.assertEqual(pixels[0,0,3],0)
        self.assertEqual(manifest,build_terrain_assets(self.dem,self.model,self.root))

    def test_rejects_footprint_with_no_valid_elevation(self):
        self.write_dem(np.full((11,11),-32768))
        with self.assertRaisesRegex(ValueError,'valid DEM'):
            build_terrain_assets(self.dem,self.model,self.root)
        self.assertFalse(list(self.root.glob('*height_hq*')))

    def test_manifest_is_published_with_matching_image(self):
        self.write_dem(np.arange(121).reshape(11,11)+100)
        manifest = build_terrain_assets(self.dem,self.model,self.root)
        saved = json.loads(next(self.root.glob('*height_hq_v1.json')).read_text())
        self.assertEqual(manifest,saved)
        self.assertTrue((self.root / Path(saved['src']).name).is_file())
        self.assertFalse(list(self.root.glob('*.tmp')))
