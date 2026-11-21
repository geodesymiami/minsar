"""Tests of insarmaps_step2.py, step 2 of an Insarmaps ingest: no network (rsync, ssh, sudo and the upload are
captured, not run)."""

import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import insarmaps_step2 as step2  # noqa: E402


class Step2(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.scratch, True)
        self.data = Path(self.scratch) / "Proj" / "mintpy"
        (self.data / "JSON").mkdir(parents=True)
        (self.data / "JSON" / "chunk_0.json").write_text("{}")
        env = unittest.mock.patch.dict(os.environ, {"SCRATCHDIR": self.scratch, "REMOTEUSER": "exouser",
                                                    "MBTILES_NUM_WORKERS": "6"})
        env.start()
        self.addCleanup(env.stop)
        for key in ("INSARMAPS_RSH", "INSARMAPS_SSH_JUMP", "INSARMAPS_REMOTE_MINSAR_HOME"):
            os.environ.pop(key, None)
        cwd = os.getcwd()
        work = tempfile.mkdtemp()                       # the step writes ./log and ./ingest_commands.log
        self.addCleanup(shutil.rmtree, work, True)
        os.chdir(work)
        self.addCleanup(os.chdir, cwd)
        self.ran = []
        for name, kw in (("run_command", {"side_effect": lambda cmd, cwd=None: self.ran.append(list(cmd))}),
                         ("subprocess.check_output", {"return_value": "secret\n"}),
                         ("subprocess.run", {"return_value": unittest.mock.Mock(returncode=0)})):
            p = unittest.mock.patch.object(step2.subprocess if "." in name else step2, name.split(".")[-1], **kw)
            p.start()
            self.addCleanup(p.stop)

    def remote_command(self):
        return step2.subprocess.run.call_args.args[0][-1]

    def test_no_mbtiles_is_sent_or_installed(self):
        step2.ingest_step2_rsync_and_remote_ingest("149.165.153.50", self.data / "JSON", data_dir=self.data)
        rsync = [c for c in self.ran if c[0] == "rsync"][0]
        self.assertIn("--exclude=*.mbtiles", rsync)
        self.assertIn("--delete", rsync)            # no chunk left over from an earlier attempt
        self.assertEqual(rsync[-1], "exouser@149.165.153.50:/data/scratch/Proj/mintpy/JSON/")
        remote = self.remote_command()
        self.assertIn("json_mbtiles2insarmaps.py --num-workers 6 -u insaradmin -p secret --host 127.0.0.1 "
                      "--json_folder /data/scratch/Proj/mintpy/JSON", remote)
        self.assertNotIn("mbtiles_dir", remote)
        self.assertNotIn("sudo", remote)
        self.assertEqual(self.ran[-1][-1], "rm -rf /data/scratch/Proj")

    def test_jobfiles_written_before_still_work(self):
        # they call (host, json_dir, mbtiles, data_dir) positionally; the .mbtiles is ignored
        step2.ingest_step2_rsync_and_remote_ingest("h", str(self.data / "JSON"), str(self.data / "JSON" / "X.mbtiles"),
                                                   str(self.data))
        self.assertIn("--json_folder /data/scratch/Proj/mintpy/JSON", self.remote_command())

    def test_data_dir_is_required(self):
        with self.assertRaises(ValueError):
            step2.ingest_step2_rsync_and_remote_ingest("h", self.data / "JSON")

    def test_a_data_dir_outside_scratchdir_is_refused(self):
        with self.assertRaises(RuntimeError):
            step2.ingest_remote_paths_for_scratch(tempfile.gettempdir())

    def test_remote_paths(self):
        self.assertEqual(step2.ingest_remote_paths_for_scratch(self.data),
                         ("/data/scratch/Proj/mintpy", "/data/scratch/Proj"))


class OnTheInsarmapsHost(unittest.TestCase):
    """Step 2 on the Insarmaps host itself: json_mbtiles2insarmaps.py on JSON/ where it is, no rsync or ssh."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.json = self.tmp / "Proj" / "mintpy" / "JSON"
        self.json.mkdir(parents=True)
        (self.json / "chunk_0.json").write_text("{}")
        env = unittest.mock.patch.dict(os.environ, {"INSARMAPS_LOCAL_HOSTS": "149.165.153.50, Insarmaps2.Example",
                                                    "MBTILES_NUM_WORKERS": "6"})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("SCRATCHDIR", None)              # not needed on the host itself
        cwd = os.getcwd()
        os.chdir(self.tmp)                              # the step writes ./log and ./ingest_commands.log
        self.addCleanup(os.chdir, cwd)
        self.mocks = {}
        for name, kw in (("run_command", {}),
                         ("subprocess.check_output", {"return_value": "secret\n"}),
                         ("subprocess.run", {"return_value": unittest.mock.Mock(returncode=0)})):
            p = unittest.mock.patch.object(step2.subprocess if "." in name else step2, name.split(".")[-1], **kw)
            self.mocks[name] = p.start()
            self.addCleanup(p.stop)

    def test_which_hosts_are_this_machine(self):
        local = step2.insarmaps_host_is_local
        for host in ("149.165.153.50", " insarmaps2.example ", "localhost", "127.0.0.1", socket.gethostname()):
            self.assertTrue(local(host), host)
        for host in ("149.165.153.51", "insarmaps.miami.edu", "", None):
            self.assertFalse(local(host), host)
        with unittest.mock.patch.dict(os.environ, {"INSARMAPS_LOCAL_HOSTS": ""}):
            self.assertFalse(local("149.165.153.50"))

    def test_uploads_where_it_is(self):
        step2.ingest_step2_rsync_and_remote_ingest("149.165.153.50", self.json)    # no data_dir, no $SCRATCHDIR
        self.mocks["run_command"].assert_not_called()                             # no mkdir, rsync or rm over ssh
        self.assertEqual(self.mocks["subprocess.check_output"].call_args.args[0],
                         ["sudo", "-n", "cat", "/data/insarmaps2/postgres_dir/.insaradmin_db_password"])
        self.assertEqual(self.mocks["subprocess.run"].call_args.args[0],
                         ["json_mbtiles2insarmaps.py", "--num-workers", "6", "-u", "insaradmin", "-p", "secret",
                          "--host", "127.0.0.1", "--json_folder", str(self.json.resolve())])
        for log in ("log", "ingest_commands.log"):
            text = (self.tmp / log).read_text()
            self.assertIn("-p *** --host 127.0.0.1", text)
            self.assertNotIn("secret", text)

    def test_a_failed_upload_exits(self):
        self.mocks["subprocess.run"].return_value = unittest.mock.Mock(returncode=1)
        with self.assertRaises(SystemExit) as e, unittest.mock.patch("sys.stdout"):
            step2.ingest_step2_rsync_and_remote_ingest("localhost", self.json)
        self.assertEqual(e.exception.code, 1)

    def test_no_password_no_upload(self):
        self.mocks["subprocess.check_output"].side_effect = subprocess.CalledProcessError(1, "sudo")
        with self.assertRaises(RuntimeError), unittest.mock.patch("sys.stdout"):
            step2.ingest_step2_rsync_and_remote_ingest("localhost", self.json)
        self.mocks["subprocess.run"].assert_not_called()


class SarveyJobfile(unittest.TestCase):
    def test_the_jobfile_line_passes_no_mbtiles(self):
        os.environ.setdefault("MINSAR_HOME", str(Path(HERE).parents[2]))
        try:
            import sarvey2insarmaps
        except ImportError as e:
            if (e.name or "").split(".")[0] not in {"h5py", "mintpy", "pandas", "minsar"}:
                raise
            self.skipTest(f"needs the minsar environment ({e})")
        line = sarvey2insarmaps.remote_ingest_job_command("h", "/s/Proj/out/JSON", "/s/Proj/out")
        python, flag, code = shlex.split(line)
        self.assertEqual((python, flag), ("python3", "-c"))
        self.assertIn("mod.ingest_step2_rsync_and_remote_ingest('h', '/s/Proj/out/JSON', data_dir='/s/Proj/out')", code)
        self.assertNotIn("mbtiles", code)


class Uploaders(unittest.TestCase):
    """egms2insarmaps.py and concatenate_csv2insarmaps.py upload through the shared step 2 (no remote --host)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        cwd = os.getcwd()
        os.chdir(self.tmp)                              # they write ./log and insarmaps.log
        self.addCleanup(os.chdir, cwd)

    def test_egms_step2(self):
        import egms2insarmaps
        csv = self.tmp / "Proj" / "egms" / "EGMS_L2a_088_0286_IW2_VV_2019_2023_1.csv"
        (csv.parent / "JSON").mkdir(parents=True)
        (csv.parent / "JSON" / "metadata.pickle").write_bytes(b"")
        csv.write_text("latitude,longitude\n45.0,7.0\n")
        with unittest.mock.patch.dict(os.environ, {"SCRATCHDIR": str(self.tmp)}), \
                unittest.mock.patch.object(egms2insarmaps, "ingest_step2_rsync_and_remote_ingest") as step:
            egms2insarmaps.main([str(csv), "--step", "2", "--insarmaps-host", "h1,h2"])
        self.assertEqual([(c.args, c.kwargs) for c in step.call_args_list],
                         [(("h1", csv.parent / "JSON"), {"data_dir": csv.parent}),
                          (("h2", csv.parent / "JSON"), {"data_dir": csv.parent})])

    def test_egms_checks_the_upload_before_converting(self):
        import egms2insarmaps
        csv = self.tmp / "elsewhere" / "EGMS_L2a_088_0286_IW2_VV_2019_2023_1.csv"
        csv.parent.mkdir()
        csv.write_text("latitude,longitude\n45.0,7.0\n")
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, True)
        with unittest.mock.patch.dict(os.environ, {"SCRATCHDIR": other}), \
                unittest.mock.patch.object(egms2insarmaps, "run_command") as run, \
                unittest.mock.patch.object(egms2insarmaps, "ingest_step2_rsync_and_remote_ingest") as step, \
                unittest.mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                egms2insarmaps.main([str(csv), "--insarmaps-host", "h1"])
        run.assert_not_called()                     # the conversion never started
        step.assert_not_called()

    def test_concatenate_checks(self):
        import concatenate_csv2insarmaps as concat
        out = self.tmp / "Proj" / "outputs"
        out.mkdir(parents=True)
        with unittest.mock.patch.dict(os.environ, {"SCRATCHDIR": str(self.tmp)}):
            concat.check_upload("h1", out)
            with self.assertRaises(RuntimeError):
                concat.check_upload("", out)                       # no host
            with self.assertRaises(RuntimeError):
                concat.check_upload("h1", tempfile.gettempdir())   # not under $SCRATCHDIR

    def test_on_the_insarmaps_host_scratchdir_is_not_needed(self):
        import concatenate_csv2insarmaps as concat
        import egms2insarmaps
        csv = self.tmp / "anywhere" / "EGMS_L2a_088_0286_IW2_VV_2019_2023_1.csv"
        (csv.parent / "JSON").mkdir(parents=True)
        (csv.parent / "JSON" / "metadata.pickle").write_bytes(b"")
        csv.write_text("latitude,longitude\n45.0,7.0\n")
        with unittest.mock.patch.dict(os.environ, {"INSARMAPS_LOCAL_HOSTS": "149.165.153.50", "SCRATCHDIR": ""}):
            concat.check_upload("149.165.153.50", csv.parent)
            with self.assertRaises(RuntimeError):
                concat.check_upload("149.165.153.50,h2", csv.parent)    # h2 is another machine: needs $SCRATCHDIR
            with unittest.mock.patch.object(egms2insarmaps, "ingest_step2_rsync_and_remote_ingest") as step:
                egms2insarmaps.main([str(csv), "--step", "2", "--insarmaps-host", "149.165.153.50"])
            self.assertEqual(step.call_args.args, ("149.165.153.50", csv.parent / "JSON"))

    def test_concatenate_upload(self):
        import concatenate_csv2insarmaps as concat
        out = self.tmp / "Proj" / "outputs"
        out.mkdir(parents=True)
        csv = out / "S1_044_x.csv"
        csv.write_text("X,Y\n7.0,45.0\n")
        with unittest.mock.patch.object(concat, "run_command") as run, \
                unittest.mock.patch.object(concat, "ingest_step2_rsync_and_remote_ingest") as step:
            concat.ingest_to_insarmaps(csv, out, "h1,h2", skip_upload=False)
            self.assertEqual(run.call_args.args[0][0], "hdfeos5_or_csv_2json_mbtiles.py")
            self.assertEqual([(c.args, c.kwargs) for c in step.call_args_list],
                             [(("h1", out / "JSON"), {"data_dir": out}), (("h2", out / "JSON"), {"data_dir": out})])
            step.reset_mock()
            concat.ingest_to_insarmaps(csv, out, "", skip_upload=True)   # converting only needs no host
            step.assert_not_called()


if __name__ == "__main__":
    unittest.main()
