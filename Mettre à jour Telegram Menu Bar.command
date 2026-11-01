#!/bin/bash
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.cargo/bin:$PATH"
REPOSITORY_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPOSITORY_DIR" || exit 1
printf '\nTelegram Menu Bar — mise à jour et sauvegarde\n\n'
python3 scripts/menubar/update.py
RESULT=$?
if [ "$RESULT" -ne 0 ] && [ -t 0 ]; then
    printf '\nAppuyez sur Entrée pour fermer cette fenêtre…'
    read -r _
fi
exit "$RESULT"
