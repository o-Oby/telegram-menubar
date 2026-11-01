# Telegram Menu Bar — fork personnel macOS

Fork non officiel du **client Telegram natif pour macOS**, destiné à votre Mac Apple Silicon.
Il utilise les sources de [TelegramMessenger/telegram-macos](https://github.com/TelegramMessenger/telegram-macos),
et non celles de Telegram Desktop (`tdesktop`). Le dépôt public est
[o-Oby/telegram-menubar](https://github.com/o-Oby/telegram-menubar), branche `codex/macos-menubar`.

**État actuel :** la compilation complète arm64 et le premier DMG **13.1.0-r1** sont vérifiés,
y compris la signature ad hoc et les paramètres propres au fork. L’installation avec un profil neuf
a été effectuée sur le Mac et le processus du fork est lancé. La connexion au compte, le proxy et
les vérifications visuelles restent à terminer dans l’application.

## Comportement prévu

- Fenêtre ouverte : présence normale dans le Dock.
- Bouton rouge ou `⌘W` : fenêtre masquée, Telegram reste connecté dans la barre de menus, Dock masqué.
- Menu **Afficher/Masquer**, ouverture depuis le Finder, notification ou lien : retour du Dock et de la fenêtre.
- Minimiser et `⌘H` conservent leur comportement natif.
- **Quitter** et `⌘Q` arrêtent réellement l’application.

L’icône du Dock et du Finder est celle de Telegram. Le nom affiché de l’application est **Telegram**.
Ce choix est conservé lors des mises à jour du fork.

Le fork réutilise l’icône monochrome et le réglage natif **Show Icon in Menu Bar**. Le Dock reste disponible
si l’icône ne peut pas être utilisée ou si elle est désactivée. Les actions Afficher/Masquer et Quitter
restent présentes lorsque le menu contient aussi des commandes d’appel. La fermeture en plein écran
attend la sortie de ce mode ; une réouverture annule la fermeture encore en attente.

## Identifiants API personnels

Créer votre application sur [my.telegram.org/apps](https://my.telegram.org/apps), selon les
[instructions officielles](https://core.telegram.org/api/obtaining_api_id), puis conserver votre
`api_id` et votre `api_hash` uniquement dans ce fichier privé :

```text
~/Library/Application Support/Telegram Menu Bar/build-credentials.json
```

Son contenu doit avoir cette forme, avec vos valeurs réelles :

```json
{
    "api_id": 0,
    "api_hash": ""
}
```

Remplacer `0` par votre identifiant numérique et la chaîne vide par votre hash de 32 caractères
hexadécimaux. Les valeurs ci-dessus sont volontairement inutilisables. Restreindre les permissions du
fichier à votre compte (`chmod 600`), et ne pas le placer dans le dépôt ni copier les clés dans un chat.
Le script refuse les identifiants officiels/de test connus et les valeurs manquantes ou invalides.

Les identifiants sont intégrés à la copie locale de l’application lors de la compilation ; ils ne sont
pas publiés dans les sources du fork. La variable `TELEGRAM_MENUBAR_CREDENTIALS` permet de désigner
un autre fichier privé.

Depuis le dossier du projet, vérifier les identifiants sans compiler ni installer :

```sh
bash scripts/menubar/build.sh --check
```

Ce contrôle ne valide pas à lui seul toute la chaîne de compilation ni la connexion au service Telegram.

## Première installation avec un profil neuf

Le fork possède sa propre identité **`fr.oby.telegram-menubar`**, l’icône Telegram d’origine et un profil privé :

```text
~/Library/Application Support/Telegram Menu Bar/profile
```

Double-cliquer **Mettre à jour Telegram Menu Bar.command**. Le script vérifie le DMG, quitte Telegram,
sauvegarde l’application officielle, prépare un profil vide, remplace `/Applications/Telegram.app`
et lance le fork. Connectez-vous ensuite avec votre compte Telegram. Le profil App Store d’origine
n’est ni lu ni copié par ce parcours et reste à son emplacement. Aucun accès complet au disque n’est nécessaire.

La clé locale du profil neuf est créée par le code natif Telegram, compilé dans un petit outil local,
puis son déchiffrement est vérifié avant utilisation. Aucun identifiant de session ni secret n’est affiché.
Un profil existant n’est jamais réinitialisé automatiquement. Si l’installation est interrompue,
un nouveau double-clic reprend la même livraison et conserve le profil déjà préparé.

La première sauvegarde contient uniquement l’ancienne application. Après connexion, les mises à jour
suivantes sauvegardent l’application **et le profil du fork** avant remplacement.
Les conversations disponibles dans le compte se retrouveront après connexion ; les données propres
à l’ancienne installation ne sont pas transférées par ce parcours.

L’extension de partage macOS TelegramShare n’est pas embarquée dans cette variante personnelle.
L’application est signée localement de façon ad hoc, sans notarisation Apple.

### Migration optionnelle de l’ancien profil

Le parcours de copie reste disponible explicitement avec `python3 scripts/menubar/update.py --migrate-profile`.
Il nécessite l’accès au conteneur App Store, effectue une sauvegarde complète et ouvre une prévisualisation.
Il attend **VALIDER** dans Terminal après vérification de la session, de la réception et du proxy.
Il ne faut pas rouvrir l’application officielle pendant cette vérification. Le lien macOS connu
`Library/Application Scripts/6N38VWS5BX.ru.keepcoder.Telegram` est conservé sans être suivi dans
la sauvegarde, puis remplacé par un dossier local vide uniquement dans la copie privée.
Aucun secret du trousseau n’est exporté. Retirer toute autorisation temporaire après la migration.

## Proxy et Proton

Le Telegram installé utilisait son proxy SOCKS5 interne **127.0.0.1:25344**, fourni par le service Proton local.
Un profil neuf ne reprend aucun réglage de l’ancien profil : configurer ce proxy dans Telegram Menu Bar
avant de se connecter. Le service Proton doit être actif. Les arguments Electron employés pour Element
ne s’appliquent pas au client natif Telegram.

Les relances et mises à jour suivantes conservent les réglages de proxy enregistrés dans le profil du fork.

## Mises à jour après installation

Double-cliquer **Mettre à jour Telegram Menu Bar.command** dans le dossier du projet.
Le parcours prévu prépare les sources dans un espace isolé, fusionne la version officielle avec les
modifications du fork, exécute les contrôles, construit et vérifie le DMG, puis publie la branche validée.
Il sauvegarde ensuite l’application et le profil du fork avant de remplacer l’application et de la relancer.
Les sauvegardes privées restent dans `~/Library/Application Support/Telegram Menu Bar/backups`,
hors du dépôt GitHub ; leur emplacement est indiqué dans le terminal.

Les mises à jour officielles internes sont désactivées à la compilation avec `PERSONAL_MENUBAR`,
y compris les chemins de recherche manuelle, de téléchargement et d’installation. Les nouvelles versions
personnalisées doivent passer par le script du fork.

Chaque nouvelle compilation reconstruit actuellement les bibliothèques natives et peut être longue ; seule une
livraison déjà construite et validée est réutilisée. Une correction limitée aux scripts d’installation,
de mise à jour, à leurs tests ou au guide peut réutiliser le même DMG après vérification de son empreinte
et de son commit source. Un changement de l’application ou de sa construction impose une nouvelle compilation.
Les prérequis sont Xcode complet avec son composant
Metal, CMake, Ninja, Meson, NASM, Yasm, Autoconf, Automake, pkg-config, Rust et Rosetta. Le script récupère
les sous-modules épinglés et compile les bibliothèques natives avant l’application arm64.
Les sous-modules `third-party/twidget` et `third-party/widget-sandbox`, réservés aux laboratoires
de performance et absents des dépendances Release, sont exclus de cette préparation.
Les adaptations Xcode 27 et les identifiants privés sont appliqués dans la préparation isolée.
Le strip des bibliothèques Rust est désactivé localement pour contourner le défaut de chargement
[Rust 1.96 sur macOS 27](https://github.com/rust-lang/rust/issues/157750) ; les versions verrouillées sont conservées.
Un premier `--check` réussi ne signifie donc pas qu’un DMG a déjà été construit.

## Choix des versions officielles

La base initiale est **13.1.0, build 283357**, associée au commit officiel
[`24295527d9122baaf40b467db7d62e44d501ddf7`](https://github.com/TelegramMessenger/telegram-macos/commit/24295527d9122baaf40b467db7d62e44d501ddf7),
intitulé « Merge branch 'release' into master (13.1) ». La révision du fork figure dans `menubar/release.json`.

Le dépôt natif n’expose actuellement ni tags de version ni releases GitHub. Son `master` contient des
changements postérieurs conservant parfois le même numéro de version : ce numéro seul ne prouve pas
qu’un commit est la publication stable.

Le script consulte le [flux stable officiel](https://mac-updates.telegram.org/updates/versions.xml), puis
recherche un commit unique d’import de publication dont les versions de l’application et de l’extension
correspondent au flux. S’il ne peut pas établir cette correspondance sans ambiguïté, il s’arrête avec un
diagnostic. Il ne remplace pas cette vérification par une fusion automatique du dernier `master`.

## En cas d’échec

Un conflit de fusion ou un échec de compilation doit laisser l’application installée et le profil en place.
Conserver le diagnostic indiqué par le terminal ; une nouvelle version peut nécessiter l’adaptation des
modifications du fork. Ne pas résoudre un conflit en écrasant automatiquement ces modifications.

Après un lancement du fork, une version plus récente peut avoir modifié le format de son profil.
Pour revenir en arrière, quitter les applications, conserver le profil courant à part, puis restaurer
l’application et son profil sauvegardés ensemble. Ne pas fusionner les bases de données ni remplacer
un profil pendant que Telegram fonctionne. Le profil App Store d’origine reste distinct du profil du fork.

Après correction d’un échec de compilation, une préparation privée existante peut être reprise :

```sh
TELEGRAM_MENUBAR_RESUME_BUILD=/private/tmp/telegram-menubar-build.ID python3 scripts/menubar/update.py --prepare-only
```

Remplacer `ID` par le dossier indiqué dans le diagnostic. Cette reprise vérifie le dossier et son dépôt,
restaure les sources suivies au nouveau commit, régénère les paramètres privés et conserve les caches.
Les contrôles de dépendances déterminent quelles bibliothèques peuvent être réutilisées. Le double-clic
normal prépare un nouvel espace isolé ; cette option est destinée à la résolution d’un échec.

Une préparation échouée peut contenir les identifiants intégrés à l’application : conserver ce dossier
privé et ne partager que des diagnostics relus, sans joindre son contenu complet au dépôt public.

## Tests ciblés

Ces contrôles utilisent des profils et processus fictifs ; ils ne remplacent pas la validation de la
compilation complète ni celle de la session réelle :

```sh
python3 tools/tests/menubar-lifecycle/run.py
python3 tools/tests/menubar-profile/check.py
python3 -m unittest discover -s scripts/menubar -p 'test_*.py'
```

La construction seule se lance avec `bash scripts/menubar/build.sh`. Les instructions d’origine dans
`INSTALL.md` décrivent les dépendances du projet ; le script du fork prépare sa propre configuration.
