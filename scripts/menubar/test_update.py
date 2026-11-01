import json
from pathlib import Path
import plistlib
import tempfile
import unittest

import update


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="telegram-updater-test-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.seed = self.root / "seed"
        self.seed.mkdir()
        update.git(self.seed, "init", "-b", "master")
        self.configure(self.seed)
        self.version(self.seed, "1.0.0", "100")
        self.put(self.seed, "common.txt", "original\n")
        self.commit(self.seed, "Initial release")
        self.base = update.git(self.seed, "rev-parse", "HEAD")
        self.upstream = self.root / "upstream.git"
        self.remote = self.root / "fork.git"
        self.repo = self.root / "repo with spaces"
        update.git(self.root, "clone", "--bare", str(self.seed), str(self.upstream))
        update.git(self.root, "init", "--bare", str(self.remote))
        update.git(self.root, "clone", str(self.upstream), str(self.repo))
        self.configure(self.repo)
        update.git(self.repo, "remote", "rename", "origin", "upstream")
        update.git(self.repo, "remote", "add", "origin", str(self.remote))
        update.git(self.repo, "switch", "-c", update.BRANCH)
        self.put(self.repo, ".gitignore", "dist/\n")
        self.put(self.repo, "customization.txt", "keep menu bar\n")
        self.put(self.repo, "menubar/release.json", json.dumps({"version": "1.0.0", "build": "100", "upstreamCommit": self.base, "revision": 1}))
        self.commit(self.repo, "Customize app")
        update.git(self.repo, "push", "origin", update.BRANCH)
        self.head = update.git(self.repo, "rev-parse", "HEAD")
        self.builds = 0
        self.target = {"version": "1.0.0", "build": "100"}
        self.workspaces = []
        self.addCleanup(self.cleanup_workspaces)

    def cleanup_workspaces(self):
        import shutil
        for root in self.workspaces:
            shutil.rmtree(root, ignore_errors=True)
        if self.repo.exists():
            for line in update.git(self.repo, "worktree", "list", "--porcelain").splitlines():
                if line.startswith("worktree "):
                    candidate = Path(line[9:])
                    if candidate != self.repo and candidate.parent.name.startswith("telegram-menubar-update-"):
                        shutil.rmtree(candidate.parent, ignore_errors=True)

    def configure(self, directory):
        update.git(directory, "config", "user.name", "Fixture")
        update.git(directory, "config", "user.email", "fixture@example.invalid")

    def put(self, directory, name, value):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def version(self, directory, version, build):
        for name in ["Telegram-Mac/Info.plist", "TelegramShare/Info.plist"]:
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(plistlib.dumps({"CFBundleShortVersionString": version, "CFBundleVersion": build}))

    def commit(self, directory, subject):
        update.git(directory, "add", ".")
        update.git(directory, "commit", "-m", subject)

    def publish(self, conflict=False, ordinary=False):
        update.git(self.seed, "switch", "-c", "release")
        self.version(self.seed, "1.1.0", "110")
        if conflict:
            self.put(self.seed, "common.txt", "upstream change\n")
        self.commit(self.seed, "Prepare release")
        update.git(self.seed, "switch", "master")
        subject = "Ordinary merge" if ordinary else "Merge branch 'release' into master (1.1)"
        update.git(self.seed, "merge", "--no-ff", "release", "-m", subject)
        update.git(self.seed, "push", str(self.upstream), "master")
        self.target = {"version": "1.1.0", "build": "110"}

    def build(self, candidate, log):
        self.builds += 1
        self.workspaces.append(candidate.parent)
        self.assertNotIn(" ", str(candidate))
        self.assertEqual((candidate / "customization.txt").read_text(), "keep menu bar\n")
        release = update.read_release(candidate)
        directory = candidate / "dist/menubar/current"
        directory.mkdir(parents=True)
        name = f"Telegram-Menu-Bar-{release['version']}-r{release['revision']}-arm64.dmg"
        (directory / name).write_bytes(b"fixture disk image")
        update.write_json(directory / "delivery.json", dict(release, sourceCommit=update.git(candidate, "rev-parse", "HEAD"), artifacts=[{"name": name, "sha256": update.digest(directory / name)}]))

    def run_update(self, **options):
        options.setdefault("build", self.build)
        return update.run_update(self.repo, latest=lambda: self.target, origin=str(self.remote), upstream=str(self.upstream), log=lambda message: None, **options)

    def assert_unchanged(self, head=None):
        head = head or self.head
        self.assertEqual(update.git(self.repo, "rev-parse", "HEAD"), head)
        self.assertEqual(update.git(self.remote, "rev-parse", update.BRANCH), head)

    def test_release_merge_preserves_fork_then_publishes_valid_delivery(self):
        self.publish()
        directory = self.run_update()
        head = update.git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(head, self.head)
        self.assert_unchanged(head)
        self.assertTrue(update.valid_delivery(directory, update.read_release(self.repo), head))
        self.assertEqual(update.git(self.repo, "status", "--porcelain"), "")

    def test_same_version_reuses_verified_artifact_and_rebuilds_corruption(self):
        directory = self.run_update()
        self.assertEqual(self.run_update(), directory)
        self.assertEqual(self.builds, 1)
        next(directory.glob("*.dmg")).write_bytes(b"corrupt")
        self.assertEqual(self.run_update(), directory)
        self.assertEqual(self.builds, 2)
        self.assert_unchanged()

    def test_installation_only_changes_reuse_original_delivery_without_rewriting_provenance(self):
        directory = self.run_update()
        manifest = directory / "delivery.json"
        original_manifest = manifest.read_bytes()
        original_dmg = next(directory.glob("*.dmg")).read_bytes()
        for path in update.INSTALLATION_ONLY_PATHS:
            self.put(self.repo, path, "installation tooling fixture\n")
        self.commit(self.repo, "Fix installer and its documentation")
        update.git(self.repo, "push", "origin", update.BRANCH)
        head = update.git(self.repo, "rev-parse", "HEAD")
        release = update.read_release(self.repo)
        self.assertNotEqual(head, self.head)
        self.assertFalse(update.valid_delivery(directory, release, head))
        self.assertTrue(update.reusable_delivery(self.repo, directory, release, head))
        installed = []
        self.assertEqual(self.run_update(install=installed.append), directory)
        self.assertEqual(installed, [directory])
        self.assertEqual(self.builds, 1)
        self.assertEqual(manifest.read_bytes(), original_manifest)
        self.assertEqual(next(directory.glob("*.dmg")).read_bytes(), original_dmg)
        self.assertEqual(json.loads(manifest.read_bytes())["sourceCommit"], self.head)
        self.assertEqual(update.read_release(self.repo)["revision"], 1)
        self.assert_unchanged(head)

    def test_app_build_configuration_and_release_changes_always_rebuild(self):
        self.run_update()
        for index, path in enumerate([
            "Telegram-Mac/app/AppDelegate.swift",
            "scripts/menubar/build.sh",
            "scripts/menubar/prepare-build.py",
            "scripts/menubar/package-build.py",
            "scripts/menubar/build-stage.py",
            "scripts/menubar/make-icon.swift",
            "configurations/Stable.xcconfig",
            "packages/ApiCredentials/Sources/ApiCredentials/Config.swift",
            "menubar/release.json",
        ], start=1):
            with self.subTest(path=path):
                previous_release = update.read_release(self.repo)
                previous = update.delivery_path(self.repo, previous_release)
                if path == "menubar/release.json":
                    value = (self.repo / path).read_text() + "\n"
                else:
                    value = "changed build or application fixture\n"
                self.put(self.repo, path, value)
                self.commit(self.repo, "Change application or build input")
                update.git(self.repo, "push", "origin", update.BRANCH)
                head = update.git(self.repo, "rev-parse", "HEAD")
                self.assertFalse(update.reusable_delivery(self.repo, previous, previous_release, head))
                directory = self.run_update()
                self.assertEqual(self.builds, index + 1)
                self.assertNotEqual(directory, previous)
                self.assertTrue(update.valid_delivery(directory, update.read_release(self.repo), update.git(self.repo, "rev-parse", "HEAD")))

    def test_reuse_allowlist_matches_exact_paths(self):
        directory = self.run_update()
        for path in [" README.md", "scripts/menubar/test_prepare_build.py", "scripts/menubar/README.md"]:
            self.put(self.repo, path, "outside explicit allowlist\n")
        self.commit(self.repo, "Change paths outside installer allowlist")
        self.assertFalse(update.reusable_delivery(self.repo, directory, update.read_release(self.repo), update.git(self.repo, "rev-parse", "HEAD")))

    def test_nonancestor_source_is_not_reused_even_with_valid_hashes(self):
        directory = self.run_update()
        self.put(self.seed, "README.md", "different branch documentation\n")
        self.commit(self.seed, "Independent source")
        unrelated = update.git(self.seed, "rev-parse", "HEAD")
        update.git(self.repo, "fetch", str(self.seed), "HEAD")
        manifest = json.loads((directory / "delivery.json").read_text())
        manifest["sourceCommit"] = unrelated
        update.write_json(directory / "delivery.json", manifest)
        release = update.read_release(self.repo)
        self.assertTrue(update.valid_delivery(directory, release, unrelated))
        self.assertFalse(update.reusable_delivery(self.repo, directory, release, self.head))
        replacement = self.run_update()
        self.assertEqual(self.builds, 2)
        self.assertNotEqual(directory, replacement)
        self.assertTrue(update.valid_delivery(replacement, update.read_release(self.repo), update.git(self.repo, "rev-parse", "HEAD")))

    def test_installation_only_changes_do_not_allow_reusing_corrupt_artifact(self):
        directory = self.run_update()
        self.put(self.repo, "scripts/menubar/install.py", "installer correction\n")
        self.commit(self.repo, "Fix installer")
        update.git(self.repo, "push", "origin", update.BRANCH)
        next(directory.glob("*.dmg")).write_bytes(b"corrupt artifact")
        self.assertFalse(update.reusable_delivery(self.repo, directory, update.read_release(self.repo), update.git(self.repo, "rev-parse", "HEAD")))
        replacement = self.run_update()
        self.assertEqual(self.builds, 2)
        self.assertTrue(update.valid_delivery(replacement, update.read_release(self.repo), update.git(self.repo, "rev-parse", "HEAD")))

    def test_invalid_delivery_json_is_rebuilt(self):
        directory = self.run_update()
        for value in ["[]", "null", "{invalid-json"]:
            (directory / "delivery.json").write_text(value)
            self.assertEqual(self.run_update(), directory)
        manifest = json.loads((directory / "delivery.json").read_text())
        for artifacts in [None, {}, [None], [{"name": 1, "sha256": "a" * 64}], [{"name": "app-arm64.dmg", "sha256": None}]]:
            (directory / "delivery.json").write_text(json.dumps(dict(manifest, artifacts=artifacts)))
            self.assertEqual(self.run_update(), directory)
        self.assertEqual(self.builds, 9)
        self.assert_unchanged()

    def test_installation_is_locked_and_retry_does_not_rebuild(self):
        attempts = []
        def install(directory):
            self.assertTrue((self.repo / ".git/menubar-updates/lock").is_dir())
            attempts.append(directory)
            if len(attempts) == 1:
                raise RuntimeError("installation failed")
        with self.assertRaisesRegex(RuntimeError, "installation failed"):
            self.run_update(install=install)
        self.run_update(install=install)
        self.assertEqual(self.builds, 1)
        self.assertEqual(len(attempts), 2)
        self.assertFalse((self.repo / ".git/menubar-updates/lock").exists())

    def test_pending_validation_resumes_older_delivery_before_discovering_new_release(self):
        directory = self.run_update()
        attempts = []
        def install(prepared):
            self.assertTrue((self.repo / ".git/menubar-updates/lock").is_dir())
            attempts.append(prepared)
        def discovery():
            self.fail("Pending validation must resume before release discovery")
        result = update.run_update(self.repo, latest=discovery, build=self.build, install=install,
                                   origin=str(self.remote), upstream=str(self.upstream), prepared=directory, log=lambda message: None)
        self.assertEqual(result, directory)
        self.assertEqual(attempts, [directory])
        self.assertEqual(self.builds, 1)

    def test_revision_changes_only_for_new_customizations(self):
        first = self.run_update()
        self.put(self.repo, "another-change", "extra")
        self.commit(self.repo, "Improve fork")
        update.git(self.repo, "push", "origin", update.BRANCH)
        second = self.run_update()
        self.assertNotEqual(first, second)
        self.assertEqual(update.read_release(self.repo)["revision"], 2)

    def test_conflict_and_build_failure_preserve_validated_branches(self):
        self.put(self.repo, "common.txt", "fork change\n")
        self.commit(self.repo, "Change shared line")
        update.git(self.repo, "push", "origin", update.BRANCH)
        head = update.git(self.repo, "rev-parse", "HEAD")
        self.publish(conflict=True)
        with self.assertRaisesRegex(RuntimeError, "Diagnostic conservé"):
            self.run_update()
        self.assert_unchanged(head)
        self.assertEqual(self.builds, 0)

    def test_same_marketing_version_with_new_build_gets_new_fork_revision(self):
        first = self.run_update()
        update.git(self.seed, "switch", "-c", "release")
        self.version(self.seed, "1.0.0", "101")
        self.commit(self.seed, "Rebuild stable version")
        update.git(self.seed, "switch", "master")
        update.git(self.seed, "merge", "--no-ff", "release", "-m", "Merge branch 'release' into master (1.0)")
        update.git(self.seed, "push", str(self.upstream), "master")
        self.target = {"version": "1.0.0", "build": "101"}
        second = self.run_update()
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertEqual(update.read_release(self.repo)["revision"], 2)

    def test_stable_source_resolves_marketing_version_from_historical_project(self):
        update.git(self.seed, "switch", "-c", "release")
        self.version(self.seed, "$(MARKETING_VERSION)", "110")
        self.put(self.seed, "Telegram.xcodeproj/project.pbxproj", "MARKETING_VERSION = 1.1.0;\nMARKETING_VERSION = 1.1.0;\n")
        self.commit(self.seed, "Publish version through Xcode settings")
        update.git(self.seed, "switch", "master")
        update.git(self.seed, "merge", "--no-ff", "release", "-m", "Merge branch 'release' into master (1.1)")
        update.git(self.seed, "push", str(self.upstream), "master")
        self.target = {"version": "1.1.0", "build": "110"}
        self.run_update()
        self.assertEqual(update.read_release(self.repo)["upstreamCommit"], update.git(self.seed, "rev-parse", "HEAD"))

    def test_unknown_stable_mapping_and_downgrade_stop_before_build(self):
        self.publish(ordinary=True)
        with self.assertRaisesRegex(RuntimeError, "unique commit officiel"):
            self.run_update()
        self.assert_unchanged()
        self.target = {"version": "0.9.0", "build": "90"}
        with self.assertRaisesRegex(RuntimeError, "Retour en arrière"):
            self.run_update()
        self.assertEqual(self.builds, 0)

    def test_build_failure_or_changed_candidate_prevents_publication(self):
        def failing(candidate, log):
            raise RuntimeError("compilation failed")
        with self.assertRaisesRegex(RuntimeError, "compilation failed"):
            self.run_update(build=failing)
        self.assert_unchanged()
        def mutating(candidate, log):
            self.build(candidate, log)
            self.put(candidate, "unexpected", "mutation")
        with self.assertRaisesRegex(RuntimeError, "modifié les sources"):
            self.run_update(build=mutating)
        self.assert_unchanged()

    def test_concurrent_local_or_remote_changes_are_not_overwritten(self):
        def local_change(candidate, log):
            self.build(candidate, log)
            self.put(self.repo, "concurrent", "keep")
            self.commit(self.repo, "User change during build")
        with self.assertRaisesRegex(RuntimeError, "branche a changé"):
            self.run_update(build=local_change)
        self.assertEqual(update.git(self.remote, "rev-parse", update.BRANCH), self.head)
        new_head = update.git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(new_head, self.head)

    def test_remote_change_during_build_is_preserved(self):
        def remote_change(candidate, log):
            self.build(candidate, log)
            other = self.root / "other-checkout"
            update.git(self.root, "clone", "--branch", update.BRANCH, str(self.remote), str(other))
            self.configure(other)
            self.put(other, "remote-edit", "keep remote change")
            self.commit(other, "Remote change")
            update.git(other, "push", "origin", update.BRANCH)
        with self.assertRaisesRegex(RuntimeError, "branche locale et le fork GitHub diffèrent"):
            self.run_update(build=remote_change)
        self.assertEqual(update.git(self.repo, "rev-parse", "HEAD"), self.head)
        self.assertNotEqual(update.git(self.remote, "rev-parse", update.BRANCH), self.head)

    def test_dirty_repo_and_wrong_remote_are_rejected(self):
        self.put(self.repo, "unsaved", "keep")
        with self.assertRaisesRegex(RuntimeError, "modifications non enregistrées"):
            self.run_update()
        (self.repo / "unsaved").unlink()
        update.git(self.repo, "remote", "set-url", "origin", str(self.upstream))
        with self.assertRaisesRegex(RuntimeError, "remote origin"):
            self.run_update()
        self.assertEqual(self.builds, 0)


if __name__ == "__main__":
    unittest.main()
