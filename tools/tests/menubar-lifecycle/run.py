from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
with tempfile.TemporaryDirectory(prefix="telegram-menubar-tests-") as temporary:
    temporary = Path(temporary)
    executable = temporary / "lifecycle-tests"
    subprocess.run([
        "xcrun", "swiftc", "-warnings-as-errors",
        "-module-cache-path", str(temporary / "module-cache"),
        str(root / "Telegram-Mac/app/MenuBarWindowController.swift"),
        str(Path(__file__).with_name("main.swift")),
        "-o", str(executable),
    ], check=True)
    raise SystemExit(subprocess.run([str(executable)]).returncode)
