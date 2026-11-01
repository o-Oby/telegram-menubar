# Initialisation native d’un profil neuf

Ce lot permet au DMG personnel 13.1.0 de démarrer avec un nouveau compte, sans lire le profil de l’application officielle. Il n’effectue aucune connexion Telegram et ne contient aucun identifiant API.

Les six fichiers sous `vendor/` sont des copies inchangées des sources utilisées par Telegram macOS 13.1.0 (build 283357). `provenance.json` indique pour chacun le dépôt, le commit, le chemin amont et le SHA-256. Les commentaires et avis présents dans les sources sont conservés. La licence GPL version 2 du projet Telegram macOS est reproduite dans `LICENSE`. Aucun avis de licence propre aux fichiers CryptoUtils/MurMurHash32 n’est présent dans les fichiers copiés à leur commit indiqué ; ces sources sont celles du sous-module Telegram-iOS utilisé par cette distribution du projet.

`main.m` appelle uniquement `AppEncryptionParameters` sur un dossier qu’il vient de créer. Il ne fait pas appel aux méthodes Keychain de l’autre classe `BuildConfig` également définie dans le fichier amont. Il vérifie le déchiffrement et la réouverture native sans imprimer de clé, sel ou contenu chiffré.

Le driver `../initialize_profile.py` vérifie les empreintes, compile avec le SDK macOS de Xcode et exécute le helper. Les dossiers sont créés en mode 700, la clé en mode 600. Une destination existante ou un parent symbolique sont refusés. Le temporaire de compilation est supprimé ; le profil reste au chemin demandé. L’installateur doit publier ce profil par renommage atomique après réussite.

Ce lot ne dépend ni d’un checkout de sous-modules ni d’un ancien dossier de construction. Pour un changement de format natif amont, actualiser ensemble les sources, leur provenance et les tests ; ne pas remplacer la clé chiffrée native par des octets aléatoires bruts.
