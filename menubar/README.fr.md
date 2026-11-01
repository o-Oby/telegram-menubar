# Telegram Menu Bar — fork personnel macOS

Fork non officiel du **client Telegram natif pour macOS**, destiné à votre Mac Apple Silicon.
Il utilise les sources de [TelegramMessenger/telegram-macos](https://github.com/TelegramMessenger/telegram-macos),
et non celles de Telegram Desktop (`tdesktop`). Le dépôt public est
[o-Oby/telegram-menubar](https://github.com/o-Oby/telegram-menubar), branche `codex/macos-menubar`.

**État actuel :** le code et les tests ciblés sont en place. La compilation complète de Telegram,
la création du premier DMG et la reprise de votre session avec le fork ne sont pas encore validées.
Les identifiants API personnels sont nécessaires pour poursuivre. L’application App Store installée
et son profil d’origine ne doivent pas être remplacés avant la validation initiale décrite ci-dessous.

## Comportement prévu

- Fenêtre ouverte : présence normale dans le Dock.
- Bouton rouge ou `⌘W` : fenêtre masquée, Telegram reste connecté dans la barre de menus, Dock masqué.
- Menu **Afficher/Masquer**, ouverture depuis le Finder, notification ou lien : retour du Dock et de la fenêtre.
- Minimiser et `⌘H` conservent leur comportement natif.
- **Quitter** et `⌘Q` arrêtent réellement l’application.

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

## Première installation et conservation de la session

La version App Store utilise un conteneur et des autorisations liés à la signature de Telegram.
Le fork possède sa propre identité **`fr.oby.telegram-menubar`**, sa propre icône et un profil privé :

```text
~/Library/Application Support/Telegram Menu Bar/profile
```

Après la compilation, le script **Mettre à jour Telegram Menu Bar.command** automatise ce parcours :

1. Construire et vérifier le DMG du fork.
2. Quitter complètement Telegram, puis sauvegarder l’application et le profil App Store fermé.
3. Copier le profil complet, y compris ses fichiers cachés et sa clé de base de données chiffrée,
   dans le dossier privé du fork. Le conteneur App Store d’origine reste intact.
4. Lancer **Telegram Menu Bar.app** en prévisualisation et vérifier la reprise de session,
   les conversations et le proxy attendu.
5. Saisir exactement **VALIDER** dans le terminal, après ces vérifications, pour remplacer
   `/Applications/Telegram.app`. Toute autre réponse laisse l’application officielle en place.

Si cette validation est interrompue, un nouveau double-clic reprend la même livraison avant de rechercher
une version plus récente. Le profil privé déjà ouvert n’est jamais écrasé par une nouvelle copie.

Cette confirmation est propre à la migration initiale : la reprise de session n’est pas garantie par
la seule copie des fichiers. Si le fork demande une nouvelle connexion ou propose de réinitialiser
les données, arrêter la validation et examiner le problème plutôt que confirmer le remplacement.

Le code local de verrouillage de Telegram peut être demandé. Aucun secret du trousseau n’est exporté.
La reprise des réglages biométriques et des données locales du portefeuille n’est pas garantie ;
le profil officiel et sa sauvegarde sont conservés pour permettre un retour en arrière.

La compilation est d’abord non signée, puis signée localement de façon ad hoc, sans notarisation Apple.
macOS peut donc demander une autorisation d’ouverture ou d’accès au conteneur pendant la migration.
Si le système refuse la lecture du profil App Store, le script doit s’arrêter avant de fermer Telegram.
Sous macOS 27, l’accès aux données d’autres apps est refusé par défaut et peut se régler dans
**Confidentialité et sécurité > Fichiers et dossiers > Terminal**. Autoriser l’accès aux données de Telegram
si cette entrée est proposée, puis relancer la même livraison. Ne pas attendre systématiquement une popup.
Ne pas déplacer le profil d’origine ni modifier ses droits pour contourner ce contrôle.

## Proxy et Proton

Le Telegram installé utilise déjà un **proxy interne à l’application**. Le fork doit conserver ce
réglage avec le profil copié. Aucun lanceur `Telegram (Proton).app` n’a été trouvé sur ce Mac.

Le script relance donc le client natif, qui réutilise ses réglages de proxy. Les arguments de lancement
Electron employés pour Element ne s’appliquent pas à Telegram. La vérification du proxy connecté fait
partie de la validation initiale, avant tout remplacement.

## Mises à jour après validation initiale

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
livraison déjà construite et validée est réutilisée. Les prérequis sont Xcode complet avec son composant
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
