#!/bin/bash
set -euo pipefail
export PATH="$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
repository_dir="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
credentials_file="${TELEGRAM_MENUBAR_CREDENTIALS:-$HOME/Library/Application Support/Telegram Menu Bar/build-credentials.json}"
python3 "$repository_dir/scripts/menubar/prepare-build.py" --root "$repository_dir" --credentials "$credentials_file" --check
if [[ "${1:-}" == "--check" ]]; then exit 0; fi
if [[ -n "${1:-}" ]]; then echo "Usage : build.sh [--check]" >&2; exit 2; fi
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo "La compilation personnelle nécessite un Mac Apple Silicon." >&2
    exit 1
fi
if [[ -n "$(git -C "$repository_dir" status --porcelain --untracked-files=normal)" ]]; then
    echo "Enregistrez les modifications Git avant de lancer la compilation isolée." >&2
    exit 1
fi
for executable in git python3 cmake ninja meson nasm yasm autoconf automake pkg-config cargo rustup; do
    command -v "$executable" >/dev/null || { echo "Outil de compilation manquant : $executable" >&2; exit 1; }
done
xcrun --find swift >/dev/null
if [[ "$(xcodebuild -showComponent MetalToolchain 2>/dev/null || true)" != *"Status: installed"* ]]; then
    echo "Le composant Metal est absent ou inaccessible. Installez-le avant la compilation : xcodebuild -downloadComponent MetalToolchain" >&2
    exit 1
fi
xcrun --find metal >/dev/null
arch -x86_64 /usr/bin/true
cache_dir="$HOME/Library/Caches/TelegramMenuBar"
mkdir -p "$cache_dir"
lock_dir="$cache_dir/build.lock"
if ! mkdir "$lock_dir" 2>/dev/null; then
    echo "Une compilation est déjà en cours. Consultez $lock_dir avant de relancer." >&2
    exit 1
fi
printf '%s\n' "$$" > "$lock_dir/pid"
build_root="$(mktemp -d /private/tmp/telegram-menubar-build.XXXXXX)"
chmod 700 "$build_root"
build_dir="$build_root/source"
source_commit="$(git -C "$repository_dir" rev-parse HEAD)"
finished=no
cleanup() {
    if [[ "$finished" == yes ]]; then
        git -C "$repository_dir" worktree remove --force "$build_dir" || true
        rm -rf "$build_root"
    else
        echo "Préparation privée et journaux conservés dans : $build_root" >&2
    fi
    rm -f "$lock_dir/pid"
    rmdir "$lock_dir"
}
trap cleanup EXIT
printf 'Compilation isolée : %s\n' "$build_dir"
git -C "$repository_dir" worktree add --detach "$build_dir" "$source_commit"
git -C "$build_dir" -c url.https://github.com/.insteadOf=git@github.com: -c url.https://gitlab.com/.insteadOf=git@gitlab.com: \
    -c submodule.third-party/twidget.update=none -c submodule.third-party/widget-sandbox.update=none \
    submodule update --init --recursive
python3 -m unittest discover -s "$build_dir/scripts/menubar" -p 'test_*.py'
python3 "$build_dir/tools/tests/menubar-profile/check.py"
python3 "$build_dir/tools/tests/menubar-lifecycle/run.py"
python3 "$build_dir/scripts/menubar/prepare-build.py" --root "$build_dir" --credentials "$credentials_file" --source-commit "$source_commit"
export CMAKE_POLICY_VERSION_MINIMUM=3.5
export MACOSX_DEPLOYMENT_TARGET=12.0
bash "$build_dir/scripts/xcode27.sh" apply > "$build_root/compatibility.log" 2>&1
abseil_file="$build_dir/submodules/tg_owt/src/third_party/abseil-cpp/absl/base/attributes.h"
if [[ -f "$abseil_file" ]]; then
    python3 - "$abseil_file" <<'PY'
import pathlib, sys
filename = pathlib.Path(sys.argv[1])
text = filename.read_text()
for suffix in ("[[clang::lifetimebound]]", "__attribute__((lifetimebound))"):
    text = text.replace("#define ABSL_ATTRIBUTE_LIFETIME_BOUND " + suffix, "#define ABSL_ATTRIBUTE_LIFETIME_BOUND")
filename.write_text(text)
PY
fi
printf 'Construction des bibliothèques natives ; journal : %s\n' "$build_root/frameworks.log"
if ! bash "$build_dir/scripts/configure_frameworks.sh" > "$build_root/frameworks.log" 2>&1; then
    tail -50 "$build_root/frameworks.log" >&2
    exit 1
fi
printf 'Construction de l’application arm64 ; journal : %s\n' "$build_root/app.log"
if ! xcodebuild build -workspace "$build_dir/Telegram-Mac.xcworkspace" -scheme Release -configuration Release \
    -derivedDataPath "$build_root/DerivedData" -destination 'generic/platform=macOS' \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=YES MACOSX_DEPLOYMENT_TARGET=12.0 \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM= \
    COMPILER_INDEX_STORE_ENABLE=NO 'SWIFT_ACTIVE_COMPILATION_CONDITIONS=$(inherited) STABLE PERSONAL_MENUBAR' \
    > "$build_root/app.log" 2>&1; then
    tail -70 "$build_root/app.log" >&2
    exit 1
fi
python3 "$build_dir/scripts/menubar/package-build.py" --root "$build_dir" \
    --app "$build_root/DerivedData/Build/Products/Release/Telegram Menu Bar.app" \
    --output "$repository_dir/dist/menubar/current"
if [[ "$(git -C "$repository_dir" rev-parse HEAD)" != "$source_commit" ]]; then
    echo "Le commit source a changé pendant la compilation. La livraison doit être revérifiée." >&2
    exit 1
fi
finished=yes
