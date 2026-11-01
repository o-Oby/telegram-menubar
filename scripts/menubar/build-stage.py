#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


def git(repository, *arguments):
    result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"Git a refusé la préparation du stage : {result.stderr.strip()}")
    return result.stdout.strip()


def common_directory(repository):
    return (repository / git(repository, "rev-parse", "--git-common-dir")).resolve()


def private_build_root(root):
    if root.parent != Path("/private/tmp") or not re.fullmatch(r"telegram-menubar-build\.[A-Za-z0-9_-]+", root.name):
        raise ValueError("Le stage à reprendre doit être un dossier /private/tmp/telegram-menubar-build.*")
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Le stage doit être un vrai dossier privé de votre compte, avec les permissions 700")
    if root.resolve() != root:
        raise ValueError("Le chemin du stage ne doit pas contenir de lien symbolique")


def require_inside(directory, root):
    if directory.is_symlink() or not directory.is_dir() or root not in directory.resolve().parents:
        raise ValueError(f"Dossier de sources absent, lié ou hors du stage : {directory}")
    if Path(git(directory, "rev-parse", "--show-toplevel")).resolve() != directory.resolve():
        raise ValueError(f"Dossier Git inattendu dans le stage : {directory}")


def initialized_submodules(repository, root):
    result = subprocess.run(["git", "-C", str(repository), "ls-files", "--stage", "-z"], check=True, capture_output=True)
    modules = []
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        mode_and_object, relative = entry.split(b"\t", 1)
        if mode_and_object.split()[0] != b"160000":
            continue
        directory = repository / os.fsdecode(relative)
        if directory.is_symlink():
            raise ValueError(f"Sous-module lié refusé : {directory}")
        if not (directory / ".git").exists():
            continue
        require_inside(directory, root)
        modules.extend(initialized_submodules(directory, root))
        modules.append(directory)
    return modules


def validate_resume(root, repository, source_commit):
    private_build_root(root)
    source = root / "source"
    require_inside(source, root)
    if common_directory(source) != common_directory(repository):
        raise ValueError("Le stage appartient à un autre dépôt Git")
    if git(source, "branch", "--show-current"):
        raise ValueError("Le stage doit être un worktree détaché, sans branche utilisateur")
    previous_commit = git(source, "rev-parse", "HEAD")
    ancestor = subprocess.run(["git", "-C", str(repository), "merge-base", "--is-ancestor", previous_commit, source_commit], capture_output=True)
    if ancestor.returncode:
        raise ValueError("Le commit du stage n’est pas un ancêtre du commit à construire")
    private = source / ".menubar-build"
    if private.is_symlink() or (private.exists() and (not private.is_dir() or private.stat().st_uid != os.getuid())):
        raise ValueError("La configuration privée du stage a un type ou un propriétaire inattendu")
    modules = initialized_submodules(source, root)
    common = common_directory(repository)
    if any(common not in common_directory(module).parents for module in modules):
        raise ValueError("Les métadonnées d’un sous-module sont hors du dépôt attendu")
    receipt = root / "build-stage.json"
    if receipt.is_symlink() or (receipt.exists() and (not receipt.is_file() or receipt.stat().st_uid != os.getuid())):
        raise ValueError("Le reçu du stage a un type ou un propriétaire inattendu")
    return source, modules


def prepare_stage(repository, source_commit, resume=None):
    repository = repository.resolve()
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit) or git(repository, "rev-parse", "HEAD") != source_commit:
        raise ValueError("Le commit à construire diffère du dépôt source")
    if resume is not None:
        root = Path(resume)
        source, modules = validate_resume(root, repository, source_commit)
        git(source, "reset", "--hard", source_commit)
        for module in modules:
            git(module, "reset", "--hard", "HEAD")
        private = source / ".menubar-build"
        if private.exists():
            shutil.rmtree(private)
    else:
        root = Path(tempfile.mkdtemp(prefix="telegram-menubar-build.", dir="/private/tmp"))
        root.chmod(0o700)
        source = root / "source"
        try:
            git(repository, "worktree", "add", "--detach", str(source), source_commit)
        except Exception as error:
            raise ValueError(f"{error}. Dossier conservé : {root}") from error
    receipt = root / "build-stage.json"
    receipt.write_text(json.dumps({"schema": 1, "gitCommonDirectory": str(common_directory(repository)), "sourceCommit": source_commit}, indent=4) + "\n")
    receipt.chmod(0o600)
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    try:
        print(prepare_stage(args.repository, args.source_commit, args.resume))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Préparation du stage interrompue : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
