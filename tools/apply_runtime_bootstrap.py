from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    env_path = Path(
        os.getenv("PRODUCTION_ENV_FILE", ".vercel/.env.production.local")
    )
    if env_path.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError as exc:
            raise SystemExit(
                "python-dotenv is required when loading a production env file"
            ) from exc
        load_dotenv(env_path, override=True)

    if not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL is required for explicit runtime bootstrap")

    # Import only after production environment variables are loaded.
    from app.startup_bootstrap import apply_startup_bootstrap

    apply_startup_bootstrap()
    print("Production runtime bootstrap completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
