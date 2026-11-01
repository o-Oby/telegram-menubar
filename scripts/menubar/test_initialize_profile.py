import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import initialize_profile as initializer


class ProfileDriverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="menubar-profile-driver-test-")
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_vendored_sources_match_pinned_checksums(self):
        self.assertEqual(initializer.verify_sources(), initializer.SOURCE_ROOT)

    def test_altered_native_source_is_rejected_before_compilation(self):
        root = self.root / "source"
        shutil.copytree(initializer.SOURCE_ROOT, root)
        source = root / "vendor/Crypto.m"
        source.write_text(source.read_text() + "\n")
        with self.assertRaisesRegex(RuntimeError, "différente de sa provenance"):
            initializer.verify_sources(root)

    def test_symbolic_native_source_is_rejected(self):
        root = self.root / "source"
        shutil.copytree(initializer.SOURCE_ROOT, root)
        source = root / "vendor/Crypto.m"
        source.unlink()
        source.symlink_to(initializer.SOURCE_ROOT / "vendor/Crypto.m")
        with self.assertRaisesRegex(RuntimeError, "symbolique"):
            initializer.verify_sources(root)

    def test_existing_destination_is_preserved_before_compilation(self):
        destination = self.root / "existing"
        destination.mkdir()
        marker = destination / "fixture"
        marker.write_text("synthetic data to preserve")
        with mock.patch.object(initializer, "compile_initializer") as compile_helper:
            with self.assertRaisesRegex(RuntimeError, "existe déjà"):
                initializer.initialize_profile(destination)
            compile_helper.assert_not_called()
        self.assertEqual(marker.read_text(), "synthetic data to preserve")

    def test_destination_symlink_is_rejected_before_compilation(self):
        destination = self.root / "link"
        destination.symlink_to(self.root / "missing")
        with mock.patch.object(initializer, "compile_initializer") as compile_helper:
            with self.assertRaisesRegex(RuntimeError, "symbolique"):
                initializer.initialize_profile(destination)
            compile_helper.assert_not_called()
        self.assertTrue(destination.is_symlink())
        self.assertFalse((self.root / "missing").exists())

    def test_parent_symlink_is_rejected_before_compilation(self):
        parent = self.root / "link"
        parent.symlink_to(self.root)
        with mock.patch.object(initializer, "compile_initializer") as compile_helper:
            with self.assertRaisesRegex(RuntimeError, "symbolique"):
                initializer.initialize_profile(parent / "new")
            compile_helper.assert_not_called()
        self.assertFalse((self.root / "new").exists())

    def test_missing_parent_is_rejected_before_compilation(self):
        with mock.patch.object(initializer, "compile_initializer") as compile_helper:
            with self.assertRaisesRegex(RuntimeError, "parent"):
                initializer.initialize_profile(self.root / "missing/new")
            compile_helper.assert_not_called()


@unittest.skipUnless(sys.platform == "darwin" and platform.machine() == "arm64", "Native Apple Silicon helper")
class NativeProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool_directory = tempfile.TemporaryDirectory(prefix="menubar-profile-native-tool-test-")
        cls.tool = initializer.compile_initializer(Path(cls.tool_directory.name).resolve() / "initialize-profile")

    @classmethod
    def tearDownClass(cls):
        cls.tool_directory.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="menubar-profile-native-data-test-")
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def run_native(self, destination):
        return subprocess.run([str(self.tool), str(destination)], text=True, capture_output=True, timeout=15)

    def test_native_initialization_decrypts_and_reopens_without_exposing_keys(self):
        destination = self.root / "fresh"
        result = self.run_native(destination)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PROFILE_INITIALIZED\n")
        self.assertEqual(result.stderr, "")
        initializer.verify_new_profile(destination)
        self.assertFalse((destination / ".tempkey").exists())

    def test_native_keys_are_distinct_between_fresh_profiles(self):
        first = self.root / "first"
        second = self.root / "second"
        self.assertEqual(self.run_native(first).returncode, 0)
        self.assertEqual(self.run_native(second).returncode, 0)
        self.assertNotEqual(hashlib.sha256((first / ".tempkeyEncrypted").read_bytes()).digest(),
                            hashlib.sha256((second / ".tempkeyEncrypted").read_bytes()).digest())

    def test_native_helper_refuses_existing_profile_without_changing_key(self):
        destination = self.root / "existing"
        self.assertEqual(self.run_native(destination).returncode, 0)
        key = destination / ".tempkeyEncrypted"
        before = key.read_bytes()
        metadata = key.stat()
        result = self.run_native(destination)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(key.read_bytes(), before)
        self.assertEqual(key.stat().st_mtime_ns, metadata.st_mtime_ns)

    def test_native_helper_refuses_symbolic_destination(self):
        target = self.root / "target"
        destination = self.root / "link"
        destination.symlink_to(target)
        self.assertNotEqual(self.run_native(destination).returncode, 0)
        self.assertTrue(destination.is_symlink())
        self.assertFalse(target.exists())

    def test_native_helper_refuses_symbolic_parent(self):
        parent = self.root / "parent-link"
        parent.symlink_to(self.root)
        self.assertNotEqual(self.run_native(parent / "new").returncode, 0)
        self.assertFalse((self.root / "new").exists())

    def test_creation_does_not_read_or_modify_other_profile_fixture(self):
        unrelated = self.root / "unrelated-profile"
        unrelated.mkdir()
        marker = unrelated / "must-not-be-read"
        marker.write_text("synthetic protected data")
        marker.chmod(0)
        before = marker.stat()
        self.assertEqual(self.run_native(self.root / "fresh").returncode, 0)
        after = marker.stat()
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(after.st_atime_ns, before.st_atime_ns)
        self.assertEqual(after.st_mode & 0o777, 0)
        marker.chmod(0o600)

    def test_driver_compiles_and_initializes_without_external_build_stage(self):
        destination = self.root / "driver-fresh"
        self.assertIsNone(initializer.initialize_profile(destination))
        initializer.verify_new_profile(destination)


if __name__ == "__main__":
    unittest.main()
