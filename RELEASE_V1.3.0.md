# Physics Education AI Agent — v1.3.0 Production Hardening

## Current curriculum foundation
- Added active Egyptian third-secondary physics curriculum context for 2026/2027.
- Registered the user's 2026 final-review PDF as a current Google Drive question source.
- Added 42 source-page records without pretending image-only pages were OCR text.
- Replicated the validated five-chapter academic hierarchy and concept map for the current curriculum context.
- Kept the legacy 2020 source available but no longer marked it as the active curriculum.

## Security
- Cookie-authenticated admin mutations now require a same-origin Origin/Referer.
- ADMIN_API_KEY header clients remain supported for trusted API automation.
- Added CSP, frame protection, MIME sniff protection, referrer policy and restrictive permissions policy.
- Added deterministic same-origin security tests.

## Content integrity
- No current-source questions are auto-published from image-only pages.
- The 2026 source remains in visual review until questions are extracted/reviewed through the existing QA workflow.
