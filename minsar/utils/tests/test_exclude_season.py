import datetime
import unittest

from minsar.utils.exclude_season import (
    date_in_exclude_season,
    iso_date_to_date,
    parse_exclude_season,
)


class TestExcludeSeason(unittest.TestCase):
    def test_parse_valid_token(self):
        self.assertEqual(parse_exclude_season("1005-0320"), ("1005", "0320"))

    def test_parse_invalid_token_format(self):
        with self.assertRaises(ValueError):
            parse_exclude_season("10-03")

    def test_parse_invalid_token_day(self):
        with self.assertRaises(ValueError):
            parse_exclude_season("1131-0320")

    def test_non_wrapping_window(self):
        start, end = parse_exclude_season("0401-1031")
        self.assertTrue(date_in_exclude_season(datetime.date(2024, 4, 1), start, end))
        self.assertTrue(date_in_exclude_season(datetime.date(2024, 10, 31), start, end))
        self.assertFalse(date_in_exclude_season(datetime.date(2024, 3, 31), start, end))
        self.assertFalse(date_in_exclude_season(datetime.date(2024, 11, 1), start, end))

    def test_wrapping_window(self):
        start, end = parse_exclude_season("1005-0320")
        self.assertTrue(date_in_exclude_season(datetime.date(2024, 10, 5), start, end))
        self.assertTrue(date_in_exclude_season(datetime.date(2025, 1, 10), start, end))
        self.assertTrue(date_in_exclude_season(datetime.date(2025, 3, 20), start, end))
        self.assertFalse(date_in_exclude_season(datetime.date(2025, 3, 21), start, end))
        self.assertFalse(date_in_exclude_season(datetime.date(2024, 10, 4), start, end))

    def test_iso_date_to_date(self):
        self.assertEqual(iso_date_to_date("2026-04-10"), datetime.date(2026, 4, 10))


if __name__ == "__main__":
    unittest.main()

