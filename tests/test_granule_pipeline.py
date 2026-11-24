"""Tests for minsar.utils.granule_pipeline (restartable per-granule download + unpack)."""
import csv
import io
import os
import tempfile
import threading
import unittest
import zipfile

from minsar.utils import granule_pipeline as gp


def make_zip_bytes(n=200000):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        z.writestr('data.bin', os.urandom(n))
    return buf.getvalue()


class FakeProduct:
    def __init__(self, name, size):
        self.properties = {'fileName': name, 'url': f'https://host.example/{name}', 'bytes': size}


class FakeResponse:
    def __init__(self, status, body, url, stop_after=None, stop_event=None):
        self.status_code, self.body, self.url = status, body, url
        self.stop_after, self.stop_event = stop_after, stop_event

    def iter_content(self, chunk_size):
        chunk = 10000
        for i in range(0, len(self.body), chunk):
            if self.stop_after is not None and i >= self.stop_after:
                if self.stop_event is not None:
                    self.stop_event.set()
                else:
                    return                      # connection dropped
            yield self.body[i:i + chunk]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def close(self):
        pass


class FakeSession:
    """Serves `content`; honours Range unless ignore_range. Records the Range headers it saw."""
    def __init__(self, content, ignore_range=False, drop_after=None):
        self.content, self.ignore_range, self.drop_after = content, ignore_range, drop_after
        self.ranges = []

    def get(self, url, stream=True, headers=None, **kwargs):
        rng = (headers or {}).get('Range')
        self.ranges.append(rng)
        drop, self.drop_after = self.drop_after, None
        if rng and not self.ignore_range:
            start = int(rng.split('=')[1].rstrip('-'))
            if start >= len(self.content):
                return FakeResponse(416, b'', url)
            return FakeResponse(206, self.content[start:], 'https://cdn.example/x', stop_after=drop)
        return FakeResponse(200, self.content, 'https://cdn.example/x', stop_after=drop)


def write(path, data):
    with open(path, 'wb') as f:
        f.write(data)


def read(path):
    with open(path, 'rb') as f:
        return f.read()


class GranulePipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.content = make_zip_bytes()
        self.name = 'ALOS2000000000-150101-WBDR1.1__D.zip'
        self.product = FakeProduct(self.name, len(self.content))
        self.final = os.path.join(self.dir, self.name)
        self.archive = os.path.join(self.dir, gp.ARCHIVE_DIR, self.name)
        # stands in for uncompress_and_rename_data.py: moves the zip to ARCHIVED_FILES
        self.post = f'mkdir -p {self.dir}/{gp.ARCHIVE_DIR} && mv {{}} {self.dir}/{gp.ARCHIVE_DIR}/'
        self.addCleanup(self.tmp.cleanup)

    def run_pipeline(self, session, post=None):
        return gp.run_pipeline([self.product], self.dir, post or self.post, 2, lambda: session)

    def rows(self):
        with open(os.path.join(self.dir, gp.TIMING_FILE)) as f:
            return list(csv.DictReader(f))

    def test_fresh_download_and_unpack(self):
        session = FakeSession(self.content)
        self.assertEqual(self.run_pipeline(session), 0)
        self.assertTrue(os.path.isfile(self.archive))
        self.assertFalse(os.path.exists(self.final + '.part'))
        rows = self.rows()
        self.assertEqual([(r['step'], r['status']) for r in rows], [('download', 'ok'), ('unpack', 'ok')])
        self.assertEqual(rows[0]['final_host'], 'cdn.example')
        self.assertEqual(int(rows[0]['bytes_this_attempt']), len(self.content))

    def test_done_is_skipped(self):
        os.makedirs(os.path.dirname(self.archive))
        write(self.archive, self.content)
        session = FakeSession(self.content)
        self.assertEqual(self.run_pipeline(session), 0)
        self.assertEqual(session.ranges, [])

    def test_complete_zip_is_only_unpacked(self):
        write(self.final, self.content)
        session = FakeSession(self.content)
        self.assertEqual(self.run_pipeline(session), 0)
        self.assertEqual(session.ranges, [])
        self.assertTrue(os.path.isfile(self.archive))

    def test_part_is_resumed(self):
        write(self.final + '.part', self.content[:70000])
        session = FakeSession(self.content)
        self.assertEqual(self.run_pipeline(session), 0)
        self.assertEqual(session.ranges, ['bytes=70000-'])
        self.assertEqual(read(self.archive), self.content)
        self.assertEqual(self.rows()[0]['resumed_from_byte'], '70000')

    def test_truncated_zip_from_old_downloader_is_resumed(self):
        write(self.final, self.content[:50000])
        self.assertEqual(gp.classify(self.dir, self.name, len(self.content)), ('resume', 50000))
        session = FakeSession(self.content)
        self.assertEqual(self.run_pipeline(session), 0)
        self.assertEqual(session.ranges, ['bytes=50000-'])
        self.assertEqual(read(self.archive), self.content)

    def test_server_ignoring_range_restarts_file(self):
        write(self.final + '.part', self.content[:70000])
        session = FakeSession(self.content, ignore_range=True)
        self.assertEqual(self.run_pipeline(session), 0)
        self.assertEqual(read(self.archive), self.content)
        self.assertEqual(self.rows()[0]['resumed_from_byte'], '0')

    def test_dropped_connection_is_retried_with_resume(self):
        session = FakeSession(self.content, drop_after=60000)
        wait = threading.Event.wait
        threading.Event.wait = lambda self, timeout=None: self.is_set()   # no 10 s pause between attempts
        try:
            self.assertEqual(self.run_pipeline(session), 0)
        finally:
            threading.Event.wait = wait
        self.assertEqual(session.ranges, [None, 'bytes=60000-'])
        self.assertEqual([r['status'] for r in self.rows() if r['step'] == 'download'], ['failed', 'ok'])
        self.assertEqual(read(self.archive), self.content)

    def test_interrupt_keeps_part_and_logs_row(self):
        stop = threading.Event()
        timing = gp.TimingLog(self.dir)
        session = FakeSession(self.content)
        response = FakeResponse(200, self.content, 'https://cdn.example/x', stop_after=40000, stop_event=stop)
        session.get = lambda *a, **k: response
        result = gp.process_granule(self.product, self.dir, self.post, lambda: session, stop, timing)
        self.assertEqual(result, 'interrupted')
        self.assertEqual(os.path.getsize(self.final + '.part'), 40000)
        self.assertFalse(os.path.exists(self.final))
        self.assertEqual(self.rows()[0]['status'], 'interrupted')

    def test_failed_unpack_leaves_zip_and_reports_unfinished(self):
        session = FakeSession(self.content)
        self.assertEqual(self.run_pipeline(session, post='false'), 1)
        self.assertTrue(os.path.isfile(self.final))
        self.assertEqual(self.rows()[-1]['status'], 'failed')

    def test_wrong_content_with_right_size_is_removed(self):
        session = FakeSession(b'x' * len(self.content))
        timing = gp.TimingLog(self.dir)
        ok = gp.download_once(session, 'u', self.dir, self.name, len(self.content), threading.Event(), timing, 1)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.final))
        self.assertFalse(os.path.exists(self.final + '.part'))


if __name__ == '__main__':
    unittest.main()
