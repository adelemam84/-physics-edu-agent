from __future__ import annotations

# Single source of truth for the application/runtime version.
# Both the full FastAPI app and the lightweight Vercel status plane import this
# value so /health, /health/ready, release diagnostics and the main runtime
# cannot silently drift to different versions.
# 1.8.14 adds deterministic Lesson Pack PDF preflight and export quality gates.
APPLICATION_VERSION = "1.8.14"
