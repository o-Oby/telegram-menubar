import errno
import json
import os
from pathlib import Path
import plistlib
import shutil
import tempfile
import unittest
from unittest import mock

import install as installer


class FakeHost:
    def __init__(self, source, paths):
        self.source = source
        self.paths = paths
        self.answer = "VALIDER"
        self.events = []
        self.fail_signature = False
        self.fail_replacement_verify = False
        self.fail_launch = False
        self.fail_quit = False
        self.fail_rollback_stop = False
        self.corrupt_profile_copy = False
        self.preview_action = None

    def stage(self, dmg, workspace):
        self.events.append("stage")
        target = workspace / installer.APP_NAME
        installer.verified_copy(self.source, target, self)
        return target

    def copy(self, source, destination):
        shutil.copytree(source, destination, symlinks=True)
        if self.corrupt_profile_copy and destination.name == "profile" and destination.parent.parent == self.paths.backups:
            (destination / ".tempkeyEncrypted").write_bytes(b"bad")

    def verify_signature(self, app):
        self.events.append(("verify", str(app)))
        if self.fail_signature and app.name == installer.APP_NAME:
            raise RuntimeError("signature invalide")
        if self.fail_replacement_verify and app == self.paths.installed and installer.app_info(app)["CFBundleIdentifier"] == installer.BUNDLE_ID:
            raise RuntimeError("signature après remplacement invalide")

    def quit(self, apps):
        self.events.append("quit")
        if self.fail_quit:
            raise RuntimeError("Telegram est encore actif")

    def assert_stopped(self, apps):
        self.events.append("stopped")
        if self.fail_rollback_stop and installer.app_info(self.paths.installed)["CFBundleIdentifier"] == installer.BUNDLE_ID:
            raise RuntimeError("application rouverte pendant le remplacement")

    def launch(self, app, preview=False):
        self.events.append(("launch", str(app), preview))
        if preview and self.preview_action:
            self.preview_action()
        if self.fail_launch and not preview:
            raise RuntimeError("relance échouée")

    def confirm(self):
        self.events.append("confirm")
        return self.answer


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="menubar-installer-test-")
        self.root = Path(self.temporary.name).resolve()
        self.paths = installer.InstallPaths(self.root / "Applications", self.root / "Support", self.root / "Group/appstore")
        self.paths.applications.mkdir()
        self.make_profile(self.paths.original_profile)
        self.make_app(self.paths.installed, personal=False)
        self.delivery = self.root / "delivery"
        self.delivery.mkdir()
        self.source = self.root / installer.APP_NAME
        self.manifest = {
            "version": "13.1.0", "build": "283357", "revision": 1,
            "sourceCommit": "a" * 40, "upstreamCommit": "b" * 40,
            "artifacts": [{"name": "Telegram-Menu-Bar-13.1.0-r1-arm64.dmg", "sha256": ""}],
        }
        self.make_app(self.source, personal=True)
        self.save_delivery()
        self.host = FakeHost(self.source, self.paths)
        self.original_app = installer.tree_hash(self.paths.installed)
        self.original_profile = installer.tree_hash(self.paths.original_profile)

    def tearDown(self):
        self.temporary.cleanup()

    def make_profile(self, path):
        (path / "accounts-metadata").mkdir(parents=True)
        (path / ".tempkeyEncrypted").write_bytes(b"x" * 64)
        (path / "accounts-metadata/fixture").write_bytes(b"synthetic session")
        (path / "network-settings").write_bytes(b"synthetic persisted proxy")
        (path / "empty").mkdir()

    def make_app(self, app, personal):
        (app / "Contents/MacOS").mkdir(parents=True)
        (app / "Contents/Resources").mkdir()
        (app / "Contents/MacOS/Telegram").write_bytes(b"fake executable")
        os.chmod(app / "Contents/MacOS/Telegram", 0o755)
        info = {
            "CFBundleIdentifier": installer.BUNDLE_ID if personal else installer.OFFICIAL_ID,
            "CFBundleExecutable": "Telegram", "CFBundleShortVersionString": "13.1.0", "CFBundleVersion": "283357",
            "SOURCE": "APP_STORE",
        }
        if personal:
            info.update(PersonalMenuBar=True, SUEnableAutomaticChecks=False, SUAutomaticallyUpdate=False,
                        PersonalMenuBarSourceCommit="a" * 40, PersonalMenuBarUpstreamCommit="b" * 40, PersonalMenuBarRevision=1)
            (app / "Contents/Resources/menubar-config.json").write_text(json.dumps({"schema": 1, "api_id": 100001, "api_hash": "c" * 32}))
        with (app / "Contents/Info.plist").open("wb") as stream:
            plistlib.dump(info, stream)

    def save_delivery(self):
        dmg = self.delivery / self.manifest["artifacts"][0]["name"]
        dmg.write_bytes(json.dumps({key: value for key, value in self.manifest.items() if key != "artifacts"}).encode())
        self.manifest["artifacts"][0]["sha256"] = installer.sha256(dmg)
        (self.delivery / "delivery.json").write_text(json.dumps(self.manifest))

    def advance(self):
        self.manifest.update(version="13.2.0", build="284000", sourceCommit="d" * 40)
        self.manifest["artifacts"][0]["name"] = "Telegram-Menu-Bar-13.2.0-r1-arm64.dmg"
        filename = self.source / "Contents/Info.plist"
        info = plistlib.loads(filename.read_bytes())
        info.update(CFBundleShortVersionString="13.2.0", CFBundleVersion="284000", PersonalMenuBarSourceCommit="d" * 40)
        filename.write_bytes(plistlib.dumps(info))
        self.save_delivery()

    def run_install(self):
        return installer.install_delivery(self.delivery, self.paths, self.host)

    def backups(self):
        return list(self.paths.backups.iterdir()) if self.paths.backups.exists() else []

    def assert_originals(self):
        self.assertEqual(installer.tree_hash(self.paths.installed), self.original_app)
        self.assertEqual(installer.tree_hash(self.paths.original_profile), self.original_profile)

    def test_initial_migration_validated_keeps_original_profile_and_verified_backup(self):
        self.host.preview_action = lambda: (self.paths.profile / "new-message").write_text("received in preview")
        receipt = self.run_install()
        self.assertEqual(receipt["status"], "validated")
        self.assertEqual(installer.app_info(self.paths.installed)["CFBundleIdentifier"], installer.BUNDLE_ID)
        self.assertFalse(self.paths.preview.exists())
        self.assertEqual(installer.tree_hash(self.paths.original_profile), self.original_profile)
        self.assertTrue((self.paths.profile / "new-message").exists())
        backup = self.backups()[0]
        self.assertEqual(installer.tree_hash(backup / "Telegram.app"), self.original_app)
        self.assertEqual(installer.tree_hash(backup / "profile"), self.original_profile)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.paths.receipt.stat().st_mode & 0o777, 0o600)
        launches = [event for event in self.host.events if isinstance(event, tuple) and event[0] == "launch"]
        self.assertEqual(launches, [("launch", str(self.paths.preview), True), ("launch", str(self.paths.installed), False)])

    def test_pending_without_terminal_resumes_without_overwriting_private_profile_or_backup(self):
        self.host.answer = None
        with self.assertRaisesRegex(RuntimeError, "VALIDER"):
            self.run_install()
        self.assert_originals()
        self.assertTrue(self.paths.preview.exists())
        backup = self.backups()[0]
        (self.paths.profile / "new-data").write_text("keep")
        self.host.answer = "VALIDER"
        self.run_install()
        self.assertEqual(self.backups(), [backup])
        self.assertEqual((self.paths.profile / "new-data").read_text(), "keep")

    def test_any_other_confirmation_keeps_official_app(self):
        self.host.answer = "oui"
        with self.assertRaisesRegex(RuntimeError, "en attente"):
            self.run_install()
        self.assert_originals()

    def test_other_delivery_cannot_replace_pending_preview(self):
        self.host.answer = None
        with self.assertRaises(RuntimeError):
            self.run_install()
        preview_hash = installer.tree_hash(self.paths.preview)
        self.advance()
        with self.assertRaisesRegex(RuntimeError, "autre livraison"):
            self.run_install()
        self.assert_originals()
        self.assertEqual(installer.tree_hash(self.paths.preview), preview_hash)
        self.assertEqual(len(self.backups()), 1)

    def test_update_backs_up_private_profile_and_preserves_new_data(self):
        self.run_install()
        (self.paths.profile / "new-data").write_text("keep")
        before = installer.tree_hash(self.paths.profile)
        old_app = installer.tree_hash(self.paths.installed)
        self.advance()
        self.host.events.clear()
        receipt = self.run_install()
        self.assertEqual(receipt["version"], "13.2.0")
        self.assertNotIn("confirm", self.host.events)
        self.assertEqual(installer.tree_hash(self.paths.profile), before)
        backup = Path(receipt["backup"])
        self.assertEqual(installer.tree_hash(backup / "profile"), before)
        self.assertEqual(installer.tree_hash(backup / "Telegram.app"), old_app)
        self.assertEqual(installer.tree_hash(self.paths.original_profile), self.original_profile)

    def test_identical_bundle_no_backup_or_quit(self):
        self.run_install()
        before = self.backups()
        self.host.events.clear()
        self.run_install()
        self.assertEqual(self.backups(), before)
        self.assertNotIn("quit", self.host.events)
        self.assertNotIn("confirm", self.host.events)

    def test_bad_signature_rejected_before_quit_or_backup(self):
        self.host.fail_signature = True
        with self.assertRaisesRegex(RuntimeError, "signature"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assertFalse(self.backups())
        self.assert_originals()

    def test_downgrade_rejected_before_quit(self):
        self.manifest["version"] = "13.0.0"
        self.save_delivery()
        with self.assertRaisesRegex(RuntimeError, "antérieure"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assert_originals()

    def test_artifact_hash_failure_rejected_before_quit(self):
        (self.delivery / self.manifest["artifacts"][0]["name"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assert_originals()

    def test_failed_quit_never_copies_profile(self):
        self.host.fail_quit = True
        with self.assertRaisesRegex(RuntimeError, "encore actif"):
            self.run_install()
        self.assertFalse(self.paths.profile.exists())
        self.assertFalse(self.backups())
        self.assert_originals()

    def test_failed_backup_never_launches_or_migrates(self):
        self.host.corrupt_profile_copy = True
        with self.assertRaisesRegex(RuntimeError, "Copie non conforme"):
            self.run_install()
        self.assertFalse(self.paths.profile.exists())
        self.assertFalse(self.paths.receipt.exists())
        self.assertNotIn("confirm", self.host.events)
        self.assert_originals()

    def test_failure_before_final_launch_rolls_back_and_can_resume(self):
        self.host.fail_replacement_verify = True
        with self.assertRaisesRegex(RuntimeError, "ancienne application restaurée"):
            self.run_install()
        self.assert_originals()
        self.assertTrue(self.paths.preview.exists())
        self.assertEqual(json.loads(self.paths.receipt.read_text())["status"], "pending-validation")
        self.host.fail_replacement_verify = False
        self.run_install()
        self.assertEqual(len(self.backups()), 1)

    def test_failure_after_launch_preserves_profile_and_resumes_without_new_backup(self):
        self.host.fail_launch = True
        with self.assertRaisesRegex(RuntimeError, "sa relance"):
            self.run_install()
        receipt = json.loads(self.paths.receipt.read_text())
        self.assertEqual(receipt["status"], "validated")
        self.assertTrue(receipt["launchPending"])
        self.assertTrue(Path(receipt["previousApplication"]).exists())
        (self.paths.profile / "new-data").write_text("keep")
        self.host.fail_launch = False
        result = self.run_install()
        self.assertFalse(result["launchPending"])
        self.assertFalse(Path(receipt["previousApplication"]).exists())
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual((self.paths.profile / "new-data").read_text(), "keep")

    def test_missing_key_never_resets_profile(self):
        (self.paths.original_profile / ".tempkeyEncrypted").unlink()
        with self.assertRaisesRegex(RuntimeError, "Profil incomplet"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assertFalse(self.paths.profile.exists())

    def test_profile_symlink_is_rejected(self):
        self.paths.support.mkdir()
        self.paths.profile.symlink_to(self.paths.original_profile)
        with self.assertRaisesRegex(RuntimeError, "symbolique"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assert_originals()

    def test_original_profile_changed_during_validation_blocks_replacement(self):
        self.host.preview_action = lambda: (self.paths.original_profile / "changed").write_text("official reopened")
        with self.assertRaisesRegex(RuntimeError, "changé pendant la validation"):
            self.run_install()
        self.assertEqual(installer.tree_hash(self.paths.installed), self.original_app)
        self.assertTrue(self.paths.preview.exists())

    def test_existing_private_profile_without_receipt_is_preserved(self):
        self.make_profile(self.paths.profile)
        before = installer.tree_hash(self.paths.profile)
        with self.assertRaisesRegex(RuntimeError, "sans reçu"):
            self.run_install()
        self.assertEqual(installer.tree_hash(self.paths.profile), before)
        self.assertNotIn("quit", self.host.events)

    def test_tree_hash_does_not_follow_symlinks(self):
        target = self.root / "outside"
        target.write_text("original")
        link = self.paths.original_profile / "symbolic-cache"
        link.symlink_to(target)
        before = installer.tree_hash(self.paths.original_profile)
        target.write_text("changed outside")
        self.assertEqual(installer.tree_hash(self.paths.original_profile), before)
        with self.assertRaisesRegex(RuntimeError, "lien sortant"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)

    def make_app_scripts_link(self, target=installer.APP_SCRIPTS_TARGET):
        link = self.paths.original_profile / installer.APP_SCRIPTS_LINK
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        self.original_profile = installer.tree_hash(self.paths.original_profile)
        return link

    def test_app_scripts_link_is_backed_up_without_following_and_localized_in_private_profile(self):
        original = self.make_app_scripts_link()
        original_access = os.access
        with mock.patch.object(installer.os, "access", side_effect=lambda path, mode: False if Path(path).name == original.name and Path(path).is_symlink() else original_access(path, mode)):
            self.run_install()
        self.assertTrue(original.is_symlink())
        self.assertEqual(installer.tree_hash(self.paths.original_profile), self.original_profile)
        saved = self.backups()[0] / "profile" / installer.APP_SCRIPTS_LINK
        self.assertTrue(saved.is_symlink())
        self.assertEqual(os.readlink(saved), installer.APP_SCRIPTS_TARGET)
        private = self.paths.profile / installer.APP_SCRIPTS_LINK
        self.assertFalse(private.is_symlink())
        self.assertTrue(private.is_dir())
        self.assertEqual(list(private.iterdir()), [])
        self.assertEqual(private.stat().st_mode & 0o777, 0o700)

    def test_app_scripts_link_with_unexpected_target_is_rejected_before_quit(self):
        self.make_app_scripts_link("../../../../different-directory")
        with self.assertRaisesRegex(RuntimeError, "lien sortant"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assertFalse(self.backups())
        self.assert_originals()

    def test_app_scripts_link_remains_forbidden_in_private_profile(self):
        self.run_install()
        link = self.paths.profile / installer.APP_SCRIPTS_LINK
        link.parent.mkdir(parents=True)
        link.symlink_to(installer.APP_SCRIPTS_TARGET)
        self.host.events.clear()
        with self.assertRaisesRegex(RuntimeError, "lien sortant"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)

    def test_localized_profile_resumes_after_interruption_before_preview(self):
        self.make_app_scripts_link()
        real_rename = Path.rename
        def stop_before_preview(source, destination):
            if destination == self.paths.preview:
                raise OSError("fixture before preview")
            return real_rename(source, destination)
        with mock.patch.object(installer.Path, "rename", autospec=True, side_effect=stop_before_preview):
            with self.assertRaisesRegex(OSError, "fixture before preview"):
                self.run_install()
        receipt = json.loads(self.paths.receipt.read_text())
        self.assertFalse(receipt["previewLaunched"])
        self.assertEqual(installer.tree_hash(self.paths.profile), receipt["privateProfileSha256"])
        self.run_install()
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(installer.tree_hash(self.paths.original_profile), self.original_profile)

    def test_relative_profile_symlinks_stay_inside_private_copy(self):
        (self.paths.original_profile / "local-link").symlink_to("accounts-metadata/fixture")
        self.run_install()
        link = self.paths.profile / "local-link"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "accounts-metadata/fixture")
        self.assertEqual(link.resolve(), self.paths.profile / "accounts-metadata/fixture")

    def test_interrupted_swap_fails_closed(self):
        self.paths.support.mkdir()
        installer.write_json(self.paths.receipt, {"schema": 1, "status": "replacing"})
        with self.assertRaisesRegex(RuntimeError, "interrompue"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assert_originals()

    def test_official_update_feed_is_rejected_before_quit(self):
        filename = self.source / "Contents/Info.plist"
        info = plistlib.loads(filename.read_bytes())
        info["SUFeedURL"] = "https://example.invalid/feed"
        filename.write_bytes(plistlib.dumps(info))
        with self.assertRaisesRegex(RuntimeError, "mises à jour officielles"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)


    def test_unsafe_rollback_keeps_journal_backup_and_workspace(self):
        self.host.fail_replacement_verify = True
        self.host.fail_rollback_stop = True
        with self.assertRaisesRegex(RuntimeError, "restauration automatique impossible"):
            self.run_install()
        receipt = json.loads(self.paths.receipt.read_text())
        self.assertEqual(receipt["status"], "replacing")
        self.assertTrue(Path(receipt["previousApplication"]).exists())
        self.assertTrue(Path(receipt["backup"]).exists())
        self.assertTrue(list(self.paths.applications.glob(".telegram-menubar-install-*")))
        self.assertEqual(installer.tree_hash(self.paths.original_profile), self.original_profile)

    def test_profile_must_still_be_valid_after_preview(self):
        self.host.preview_action = lambda: (self.paths.profile / ".tempkeyEncrypted").unlink()
        with self.assertRaisesRegex(RuntimeError, "Profil incomplet"):
            self.run_install()
        self.assert_originals()
        self.assertTrue(self.paths.preview.exists())

    def test_non_object_manifest_has_actionable_error(self):
        (self.delivery / "delivery.json").write_text("[]")
        with self.assertRaisesRegex(RuntimeError, "Manifest.*objet JSON"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)

    def test_non_object_api_config_has_actionable_error(self):
        (self.source / "Contents/Resources/menubar-config.json").write_text("[]")
        with self.assertRaisesRegex(RuntimeError, "Configuration API.*objet JSON"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)

    def test_non_object_receipt_has_actionable_error(self):
        self.paths.support.mkdir()
        self.paths.receipt.write_text("[]")
        with self.assertRaisesRegex(RuntimeError, "Reçu.*objet JSON"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assertEqual(self.paths.receipt.read_text(), "[]")

    def test_non_object_artifact_is_rejected(self):
        self.manifest["artifacts"] = [[]]
        (self.delivery / "delivery.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(RuntimeError, "artefact invalide"):
            self.run_install()
        self.assertNotIn("quit", self.host.events)

    def test_cleanup_failure_does_not_hide_original_failure(self):
        self.host.fail_signature = True
        original_remove = shutil.rmtree

        def fail_workspace(path, *args, **kwargs):
            if Path(path).name.startswith(".telegram-menubar-install-"):
                raise OSError("cleanup fixture")
            return original_remove(path, *args, **kwargs)

        with mock.patch.object(installer.shutil, "rmtree", side_effect=fail_workspace), mock.patch.object(installer.sys, "stderr"):
            with self.assertRaisesRegex(RuntimeError, "signature invalide"):
                self.run_install()
        self.assert_originals()


    def test_source_profile_access_denied_before_quit(self):
        original_access = os.access
        with mock.patch.object(installer.os, "access", side_effect=lambda path, mode: False if path == self.paths.original_profile else original_access(path, mode)):
            with self.assertRaisesRegex(RuntimeError, "macOS refuse la lecture.*profil"):
                self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assertFalse(self.backups())
        self.assert_originals()

    def test_source_key_access_denied_before_quit(self):
        original_access = os.access
        key = self.paths.original_profile / ".tempkeyEncrypted"
        with mock.patch.object(installer.os, "access", side_effect=lambda path, mode: False if path == key else original_access(path, mode)):
            with self.assertRaisesRegex(RuntimeError, "Autorisez.*Terminal"):
                self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assert_originals()

    def test_walk_access_denied_is_not_silently_ignored(self):
        def denied_walk(path, **kwargs):
            kwargs["onerror"](PermissionError(errno.EACCES, "fixture unreadable directory"))
        with mock.patch.object(installer.os, "walk", side_effect=denied_walk):
            with self.assertRaisesRegex(RuntimeError, "Confidentialité et sécurité"):
                self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assert_originals()

    def test_private_profile_access_denied_before_update_quit(self):
        self.run_install()
        self.advance()
        self.host.events.clear()
        original_access = os.access
        with mock.patch.object(installer.os, "access", side_effect=lambda path, mode: False if path == self.paths.profile else original_access(path, mode)):
            with self.assertRaisesRegex(RuntimeError, "macOS refuse la lecture"):
                self.run_install()
        self.assertNotIn("quit", self.host.events)
        self.assertEqual(len(self.backups()), 1)

    def test_read_only_previous_app_is_archived_by_rename(self):
        for path in [self.paths.installed, *self.paths.installed.rglob("*")]:
            os.chmod(path, 0o555 if path.is_dir() else 0o444)
        old_hash = installer.tree_hash(self.paths.installed)
        try:
            receipt = self.run_install()
            archived = Path(receipt["archivedApplication"])
            self.assertIn(archived.parent, [Path(receipt["backup"]), self.paths.applications])
            self.assertEqual(installer.tree_hash(archived), old_hash)
            self.assertNotIn("previousApplication", receipt)
            self.assertFalse(receipt["launchPending"])
            metadata = json.loads((Path(receipt["backup"]) / "original-application.json").read_text())
            self.assertEqual(metadata["application"], str(archived))
        finally:
            for path in self.root.rglob("*"):
                if path.is_dir():
                    os.chmod(path, 0o755)

    def test_cross_volume_archive_keeps_previous_without_pending_launch(self):
        original_rename = Path.rename
        def different_volume(path, target):
            if path.name.startswith(".Telegram.previous-"):
                raise OSError(errno.EXDEV, "fixture cross-volume rename")
            return original_rename(path, target)
        with mock.patch.object(Path, "rename", different_volume):
            receipt = self.run_install()
        archived = Path(receipt["archivedApplication"])
        self.assertEqual(archived.parent, self.paths.applications)
        self.assertTrue(archived.name.startswith(".Telegram.previous-"))
        self.assertEqual(installer.tree_hash(archived), self.original_app)
        self.assertNotIn("previousApplication", receipt)
        self.assertFalse(receipt["launchPending"])
        self.run_install()
        self.assertEqual(len(self.backups()), 1)
        self.assertTrue(archived.exists())

    def test_archive_failure_does_not_mark_successful_launch_pending(self):
        original_rename = Path.rename
        def denied_archive(path, target):
            if path.name.startswith(".Telegram.previous-"):
                raise OSError(errno.EIO, "fixture archive unavailable")
            return original_rename(path, target)
        with mock.patch.object(Path, "rename", denied_archive):
            with self.assertRaisesRegex(RuntimeError, "finalisation a échoué"):
                self.run_install()
        receipt = json.loads(self.paths.receipt.read_text())
        self.assertFalse(receipt["launchPending"])
        self.assertTrue(Path(receipt["previousApplication"]).exists())
        self.run_install()
        receipt = json.loads(self.paths.receipt.read_text())
        self.assertNotIn("previousApplication", receipt)
        self.assertTrue(Path(receipt["archivedApplication"]).exists())
        self.assertEqual(len(self.backups()), 1)


class ClockFixture:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


class MacHostTests(unittest.TestCase):
    def setUp(self):
        self.app = Path("/fixture/Telegram.app")
        self.executable = str(self.app / "Contents/MacOS/Telegram")
        self.helper = str(self.app / "Contents/Frameworks/Helper.app/Contents/MacOS/Helper")
        self.host = installer.MacHost()
        self.host.run = mock.Mock(return_value="")
        self.clock = ClockFixture()

    def launch(self, running):
        self.host.running = mock.Mock(side_effect=lambda apps: running(self.clock.now))
        with mock.patch.object(installer.time, "monotonic", self.clock.monotonic), mock.patch.object(installer.time, "sleep", self.clock.sleep):
            self.host.launch(self.app)

    def test_launch_requires_stable_main_process(self):
        self.launch(lambda now: [self.executable])
        self.assertGreaterEqual(self.clock.now, 3)

    def test_helpers_do_not_count_as_successful_launch(self):
        with self.assertRaisesRegex(RuntimeError, "processus principal"):
            self.launch(lambda now: [self.helper])

    def test_immediate_crash_does_not_count_as_successful_launch(self):
        with self.assertRaisesRegex(RuntimeError, "processus principal"):
            self.launch(lambda now: [self.executable] if now < 1 else [])

    def test_launch_stability_resets_after_interruption(self):
        self.launch(lambda now: [self.executable] if now < 1 or now >= 4 else [])
        self.assertGreaterEqual(self.clock.now, 7)

    def test_quit_applescript_guards_against_launching_stopped_app(self):
        self.host.running = mock.Mock(side_effect=[[self.executable], [self.executable], [], []])
        self.host.quit([self.app])
        command = self.host.run.call_args.args[0]
        self.assertEqual(command[:2], ["/usr/bin/osascript", "-e"])
        self.assertIn('if application "/fixture/Telegram.app" is running then', command[2])
        self.assertIn('tell application "/fixture/Telegram.app" to quit', command[2])


if __name__ == "__main__":
    unittest.main()
