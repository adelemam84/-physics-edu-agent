#!/usr/bin/env bash
set -euo pipefail

# Manual controlled production release path.
# This intentionally mirrors the GitHub Actions release gates so production can
# be released without GitHub Actions minutes/billing. It never enables content
# ingestion and requires an explicit --promote flag before changing canonical traffic.

VERCEL_CLI_VERSION="${VERCEL_CLI_VERSION:-59.17.0}"
PRODUCTION_URL="${PRODUCTION_URL:-https://physics-edu-agent.vercel.app}"
PROJECT_ID="${VERCEL_PROJECT_ID:-prj_YVuUR2a1VFpZQwdXmUwTRpGbE1sL}"
ORG_ID="${VERCEL_ORG_ID:-team_GsqjHJAXTirB3YVlUto63rma}"
EXPECTED_SHA=""
PROMOTE=0

usage() {
  cat <<'EOF'
Usage:
  tools/manual_production_release.sh [--expected-sha <sha>] [--promote]

Default behavior is stage + verify only. --promote is required to move canonical
production traffic. The script uses the locally authenticated Vercel CLI; no
GitHub Actions execution is required.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --expected-sha)
      EXPECTED_SHA="${2:-}"
      shift 2
      ;;
    --promote)
      PROMOTE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v git >/dev/null
command -v python >/dev/null
command -v npm >/dev/null

if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
  echo "Release must run from main" >&2
  exit 1
fi

HEAD_SHA="$(git rev-parse HEAD)"
if [ -n "$EXPECTED_SHA" ] && [ "$EXPECTED_SHA" != "$HEAD_SHA" ]; then
  echo "Expected SHA $EXPECTED_SHA but current HEAD is $HEAD_SHA" >&2
  exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=all)" ]; then
  echo "Release workspace must be clean" >&2
  git status --short >&2
  exit 1
fi

echo "==> Compile and deterministic regression suite"
python -m compileall -q app index.py status.py
python -m unittest discover -s tests -v

echo "==> Install uv for local Vercel build"
python -m pip install --disable-pip-version-check --upgrade uv
command -v uv >/dev/null

echo "==> Install pinned Vercel CLI locally via npx"
VERCEL=(npx --yes "vercel@${VERCEL_CLI_VERSION}")

export VERCEL_PROJECT_ID="$PROJECT_ID"
export VERCEL_ORG_ID="$ORG_ID"

echo "==> Pull production configuration"
"${VERCEL[@]}" pull --yes --environment=production

python - <<'PY'
from pathlib import Path

path = Path(".vercel/.env.production.local")
if not path.is_file():
    raise SystemExit("Vercel production environment file was not pulled")

present = set()
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key = line.split("=", 1)[0].strip()
    if key:
        present.add(key)

required = {
    "DATABASE_URL",
    "ADMIN_API_KEY",
    "STUDENT_SESSION_SECRET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL_S3",
    "AWS_REGION",
}
missing = sorted(required - present)
if missing:
    raise SystemExit("Missing required production environment keys: " + ", ".join(missing))
print("Required production environment keys are present")
PY

echo "==> Build production artifact"
"${VERCEL[@]}" build --prod

for generated in pyproject.toml uv.lock; do
  if [ -e "$generated" ] && ! git ls-files --error-unmatch "$generated" >/dev/null 2>&1; then
    printf '/%s\n' "$generated" >> .git/info/exclude
  fi
done

DIRTY="$(git status --porcelain --untracked-files=all)"
if [ -n "$DIRTY" ]; then
  printf '%s\n' "$DIRTY" >&2
  echo "Vercel pull/build changed unexpected tracked or unignored files" >&2
  exit 1
fi

BOOTSTRAP_TOKEN="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
STAGE_URL=""
BOOTSTRAP_URL=""

cleanup() {
  if [ -n "$BOOTSTRAP_URL" ]; then
    "${VERCEL[@]}" remove "$BOOTSTRAP_URL" --yes >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> Create isolated bootstrap deployment"
BOOTSTRAP_URL="$("${VERCEL[@]}" deploy --prebuilt --prod --skip-domain --yes   --env RELEASE_GIT_REF=main   --env RELEASE_GIT_SHA="$HEAD_SHA"   --env RELEASE_BOOTSTRAP_TOKEN="$BOOTSTRAP_TOKEN")"

test -n "$BOOTSTRAP_URL"
"${VERCEL[@]}" curl /api/internal/release-bootstrap   --deployment "$BOOTSTRAP_URL" --   --request POST   --header "X-Release-Bootstrap-Token: $BOOTSTRAP_TOKEN"   --fail-with-body > /tmp/physics-release-bootstrap.json

python - <<'PY'
import json
from pathlib import Path
x=json.loads(Path("/tmp/physics-release-bootstrap.json").read_text())
if x.get("status") != "ok" or x.get("runtime_bootstrap") != "applied":
    raise SystemExit(f"Runtime bootstrap failed: {x}")
print("Runtime bootstrap passed")
PY

echo "==> Stage production deployment without bootstrap credential"
STAGE_URL="$("${VERCEL[@]}" deploy --prebuilt --prod --skip-domain --yes   --env RELEASE_GIT_REF=main   --env RELEASE_GIT_SHA="$HEAD_SHA")"
test -n "$STAGE_URL"

"${VERCEL[@]}" curl /health --deployment "$STAGE_URL" > /tmp/physics-stage-health.json
"${VERCEL[@]}" curl /health/ready --deployment "$STAGE_URL" > /tmp/physics-stage-ready.json

python - <<'PY'
import json
from pathlib import Path
from app.version import APPLICATION_VERSION

health=json.loads(Path("/tmp/physics-stage-health.json").read_text())
ready=json.loads(Path("/tmp/physics-stage-ready.json").read_text())
if health.get("status") != "ok":
    raise SystemExit(f"staged /health failed: {health}")
if ready.get("status") != "ready":
    raise SystemExit(f"staged /health/ready failed: {ready}")
if health.get("version") != APPLICATION_VERSION or ready.get("version") != APPLICATION_VERSION:
    raise SystemExit(f"staged version drift: health={health} ready={ready}")
if ready.get("content_ingestion") != "locked":
    raise SystemExit(f"content ingestion must stay locked: {ready}")
print(f"Staged health checks passed for {APPLICATION_VERSION}")
PY

echo "Verified staged deployment: $STAGE_URL"

if [ "$PROMOTE" -ne 1 ]; then
  echo "Stage-only mode complete. Canonical production was NOT changed."
  echo "Re-run from the same clean main SHA with --promote to promote after verification."
  exit 0
fi

echo "==> Promote verified deployment"
"${VERCEL[@]}" promote "$STAGE_URL" --yes

curl --fail --silent --show-error "$PRODUCTION_URL/health" > /tmp/physics-prod-health.json
curl --fail --silent --show-error "$PRODUCTION_URL/health/ready" > /tmp/physics-prod-ready.json

python - <<'PY'
import json
from pathlib import Path
from app.version import APPLICATION_VERSION

health=json.loads(Path("/tmp/physics-prod-health.json").read_text())
ready=json.loads(Path("/tmp/physics-prod-ready.json").read_text())
if health.get("status") != "ok" or ready.get("status") != "ready":
    raise SystemExit(f"Production smoke failed: health={health} ready={ready}")
if health.get("version") != APPLICATION_VERSION or ready.get("version") != APPLICATION_VERSION:
    raise SystemExit(f"Production version drift: health={health} ready={ready}")
if ready.get("content_ingestion") != "locked":
    raise SystemExit(f"Production content ingestion must stay locked: {ready}")
print(f"Production smoke passed for {APPLICATION_VERSION}")
PY

echo "Production release complete: $PRODUCTION_URL"
