from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    if sys.version_info[:2] != (3, 14):
        sys.exit("The build requires Python 3.14.")

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
         "--name", "notepad", "--workpath", ".build/pyinstaller",
         "--version-file", "version-info.txt", "--add-data", "docs_view.js:.", "support_app.py"],
        cwd=Path(__file__).resolve().parent,
        check=True,
    )
