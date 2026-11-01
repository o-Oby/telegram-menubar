import contextlib
import importlib.util
import io
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_module(name, filename):
    specification = importlib.util.spec_from_file_location(name, pathlib.Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


prepare = load_module("prepare_build", "prepare-build.py")
package = load_module("package_build", "package-build.py")


class BuildPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="telegram-menubar-prepare-test-")
        self.base = pathlib.Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        for relative in ("Telegram.xcodeproj/project.pbxproj", "Telegram-Mac/Info.plist", "menubar/release.json", "scripts/configure_frameworks.sh"):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        self.credentials = self.base / "credentials.json"
        self.write_credentials({"api_id": 123456789, "api_hash": "b" * 32})
        self.commit = "a" * 40
        self.before = (self.root / "Telegram.xcodeproj/project.pbxproj").read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def write_credentials(self, data):
        self.credentials.write_text(json.dumps(data))
        self.credentials.chmod(0o600)

    def test_prepares_own_identity_and_private_config_without_losing_source_entries(self):
        marker = prepare.prepare(self.root, self.credentials, self.commit)
        self.assertEqual(marker.stat().st_mode & 0o777, 0o700)
        self.assertEqual((marker / "menubar-config.json").stat().st_mode & 0o777, 0o600)
        configuration = json.loads((marker / "menubar-config.json").read_text())
        self.assertEqual(configuration, {"schema": 1, "api_id": 123456789, "api_hash": "b" * 32})
        info = plistlib.loads((self.root / "Telegram-Mac/Info.plist").read_bytes())
        self.assertIs(info["PersonalMenuBar"], True)
        self.assertEqual(info["PersonalMenuBarSourceCommit"], self.commit)
        self.assertNotIn("SUFeedURL", info)
        self.assertIs(info["SUAutomaticallyUpdate"], False)
        _, project = prepare.load_project(self.root)
        _, original = prepare.load_project(ROOT)
        objects = project["objects"]
        original_objects = original["objects"]
        main = next(value for value in objects.values() if value.get("isa") == "PBXNativeTarget" and value.get("name") == "Telegram")
        for key in objects[main["buildConfigurationList"]]["buildConfigurations"]:
            settings = objects[key]["buildSettings"]
            self.assertEqual(settings["PRODUCT_BUNDLE_IDENTIFIER"], "fr.oby.telegram-menubar")
            self.assertEqual(settings["PRODUCT_NAME"], "Telegram Menu Bar")
            self.assertEqual(settings["PRODUCT_MODULE_NAME"], "Telegram")
            self.assertEqual(settings["EXECUTABLE_NAME"], "Telegram")
            self.assertEqual(settings["DEVELOPMENT_TEAM"], "")
            self.assertEqual(settings["CODE_SIGN_ENTITLEMENTS"], "")
        self.assertFalse(main["dependencies"])
        for key, value in objects.items():
            if value.get("isa") == "PBXSourcesBuildPhase":
                self.assertEqual(value, original_objects[key])
        entitlements = plistlib.loads((marker / "personal.entitlements").read_bytes())
        self.assertNotIn("com.apple.security.app-sandbox", entitlements)
        self.assertNotIn("com.apple.security.application-groups", entitlements)
        self.assertNotIn("keychain-access-groups", entitlements)
        framework_script = (self.root / "scripts/configure_frameworks.sh").read_text()
        self.assertIn("CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM=", framework_script)

    def test_refuses_missing_invalid_official_and_test_credentials_before_editing(self):
        cases = [None, {}, {"api_id": 9, "api_hash": "b" * 32}, {"api_id": 17349, "api_hash": "b" * 32}, {"api_id": True, "api_hash": "b" * 32}, {"api_id": 2**31, "api_hash": "b" * 32}, {"api_id": 123456789, "api_hash": "secret"}, {"api_id": 123456789, "api_hash": "0" * 32}]
        for data in cases:
            with self.subTest(data_type=type(data).__name__):
                self.write_credentials(data)
                with self.assertRaises(ValueError):
                    prepare.prepare(self.root, self.credentials, self.commit)
                self.assertEqual((self.root / "Telegram.xcodeproj/project.pbxproj").read_bytes(), self.before)
                self.assertFalse((self.root / ".menubar-build").exists())
        self.credentials.unlink()
        with self.assertRaisesRegex(ValueError, "my.telegram.org/apps"):
            prepare.read_credentials(self.credentials)

    def test_refuses_public_symlinked_and_in_repository_credentials(self):
        self.credentials.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "chmod 600"):
            prepare.read_credentials(self.credentials)
        self.credentials.chmod(0o600)
        link = self.base / "linked.json"
        link.symlink_to(self.credentials)
        with self.assertRaises(ValueError):
            prepare.read_credentials(link)
        local = self.root / "credentials.json"
        shutil.copy2(self.credentials, local)
        with self.assertRaisesRegex(ValueError, "hors du dépôt"):
            prepare.prepare(self.root, local, self.commit)

    def test_refuses_release_drift_and_changed_extension_layout(self):
        path = self.root / "menubar/release.json"
        release = json.loads(path.read_text())
        release["build"] = "999999"
        path.write_text(json.dumps(release))
        with self.assertRaisesRegex(ValueError, "build des sources"):
            prepare.prepare(self.root, self.credentials, self.commit)
        release["build"] = "283357"
        release["version"] = "99.0"
        path.write_text(json.dumps(release))
        with self.assertRaisesRegex(ValueError, "version marketing"):
            prepare.prepare(self.root, self.credentials, self.commit)
        self.assertEqual((self.root / "Telegram.xcodeproj/project.pbxproj").read_bytes(), self.before)
        text, project = prepare.load_project(self.root)
        target = next(value for value in project["objects"].values() if value.get("isa") == "PBXNativeTarget" and value.get("name") == "Telegram")
        target["dependencies"] = []
        with self.assertRaisesRegex(ValueError, "structure de l’extension"):
            prepare.prepare_project(text, project, "13.1.0")

    def test_manual_update_entry_points_have_immutable_guard(self):
        source = (ROOT / "Telegram-Mac/updater/AppUpdateViewController.swift").read_text()
        self.assertIn("#if PERSONAL_MENUBAR\nlet officialUpdaterEnabled = false", source)
        for declaration in (
            "func updateApplication(sharedContext: SharedAccountContext)",
            "func updater_resetWithUpdaterSource(_ source: UpdaterSource, force: Bool = true)",
            "func updateAppIfNeeded()",
            "private func stageNewerUpdate()",
            "private func resetUpdater()",
            "override func checkForUpdates(at URL: URL!, host aHost: SUHost!, domain: String!)",
            "override func checkForUpdates(at url: URL!, host aHost: SUHost!, domain: String!)",
            "override func install(withToolAndRelaunch relaunch: Bool, displayingUserInterface showUI: Bool)",
            "override func extractUpdate()",
        ):
            body = source.split(declaration + " {", 1)[1].lstrip()
            self.assertTrue(body.startswith("guard officialUpdaterEnabled else { return }"), declaration)
        bodies = source.split("override func downloadUpdate() {")[1:]
        self.assertEqual(len(bodies), 2)
        self.assertTrue(all(body.lstrip().startswith("guard officialUpdaterEnabled else { return }") for body in bodies))
        delegate = (ROOT / "Telegram-Mac/app/AppDelegate.swift").read_text()
        body = delegate.split("@IBAction func checkForUpdates(_ sender: Any) {", 1)[1].lstrip()
        self.assertTrue(body.startswith("#if !APP_STORE\n            guard officialUpdaterEnabled else { return }"))

    def test_packages_only_valid_personal_arm64_bundle_and_preserves_old_delivery(self):
        private = prepare.prepare(self.root, self.credentials, self.commit)
        app = self.base / "Telegram Menu Bar.app"
        resources = app / "Contents/Resources"
        resources.mkdir(parents=True)
        executable = app / "Contents/MacOS/Telegram"
        executable.parent.mkdir()
        executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"fixture-not-executable")
        info = plistlib.loads((self.root / "Telegram-Mac/Info.plist").read_bytes())
        info.update({"CFBundleIdentifier": "fr.oby.telegram-menubar", "CFBundleExecutable": "Telegram", "CFBundleShortVersionString": "13.1.0"})
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        output = self.base / "output/current"
        output.mkdir(parents=True)
        (output / "old-delivery").write_text("keep previous artifact")
        calls = []
        def fake_run(*arguments):
            values = list(map(str, arguments))
            calls.append(values)
            if values[:2] == ["/usr/bin/lipo", "-archs"]:
                return "arm64"
            if values[0] == "/usr/bin/iconutil":
                pathlib.Path(values[-1]).write_bytes(b"icns-test")
            if values[:2] == ["/usr/bin/hdiutil", "create"]:
                pathlib.Path(values[-1]).write_bytes(b"dmg-test")
            return ""
        with patch.object(package, "run", fake_run), contextlib.redirect_stdout(io.StringIO()):
            package.finish(self.root, app, output)
        manifest = json.loads((output / "delivery.json").read_text())
        self.assertEqual(manifest["sourceCommit"], self.commit)
        self.assertEqual(manifest["architecture"], "arm64")
        self.assertTrue(manifest["manualUpdates"])
        self.assertEqual(package.digest(output / manifest["artifacts"][0]["name"]), manifest["artifacts"][0]["sha256"])
        self.assertEqual(json.loads((resources / "menubar-config.json").read_text())["schema"], 1)
        self.assertEqual(len(list(output.parent.glob("current.previous-*/old-delivery"))), 1)
        self.assertTrue(any(call[:4] == ["/usr/bin/codesign", "--verify", "--deep", "--strict"] for call in calls))
        info["CFBundleIdentifier"] = "ru.keepcoder.Telegram"
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        calls.clear()
        with patch.object(package, "run", fake_run), self.assertRaisesRegex(ValueError, "variante personnelle"):
            package.finish(self.root, app, output)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
