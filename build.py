from pathlib import Path
import shutil
import subprocess
import sys


if __name__ == "__main__":
    if sys.version_info[:2] != (3, 14):
        sys.exit("The build requires Python 3.14.")

    project_dir = Path(__file__).resolve().parent
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
         "--name", "notepad", "--workpath", ".build/pyinstaller",
         "--version-file", "version-info.txt", "--add-data", "docs_view.js:.", "support_app.py"],
        cwd=project_dir,
        check=True,
    )
    for command in ("set-doc-url.cmd", "stop-anti.cmd"):
        shutil.copy2(project_dir / command, project_dir / "dist" / command)
