# ============================================================
# HelpDesk Enterprise Copilot - Bootstrap / Setup
# Creates venv, installs deps, creates .env from example.
# Usage:  python scripts/bootstrap.py
# ============================================================

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"


def run(cmd: list, cwd: Path = ROOT) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd).returncode


def main():
    print(f"Project root: {ROOT}")

    # 1. Create virtual environment
    if not (VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / "python").exists():
        print(">> Creating virtual environment...")
        if run([sys.executable, "-m", "venv", str(VENV_DIR)]) != 0:
            sys.exit("Failed to create venv")
    else:
        print(">> Virtual environment already exists")

    pip = VENV_DIR / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
    python = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    # 2. Install dependencies
    print(">> Installing dependencies...")
    if run([str(pip), "install", "--upgrade", "pip"]) != 0:
        sys.exit("pip upgrade failed")
    if run([str(pip), "install", "-r", str(REQUIREMENTS)]) != 0:
        sys.exit("Dependency install failed")

    # 3. Create .env from example
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        print(">> Creating .env from .env.example")
        shutil.copy(ENV_EXAMPLE, ENV_FILE)

    # 4. Ensure data/logs dirs
    for d in (ROOT / "data", ROOT / "logs"):
        d.mkdir(parents=True, exist_ok=True)

    print("\nDone!")
    print("\nNext steps:")
    print(f"  API:  {python} -m uvicorn app.main:app --reload --port 8000")
    print(f"  UI:   {python} -m streamlit run ui/app.py")
    print(f"  Test: {python} -m pytest")


if __name__ == "__main__":
    main()