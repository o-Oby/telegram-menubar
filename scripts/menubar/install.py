import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass

BUNDLE_ID = "fr.oby.telegram-menubar"
OFFICIAL_ID = "ru.keepcoder.Telegram"
APP_NAME = "Telegram Menu Bar.app"
APP_SCRIPTS_LINK = Path("Library/Application Scripts/6N38VWS5BX.ru.keepcoder.Telegram")
APP_SCRIPTS_TARGET = "../../../../Application Scripts/6N38VWS5BX.ru.keepcoder.Telegram"


@dataclass(frozen=True)
class InstallPaths:
    applications: Path
    support: Path
    original_profile: Path

    @property
    def installed(self):
        return self.applications / "Telegram.app"

    @property
    def preview(self):
        return self.applications / APP_NAME

    @property
    def profile(self):
        return self.support / "profile"

    @property
    def receipt(self):
        return self.support / "installation-state.json"

    @property
    def backups(self):
        return self.support / "backups"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(directory):
    digest = hashlib.sha256()

    def visit(path, relative):
        metadata = path.lstat()
        mode = metadata.st_mode
        if stat.S_ISLNK(mode):
            entry = [relative, "link", os.readlink(path)]
        elif stat.S_ISDIR(mode):
            entry = [relative, "directory", stat.S_IMODE(mode)]
        elif stat.S_ISREG(mode):
            entry = [relative, "file", stat.S_IMODE(mode), sha256(path)]
        else:
            raise RuntimeError(f"Fichier spécial non pris en charge : {path}")
        digest.update(json.dumps(entry, ensure_ascii=True, separators=(",", ":")).encode() + b"\n")
        if stat.S_ISDIR(mode):
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(child, relative + "/" + child.name)

    visit(directory, ".")
    return digest.hexdigest()


def no_symlink_path(path):
    for entry in [path, *path.parents]:
        if entry.is_symlink():
            raise RuntimeError(f"Chemin symbolique refusé : {entry}")


def require_directory(path):
    no_symlink_path(path)
    if not path.is_dir():
        raise RuntimeError(f"Dossier absent : {path}")


def private_directory(path):
    no_symlink_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def write_json(path, value):
    no_symlink_path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json_object(path, label):
    no_symlink_path(path)
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"{label} illisible : {path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} invalide : un objet JSON est requis dans {path}.")
    return value


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def raise_walk_error(error):
    raise error


def require_profile_access(path, directory=False):
    permissions = os.R_OK | (os.X_OK if directory else 0)
    if not os.access(path, permissions):
        raise PermissionError(errno.EACCES, "Lecture du profil refusée", str(path))


def app_scripts_link(path, entry):
    return entry.relative_to(path) == APP_SCRIPTS_LINK and os.readlink(entry) == APP_SCRIPTS_TARGET


def profile_valid(path, allow_app_scripts_link=False):
    try:
        require_directory(path)
        require_directory(path / "accounts-metadata")
        require_profile_access(path, directory=True)
        require_profile_access(path / "accounts-metadata", directory=True)
        key = path / ".tempkeyEncrypted"
        if key.is_symlink() or not key.is_file() or key.stat().st_size != 64:
            raise RuntimeError(f"Profil incomplet : clé locale de 64 octets attendue dans {path}. Aucune réinitialisation effectuée.")
        require_profile_access(key)
        for root, directories, files in os.walk(path, followlinks=False, onerror=raise_walk_error):
            for name in directories + files:
                entry = Path(root) / name
                if entry.is_symlink():
                    if allow_app_scripts_link and app_scripts_link(path, entry):
                        continue
                    target = os.readlink(entry)
                    if os.path.isabs(target) or os.path.commonpath([str(path), str(entry.resolve())]) != str(path):
                        raise RuntimeError(f"Le profil contient un lien sortant ou absolu : {entry}. La copie privée ne doit pas modifier le profil original.")
                require_profile_access(entry, directory=name in directories)
    except PermissionError as error:
        raise RuntimeError(
            f"macOS refuse la lecture du profil Telegram : {path}. "
            "Autorisez l’application qui exécute ce script, par exemple Terminal, à accéder aux données de Telegram "
            "dans Réglages Système > Confidentialité et sécurité, puis relancez le script. Aucun profil n’a été réinitialisé."
        ) from error


def version_key(version, build):
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Version de l’application non reconnue.")
    if not isinstance(build, str) or not re.fullmatch(r"\d+", build):
        raise RuntimeError("Numéro de compilation non reconnu.")
    return tuple(map(int, version.split("."))), int(build)


def read_delivery(directory):
    manifest = directory / "delivery.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError("Manifest de livraison absent ou symbolique.")
    delivery = read_json_object(manifest, "Manifest de livraison")
    version_key(delivery.get("version"), delivery.get("build"))
    if type(delivery.get("revision")) is not int or delivery["revision"] < 1:
        raise RuntimeError("Révision de livraison invalide.")
    for key in ["sourceCommit", "upstreamCommit"]:
        if not re.fullmatch(r"[a-f0-9]{40}", str(delivery.get(key, ""))):
            raise RuntimeError("Commit de livraison invalide.")
    artifacts = delivery.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RuntimeError("Livraison sans artefact.")
    dmgs = []
    names = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise RuntimeError("Entrée d’artefact invalide dans le manifest.")
        name = artifact.get("name")
        expected = artifact.get("sha256")
        if not isinstance(name, str) or not name or Path(name).name != name or name in names:
            raise RuntimeError("Nom d’artefact invalide.")
        names.add(name)
        path = directory / name
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise RuntimeError("Empreinte d’artefact invalide.")
        if path.is_symlink() or not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"La vérification SHA-256 a échoué : {path}")
        if name.endswith("-arm64.dmg"):
            dmgs.append((path, expected))
    if len(dmgs) != 1:
        raise RuntimeError("Un unique DMG arm64 est requis.")
    return delivery, dmgs[0]


def app_info(app):
    require_directory(app)
    filename = app / "Contents/Info.plist"
    no_symlink_path(filename)
    with filename.open("rb") as stream:
        info = plistlib.load(stream)
    if not isinstance(info, dict):
        raise RuntimeError(f"Info.plist invalide : {app}")
    version_key(info.get("CFBundleShortVersionString"), info.get("CFBundleVersion"))
    if info.get("CFBundleExecutable") != "Telegram":
        raise RuntimeError(f"Exécutable Telegram inattendu : {app}")
    executable = app / "Contents/MacOS/Telegram"
    if executable.is_symlink() or not executable.is_file():
        raise RuntimeError(f"Exécutable absent ou symbolique : {app}")
    return info


def verify_personal(app, host, delivery=None):
    info = app_info(app)
    if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("PersonalMenuBar") is not True:
        raise RuntimeError("Le binaire n’est pas la variante personnelle Telegram Menu Bar.")
    if any(info.get(key) for key in ["SUFeedURL", "SFEED_URL", "SUPublicDSAKeyFile", "SUPublicEDKey"]):
        raise RuntimeError("Le binaire contient une configuration de mises à jour officielles.")
    if info.get("SUEnableAutomaticChecks") is not False or info.get("SUAutomaticallyUpdate") is not False:
        raise RuntimeError("La désactivation des mises à jour internes n’est pas confirmée.")
    config_path = app / "Contents/Resources/menubar-config.json"
    no_symlink_path(config_path)
    config = read_json_object(config_path, "Configuration API embarquée")
    api_id = config.get("api_id")
    if type(config.get("schema")) is not int or config["schema"] != 1 or type(api_id) is not int or not 0 < api_id < 2**31 or api_id in [9, 17349]:
        raise RuntimeError("Les identifiants API personnels embarqués sont invalides.")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", str(config.get("api_hash", ""))):
        raise RuntimeError("Les identifiants API personnels embarqués sont invalides.")
    if delivery:
        expected = {
            "CFBundleShortVersionString": delivery["version"],
            "CFBundleVersion": delivery["build"],
            "PersonalMenuBarSourceCommit": delivery["sourceCommit"],
            "PersonalMenuBarUpstreamCommit": delivery["upstreamCommit"],
            "PersonalMenuBarRevision": delivery["revision"],
        }
        if any(info.get(key) != value for key, value in expected.items()):
            raise RuntimeError("Le binaire ne correspond pas au manifest de livraison.")
    host.verify_signature(app)
    return info


def verified_copy(source, destination, host):
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"La destination existe déjà : {destination}")
    before = tree_hash(source)
    host.copy(source, destination)
    if tree_hash(source) != before or tree_hash(destination) != before:
        raise RuntimeError(f"Copie non conforme ou source modifiée pendant la sauvegarde : {source}")
    return before


def make_backup(paths, source_profile, host):
    private_directory(paths.backups)
    backup = paths.backups / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12])
    backup.mkdir(mode=0o700)
    app_hash = verified_copy(paths.installed, backup / "Telegram.app", host)
    host.verify_signature(backup / "Telegram.app")
    profile_hash = verified_copy(source_profile, backup / "profile", host) if source_profile is not None else None
    host.assert_stopped([paths.installed, paths.preview])
    metadata = {
        "schema": 1, "completedAt": timestamp(), "applicationSha256": app_hash,
        "sourceApplication": str(paths.installed),
    }
    if source_profile is None:
        metadata["scope"] = "application"
    else:
        metadata.update(profileSha256=profile_hash, sourceProfile=str(source_profile))
    write_json(backup / "backup.json", metadata)
    instructions = backup / "RESTAURATION.txt"
    if source_profile is None:
        instructions.write_text(
            "Quitter toutes les instances de Telegram avant toute restauration.\n"
            "Telegram.app contient uniquement l’application sauvegardée.\n"
            "Le profil officiel n’a été ni lu, ni copié, ni modifié par cet installateur.\n"
            "Le nouveau profil privé de Telegram Menu Bar est conservé séparément.\n"
        )
    else:
        instructions.write_text(
            "Quitter toutes les instances de Telegram avant toute restauration.\n"
            "Telegram.app contient l’application sauvegardée ; profile contient son profil complet.\n"
            "Ne jamais mélanger des fichiers de deux profils et conserver le profil actuel avant de le remplacer.\n"
            "Le profil officiel dans Library/Group Containers n’a pas été modifié par cet installateur.\n"
        )
    os.chmod(instructions, 0o600)
    return backup, app_hash, profile_hash


def verify_backup(paths, receipt, host):
    backup = Path(receipt["backup"])
    if backup.parent != paths.backups or not backup.name or backup.name.startswith("."):
        raise RuntimeError("Chemin de sauvegarde inattendu dans le reçu.")
    require_directory(backup)
    metadata = read_json_object(backup / "backup.json", "Manifest de sauvegarde")
    entries = [("Telegram.app", "applicationSha256")]
    if metadata.get("scope") != "application":
        entries.append(("profile", "profileSha256"))
    for name, key in entries:
        if tree_hash(backup / name) != metadata.get(key):
            raise RuntimeError(f"Sauvegarde altérée : {backup}")
    host.verify_signature(backup / "Telegram.app")
    return backup, metadata


def pending_error(paths, receipt):
    return RuntimeError(
        "Première installation en attente de validation. Dans Telegram Menu Bar, vérifiez la session connectée, "
        "la réception d’un message et le proxy Proton attendu. L’application et le profil officiels sont conservés. "
        f"Relancez la livraison {receipt['deliveryDirectory']} dans Terminal puis saisissez exactement VALIDER. "
        f"Reçu : {paths.receipt} ; sauvegarde : {receipt['backup']}."
    )


def clean_previous(paths, receipt):
    value = receipt.get("previousApplication")
    if not value:
        return
    previous = Path(value)
    if previous.parent != paths.applications or not previous.name.startswith(".Telegram.previous-"):
        raise RuntimeError("Chemin de restauration inattendu.")
    backup = Path(receipt["backup"])
    if backup.parent != paths.backups:
        raise RuntimeError("Chemin de sauvegarde inattendu pour l’ancienne application.")
    require_directory(backup)
    archived = backup / "Telegram-original.app"
    no_symlink_path(archived)
    expected_hash = receipt["previousApplicationSha256"]
    if previous.exists():
        require_directory(previous)
        if tree_hash(previous) != expected_hash:
            raise RuntimeError(f"L’ancienne application a changé ; elle est conservée : {previous}")
        if archived.exists():
            raise RuntimeError(f"Une archive de l’ancienne application existe déjà : {archived}. Les deux copies sont conservées.")
        try:
            previous.rename(archived)
        except OSError as error:
            if error.errno not in [errno.EXDEV, errno.EACCES, errno.EPERM]:
                raise
            archived = previous
    if archived.exists():
        require_directory(archived)
        if tree_hash(archived) != expected_hash:
            raise RuntimeError(f"L’archive de l’ancienne application a changé : {archived}")
        receipt["archivedApplication"] = str(archived)
        receipt["archivedApplicationSha256"] = expected_hash
        write_json(backup / "original-application.json", {
            "schema": 1, "archivedAt": timestamp(), "application": str(archived), "applicationSha256": expected_hash,
        })
    receipt.pop("previousApplication", None)
    receipt.pop("previousApplicationSha256", None)


def replace_application(paths, candidate, delivery, candidate_hash, backup, old_receipt, host):
    host.quit([paths.installed, paths.preview])
    host.assert_stopped([paths.installed, paths.preview])
    old_hash = tree_hash(paths.installed)
    previous = paths.applications / (".Telegram.previous-" + uuid.uuid4().hex + ".app")
    journal = {"schema": 1, "status": "replacing", "backup": str(backup), "previousApplication": str(previous),
               "candidateApplication": str(candidate), "previousReceipt": old_receipt, "startedAt": timestamp()}
    write_json(paths.receipt, journal)
    moved_old = False
    moved_new = False
    launch_attempted = False
    try:
        paths.installed.rename(previous)
        moved_old = True
        candidate.rename(paths.installed)
        moved_new = True
        verify_personal(paths.installed, host, delivery)
        if tree_hash(paths.installed) != candidate_hash:
            raise RuntimeError("L’application a changé pendant le remplacement.")
        receipt = {
            "schema": 1, "status": "validated", "validatedAt": old_receipt.get("validatedAt", timestamp()),
            "updatedAt": timestamp(), "backup": str(backup), "applicationSha256": candidate_hash,
            "version": delivery["version"], "build": delivery["build"], "revision": delivery["revision"],
            "sourceCommit": delivery["sourceCommit"], "upstreamCommit": delivery["upstreamCommit"],
            "launchPending": True, "previousApplication": str(previous), "previousApplicationSha256": old_hash,
        }
        if old_receipt.get("installationMode") == "fresh":
            receipt["installationMode"] = "fresh"
        write_json(paths.receipt, receipt)
        launch_attempted = True
        host.launch(paths.installed, preview=False)
        receipt["launchPending"] = False
        write_json(paths.receipt, receipt)
        clean_previous(paths, receipt)
        write_json(paths.receipt, receipt)
        return receipt
    except BaseException as error:
        if launch_attempted:
            raise RuntimeError(
                f"L’application a été remplacée, mais sa relance ou la finalisation a échoué : {error}. "
                f"Le profil actuel, l’ancienne application et la sauvegarde {backup} sont conservés. "
                "Relancez la même livraison ; aucun profil ne sera réinitialisé."
            ) from error
        try:
            host.assert_stopped([paths.installed, paths.preview, previous])
            if moved_new:
                paths.installed.rename(candidate)
            if moved_old:
                previous.rename(paths.installed)
            write_json(paths.receipt, old_receipt)
        except BaseException as rollback_error:
            raise RuntimeError(
                f"Remplacement interrompu ({error}) ; restauration automatique impossible ({rollback_error}). "
                f"Ne relancez pas Telegram avant vérification. Ancienne application : {previous} ; sauvegarde : {backup}."
            ) from error
        raise RuntimeError(f"Remplacement annulé avant lancement ; ancienne application restaurée. Sauvegarde : {backup}. {error}") from error


def install_fresh(directory, paths, delivery, dmg_hash, candidate, candidate_hash, receipt, host):
    if receipt and (receipt.get("status") != "pending-fresh" or receipt.get("installationMode") != "fresh"):
        raise RuntimeError("Un reçu de migration existe déjà. Il est conservé ; aucun nouveau profil ne sera créé.")
    if paths.preview.exists() or paths.preview.is_symlink():
        raise RuntimeError("Une prévisualisation existe déjà. Elle est conservée ; aucune installation neuve effectuée.")
    if not receipt:
        if paths.profile.exists() or paths.profile.is_symlink():
            raise RuntimeError("Un profil privé existe sans reçu. Il est conservé ; aucune installation neuve effectuée.")
        host.quit([paths.installed, paths.preview])
        backup, app_hash, _ = make_backup(paths, None, host)
        receipt = {
            "schema": 1, "status": "pending-fresh", "installationMode": "fresh", "createdAt": timestamp(),
            "backup": str(backup), "deliveryDirectory": str(directory), "dmgSha256": dmg_hash,
            "applicationSha256": candidate_hash, "originalApplicationSha256": app_hash,
        }
        write_json(paths.receipt, receipt)
    if receipt.get("dmgSha256") != dmg_hash or receipt.get("applicationSha256") != candidate_hash:
        raise RuntimeError(f"Une autre livraison attend son installation : {receipt.get('deliveryDirectory')}. Terminez-la avant de changer de version.")
    backup, metadata = verify_backup(paths, receipt, host)
    if metadata.get("scope") != "application" or metadata.get("applicationSha256") != receipt.get("originalApplicationSha256"):
        raise RuntimeError("La sauvegarde de l’installation neuve ne correspond pas au reçu.")
    if tree_hash(paths.installed) != receipt.get("originalApplicationSha256"):
        raise RuntimeError("L’application officielle a changé depuis la sauvegarde. Elle est conservée ; vérification manuelle nécessaire.")
    host.quit([paths.installed, paths.preview])
    if not paths.profile.exists():
        prepared = receipt.get("preparedProfile")
        if prepared:
            temporary = Path(prepared)
            if temporary.parent != paths.support or not re.fullmatch(r"\.profile-[a-f0-9]{32}", temporary.name):
                raise RuntimeError("Chemin du profil préparé inattendu dans le reçu.")
            profile_valid(temporary)
            if tree_hash(temporary) != receipt.get("privateProfileSha256"):
                raise RuntimeError("Le profil préparé a changé. Il est conservé ; aucune réinitialisation effectuée.")
        elif receipt.get("privateProfileSha256"):
            raise RuntimeError("Le profil privé préparé a disparu. Aucune réinitialisation effectuée.")
        else:
            temporary = paths.support / (".profile-" + uuid.uuid4().hex)
            host.initialize_profile(temporary)
            profile_valid(temporary)
            receipt["preparedProfile"] = str(temporary)
            receipt["privateProfileSha256"] = tree_hash(temporary)
            write_json(paths.receipt, receipt)
        temporary.rename(paths.profile)
    profile_valid(paths.profile)
    if tree_hash(paths.profile) != receipt.get("privateProfileSha256"):
        raise RuntimeError("Le profil privé diffère du profil préparé. Il est conservé ; aucune réinitialisation effectuée.")
    if tree_hash(paths.installed) != receipt.get("originalApplicationSha256"):
        raise RuntimeError("L’application officielle a changé pendant la préparation. Aucun remplacement effectué.")
    return replace_application(paths, candidate, delivery, candidate_hash, backup, receipt, host)


def install_delivery(directory, paths, host, fresh=False):
    directory = Path(directory).resolve()
    delivery, (dmg, dmg_hash) = read_delivery(directory)
    require_directory(paths.applications)
    require_directory(paths.installed)
    installed_info = app_info(paths.installed)
    installed_id = installed_info.get("CFBundleIdentifier")
    if installed_id == BUNDLE_ID:
        verify_personal(paths.installed, host)
    elif installed_id == OFFICIAL_ID and installed_info.get("SOURCE") == "APP_STORE":
        host.verify_signature(paths.installed)
    else:
        raise RuntimeError("L’application installée n’est ni Telegram App Store ni le fork personnel attendu.")
    if version_key(delivery["version"], delivery["build"]) < version_key(installed_info["CFBundleShortVersionString"], installed_info["CFBundleVersion"]):
        raise RuntimeError("Retour à une version antérieure refusé avant fermeture de Telegram.")
    if installed_id == BUNDLE_ID and delivery["version"] == installed_info["CFBundleShortVersionString"] and delivery["build"] == installed_info["CFBundleVersion"]:
        if delivery["revision"] < installed_info.get("PersonalMenuBarRevision", 0):
            raise RuntimeError("Retour à une révision antérieure du fork refusé.")
    private_directory(paths.support)
    no_symlink_path(paths.receipt)
    no_symlink_path(paths.profile)
    receipt = read_json_object(paths.receipt, "Reçu d’installation") if paths.receipt.exists() else None
    if receipt is not None and (type(receipt.get("schema")) is not int or receipt.get("schema") != 1 or receipt.get("status") not in ["pending-validation", "pending-fresh", "validated"]):
        raise RuntimeError(f"Une installation interrompue demande une vérification manuelle : {paths.receipt}. Les sauvegardes sont conservées.")
    workspace = Path(tempfile.mkdtemp(prefix=".telegram-menubar-install-", dir=paths.applications))
    try:
        candidate = host.stage(dmg, workspace)
        verify_personal(candidate, host, delivery)
        candidate_hash = tree_hash(candidate)
        if installed_id == BUNDLE_ID:
            if not receipt or receipt.get("status") != "validated":
                raise RuntimeError("Le fork installé ne dispose pas d’un reçu de validation initiale. Aucune installation automatique effectuée.")
            profile_valid(paths.profile)
            if tree_hash(paths.installed) != receipt.get("applicationSha256"):
                raise RuntimeError("L’application installée diffère de son reçu. Vérification manuelle nécessaire.")
            if paths.preview.exists() or paths.preview.is_symlink():
                raise RuntimeError(f"Une application de prévisualisation existe encore : {paths.preview}")
            if tree_hash(paths.installed) == candidate_hash:
                host.launch(paths.installed, preview=False)
                receipt["launchPending"] = False
                write_json(paths.receipt, receipt)
                clean_previous(paths, receipt)
                write_json(paths.receipt, receipt)
                return receipt
            if receipt.get("launchPending") or receipt.get("previousApplication"):
                raise RuntimeError("Finalisez d’abord la relance de la livraison actuellement installée avant une autre mise à jour.")
            host.quit([paths.installed, paths.preview])
            profile_valid(paths.profile)
            backup, _, _ = make_backup(paths, paths.profile, host)
            return replace_application(paths, candidate, delivery, candidate_hash, backup, receipt, host)
        if fresh or (receipt and receipt.get("status") == "pending-fresh"):
            return install_fresh(directory, paths, delivery, dmg_hash, candidate, candidate_hash, receipt, host)
        if receipt and receipt.get("status") != "pending-validation":
            raise RuntimeError("Le reçu validé ne correspond plus à l’application officielle installée.")
        if not receipt:
            if paths.profile.exists() or paths.profile.is_symlink() or paths.preview.exists() or paths.preview.is_symlink():
                raise RuntimeError("Un profil privé ou une prévisualisation existe sans reçu. Ils sont conservés ; vérification manuelle nécessaire.")
            profile_valid(paths.original_profile, allow_app_scripts_link=True)
            host.quit([paths.installed, paths.preview])
            backup, app_hash, profile_hash = make_backup(paths, paths.original_profile, host)
            receipt = {
                "schema": 1, "status": "pending-validation", "createdAt": timestamp(), "backup": str(backup),
                "deliveryDirectory": str(directory), "dmgSha256": dmg_hash, "applicationSha256": candidate_hash,
                "originalApplicationSha256": app_hash, "originalProfileSha256": profile_hash, "previewLaunched": False,
            }
            write_json(paths.receipt, receipt)
        if receipt.get("dmgSha256") != dmg_hash or receipt.get("applicationSha256") != candidate_hash:
            raise RuntimeError(f"Une autre livraison attend sa validation : {receipt['deliveryDirectory']}. Terminez cette première installation avant de changer de version.")
        backup, metadata = verify_backup(paths, receipt, host)
        if tree_hash(paths.installed) != receipt["originalApplicationSha256"]:
            raise RuntimeError("L’application officielle a changé depuis la sauvegarde. Elle est conservée ; vérification manuelle nécessaire.")
        host.quit([paths.installed, paths.preview])
        if not paths.profile.exists():
            if receipt.get("previewLaunched"):
                raise RuntimeError("Le profil privé précédemment lancé a disparu. Aucune copie ancienne ne sera rétablie automatiquement.")
            temporary = paths.support / (".profile-" + uuid.uuid4().hex)
            verified_copy(backup / "profile", temporary, host)
            scripts = temporary / APP_SCRIPTS_LINK
            if scripts.is_symlink() and app_scripts_link(temporary, scripts):
                no_symlink_path(scripts.parent)
                scripts.unlink()
                scripts.mkdir(mode=0o700)
            profile_valid(temporary)
            receipt["privateProfileSha256"] = tree_hash(temporary)
            write_json(paths.receipt, receipt)
            temporary.rename(paths.profile)
        elif not receipt.get("previewLaunched") and tree_hash(paths.profile) != receipt.get("privateProfileSha256", metadata["profileSha256"]):
            raise RuntimeError("Le profil privé incomplet diffère de la sauvegarde. Il est conservé pour vérification.")
        profile_valid(paths.profile)
        if paths.preview.exists() or paths.preview.is_symlink():
            if tree_hash(paths.preview) != candidate_hash:
                raise RuntimeError("La prévisualisation a changé ; aucun remplacement automatique effectué.")
            verify_personal(paths.preview, host, delivery)
        else:
            candidate.rename(paths.preview)
        receipt["previewLaunched"] = True
        write_json(paths.receipt, receipt)
        host.launch(paths.preview, preview=True)
        if host.confirm() != "VALIDER":
            raise pending_error(paths, receipt)
        host.quit([paths.installed, paths.preview])
        profile_valid(paths.profile)
        if tree_hash(paths.installed) != receipt["originalApplicationSha256"] or tree_hash(paths.original_profile) != receipt["originalProfileSha256"]:
            raise RuntimeError("L’application ou le profil officiel a changé pendant la validation. Ils sont conservés ; vérification manuelle nécessaire avant remplacement.")
        return replace_application(paths, paths.preview, delivery, candidate_hash, backup, receipt, host)
    finally:
        try:
            recovery = read_json_object(paths.receipt, "Reçu d’installation") if paths.receipt.exists() else {}
            if workspace.exists() and not (workspace / "volume").exists() and recovery.get("status") != "replacing":
                shutil.rmtree(workspace)
        except Exception as cleanup_error:
            print(f"Dossier temporaire conservé : {workspace}. Nettoyage incomplet : {cleanup_error}", file=sys.stderr)


class MacHost:
    def initialize_profile(self, destination):
        from initialize_profile import initialize_profile
        print("Création d’un profil Telegram neuf…", flush=True)
        initialize_profile(destination)

    def run(self, command, timeout=120):
        process = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if process.returncode:
            raise RuntimeError(f"Échec de {Path(command[0]).name} : {process.stderr.strip() or process.stdout.strip()}")
        return process.stdout

    def copy(self, source, destination):
        print(f"Copie vérifiée en cours : {destination}", flush=True)
        self.run(["/usr/bin/ditto", str(source), str(destination)], timeout=3600)

    def verify_signature(self, app):
        self.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
        architectures = self.run(["/usr/bin/lipo", "-archs", str(app / "Contents/MacOS/Telegram")]).split()
        if "arm64" not in architectures:
            raise RuntimeError("Le binaire ne prend pas en charge Apple Silicon.")

    def stage(self, dmg, workspace):
        self.run(["/usr/bin/hdiutil", "verify", str(dmg)], timeout=300)
        mount = workspace / "volume"
        mount.mkdir()
        self.run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg)], timeout=300)
        try:
            app = mount / APP_NAME
            require_directory(app)
            candidate = workspace / APP_NAME
            verified_copy(app, candidate, self)
            return candidate
        finally:
            self.run(["/usr/bin/hdiutil", "detach", str(mount)], timeout=60)
            mount.rmdir()

    def running(self, apps):
        commands = self.run(["/bin/ps", "-axww", "-o", "command="]).splitlines()
        result = []
        prefixes = tuple(str(app) + "/Contents/" for app in apps)
        for command in commands:
            if command.startswith(prefixes):
                result.append(command)
            elif command.startswith("/") and re.match(r"^.+?\.app/Contents/MacOS/Telegram(?:\s|$)", command):
                raise RuntimeError("Une autre copie de Telegram est ouverte. Fermez-la avant de reprendre cette installation.")
        return result

    def assert_stopped(self, apps):
        if self.running(apps):
            raise RuntimeError("Telegram est encore actif. Aucun arrêt forcé effectué ; quittez-le puis relancez le script.")

    def quit(self, apps):
        deadline = time.monotonic() + 45
        for app in apps:
            if self.running([app, *[other for other in apps if other != app]]):
                if not any(command.startswith(str(app) + "/Contents/") for command in self.running(apps)):
                    continue
                literal = str(app).replace("\\", "\\\\").replace('"', '\\"')
                script = f'if application "{literal}" is running then\n with timeout of 5 seconds\n  tell application "{literal}" to quit\n end timeout\nend if'
                try:
                    self.run(["/usr/bin/osascript", "-e", script], timeout=8)
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
        while self.running(apps) and time.monotonic() < deadline:
            time.sleep(0.25)
        self.assert_stopped(apps)

    def launch(self, app, preview=False):
        command = ["/usr/bin/open", "-a", str(app)]
        if preview:
            command += ["--args", "--menubar-preview"]
        self.run(command)
        deadline = time.monotonic() + 12
        stable_since = None
        executable = str(app / "Contents/MacOS/Telegram")
        while time.monotonic() < deadline:
            running = any(command == executable or command.startswith(executable + " ") for command in self.running([app]))
            if running:
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic() - stable_since >= 3:
                    return
            else:
                stable_since = None
            time.sleep(0.25)
        raise RuntimeError("Le processus principal Telegram n’est pas resté actif pendant trois secondes après son ouverture.")

    def confirm(self):
        if not sys.stdin.isatty():
            return None
        print("\nVérifiez dans Telegram Menu Bar : session déjà connectée, réception d’un message, et proxy Proton attendu.\n"
              "Le profil original reste intact. Saisissez VALIDER uniquement si ces vérifications réussissent.\n"
              "Toute autre réponse conserve la prévisualisation et reporte le remplacement.", flush=True)
        try:
            return input("Confirmation : ").strip()
        except (EOFError, KeyboardInterrupt):
            return None


def install_on_mac(directory, fresh=False):
    if sys.platform != "darwin":
        raise RuntimeError("L’installation est disponible uniquement sur macOS.")
    home = Path.home()
    paths = InstallPaths(Path("/Applications"), home / "Library/Application Support/Telegram Menu Bar",
                         home / "Library/Group Containers/6N38VWS5BX.ru.keepcoder.Telegram/appstore")
    return install_delivery(directory, paths, MacHost(), fresh=fresh)
