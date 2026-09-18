from __future__ import annotations

# Single source of truth for the application/runtime version.
# Both the full FastAPI app and the lightweight Vercel status plane import this
# value so /health, /health/ready, release diagnostics and the main runtime
# cannot silently drift to different versions.
# 1.8.24 adds persistent exact-digest teacher approval for Presentation Studio,
# server-side approval history/revocation and approval-gated final PPTX exports.
APPLICATION_VERSION = "1.8.24"
