from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit(
            "DATABASE_URL is required; run through 'vercel env run -e production -- ...'"
        )
    if database_url == "[SENSITIVE]":
        raise SystemExit(
            "DATABASE_URL is masked; production bootstrap must use 'vercel env run'"
        )

    # Import only after production environment variables are injected.
    from app.startup_bootstrap import apply_startup_bootstrap

    apply_startup_bootstrap()
    print("Production runtime bootstrap completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
