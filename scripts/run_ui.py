# ============================================================
# Run the Streamlit UI.
# Usage:
#   python scripts/run_ui.py            # default port 8501
#   python scripts/run_ui.py --port 8502
# ============================================================

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="Start the HelpDesk Copilot UI")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()

    os.environ.setdefault("API_BASE_URL", "http://localhost:8000")

    import streamlit.web.cli as stcli

    print(f"Starting Streamlit UI on :{args.port} -> API: {os.environ['API_BASE_URL']}")
    sys.argv = ["streamlit", "run", str(ROOT / "ui" / "app.py"), "--port", str(args.port)]
    stcli.main()


if __name__ == "__main__":
    main()