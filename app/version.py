from __future__ import annotations

# Single source of truth for the application/runtime version.
# Both the full FastAPI app and the lightweight Vercel status plane import this
# value so /health, /health/ready, release diagnostics and the main runtime
# cannot silently drift to different versions.
# 1.8.27 adds subject-aware science profiles and an end-to-end Presentation
# acceptance matrix for physics, chemistry, and middle-school science.
APPLICATION_VERSION = "1.8.27"
