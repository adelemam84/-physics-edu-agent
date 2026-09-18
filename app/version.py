from __future__ import annotations

# Single source of truth for the application/runtime version.
# Both the full FastAPI app and the lightweight Vercel status plane import this
# value so /health, /health/ready, release diagnostics and the main runtime
# cannot silently drift to different versions.
# 1.8.25 expands the source-grounded visual engine across physics, chemistry,
# and middle-school science with strict specs and editable native PPTX shapes.
APPLICATION_VERSION = "1.8.25"
