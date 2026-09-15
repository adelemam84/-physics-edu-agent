from __future__ import annotations

import os

from app.startup_schema import ensure_runtime_schema


def main() -> int:
    marker = (
        os.getenv("RELEASE_GIT_SHA", "").strip()
        or os.getenv("GITHUB_SHA", "").strip()
    )
    if not marker:
        raise SystemExit("RELEASE_GIT_SHA or GITHUB_SHA is required")

    result = ensure_runtime_schema(marker=marker)
    print(
        "Release schema status:",
        result.get("reason"),
        "migrated=" + str(bool(result.get("migrated"))).lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
