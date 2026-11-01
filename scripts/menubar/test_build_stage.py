import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

specification = importlib.util.spec_from_file_location("build_stage", Path(__file__).with_name("build-stage.py"))
stage = importlib.util.module_from_spec(specification)
specification.loader.exec_module(stage)


class BuildStageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="menubar-stage-test-", dir="/private/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repository = self.base / "repository"
        self.repository.mkdir()
        self.initialize(self.repository)
        (self.repository / ".gitignore").write_text("cache/\n.menubar-build/\n")
        (self.repository / "source.txt").write_text("old source\n")
        self.commit(self.repository, "Initial fixture")
        self.old_head = stage.git(self.repository, "rev-parse", "HEAD")
        self.roots = []
        self.addCleanup(self.clean_stages)

    def initialize(self, directory):
        stage.git(directory, "init", "-b", "main")
        stage.git(directory, "config", "user.name", "Stage fixture")
        stage.git(directory, "config", "user.email", "fixture@example.invalid")

    def commit(self, directory, message):
        stage.git(directory, "add", ".")
        stage.git(directory, "commit", "-m", message)

    def clean_stages(self):
        for root in self.roots:
            subprocess.run(["git", "-C", str(self.repository), "worktree", "remove", "--force", str(root / "source")], capture_output=True)
            shutil.rmtree(root, ignore_errors=True)
        subprocess.run(["git", "-C", str(self.repository), "worktree", "prune"], capture_output=True)

    def new_stage(self):
        root = stage.prepare_stage(self.repository, stage.git(self.repository, "rev-parse", "HEAD"))
        self.roots.append(root)
        return root

    def test_new_stage_is_private_detached_and_shares_repository(self):
        root = self.new_stage()
        self.assertEqual(root.parent, Path("/private/tmp"))
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((root / "build-stage.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(stage.git(root / "source", "branch", "--show-current"), "")
        self.assertEqual(stage.common_directory(root / "source"), stage.common_directory(self.repository))

    def test_resume_restores_sources_and_submodules_preserving_ignored_caches(self):
        library = self.base / "library"
        library.mkdir()
        self.initialize(library)
        (library / ".gitignore").write_text("cache/\n")
        (library / "library.txt").write_text("original library\n")
        self.commit(library, "Library fixture")
        stage.git(self.repository, "-c", "protocol.file.allow=always", "submodule", "add", str(library), "submodules/library")
        self.commit(self.repository, "Add library")
        root = self.new_stage()
        source = root / "source"
        stage.git(source, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--recursive")
        module = source / "submodules/library"
        (module / "library.txt").write_text("compatibility patch\n")
        (source / "source.txt").write_text("personal build patch\n")
        for cache in [source / "cache", module / "cache", root / "DerivedData"]:
            cache.mkdir()
            (cache / "output").write_text("reuse only after stamp validation")
        private = source / ".menubar-build"
        private.mkdir(mode=0o700)
        (private / "menubar-config.json").write_text("private configuration fixture")
        (source / "preserved-diagnostic.txt").write_text("keep untracked diagnostic")
        (self.repository / "source.txt").write_text("new committed source\n")
        self.commit(self.repository, "Fix build fixture")
        new_head = stage.git(self.repository, "rev-parse", "HEAD")
        self.assertEqual(stage.prepare_stage(self.repository, new_head, root), root)
        self.assertEqual(stage.git(source, "rev-parse", "HEAD"), new_head)
        self.assertEqual((source / "source.txt").read_text(), "new committed source\n")
        self.assertEqual((module / "library.txt").read_text(), "original library\n")
        self.assertFalse(private.exists())
        self.assertTrue((source / "preserved-diagnostic.txt").exists())
        for cache in [source / "cache", module / "cache", root / "DerivedData"]:
            self.assertTrue((cache / "output").exists())
        self.assertEqual(stage.git(self.repository, "status", "--porcelain"), "")

    def test_rejects_bad_paths_permissions_symlinks_and_other_repository_before_reset(self):
        root = self.new_stage()
        tracked = root / "source/source.txt"
        tracked.write_text("keep private edit")
        with self.assertRaisesRegex(ValueError, "/private/tmp"):
            stage.prepare_stage(self.repository, self.old_head, self.base)
        link = Path(tempfile.mkdtemp(prefix="telegram-menubar-build.", dir="/private/tmp"))
        link.rmdir()
        link.symlink_to(root)
        self.addCleanup(link.unlink)
        with self.assertRaisesRegex(ValueError, "vrai dossier"):
            stage.prepare_stage(self.repository, self.old_head, link)
        root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "permissions 700"):
            stage.prepare_stage(self.repository, self.old_head, root)
        root.chmod(0o700)
        other = self.base / "other"
        other.mkdir()
        self.initialize(other)
        (other / "file").write_text("other")
        self.commit(other, "Other repository")
        with self.assertRaisesRegex(ValueError, "autre dépôt"):
            stage.prepare_stage(other, stage.git(other, "rev-parse", "HEAD"), root)
        self.assertEqual(tracked.read_text(), "keep private edit")
        self.assertEqual(stage.git(root / "source", "rev-parse", "HEAD"), self.old_head)

    def test_rejects_branch_nonancestor_and_symlinked_private_config_before_reset(self):
        root = self.new_stage()
        source = root / "source"
        stage.git(source, "switch", "-c", "fixture-user-branch")
        with self.assertRaisesRegex(ValueError, "sans branche utilisateur"):
            stage.prepare_stage(self.repository, self.old_head, root)
        stage.git(source, "switch", "--detach", self.old_head)
        (source / "extra").write_text("stage-only commit")
        self.commit(source, "Unrelated stage change")
        with self.assertRaisesRegex(ValueError, "ancêtre"):
            stage.prepare_stage(self.repository, self.old_head, root)
        stage.git(source, "reset", "--hard", self.old_head)
        (source / "source.txt").write_text("must remain")
        outside = self.base / "private-outside"
        outside.mkdir()
        (outside / "keep").write_text("must remain")
        (source / ".menubar-build").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "configuration privée"):
            stage.prepare_stage(self.repository, self.old_head, root)
        self.assertEqual((outside / "keep").read_text(), "must remain")
        self.assertEqual((source / "source.txt").read_text(), "must remain")


if __name__ == "__main__":
    unittest.main()
