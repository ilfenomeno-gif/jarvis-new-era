import os
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
VENV_PYTHON = VENV_DIR / (
    "Scripts/python.exe" if platform.system() == "Windows" else "bin/python"
)

if not VENV_PYTHON.is_file():
    subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        cwd=PROJECT_DIR,
        check=True,
    )

try:
    using_venv = os.path.samefile(sys.executable, VENV_PYTHON)
except OSError:
    using_venv = str(Path(sys.executable).resolve()).casefold() == str(
        VENV_PYTHON.resolve()
    ).casefold()

if not using_venv:
    os.execv(
        str(VENV_PYTHON),
        [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
    )

os.chdir(PROJECT_DIR)

print("Installing requirements...")
subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)

print("Installing Playwright browsers...")
subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

if platform.system() == "Windows":
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        postinstall = Path(sys.executable).parent / "Scripts" / "pywin32_postinstall.py"
        print(
            "\n⚠️  pywin32 did not install correctly — desktop shortcut creation "
            "will fall back to a slower method that may not work on this machine.\n"
            "    Try fixing it manually with:\n"
            f'    "{sys.executable}" -m pip install --force-reinstall pywin32\n'
            f'    "{sys.executable}" "{postinstall}" -install\n'
        )

print(f"\n✅ Setup complete! Run '{VENV_PYTHON} main.py' to start MARK LII.")
