#!/usr/bin/env python3
"""Tests for create_data_download_commands.py."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from minsar.scripts import create_data_download_commands as cdd


class TestCreateDataDownloadCommands(unittest.TestCase):
    def test_path_section(self):
        self.assertEqual(cdd.path_section('SenD/net/S1_desc_169_filtDel4DS.he5'), cdd.SECTION_RADAR)
        self.assertEqual(cdd.path_section('SenA/net/geo_S1_asc_060_filtDel4DS.he5'), cdd.SECTION_GEOCODED)
        self.assertEqual(cdd.path_section('LaPalma/miaplpy/S1_vert_169.he5'), cdd.SECTION_GEOCODED)
        self.assertEqual(cdd.path_section('SenA/net/geo_S1_asc_060_filtDel4DS.gpkg'), cdd.SECTION_GPKG)

    def test_geocoded_section_header(self):
        meta = {'lat_step': '0.0008', 'lon_step': '0.00056'}
        self.assertEqual(
            cdd.geocoded_section_header(meta),
            '# geocoded (--lalo-step 0.0008 0.00056):',
        )
        self.assertEqual(cdd.geocoded_section_header({}), '# geocoded:')

    def test_parse_data_files_header(self):
        text = '# geocode-lalo-step 0.0008 0.00056\n/path/a.he5\n'
        meta, paths = cdd.parse_data_files(text)
        self.assertEqual(meta['lat_step'], '0.0008')
        self.assertEqual(meta['lon_step'], '0.00056')
        self.assertEqual(paths, ['/path/a.he5'])

    def test_writes_grouped_download_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_files = root / 'data_files.txt'
            data_files.write_text(
                '\n'.join([
                    '# geocode-lalo-step 0.0008 0.00056',
                    f'{root}/LaPalma/miaplpy/S1_vert_169.he5',
                    f'{root}/LaPalmaSenD169/net/S1_desc_169_filtDel4DS.he5',
                    f'{root}/LaPalmaSenA60/net/S1_asc_060_filtDel4DS.he5',
                    f'{root}/LaPalmaSenA60/net/geo_S1_asc_060_filtDel4DS.he5',
                    f'{root}/LaPalmaSenA60/net/geo_S1_asc_060_filtDel4DS.gpkg',
                ]) + '\n',
                encoding='utf-8',
            )
            os.environ['SCRATCHDIR'] = str(root)
            os.environ['REMOTEHOST_DATA'] = 'example.org'
            os.environ['REMOTE_DIR'] = '/data/HDF5EOS/'

            cdd.main([str(data_files)])

            out = (root / 'download_commands.txt').read_text(encoding='utf-8')
            self.assertTrue(out.startswith('# MinSAR data downloads.\n# radar-coded:\n'))
            self.assertIn('\n\n# geocoded (--lalo-step 0.0008 0.00056):\n', out)
            self.assertIn('\n\n# same as *.gpkg files:\n', out)
            radar_block = out.split('# geocoded')[0]
            self.assertEqual(radar_block.count('wget '), 2)
            self.assertNotIn('Ascending', out)
            self.assertNotIn('Descending', out)
            self.assertNotIn('GeoPackage', out)


if __name__ == '__main__':
    unittest.main()
