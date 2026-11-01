#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import plistlib
import shutil
import subprocess
import sys
import time

MACHO = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def run(*args):
    try:
        return subprocess.run(list(map(str, args)), check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{args[0]} a échoué : {error.stderr.strip()[-6000:]}") from None


def digest(filename):
    hash_value = hashlib.sha256()
    with filename.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(block)
    return hash_value.hexdigest()


def finish(root, app, output):
    private = root / ".menubar-build"
    metadata = json.loads((private / "build.json").read_text())
    if not app.is_dir() or app.is_symlink() or (app / "Contents/PlugIns").exists():
        raise ValueError("Bundle personnel absent, lié ou contenant une extension non prise en charge")
    info_path = app / "Contents/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    expected = {
        "CFBundleIdentifier": "fr.oby.telegram-menubar",
        "CFBundleExecutable": "Telegram",
        "CFBundleShortVersionString": metadata["version"],
        "CFBundleVersion": str(metadata["build"]),
        "PersonalMenuBar": True,
        "PersonalMenuBarSourceCommit": metadata["sourceCommit"],
        "PersonalMenuBarRevision": metadata["revision"],
    }
    if any(info.get(key) != value for key, value in expected.items()):
        raise ValueError("Le bundle compilé ne correspond pas à la variante personnelle épinglée")
    if info.get("SUFeedURL") or info.get("SUEnableAutomaticChecks") is not False or info.get("SUAutomaticallyUpdate") is not False:
        raise ValueError("Les mises à jour officielles ne sont pas désactivées dans le bundle")
    if run("/usr/bin/lipo", "-archs", app / "Contents/MacOS/Telegram") != "arm64":
        raise ValueError("L’exécutable livré n’est pas exclusivement arm64")
    resources = app / "Contents/Resources"
    shutil.copy2(private / "menubar-config.json", resources / "menubar-config.json")
    iconset = private / "PersonalMenuBar.iconset"
    run("/usr/bin/xcrun", "swift", root / "scripts/menubar/make-icon.swift", iconset)
    run("/usr/bin/iconutil", "-c", "icns", iconset, "-o", resources / "PersonalMenuBar.icns")
    for key in ("CFBundleIconName", "CFBundleIcons"):
        info.pop(key, None)
    info["CFBundleIconFile"] = "PersonalMenuBar.icns"
    info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
    entries = list(app.rglob("*"))
    for entry in entries:
        if not entry.is_file() or entry.is_symlink():
            continue
        with entry.open("rb") as stream:
            magic = stream.read(4)
        if magic in MACHO:
            run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", entry)
    for entry in sorted(entries, key=lambda item: len(item.parts), reverse=True):
        if entry.is_dir() and not entry.is_symlink() and entry.suffix in (".framework", ".app", ".xpc", ".appex"):
            run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", entry)
    run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", "--entitlements", private / "personal.entitlements", app)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
    disk = private / "disk-image"
    disk.mkdir()
    shutil.copytree(app, disk / "Telegram Menu Bar.app", symlinks=True)
    (disk / "Applications").symlink_to("/Applications")
    name = f"Telegram-Menu-Bar-{metadata['version']}-r{metadata['revision']}-arm64.dmg"
    dmg = private / name
    run("/usr/bin/hdiutil", "create", "-volname", "Telegram Menu Bar", "-srcfolder", disk, "-fs", "HFS+", "-format", "UDZO", dmg)
    run("/usr/bin/hdiutil", "verify", dmg)
    prepared = output.with_name(output.name + f".preparation-{time.time_ns()}")
    prepared.mkdir(parents=True)
    shutil.copy2(dmg, prepared / name)
    checksum = digest(prepared / name)
    delivery = {**metadata, "platform": "darwin", "architecture": "arm64", "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "artifacts": [{"name": name, "sha256": checksum}]}
    (prepared / "delivery.json").write_text(json.dumps(delivery, indent=4) + "\n")
    (prepared / "SHA256SUMS").write_text(f"{checksum}  {name}\n")
    if output.exists():
        output.rename(output.with_name(output.name + f".previous-{time.time_ns()}"))
    prepared.rename(output)
    print(f"DMG personnel signé et vérifié : {output / name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--app", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        finish(args.root, args.app, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Livraison interrompue : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
