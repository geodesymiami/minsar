"""Tests of sarvey2insarmaps.py's step 1, write_insarmaps_points: the points and metadata.pickle it writes from the CSV
the script makes (HDF-EOS5 column names, metres, positions corrected for the DEM error), checked against what step 1
(insarmaps_ingester.py) writes for the same points from the CSV format it reads (SARvey's names, mm). Needs the minsar
environment and insarmaps_ingester.py on PATH ($MINSAR_HOME/tools/insarmaps_scripts); skipped without them."""

import os
import pickle
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

NAME = "TSX_desc_036_sarvey_20200101_20200206_N2595W08012_N2594W08012_N2594W08012_N2595W08012"
DATES = ["20200101", "20200113", "20200125", "20200206"]
# extract_metadata_from_inputs' attributes for a TSX descending stack that names no beam mode
STACK = {"PLATFORM": "TSX", "ORBIT_DIRECTION": "DESCENDING", "relative_orbit": 36, "orbit_direction": "D",
         "look_direction": "R", "data_type": "LOS_TIMESERIES"}
POINT_FILES = ("points.json", "p.npy", "lon.npy", "lat.npy", "m.npy", "d.npy", "attr_dem_error.npy",
               "attr_elevation.npy", "attr_coherence.npy", "attr_omega.npy", "attr_st_consist.npy",
               "attr_point_ID.npy")


def setUpModule():
    global pd, s2i
    os.environ.setdefault("MINSAR_HOME", str(Path(HERE).parents[2]))
    try:
        import pandas as pd
        import sarvey2insarmaps as s2i
    except ImportError as e:
        if (e.name or "").split(".")[0] not in {"h5py", "mintpy", "pandas", "minsar"}:
            raise
        raise unittest.SkipTest(f"needs the minsar environment ({e})")
    if shutil.which("insarmaps_ingester.py") is None:
        raise unittest.SkipTest("needs insarmaps_ingester.py on PATH ($MINSAR_HOME/tools/insarmaps_scripts)")


def shapefile_csv(path):
    """What ogr2ogr writes from a SARvey shapefile: X/Y and SARvey's fields, the displacement and st_consist in mm.
    Row 4 misses a date; row 5 has a value at one date only, so it is no point."""
    rng = np.random.default_rng(7)
    n = 6
    df = pd.DataFrame({
        "X": -80.12 + rng.uniform(0, 0.005, n), "Y": 25.944 + rng.uniform(0, 0.007, n),
        "point_id": np.arange(100, 100 + n), "velocity": rng.normal(0, 5, n), "coherence": rng.uniform(0.3, 0.95, n),
        "omega": rng.uniform(20, 3000, n), "st_consist": rng.uniform(0.5, 18, n), "dem": rng.uniform(-28, -17, n),
        "dem_error": rng.normal(-30, 50, n),
    })
    for i, day in enumerate(DATES):
        df["D" + day] = rng.normal(0, 20, n) + 3 * i
    df.loc[4, "D20200125"] = np.nan
    df.loc[5, ["D20200113", "D20200125", "D20200206"]] = np.nan
    df.to_csv(path, index=False)
    return pd.read_csv(path)


def make_stack(inputs):
    """slcStack.h5 and geometryRadar.h5 with the attributes extract_metadata_from_inputs reads (STACK's)."""
    import h5py

    inputs.mkdir(parents=True, exist_ok=True)
    with h5py.File(inputs / "slcStack.h5", "w") as f:
        f.create_dataset("slc", data=np.zeros((2, 4, 5), dtype=np.complex64))
        f.attrs.update({"FILE_TYPE": "timeseries", "LENGTH": "4", "WIDTH": "5", "PLATFORM": "TSX",
                        "ORBIT_DIRECTION": "DESCENDING", "relative_orbit": "36"})
    with h5py.File(inputs / "geometryRadar.h5", "w") as f:
        for name in ("incidenceAngle", "azimuthAngle", "height"):
            f.create_dataset(name, data=np.full((4, 5), 30.0, dtype=np.float32))
        f.attrs.update({"FILE_TYPE": "geometry", "LENGTH": "4", "WIDTH": "5"})


class WritePoints(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        cwd = os.getcwd()
        os.chdir(self.tmp)                              # the CSV steps write ./ingest_commands.log
        self.addCleanup(os.chdir, cwd)
        self.mm = shapefile_csv(self.tmp / "shapefile.csv")
        # the script's CSV, made by its own steps (main): HDF-EOS5 names, metres, then the corrected positions
        self.csv = self.tmp / "new" / f"{NAME}.csv"
        self.csv.parent.mkdir()
        shutil.copy(self.tmp / "shapefile.csv", self.csv)
        import correct_geolocation
        with unittest.mock.patch("sys.stdout"):
            s2i.rename_csv_columns_for_hdfeos5(self.csv)
            s2i.convert_displacement_mm_to_m(self.csv)
            correct_geolocation.correct_geolocation_csv(str(self.csv), str(self.csv))
        self.final = pd.read_csv(self.csv, float_precision="round_trip")

    def write(self, json_dir, stack=STACK):
        with unittest.mock.patch("sys.stdout"):
            return s2i.write_insarmaps_points(self.csv, json_dir, self.tmp / "inputs", stack=stack)

    def step1_on_the_shapefile_csv(self):
        """What step 1 writes for the same points from the CSV it reads: SARvey's names and mm, and the corrected
        positions as X_geocorr/Y_geocorr, the names it takes first."""
        old = self.mm.copy()
        old["X_geocorr"] = self.final["longitude_corrected"]
        old["Y_geocorr"] = self.final["latitude_corrected"]
        path = self.tmp / "old" / f"{NAME}.csv"
        path.parent.mkdir()
        old.to_csv(path, index=False)
        subprocess.run(["insarmaps_ingester.py", str(path), str(path.parent / "JSON")], check=True,
                       capture_output=True)
        return path.parent / "JSON"

    def test_the_points_are_step1s_for_the_same_points(self):
        old_dir = self.step1_on_the_shapefile_csv()
        self.assertEqual(self.write(self.tmp / "new" / "JSON"), 5)
        points_bundle = s2i.load_insarmaps_ingester().points_bundle
        old = points_bundle.read_points(str(old_dir), mmap=False)
        new = points_bundle.read_points(str(self.tmp / "new" / "JSON"), mmap=False)
        self.assertEqual(new[0], old[0])                # points, dates, attributes and their column types
        np.testing.assert_array_equal(new[1], old[1], err_msg="p")
        # the CSV's values exactly: the displacement in metres, the corrected positions
        np.testing.assert_array_equal(new[5], self.final[["D" + day for day in DATES]].to_numpy(float)[:5])
        np.testing.assert_array_equal(new[2], self.final["longitude_corrected"][:5])
        np.testing.assert_array_equal(new[3], self.final["latitude_corrected"][:5])
        self.assertFalse(np.any(new[3] == self.final["latitude"][:5]))
        # step 1's values for the same points. Not to the bit: the script's CSV steps (rename, mm to m, geolocation)
        # each read the CSV back with pandas' default parser, which moves most values in their last digit or two
        for k, name in ((2, "lon"), (3, "lat"), (4, "m"), (5, "d")):
            np.testing.assert_allclose(new[k], old[k], rtol=1e-12, atol=0, err_msg=name)
        self.assertEqual(list(new[6]), ["dem_error", "elevation", "coherence", "omega", "st_consist", "point_ID"])
        for name in new[6]:
            np.testing.assert_allclose(new[6][name], old[6][name], rtol=1e-12, atol=0, err_msg=name)
        np.testing.assert_array_equal(new[6]["point_ID"], old[6]["point_ID"])
        # in the units the map shows: d in m, st_consist in mm
        np.testing.assert_allclose(new[5][0], self.mm.loc[0, ["D" + day for day in DATES]].to_numpy(float) / 1000,
                                   rtol=1e-12)
        np.testing.assert_allclose(new[6]["st_consist"], self.mm["st_consist"][:5], rtol=1e-12)

    def test_the_area_is_step1s_with_the_stacks_mission_orbit_direction_and_beam_mode(self):
        old_dir = self.step1_on_the_shapefile_csv()
        self.write(self.tmp / "new" / "JSON")
        old = pickle.loads((old_dir / "metadata.pickle").read_bytes())
        new = pickle.loads((self.tmp / "new" / "JSON" / "metadata.pickle").read_bytes())
        for key in ("area", "project_name", "mid_long", "mid_lat", "country", "region", "chunk_num",
                    "string_dates_sql", "decimal_dates_sql", "needed_attributes"):
            self.assertEqual(new[key], old[key], key)
        self.assertEqual(new["area"], NAME)
        # step 1 guesses S1 and IW, and no orbit or direction, from a name like TSX_desc_036_...
        stack = {"mission": "TSX", "beam_mode": "SM", "relative_orbit": 36, "flight_direction": "D"}
        self.assertEqual(dict(zip(new["attribute_keys"], new["attribute_values"])),
                         {**dict(zip(old["attribute_keys"], old["attribute_values"])), **stack})
        needed = new["needed_attributes"]               # the ones step 2 puts into extra_attributes
        self.assertEqual({k: v for k, v in new["attributes"].items() if k in needed},
                         {**{k: v for k, v in old["attributes"].items() if k in needed}, **stack})

    def test_the_stacks_own_values(self):
        self.write(self.tmp / "JSON", stack={"PLATFORM": "SENTINEL-1", "flight_direction": "ASCENDING",
                                             "relative_orbit": "128", "beam_mode": "IW", "look_direction": "R"})
        a = pickle.loads((self.tmp / "JSON" / "metadata.pickle").read_bytes())["attributes"]
        self.assertEqual((a["mission"], a["flight_direction"], a["relative_orbit"], a["beam_mode"]),
                         ("S1", "A", 128, "IW"))
        self.write(self.tmp / "JSON", stack={})
        a = pickle.loads((self.tmp / "JSON" / "metadata.pickle").read_bytes())["attributes"]
        self.assertEqual((a["mission"], a["beam_mode"]), ("S1", "IW"))
        self.assertNotIn("flight_direction", a)
        self.assertNotIn("relative_orbit", a)

    def test_the_logged_and_jobfile_commands_write_the_same_files(self):
        inputs = self.tmp / "inputs"
        make_stack(inputs)
        with unittest.mock.patch("sys.stdout"):
            s2i.write_insarmaps_points(self.csv, self.tmp / "new" / "JSON", inputs)
        shown = s2i.write_points_command(self.csv, self.tmp / "shown" / "JSON", inputs, cwd=str(self.tmp))
        self.assertEqual(shlex.split(shown)[:2], ["python3", "-c"])
        self.assertIn("write_insarmaps_points('new/" + NAME + ".csv', 'shown/JSON', 'inputs')", shlex.split(shown)[2])
        jobfile = s2i.write_points_command(self.csv, self.tmp / "job" / "JSON", inputs)
        self.assertIn(f"write_insarmaps_points({str(self.csv.resolve())!r}, ", shlex.split(jobfile)[2])
        subprocess.run(["bash", "-c", shown], check=True, capture_output=True, cwd=self.tmp)
        subprocess.run(["bash", "-c", jobfile], check=True, capture_output=True, cwd="/")
        for folder in ("shown", "job"):
            for name in POINT_FILES:
                self.assertEqual((self.tmp / folder / "JSON" / name).read_bytes(),
                                 (self.tmp / "new" / "JSON" / name).read_bytes(), f"{folder}/JSON/{name}")
            self.assertEqual(pickle.loads((self.tmp / folder / "JSON" / "metadata.pickle").read_bytes()),
                             pickle.loads((self.tmp / "new" / "JSON" / "metadata.pickle").read_bytes()))

    def test_it_needs_the_corrected_positions(self):
        self.final.drop(columns=["latitude_corrected"]).to_csv(self.csv, index=False)
        with self.assertRaisesRegex(ValueError, "latitude_corrected"):
            self.write(self.tmp / "JSON")


class LoadIngester(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, s2i, "_insarmaps_ingester", s2i._insarmaps_ingester)
        s2i._insarmaps_ingester = None

    def test_not_on_path(self):
        with unittest.mock.patch.object(s2i.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "insarmaps_ingester.py not found on PATH"):
                s2i.load_insarmaps_ingester()

    def test_a_script_without_the_writers(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        script = tmp / "insarmaps_ingester.py"
        script.write_text("def get_date(text):\n    return text\n")
        with unittest.mock.patch.object(s2i.shutil, "which", return_value=str(script)):
            with self.assertRaisesRegex(RuntimeError, "write_csv_points.*git pull in both"):
                s2i.load_insarmaps_ingester()
        self.assertNotIn(str(tmp), sys.path)
        self.assertIsNone(s2i._insarmaps_ingester)


if __name__ == "__main__":
    unittest.main()
