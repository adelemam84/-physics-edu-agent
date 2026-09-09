# Phase X — Production Acceptance & Safe Diagnostics

## Goal

Turn Lesson Studio acceptance into a production-grade, read-only verification layer that reflects the hardened release contract already enforced by approval and PDF export.

## Implemented scope

- Initialize Lesson Studio release-state, reference-library, curriculum-map, and version-history schemas during application startup.
- Keep the acceptance GET path durable-state read-only: no DDL, cache update, approval mutation, PDF creation, or object deletion.
- Verify teacher approval against both the current content hash and current diagram-manifest hash.
- Verify the final PDF against both the current content hash and current diagram-manifest hash.
- Detect stale active teacher approvals and hash-stale active PDF bindings as system-owned integrity blockers.
- Treat malformed scientific-reference findings payloads as invalid instead of assuming they are nonblocking.
- Keep PDF hash freshness separate from release status so a review-state transition does not falsely report immutable PDF hashes as stale.
- Report orphan binding hashes separately without treating them as active approval.
- Require at least one single end-to-end lesson job to satisfy source binding, OCR review, scientific reference review, teacher approval, and fresh final PDF together.
- Keep missing real references, curriculum mapping, OCR review, and teacher approval as teacher/external gates; never fabricate scientific content to close them.

## Acceptance contract

`platform_ready` means that runtime configuration, required persistence schema, and active release bindings are healthy.

`acceptance_ready` additionally requires the real-content/human gates and at least one complete end-to-end release job.

Production-code readiness and content readiness remain separate concepts.

## Safety invariants

1. Source material remains the source of truth.
2. No scientific content is invented to satisfy a readiness check.
3. No diagnostic GET endpoint grants teacher approval.
4. A stale teacher approval never counts as current.
5. A PDF whose content or diagram binding is stale never counts as final.
6. Malformed review metadata fails closed rather than satisfying a scientific gate.
7. Final acceptance is demonstrated by one coherent release path, not by combining unrelated partial jobs.
