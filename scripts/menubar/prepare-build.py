#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import plistlib
import re
import stat
import subprocess
import sys

BUNDLE_ID = "fr.oby.telegram-menubar"
PRODUCT_NAME = "Telegram Menu Bar"
DEFAULT_CREDENTIALS = pathlib.Path.home() / "Library/Application Support/Telegram Menu Bar/build-credentials.json"


def read_credentials(filename):
    try:
        info = filename.lstat()
    except FileNotFoundError:
        raise ValueError(f"Identifiants API personnels manquants : {filename}. Renseignez api_id et api_hash obtenus sur https://my.telegram.org/apps.") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError(f"Le fichier des identifiants doit être un fichier privé de votre compte (chmod 600) : {filename}")
    try:
        data = json.loads(filename.read_text())
    except (ValueError, UnicodeError):
        raise ValueError(f"Le fichier des identifiants n’est pas un JSON valide : {filename}") from None
    if not isinstance(data, dict):
        raise ValueError(f"Objet JSON attendu pour les identifiants : {filename}")
    api_id, api_hash = data.get("api_id"), data.get("api_hash")
    if type(api_id) is not int or not 0 < api_id < 2**31 or api_id in (9, 17349):
        raise ValueError(f"Renseignez votre api_id personnel dans {filename} ; les identifiants officiels et de test ne conviennent pas.")
    if not isinstance(api_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash) or set(api_hash) == {"0"}:
        raise ValueError(f"Renseignez votre api_hash personnel de 32 caractères hexadécimaux dans {filename}.")
    return {"schema": 1, "api_id": api_id, "api_hash": api_hash.lower()}


def read_release(root):
    release = json.loads((root / "menubar/release.json").read_text())
    if not isinstance(release, dict) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", str(release.get("version", ""))):
        raise ValueError("Version officielle invalide dans menubar/release.json")
    if not re.fullmatch(r"[1-9][0-9]*", str(release.get("build", ""))):
        raise ValueError("Numéro de build officiel invalide")
    if not re.fullmatch(r"[a-f0-9]{40}", str(release.get("upstreamCommit", ""))):
        raise ValueError("Commit officiel épinglé invalide")
    if type(release.get("revision")) is not int or release["revision"] < 1:
        raise ValueError("Révision personnelle invalide")
    info = plistlib.loads((root / "Telegram-Mac/Info.plist").read_bytes())
    if str(info.get("CFBundleVersion")) != str(release["build"]):
        raise ValueError("Le build des sources ne correspond pas à la publication épinglée")
    return release


def load_project(root):
    filename = root / "Telegram.xcodeproj/project.pbxproj"
    result = subprocess.run(["/usr/bin/plutil", "-convert", "json", "-o", "-", str(filename)], check=True, capture_output=True)
    return filename.read_text(), json.loads(result.stdout)


def edit_object(text, identifier, edit):
    expression = re.compile(r"^\t\t" + re.escape(identifier) + r"(?: /\*[^\n]*?\*/)? = \{\n.*?^\t\t\};", re.M | re.S)
    result, count = expression.subn(lambda match: edit(match.group()), text)
    if count != 1:
        raise ValueError(f"Objet Xcode introuvable ou ambigu : {identifier}")
    return result


def set_build_setting(block, key, value):
    line = f"\t\t\t\t{key} = {value};"
    updated, count = re.subn(r"^\t\t\t\t" + re.escape(key) + r" = [^\n]*;", line, block, flags=re.M)
    if count > 1:
        raise ValueError(f"Réglage Xcode ambigu : {key}")
    if not count:
        marker = "\t\t\tbuildSettings = {"
        if block.count(marker) != 1:
            raise ValueError("Dictionnaire Xcode buildSettings introuvable")
        updated = block.replace(marker, marker + "\n" + line, 1)
    return updated


def prepare_project(text, project, version):
    objects = project["objects"]
    candidates = [(key, value) for key, value in objects.items() if value.get("isa") == "PBXNativeTarget" and value.get("name") == "Telegram"]
    if len(candidates) != 1:
        raise ValueError("Cible principale Telegram introuvable ou ambiguë")
    target_id, target = candidates[0]
    configurations = objects[target["buildConfigurationList"]]["buildConfigurations"]
    for identifier in configurations:
        settings = objects[identifier]["buildSettings"]
        if str(settings.get("MARKETING_VERSION")) != version:
            raise ValueError("La version marketing des sources diffère de la publication épinglée")
        replacements = {
            "PRODUCT_BUNDLE_IDENTIFIER": BUNDLE_ID,
            "PRODUCT_NAME": json.dumps(PRODUCT_NAME),
            "PRODUCT_MODULE_NAME": "Telegram",
            "EXECUTABLE_NAME": "Telegram",
            "CODE_SIGN_ENTITLEMENTS": '""',
            "CODE_SIGN_IDENTITY": '"-"',
            "DEVELOPMENT_TEAM": '""',
            "CODE_SIGN_STYLE": "Manual",
            "CODE_SIGNING_ALLOWED": "NO",
            "CODE_SIGNING_REQUIRED": "NO",
            "ENABLE_APP_SANDBOX": "NO",
            "CODE_SIGN_INJECT_BASE_ENTITLEMENTS": "NO",
            "PROVISIONING_PROFILE_SPECIFIER": '""',
        }
        def update(block):
            for key, value in replacements.items():
                block = set_build_setting(block, key, value)
            return block
        text = edit_object(text, identifier, update)
    removals = []
    for identifier in target.get("dependencies", []):
        linked = objects.get(objects[identifier].get("target"), {})
        if linked.get("name") == "TelegramShare":
            removals.append(identifier)
    for identifier in target.get("buildPhases", []):
        phase = objects[identifier]
        if phase.get("isa") == "PBXCopyFilesBuildPhase":
            products = [objects.get(objects.get(file, {}).get("fileRef"), {}).get("path") for file in phase.get("files", [])]
            if "TelegramShare.appex" in products:
                if products != ["TelegramShare.appex"]:
                    raise ValueError("La phase d’intégration des extensions contient des produits inconnus")
                removals.append(identifier)
    if len(removals) != 2:
        raise ValueError("La structure de l’extension TelegramShare a changé ; vérifiez l’adaptation personnelle")
    def unlink_share(block):
        for identifier in removals:
            block, count = re.subn(r"^\t\t\t\t" + re.escape(identifier) + r" /\*[^\n]*?\*/,\n", "", block, flags=re.M)
            if count != 1:
                raise ValueError("Impossible de détacher proprement TelegramShare")
        return block
    return edit_object(text, target_id, unlink_share)


def prepare(root, credentials, source_commit):
    root = root.resolve()
    release = read_release(root)
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise ValueError("Commit du fork invalide")
    config = read_credentials(credentials)
    if root == credentials.resolve() or root in credentials.resolve().parents:
        raise ValueError("Les identifiants personnels doivent être hors du dépôt de sources")
    original, project = load_project(root)
    updated = prepare_project(original, project, release["version"])
    framework_path = root / "scripts/configure_frameworks.sh"
    framework_text = framework_path.read_text()
    framework_marker = "-configuration Release BUILD_LIBRARY_FOR_DISTRIBUTION=YES"
    if framework_text.count(framework_marker) != 1:
        raise ValueError("La commande de compilation des bibliothèques natives a changé")
    framework_text = framework_text.replace(framework_marker, framework_marker + " MACOSX_DEPLOYMENT_TARGET=12.0 CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM=")
    marker = root / ".menubar-build"
    if marker.exists():
        raise ValueError("Cette préparation a déjà été appliquée ; utilisez une nouvelle préparation isolée")
    marker.mkdir(mode=0o700)
    output = marker / "menubar-config.json"
    output.write_text(json.dumps(config) + "\n")
    output.chmod(0o600)
    info_path = root / "Telegram-Mac/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info.update({
        "CFBundleDisplayName": PRODUCT_NAME,
        "CFBundleName": PRODUCT_NAME,
        "CFBundleIconFile": "PersonalMenuBar.icns",
        "PersonalMenuBar": True,
        "PersonalMenuBarRevision": release["revision"],
        "PersonalMenuBarSourceCommit": source_commit,
        "PersonalMenuBarUpstreamCommit": release["upstreamCommit"],
        "SUEnableAutomaticChecks": False,
        "SUAutomaticallyUpdate": False,
    })
    for key in ("SUFeedURL", "SUPublicDSAKeyFile", "SUPublicEDKey", "CFBundleIconName", "CFBundleIcons"):
        info.pop(key, None)
    info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
    (root / "Telegram.xcodeproj/project.pbxproj").write_text(updated)
    framework_path.write_text(framework_text)
    (marker / "personal.entitlements").write_bytes(plistlib.dumps({
        "com.apple.security.device.audio-input": True,
        "com.apple.security.device.camera": True,
        "com.apple.security.personal-information.location": True,
    }))
    (marker / "build.json").write_text(json.dumps({**release, "sourceCommit": source_commit, "manualUpdates": True}, indent=4) + "\n")
    return marker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--credentials", type=pathlib.Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--source-commit")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        read_credentials(args.credentials)
        root = args.root.resolve()
        if root == args.credentials.resolve() or root in args.credentials.resolve().parents:
            raise ValueError("Les identifiants personnels doivent être hors du dépôt de sources")
        release = read_release(root)
        if args.check:
            original, project = load_project(root)
            prepare_project(original, project, release["version"])
            print("Identifiants API privés et version épinglée valides. Aucune compilation ni installation effectuée.")
        else:
            print(prepare(args.root.resolve(), args.credentials, args.source_commit or ""))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Préparation interrompue : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
