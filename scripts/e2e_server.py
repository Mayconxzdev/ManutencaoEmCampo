"""Start an isolated, synthetic API for public portfolio browser tests.

This helper recreates only ``.e2e_data`` in this repository. It deliberately
does not inspect installed services, mounted shares, external paths or user
data. It is not an operational deployment script.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
E2E_DATA = ROOT / ".e2e_data"


def main() -> None:
    environment = os.environ.copy()
    environment["MEC_DATA_DIR"] = str(E2E_DATA)
    environment["MEC_TIMEZONE"] = "America/Sao_Paulo"
    environment["MEC_APP_VERSION"] = "1.0.0-demo-e2e"

    subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "seed_demo.py"), "--reset"],
        cwd=BACKEND,
        env=environment,
        check=True,
    )

    os.environ.update({key: value for key, value in environment.items() if key.startswith("MEC_")})
    sys.path.insert(0, str(BACKEND))
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8124, log_level="warning")


if __name__ == "__main__":
    main()
