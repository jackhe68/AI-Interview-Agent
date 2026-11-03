"""Code packaging never reads or replaces runtime data; all data here is fictional."""
import hashlib
import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_package', ROOT/'deploy/package_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='code-release-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'source'
        for name in release.RELEASE_FILES:
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# fictional code or asset')
        self.runtime = ('interviews.db', '.env', '.secret_key', 'interviews.db.deletions.jsonl',
                        '.public-test/trials.db', 'models/private.bin', 'uploads/recording.wav',
                        '.speech-temp/private.wav', '.test-artifacts/private.txt', 'private.py')
        for name in self.runtime:
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fictional runtime data')
        self.output = Path(self.temp.name)/'code.tar.gz'

    def test_allowlist_never_reads_runtime_files_and_manifest_matches(self):
        original = Path.read_bytes
        def checked(path):
            self.assertNotIn(path.relative_to(self.root).as_posix(), self.runtime)
            return original(path)
        with patch.object(Path, 'read_bytes', checked):
            release.build_release(self.root, self.output)
        with tarfile.open(self.output) as archive:
            self.assertEqual(set(archive.getnames()), set(release.RELEASE_FILES)|{'release-manifest.json'})
            manifest = json.load(archive.extractfile('release-manifest.json'))
            for entry in manifest['files']:
                self.assertEqual(hashlib.sha256(archive.extractfile(entry['path']).read()).hexdigest(), entry['sha256'])

    def test_update_preserves_existing_server_data_and_configuration(self):
        destination = Path(self.temp.name)/'server'
        for name in self.runtime:
            path = destination/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fictional newer server data')
        release.build_release(self.root, self.output)
        with tarfile.open(self.output) as archive:
            archive.extractall(destination, filter='data')
        for name in self.runtime:
            self.assertEqual((destination/name).read_bytes(), b'fictional newer server data')
        self.assertEqual((destination/'app.py').read_bytes(), b'# fictional code or asset')

    def test_missing_required_source_aborts_without_output(self):
        (self.root/'app.py').unlink()
        with self.assertRaises(ValueError): release.build_release(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b'previous release')
        with self.assertRaises(ValueError): release.build_release(self.root, self.output)
        self.assertEqual(self.output.read_bytes(), b'previous release')

    def test_linked_code_cannot_read_outside_the_source_tree(self):
        linked = self.root/'app.py'
        linked.unlink()
        try:
            linked.symlink_to(self.root/'.env')
        except OSError:
            # Exercise the resolved-path guard even without Windows symlink privileges.
            linked.write_bytes(b'fictional code')
            original = Path.resolve
            with patch.object(Path, 'resolve', lambda path: self.root/'.env' if path == linked else original(path)):
                with self.assertRaises(ValueError): release.build_release(self.root, self.output)
            self.assertFalse(self.output.exists())
            return
        with self.assertRaises(ValueError): release.build_release(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_failed_write_does_not_leave_a_publishable_archive(self):
        with patch.object(tarfile.TarFile, 'addfile', side_effect=OSError('fictional disk error')):
            with self.assertRaises(OSError): release.build_release(self.root, self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__': unittest.main(verbosity=2)
