#!/usr/bin/env python3
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

BRANCH = "codex/macos-menubar"
ORIGIN = "https://github.com/o-Oby/telegram-menubar.git"
UPSTREAM = "https://github.com/TelegramMessenger/telegram-macos.git"
FEED = "https://mac-updates.telegram.org/updates/versions.xml"
INSTALLATION_ONLY_PATHS = frozenset({
    "scripts/menubar/install.py",
    "scripts/menubar/update.py",
    "scripts/menubar/test_install.py",
    "scripts/menubar/test_update.py",
    "README.md",
    "menubar/README.fr.md",
    "Mettre à jour Telegram Menu Bar.command",
    "scripts/menubar/initialize_profile.py",
    "scripts/menubar/test_initialize_profile.py",
    "scripts/menubar/profile-initializer/LICENSE",
    "scripts/menubar/profile-initializer/README.md",
    "scripts/menubar/profile-initializer/main.m",
    "scripts/menubar/profile-initializer/provenance.json",
    "scripts/menubar/profile-initializer/vendor/BuildConfig.m",
    "scripts/menubar/profile-initializer/vendor/Crypto.m",
    "scripts/menubar/profile-initializer/vendor/MurMurHash32.m",
    "scripts/menubar/profile-initializer/vendor/include/BuildConfig/BuildConfig.h",
    "scripts/menubar/profile-initializer/vendor/include/CryptoUtils/Crypto.h",
    "scripts/menubar/profile-initializer/vendor/include/MurMurHash32/MurMurHash32.h",
})


def git(repository, *args):
    result = subprocess.run(["git", "-C", str(repository), *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} : {result.stderr.strip()}")
    return result.stdout.strip()


def write_json(filename, value):
    filename.write_text(json.dumps(value, indent=4, ensure_ascii=False) + "\n")


def digest(filename):
    result = hashlib.sha256()
    with filename.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def version_tuple(version):
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Version stable non reconnue.")
    return tuple(map(int, version.split(".")))


def read_release(repository):
    release = json.loads((repository / "menubar/release.json").read_text())
    version_tuple(release["version"])
    if not re.fullmatch(r"[0-9]+", release["build"]):
        raise RuntimeError("Numéro de compilation invalide.")
    if not re.fullmatch(r"[a-f0-9]{40}", release["upstreamCommit"]):
        raise RuntimeError("Commit officiel invalide.")
    if type(release["revision"]) is not int or release["revision"] < 1:
        raise RuntimeError("Révision du fork invalide.")
    return release


def latest_stable():
    request = urllib.request.Request(FEED, headers={"User-Agent": "Telegram-Menu-Bar-Updater"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise RuntimeError("Le flux de versions est trop volumineux.")
    namespace = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
    releases = []
    for item in ET.fromstring(payload).findall("./channel/item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        version = enclosure.get(namespace + "shortVersionString")
        build = enclosure.get(namespace + "version")
        if version and build and re.fullmatch(r"\d+\.\d+\.\d+", version) and re.fullmatch(r"\d+", build):
            releases.append({"version": version, "build": build})
    if not releases:
        raise RuntimeError("Le flux officiel ne contient aucune version stable reconnue.")
    return max(releases, key=lambda release: (version_tuple(release["version"]), int(release["build"])))


def normalized_remote(url):
    return re.sub(r"\.git$", "", url.replace("git@github.com:", "https://github.com/").rstrip("/"))


def check_remote(repository, name, expected):
    for direction in ([[], ["--push"]] if name == "origin" else [[]]):
        value = git(repository, "remote", "get-url", *direction, "--all", name)
        if normalized_remote(value) != normalized_remote(expected):
            raise RuntimeError(f"Le remote {name} ne correspond pas au dépôt attendu.")


def clean_head(repository, expected=None):
    if git(repository, "branch", "--show-current") != BRANCH:
        raise RuntimeError(f"Ouvrez la branche {BRANCH}.")
    if git(repository, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Le dépôt contient des modifications non enregistrées. Enregistrez-les avant la mise à jour.")
    head = git(repository, "rev-parse", "HEAD")
    if expected and head != expected:
        raise RuntimeError("La branche a changé pendant la préparation ; aucune modification locale écrasée.")
    return head


def fetch_origin(repository, head):
    git(repository, "fetch", "--no-tags", "origin", f"refs/heads/{BRANCH}")
    if git(repository, "rev-parse", "FETCH_HEAD") != head:
        raise RuntimeError("La branche locale et le fork GitHub diffèrent. Synchronisez-les avant de continuer.")


def release_source(repository, target):
    git(repository, "fetch", "--no-tags", "upstream", "refs/heads/master")
    entries = git(repository, "log", "--first-parent", "--format=%H%x09%s", "FETCH_HEAD").splitlines()
    matches = []
    for entry in entries:
        commit, subject = entry.split("\t", 1)
        if not re.fullmatch(r"Merge branch 'release' into master \([0-9.]+\)", subject):
            continue
        versions = []
        project_versions = None
        for filename in ["Telegram-Mac/Info.plist", "TelegramShare/Info.plist"]:
            info = plistlib.loads(git(repository, "show", f"{commit}:{filename}").encode())
            version = str(info.get("CFBundleShortVersionString"))
            if version == "$(MARKETING_VERSION)":
                if project_versions is None:
                    project = git(repository, "show", f"{commit}:Telegram.xcodeproj/project.pbxproj")
                    project_versions = set(re.findall(r'^\s*MARKETING_VERSION = "?([0-9.]+)"?;', project, re.M))
                if len(project_versions) != 1:
                    continue
                version = next(iter(project_versions))
            versions.append((version, str(info.get("CFBundleVersion"))))
        if versions == [(target["version"], target["build"])] * 2:
            matches.append(commit)
    if len(matches) != 1:
        raise RuntimeError(
            f"La version {target['version']} ({target['build']}) n’a pas un unique commit officiel de publication identifiable. "
            "Une vérification de la correspondance version/source est nécessaire ; master n’est pas assimilé à une version stable."
        )
    return matches[0]


def valid_delivery(directory, release, head):
    try:
        delivery = json.loads((directory / "delivery.json").read_text())
        if not isinstance(delivery, dict):
            return False
        if any(delivery.get(key) != value for key, value in release.items()) or delivery.get("sourceCommit") != head:
            return False
        artifacts = delivery["artifacts"]
        if not isinstance(artifacts, list) or not artifacts:
            return False
        if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("sha256"), str) for item in artifacts):
            return False
        names = [item["name"] for item in artifacts]
        if len(names) != len(set(names)) or sum(name.endswith("-arm64.dmg") for name in names) != 1:
            return False
        return all(
            Path(item["name"]).name == item["name"] and
            re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) and
            not (directory / item["name"]).is_symlink() and
            (directory / item["name"]).is_file() and
            digest(directory / item["name"]) == item["sha256"]
            for item in artifacts
        )
    except (OSError, ValueError, TypeError, KeyError):
        return False


def reusable_delivery(repository, directory, release, head):
    try:
        delivery = json.loads((directory / "delivery.json").read_text())
        if not isinstance(delivery, dict):
            return False
        source = delivery.get("sourceCommit")
        if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{40}", source):
            return False
        if not valid_delivery(directory, release, source):
            return False
        git(repository, "merge-base", "--is-ancestor", source, head)
        paths = subprocess.check_output(["git", "-C", str(repository), "diff", "--no-renames", "--name-only", "-z", source, head, "--"], text=True).split("\0")
        return all(path in INSTALLATION_ONLY_PATHS for path in paths if path)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        return False


def delivery_path(repository, release):
    return repository / "dist/menubar" / f"v{release['version']}-r{release['revision']}"


def build_candidate(candidate, log_file):
    with log_file.open("a") as log:
        process = subprocess.Popen(["bash", "scripts/menubar/build.sh"], cwd=candidate, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        if process.wait():
            raise RuntimeError(f"La construction a échoué. Journal : {log_file}")


def run_update(repository, latest=latest_stable, build=build_candidate, install=None, origin=ORIGIN, upstream=UPSTREAM, log=print, prepared=None):
    repository = Path(repository).resolve()
    if Path(git(repository, "rev-parse", "--show-toplevel")).resolve() != repository:
        raise RuntimeError("Le script doit être lancé à la racine du fork.")
    state = (repository / git(repository, "rev-parse", "--git-common-dir")).resolve() / "menubar-updates"
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise RuntimeError(f"Une mise à jour est déjà en cours. En cas d’interruption, consultez {lock}.") from error
    run_dir = None
    try:
        write_json(lock / "owner.json", {"pid": os.getpid(), "started": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        head = clean_head(repository)
        check_remote(repository, "origin", origin)
        check_remote(repository, "upstream", upstream)
        fetch_origin(repository, head)
        if prepared is not None:
            prepared = Path(prepared).resolve()
            if repository / "dist/menubar" not in prepared.parents:
                raise RuntimeError("La livraison à reprendre doit se trouver dans le dossier dist/menubar du fork.")
            manifest = json.loads((prepared / "delivery.json").read_text())
            if not isinstance(manifest, dict):
                raise RuntimeError("Le manifeste à reprendre est invalide.")
            release = {key: manifest[key] for key in ["version", "build", "revision", "upstreamCommit"]}
            source = manifest["sourceCommit"]
            if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{40}", source) or not valid_delivery(prepared, release, source):
                raise RuntimeError("La livraison à reprendre n’est plus valide.")
            git(repository, "merge-base", "--is-ancestor", source, head)
            log("Reprise de la livraison déjà préparée avant de rechercher une nouvelle version…")
            if install:
                install(prepared)
            return prepared
        current = read_release(repository)
        log("Recherche de la dernière version stable native de Telegram…")
        target = latest()
        target_version = version_tuple(target["version"])
        if not re.fullmatch(r"\d+", target["build"]):
            raise RuntimeError("Numéro de compilation officiel non reconnu.")
        if (target_version, int(target["build"])) < (version_tuple(current["version"]), int(current["build"])):
            raise RuntimeError("Retour en arrière automatique refusé.")
        same_version = all(target[key] == current[key] for key in ["version", "build"])
        destination = delivery_path(repository, current)
        if same_version and reusable_delivery(repository, destination, current, head):
            log("La livraison courante est déjà construite et vérifiée.")
            if install:
                install(destination)
            return destination
        identifier = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + f"-{os.getpid()}"
        run_dir = state / identifier
        run_dir.mkdir()
        root = Path(tempfile.mkdtemp(prefix="telegram-menubar-update-"))
        candidate = root / "worktree"
        candidate_branch = f"codex/menubar-update/{identifier}"
        write_json(run_dir / "preparation.json", {"candidate": str(candidate), "branch": candidate_branch, "base": head, "target": target})
        log_file = run_dir / "build.log"
        log_file.write_text(f"Source initiale : {head}\nPréparation : {candidate}\n")
        git(repository, "worktree", "add", "-b", candidate_branch, str(candidate), head)
        next_release = dict(current)
        if not same_version:
            commit = release_source(candidate, target)
            git(candidate, "merge", "--no-ff", "--no-edit", commit)
            next_release.update(target, upstreamCommit=commit, revision=1 if target["version"] != current["version"] else current["revision"] + 1)
        elif (destination / "delivery.json").exists():
            try:
                previous = json.loads((destination / "delivery.json").read_text())
            except (OSError, ValueError):
                previous = {}
            if isinstance(previous, dict) and previous.get("sourceCommit", head) != head:
                next_release["revision"] += 1
        if next_release != current:
            write_json(candidate / "menubar/release.json", next_release)
            git(candidate, "add", "menubar/release.json")
            git(candidate, "commit", "-m", f"Prepare menu bar {target['version']} revision {next_release['revision']}")
        candidate_head = git(candidate, "rev-parse", "HEAD")
        log(f"Construction et tests dans {candidate}…")
        build(candidate, log_file)
        if git(candidate, "rev-parse", "HEAD") != candidate_head or git(candidate, "status", "--porcelain", "--untracked-files=normal"):
            raise RuntimeError("La construction a modifié les sources préparées. Publication annulée.")
        built = candidate / "dist/menubar/current"
        if not valid_delivery(built, next_release, candidate_head):
            raise RuntimeError("Livraison absente, invalide ou différente des sources construites.")
        destination = delivery_path(repository, next_release)
        staging = destination.parent / f".preparation-{identifier}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(built, staging, symlinks=True)
        if not valid_delivery(staging, next_release, candidate_head):
            raise RuntimeError("La copie de la livraison ne correspond pas à la construction.")
        clean_head(repository, head)
        check_remote(repository, "origin", origin)
        fetch_origin(repository, head)
        git(repository, "push", "origin", f"{candidate_head}:refs/heads/{BRANCH}")
        clean_head(repository, head)
        git(repository, "merge", "--ff-only", candidate_head)
        if destination.exists():
            destination.rename(destination.with_name(destination.name + "-previous-" + identifier))
        staging.rename(destination)
        write_json(run_dir / "delivery.json", {"directory": str(destination), "sourceCommit": candidate_head})
        git(repository, "worktree", "remove", str(candidate))
        root.rmdir()
        git(repository, "branch", "-d", candidate_branch)
        log(f"Livraison validée : {destination}")
        if install:
            try:
                install(destination)
            except Exception as error:
                raise RuntimeError(f"{error}\nLe DMG validé reste disponible ; relancez le script pour reprendre l’installation.") from error
        return destination
    except Exception as error:
        if run_dir:
            try:
                with (run_dir / "build.log").open("a") as stream:
                    stream.write(f"\nÉCHEC : {error}\n")
            except OSError:
                pass
            raise RuntimeError(f"{error}\nDiagnostic conservé : {run_dir}") from error
        raise
    finally:
        shutil.rmtree(lock)


def main():
    repository = Path(__file__).resolve().parents[2]
    check = subprocess.run(["bash", "scripts/menubar/build.sh", "--check"], cwd=repository)
    if check.returncode:
        return check.returncode
    from install import install_on_mac
    prepare_only = "--prepare-only" in sys.argv
    fresh = "--migrate-profile" not in sys.argv
    receipt_path = Path.home() / "Library/Application Support/Telegram Menu Bar/installation-state.json"
    pending = None
    if not prepare_only and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if isinstance(receipt, dict) and receipt.get("status") in ["pending-validation", "pending-fresh"]:
            pending = receipt.get("deliveryDirectory")
            fresh = receipt["status"] == "pending-fresh"
        elif isinstance(receipt, dict) and receipt.get("status") == "validated" and (receipt.get("launchPending") or receipt.get("previousApplication")):
            pending = str(repository / "dist/menubar" / f"v{receipt['version']}-r{receipt['revision']}")
    installer = None if prepare_only else lambda directory: install_on_mac(directory, fresh=fresh)
    destination = run_update(repository, install=installer, prepared=pending)
    subprocess.run(["/usr/bin/open", str(destination)], check=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"\nMise à jour interrompue : {error}", file=sys.stderr)
        sys.exit(1)
