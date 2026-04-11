#!/usr/bin/env python3
"""Unit tests for get_sar_coverage.py --select orbit ranking (Sentinel-1)."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_GSC_PATH = _REPO_ROOT / "minsar" / "scripts" / "get_sar_coverage.py"


def _ensure_asf_search_stub() -> None:
    """Minimal asf_search stub so get_sar_coverage.py imports without ASF installed."""
    if 'asf_search' in sys.modules:
        return
    asf_mod = types.ModuleType('asf_search')
    const_mod = types.ModuleType('asf_search.constants')

    class _INTERNAL:
        CMR_TIMEOUT = 90

    const_mod.INTERNAL = _INTERNAL()
    sys.modules['asf_search'] = asf_mod
    sys.modules['asf_search.constants'] = const_mod


def _ensure_shapely_stub() -> None:
    """Minimal shapely stub so get_sar_coverage.py imports when shapely is not installed."""
    if 'shapely' in sys.modules:
        return
    wkt_mod = types.ModuleType('shapely.wkt')
    wkt_mod.loads = lambda wkt: None  # noqa: ARG005
    geom_mod = types.ModuleType('shapely.geometry')
    geom_mod.shape = lambda geom: None  # noqa: ARG005
    sys.modules['shapely'] = types.ModuleType('shapely')
    sys.modules['shapely.wkt'] = wkt_mod
    sys.modules['shapely.geometry'] = geom_mod


def _ensure_get_sar_coverage_import_deps() -> None:
    _ensure_asf_search_stub()
    _ensure_shapely_stub()


def _load_get_sar_coverage():
    _ensure_get_sar_coverage_import_deps()
    spec = importlib.util.spec_from_file_location("get_sar_coverage", _GSC_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gsc = _load_get_sar_coverage()


class TestS1SelectSort(unittest.TestCase):
    """Sentinel-1 --select prefers full-AOI consistency, then margin, then incidence."""

    def test_prefers_higher_coverage_ratio_over_incidence(self):
        """High incidence but many dropped dates loses to lower incidence with full cover."""
        orbits = [
            {'orbit': 108, 'inc': 44.0, 'subswath': 'IW2', 'count': 94},
            {'orbit': 35, 'inc': 40.0, 'subswath': 'IW2', 'count': 375},
        ]
        metrics = {
            (108, 'Ascending'): {
                'n_acquisitions_removed': 182,
                'n_intersecting_dates': 276,
                'min_dist_m': 40.0,
            },
            (35, 'Ascending'): {
                'n_acquisitions_removed': 6,
                'n_intersecting_dates': 381,
                'min_dist_m': 1060.0,
            },
        }
        best = gsc._best_orbit_for_direction(orbits, 'Ascending', 'Sentinel-1', metrics)
        self.assertIsNotNone(best)
        self.assertEqual(best['orbit'], 35)
        self.assertEqual(best['label'], 'SenA35')

    def test_larger_margin_wins_before_incidence(self):
        """Same ratio and drops: larger AOI→footprint margin wins over higher incidence."""
        orbits = [
            {'orbit': 1, 'inc': 40.0, 'subswath': 'IW2', 'count': 100},
            {'orbit': 2, 'inc': 45.0, 'subswath': 'IW2', 'count': 100},
        ]
        metrics = {
            (1, 'Ascending'): {
                'n_acquisitions_removed': 0,
                'n_intersecting_dates': 100,
                'min_dist_m': 2000.0,
            },
            (2, 'Ascending'): {
                'n_acquisitions_removed': 0,
                'n_intersecting_dates': 100,
                'min_dist_m': 100.0,
            },
        }
        best = gsc._best_orbit_for_direction(orbits, 'Ascending', 'Sentinel-1', metrics)
        self.assertIsNotNone(best)
        self.assertEqual(best['orbit'], 1)

    def test_tie_breaker_incidence_when_coverage_equal(self):
        """Same ratio, drops, and margin: higher incidence wins."""
        orbits = [
            {'orbit': 10, 'inc': 41.0, 'subswath': 'IW2', 'count': 100},
            {'orbit': 20, 'inc': 43.0, 'subswath': 'IW2', 'count': 100},
        ]
        metrics = {
            (10, 'Descending'): {
                'n_acquisitions_removed': 0,
                'n_intersecting_dates': 100,
                'min_dist_m': 500.0,
            },
            (20, 'Descending'): {
                'n_acquisitions_removed': 0,
                'n_intersecting_dates': 100,
                'min_dist_m': 500.0,
            },
        }
        best = gsc._best_orbit_for_direction(orbits, 'Descending', 'Sentinel-1', metrics)
        self.assertIsNotNone(best)
        self.assertEqual(best['orbit'], 20)
        self.assertEqual(best['label'], 'SenD20')

    def test_fewer_drops_wins_same_ratio(self):
        """Same ratio (e.g. 50%) but fewer absolute drops wins."""
        orbits = [
            {'orbit': 1, 'inc': 40.0, 'subswath': 'IW2', 'count': 5},
            {'orbit': 2, 'inc': 40.0, 'subswath': 'IW2', 'count': 50},
        ]
        metrics = {
            (1, 'Ascending'): {
                'n_acquisitions_removed': 5,
                'n_intersecting_dates': 10,
                'min_dist_m': 400.0,
            },
            (2, 'Ascending'): {
                'n_acquisitions_removed': 50,
                'n_intersecting_dates': 100,
                'min_dist_m': 400.0,
            },
        }
        best = gsc._best_orbit_for_direction(orbits, 'Ascending', 'Sentinel-1', metrics)
        self.assertEqual(best['orbit'], 1)

    def test_nisar_unchanged_max_incidence(self):
        """Non-S1 platforms ignore s1_metrics and use max incidence."""
        orbits = [
            {'orbit': 100, 'inc': 30.0, 'subswath': '-', 'count': 10},
            {'orbit': 200, 'inc': 35.0, 'subswath': '-', 'count': 5},
        ]
        fake_metrics = {(100, 'Ascending'): {'n_acquisitions_removed': 999, 'n_intersecting_dates': 1000, 'min_dist_m': 0.0}}
        best = gsc._best_orbit_for_direction(orbits, 'Ascending', 'NISAR', fake_metrics)
        self.assertEqual(best['orbit'], 200)


if __name__ == '__main__':
    unittest.main()
