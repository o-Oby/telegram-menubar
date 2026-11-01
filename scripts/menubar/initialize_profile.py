import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile

SOURCE_ROOT = Path(__file__).resolve().parent / "profile-initializer"
VENDORED_FILES = {
    "vendor/BuildConfig.m", "vendor/Crypto.m", "vendor/MurMurHash32.m",
    "vendor/include/BuildConfig/BuildConfig.h", "vendor/include/CryptoUtils/Crypto.h",
    "vendor/include/MurMurHash32/MurMurHash32.h",
}


def real_path(path):
    for entry in [path, *path.parents]:
        if entry.is_symlink():
            raise RuntimeError(f"Chemin symbolique refusé : {entry}")


def validate_destination(destination):
    destination = Path(os.path.abspath(destination))
    real_path(destination)
    if os.path.lexists(destination):
        raise RuntimeError("Le profil de destination existe déjà ; il est conservé.")
    if not destination.parent.is_dir():
        raise RuntimeError("Le dossier parent de la destination doit déjà exister.")
    return destination


def verify_sources(root=SOURCE_ROOT):
    real_path(root)
    manifest_path = root / "provenance.json"
    real_path(manifest_path)
    try:
        provenance = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError("Provenance de l’initialisateur natif absente ou invalide.") from error
    if not isinstance(provenance, dict) or provenance.get("schema") != 1 or not isinstance(provenance.get("files"), list):
        raise RuntimeError("Provenance de l’initialisateur natif invalide.")
    entries = provenance["files"]
    if len(entries) != len(VENDORED_FILES) or any(not isinstance(entry, dict) for entry in entries) or {entry.get("file") for entry in entries} != VENDORED_FILES:
        raise RuntimeError("Liste des sources natives épinglées invalide.")
    for entry in entries:
        path = root / entry["file"]
        real_path(path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
            raise RuntimeError(f"Source native différente de sa provenance : {entry['file']}")
    real_path(root / "main.m")
    return root


def run(command):
    process = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=120)
    if process.returncode:
        raise RuntimeError(f"Initialisation native interrompue : {process.stderr.strip()[-3000:]}")
    return process.stdout.strip()


def compile_initializer(executable, source_root=SOURCE_ROOT):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("L’initialisateur natif exige macOS sur Apple Silicon.")
    root = verify_sources(source_root)
    compiler = run(["/usr/bin/xcrun", "--sdk", "macosx", "--find", "clang"])
    sdk = run(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"])
    run([
        compiler, "-arch", "arm64", "-isysroot", sdk, "-mmacosx-version-min=13.0", "-fobjc-arc", "-fblocks",
        "-O2", "-Wno-deprecated-declarations", "-I", root / "vendor/include",
        root / "main.m", root / "vendor/BuildConfig.m", root / "vendor/Crypto.m", root / "vendor/MurMurHash32.m",
        "-framework", "Foundation", "-framework", "AppKit", "-framework", "Security", "-o", executable,
    ])
    os.chmod(executable, 0o700)
    return Path(executable)


def verify_new_profile(destination):
    real_path(destination)
    expected = {"accounts-metadata", ".tempkeyEncrypted"}
    if {entry.name for entry in destination.iterdir()} != expected:
        raise RuntimeError("Le profil neuf contient des éléments inattendus ; il est conservé pour vérification.")
    for directory in [destination, destination / "accounts-metadata"]:
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RuntimeError("Un dossier du profil neuf n’est pas privé et réel.")
    if any((destination / "accounts-metadata").iterdir()):
        raise RuntimeError("Les métadonnées du nouveau compte doivent être vides.")
    key = destination / ".tempkeyEncrypted"
    metadata = key.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 64 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("La clé native neuve n’est pas un fichier régulier privé de 64 octets.")


def initialize_profile(destination):
    destination = validate_destination(destination)
    with tempfile.TemporaryDirectory(prefix="telegram-menubar-profile-tool-") as workspace:
        executable = compile_initializer(Path(workspace) / "initialize-profile")
        if run([executable, destination]) != "PROFILE_INITIALIZED":
            raise RuntimeError("L’initialisateur natif n’a pas confirmé la création du profil.")
    verify_new_profile(destination)


def main():
    parser = argparse.ArgumentParser(description="Créer un profil Telegram Menu Bar neuf, sans importer de session.")
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    try:
        initialize_profile(arguments.destination)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Profil neuf initialisé et vérifié ; aucune session importée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
