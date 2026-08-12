# ============================================================
# Run the FastAPI backend.
# Usage:
#   python scripts/run_api.py          # dev (auto-reload)
#   python scripts/run_api.py --prod   # production
# ============================================================

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Start the HelpDesk Copilot v12 API")
    parser.add_argument("--prod", action="store_true", help="Run in production mode (no reload)")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    port = args.port or settings.API_PORT

    import uvicorn

    print(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} on :{port}")
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=port,
        reload=not args.prod,
        log_level="info",
    )


if __name__ == "__main__":
    main()