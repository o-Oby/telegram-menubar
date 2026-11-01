from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
sources = root / "packages/ApiCredentials/Sources/ApiCredentials"
with tempfile.TemporaryDirectory(prefix="telegram-menubar-profile-") as temporary:
    directory = Path(temporary)
    binary = directory / "profile-tests"
    subprocess.run([
        "swiftc", "-module-cache-path", str(directory / "cache"),
        str(sources / "PersonalMenuBarConfiguration.swift"),
        str(Path(__file__).with_name("main.swift")), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)
    for name, flags in [("upstream", []), ("personal", ["-D", "PERSONAL_MENUBAR"])]:
        subprocess.run([
            "swiftc", "-typecheck", "-module-cache-path", str(directory / "cache"),
            *flags, *map(str, sources.glob("*.swift")),
        ], check=True)
        print(f"{name}: ApiCredentials typecheck passed", flush=True)
