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
SOURCE_SHA="${RELEASE_SOURCE_SHA:-}"
SOURCE_REF="${RELEASE_SOURCE_REF:-}"
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

ARCHIVE_SOURCE=0
if [ -n "$SOURCE_SHA" ]; then
  ARCHIVE_SOURCE=1
  case "$SOURCE_SHA" in
    *[!0-9a-fA-F]*|"")
      echo "RELEASE_SOURCE_SHA must be a hexadecimal Git commit SHA" >&2
      exit 1
      ;;
  esac
  if [ "${#SOURCE_SHA}" -ne 40 ]; then
    echo "RELEASE_SOURCE_SHA must be exactly 40 hexadecimal characters" >&2
    exit 1
  fi
  if [ "$SOURCE_REF" != "main" ]; then
    echo "Archive release source must declare RELEASE_SOURCE_REF=main" >&2
    exit 1
  fi
  HEAD_SHA="$SOURCE_SHA"
else
  if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
    echo "Release must run from main" >&2
    exit 1
  fi
  HEAD_SHA="$(git rev-parse HEAD)"
  if [ -n "$(git status --porcelain --untracked-files=all)" ]; then
    echo "Release workspace must be clean" >&2
    git status --short >&2
    exit 1
  fi
fi

if [ -n "$EXPECTED_SHA" ] && [ "$EXPECTED_SHA" != "$HEAD_SHA" ]; then
  echo "Expected SHA $EXPECTED_SHA but release source is $HEAD_SHA" >&2
  exit 1
fi

echo "==> Compile and deterministic regression suite"
python -m compileall -q app index.py status.py
python -m unittest discover -s tests -v

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

echo "==> Verify workspace after Vercel pull"
if [ "$ARCHIVE_SOURCE" -eq 0 ]; then
  DIRTY="$(git status --porcelain --untracked-files=all)"
  if [ -n "$DIRTY" ]; then
    printf '%s\n' "$DIRTY" >&2
    echo "Vercel pull changed unexpected tracked or unignored files" >&2
    exit 1
  fi
else
  test -f ".vercel/project.json"
  test -f ".vercel/.env.production.local"
  echo "Archive source workspace verified without mutable Git network state"
fi

BOOTSTRAP_TOKEN="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
STAGE_URL=""
BOOTSTRAP_URL=""
TMP_DIR=".git/release-tmp"
rm -rf -- "$TMP_DIR"
mkdir -p "$TMP_DIR"

cleanup() {
  rm -rf -- "$TMP_DIR"
  if [ -n "$BOOTSTRAP_URL" ]; then
    "${VERCEL[@]}" remove "$BOOTSTRAP_URL" --yes >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

deploy_isolated() {
  local label="$1"
  shift
  local out=""
  local url=""
  for attempt in 1 2 3; do
    echo "==> $label attempt=$attempt" >&2
    if out="$("${VERCEL[@]}" deploy --prod --skip-domain --yes --no-wait "$@" 2>&1)"; then
      printf '%s\n' "$out" >&2
      url="$(printf '%s\n' "$out" | grep -Eo 'https://[^[:space:]]+\.vercel\.app' | tail -n 1 || true)"
      if [ -n "$url" ]; then
        # `deploy --no-wait` returns while Vercel may still be processing.
        # Wait on that exact deployment so retries never create duplicates.
        if "${VERCEL[@]}" inspect "$url" --wait --timeout=5m >/dev/null 2>&1; then
          printf '%s\n' "$url"
          return 0
        fi
        echo "$label did not reach READY within 5 minutes: $url" >&2
        "${VERCEL[@]}" remove "$url" --yes >/dev/null 2>&1 || true
      else
        echo "$label returned no parseable Vercel deployment URL" >&2
      fi
    else
      printf '%s\n' "$out" >&2
    fi
    sleep $((attempt * 5))
  done
  echo "$label failed after 3 attempts" >&2
  return 1
}

echo "==> Create isolated bootstrap deployment"
BOOTSTRAP_URL="$(deploy_isolated "bootstrap deployment"   --env RELEASE_GIT_REF=main   --env RELEASE_GIT_SHA="$HEAD_SHA"   --env RELEASE_BOOTSTRAP_TOKEN="$BOOTSTRAP_TOKEN")"

test -n "$BOOTSTRAP_URL"
"${VERCEL[@]}" curl "${BOOTSTRAP_URL}/api/internal/release-bootstrap" -X POST -H "X-Release-Bootstrap-Token: $BOOTSTRAP_TOKEN" --fail-with-body > "$TMP_DIR/bootstrap.json"

python - <<'PY'
import json
from pathlib import Path
x=json.loads(Path(".git/release-tmp/bootstrap.json").read_text())
if x.get("status") != "ok" or x.get("runtime_bootstrap") != "applied":
    raise SystemExit(f"Runtime bootstrap failed: {x}")
print("Runtime bootstrap passed")
PY

echo "==> Stage production deployment without bootstrap credential"
STAGE_URL="$(deploy_isolated "staged production deployment"   --env RELEASE_GIT_REF=main   --env RELEASE_GIT_SHA="$HEAD_SHA")"
test -n "$STAGE_URL"

"${VERCEL[@]}" curl "${STAGE_URL}/health" --fail-with-body > "$TMP_DIR/stage-health.json"
"${VERCEL[@]}" curl "${STAGE_URL}/health/ready" --fail-with-body > "$TMP_DIR/stage-ready.json"
"${VERCEL[@]}" curl "${STAGE_URL}/api/admin/session" --fail-with-body > "$TMP_DIR/stage-admin-session.json"

python - <<'PY'
import json
from pathlib import Path
from app.version import APPLICATION_VERSION

health=json.loads(Path(".git/release-tmp/stage-health.json").read_text())
ready=json.loads(Path(".git/release-tmp/stage-ready.json").read_text())
if health.get("status") != "ok":
    raise SystemExit(f"staged /health failed: {health}")
if ready.get("status") != "ready":
    raise SystemExit(f"staged /health/ready failed: {ready}")
if health.get("version") != APPLICATION_VERSION or ready.get("version") != APPLICATION_VERSION:
    raise SystemExit(f"staged version drift: health={health} ready={ready}")
if ready.get("content_ingestion") != "locked":
    raise SystemExit(f"content ingestion must stay locked: {ready}")
session=json.loads(Path(".git/release-tmp/stage-admin-session.json").read_text())
if session.get("configured") is not True:
    raise SystemExit("Staged ADMIN_API_KEY is not configured at runtime")
print(f"Staged health and ADMIN_API_KEY presence checks passed for {APPLICATION_VERSION}")
PY

echo "Verified staged deployment: $STAGE_URL"

if [ "$PROMOTE" -ne 1 ]; then
  echo "Stage-only mode complete. Canonical production was NOT changed."
  echo "Re-run from the same clean main SHA with --promote to promote after verification."
  exit 0
fi

echo "==> Promote verified deployment"
"${VERCEL[@]}" promote "$STAGE_URL" --yes

curl --fail --silent --show-error "$PRODUCTION_URL/health" > "$TMP_DIR/prod-health.json"
curl --fail --silent --show-error "$PRODUCTION_URL/health/ready" > "$TMP_DIR/prod-ready.json"
curl --fail --silent --show-error "$PRODUCTION_URL/api/admin/session" > "$TMP_DIR/prod-admin-session.json"

python - <<'PY'
import json
from pathlib import Path
from app.version import APPLICATION_VERSION

health=json.loads(Path(".git/release-tmp/prod-health.json").read_text())
ready=json.loads(Path(".git/release-tmp/prod-ready.json").read_text())
if health.get("status") != "ok" or ready.get("status") != "ready":
    raise SystemExit(f"Production smoke failed: health={health} ready={ready}")
if health.get("version") != APPLICATION_VERSION or ready.get("version") != APPLICATION_VERSION:
    raise SystemExit(f"Production version drift: health={health} ready={ready}")
if ready.get("content_ingestion") != "locked":
    raise SystemExit(f"Production content ingestion must stay locked: {ready}")
session=json.loads(Path(".git/release-tmp/prod-admin-session.json").read_text())
if session.get("configured") is not True:
    raise SystemExit("Production ADMIN_API_KEY is not configured after promotion")
print(f"Production health and ADMIN_API_KEY presence checks passed for {APPLICATION_VERSION}")
PY

echo "Production release complete: $PRODUCTION_URL"
