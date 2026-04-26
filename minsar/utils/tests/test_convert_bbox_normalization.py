import unittest

from minsar.utils.convert_bbox import _input_to_bounds


class TestConvertBboxNormalization(unittest.TestCase):
    def test_bbox_longitudes_below_minus_180_are_wrapped(self):
        min_lat, max_lat, min_lon, max_lon = _input_to_bounds(
            "54.535:54.656,-199.812:-199.601"
        )
        self.assertEqual(min_lat, 54.535)
        self.assertEqual(max_lat, 54.656)
        self.assertAlmostEqual(min_lon, 160.188, places=3)
        self.assertAlmostEqual(max_lon, 160.399, places=3)

    def test_polygon_longitudes_below_minus_180_are_wrapped(self):
        min_lat, max_lat, min_lon, max_lon = _input_to_bounds(
            "POLYGON((-199.812 54.535,-199.601 54.535,-199.601 54.656,-199.812 54.656,-199.812 54.535))"
        )
        self.assertEqual(min_lat, 54.535)
        self.assertEqual(max_lat, 54.656)
        self.assertAlmostEqual(min_lon, 160.188, places=3)
        self.assertAlmostEqual(max_lon, 160.399, places=3)


if __name__ == "__main__":
    unittest.main()

