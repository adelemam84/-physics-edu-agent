#!/usr/bin/env bash
set -euo pipefail

# Zero-cost manual EDU-001/EDU-003 maintenance runner.
# Runs only against an isolated Vercel production deployment (--skip-domain).
# It may temporarily enable content ingestion on that isolated deployment only.
# It never promotes traffic and never auto-approves visual question transcriptions.

VERCEL_CLI_VERSION="${VERCEL_CLI_VERSION:-59.17.0}"
PROJECT_ID="${VERCEL_PROJECT_ID:-prj_YVuUR2a1VFpZQwdXmUwTRpGbE1sL}"
ORG_ID="${VERCEL_ORG_ID:-team_GsqjHJAXTirB3YVlUto63rma}"
EXPECTED_SHA=""
EVIDENCE_DIR="${EVIDENCE_DIR:-maintenance-evidence/manual-$(date -u +%Y%m%dT%H%M%SZ)}"

usage() {
  cat <<'EOF'
Usage:
  tools/manual_content_maintenance.sh [--expected-sha <sha>]

Runs EDU-001 source coverage (only when incomplete) and EDU-003 source-grounded
visual transcription assistance through an isolated Vercel deployment.

Safety:
- requires clean main
- never promotes a deployment
- canonical production content ingestion remains untouched
- visual suggestions remain advisory and require human review
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --expected-sha)
      EXPECTED_SHA="${2:-}"
      shift 2
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
  echo "Maintenance must run from main" >&2
  exit 1
fi

HEAD_SHA="$(git rev-parse HEAD)"
if [ -n "$EXPECTED_SHA" ] && [ "$EXPECTED_SHA" != "$HEAD_SHA" ]; then
  echo "Expected SHA $EXPECTED_SHA but current HEAD is $HEAD_SHA" >&2
  exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=all)" ]; then
  echo "Maintenance workspace must be clean" >&2
  git status --short >&2
  exit 1
fi

echo "==> Compile maintenance runtime and run deterministic tests"
python -m compileall -q app index.py status.py
python -m unittest tests.test_content_completion_contract   tests.test_visual_review_source_page_fallback   tests.test_visual_review_triage   tests.test_visual_review_model_failover   -v

VERCEL=(npx --yes "vercel@${VERCEL_CLI_VERSION}")
export VERCEL_PROJECT_ID="$PROJECT_ID"
export VERCEL_ORG_ID="$ORG_ID"

echo "==> Pull production configuration"
"${VERCEL[@]}" pull --yes --environment=production

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

mkdir -p "$EVIDENCE_DIR"
MAINT_TOKEN="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
DEPLOYMENT_URL=""

cleanup() {
  if [ -n "$DEPLOYMENT_URL" ]; then
    "${VERCEL[@]}" remove "$DEPLOYMENT_URL" --yes >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> Create isolated maintenance deployment"
OUT="$("${VERCEL[@]}" deploy --prebuilt --prod --skip-domain --yes   --env RELEASE_GIT_REF=main   --env RELEASE_GIT_SHA="$HEAD_SHA"   --env CONTENT_INGESTION_ENABLED=true   --env CONTENT_MAINTENANCE_TOKEN="$MAINT_TOKEN"   --env AI_FREE_ONLY=true)"
DEPLOYMENT_URL="$(printf '%s\n' "$OUT" | grep -Eo 'https://[^[:space:]]+\.vercel\.app' | tail -n 1 || true)"
test -n "$DEPLOYMENT_URL"

echo "==> Wait for isolated deployment readiness"
"${VERCEL[@]}" inspect "$DEPLOYMENT_URL" --wait

vcurl() {
  local path="$1"
  shift
  "${VERCEL[@]}" curl "$path" --deployment "$DEPLOYMENT_URL" --     --header "X-Content-Maintenance-Token: $MAINT_TOKEN"     "$@"
}

echo "==> Capture pre-maintenance status"
vcurl "/api/internal/content-maintenance/status" --fail-with-body > "$EVIDENCE_DIR/pre-status.json"

read -r covered total < <(python - "$EVIDENCE_DIR/pre-status.json" <<'PY'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
print(int(data.get("covered_lessons") or 0), int(data.get("total_lessons") or 0))
PY
)

run_source() {
  local key="$1"
  echo "==> Register/extract/map source: $key"
  vcurl "/api/internal/content-maintenance/source/$key/register"     --request POST --fail-with-body > "$EVIDENCE_DIR/$key-register.json"

  read -r doc_id page_count < <(python - "$EVIDENCE_DIR/$key-register.json" <<'PY'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
doc=data["document"]
print(int(doc["id"]), int(doc["page_count"]))
PY
)

  : > "$EVIDENCE_DIR/$key-extract.jsonl"
  local start=1
  while [ "$start" -le "$page_count" ]; do
    vcurl "/api/internal/content-maintenance/source/$key/extract?document_id=$doc_id&start_page=$start"       --request POST --fail-with-body >> "$EVIDENCE_DIR/$key-extract.jsonl"
    printf '\n' >> "$EVIDENCE_DIR/$key-extract.jsonl"
    start=$((start + 15))
  done

  vcurl "/api/internal/content-maintenance/source/$key/map?document_id=$doc_id"     --request POST --fail-with-body > "$EVIDENCE_DIR/$key-map.json"
}

if [ "$total" -gt 0 ] && [ "$covered" -eq "$total" ]; then
  echo "EDU-001 already complete ($covered/$total); source import skipped."
else
  run_source electrical
  run_source modern
fi

echo "==> Read pending EDU-003 queue"
vcurl "/api/internal/content-maintenance/visual-pending" --fail-with-body > "$EVIDENCE_DIR/visual-pending.json"

python - "$EVIDENCE_DIR/visual-pending.json" <<'PY' > "$EVIDENCE_DIR/visual-ids.txt"
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
for qid in data.get("question_ids", []):
    print(int(qid))
PY

: > "$EVIDENCE_DIR/visual-results.jsonl"
: > "$EVIDENCE_DIR/visual-errors.txt"
processed=0
failed=0

while read -r qid; do
  [ -n "$qid" ] || continue
  echo "==> EDU-003 question $qid"
  if vcurl "/api/internal/content-maintenance/visual/$qid"       --request POST --max-time 270 --fail-with-body > /tmp/visual-one.json; then
    python - /tmp/visual-one.json "$qid" <<'PY'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
if data.get("status") != "suggested":
    raise SystemExit(f"question {sys.argv[2]} did not produce a suggestion: {data}")
PY
    cat /tmp/visual-one.json >> "$EVIDENCE_DIR/visual-results.jsonl"
    printf '\n' >> "$EVIDENCE_DIR/visual-results.jsonl"
    processed=$((processed + 1))
  else
    echo "$qid" >> "$EVIDENCE_DIR/visual-errors.txt"
    failed=$((failed + 1))
  fi
done < "$EVIDENCE_DIR/visual-ids.txt"

echo "EDU-003 processed=$processed failed=$failed"

echo "==> Capture and validate final maintenance state"
vcurl "/api/internal/content-maintenance/status" --fail-with-body > "$EVIDENCE_DIR/final-status.json"

python - "$EVIDENCE_DIR/final-status.json" <<'PY'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
covered=int(data.get("covered_lessons") or 0)
total=int(data.get("total_lessons") or 0)
if total <= 0 or covered != total:
    raise SystemExit(f"EDU-001 source coverage incomplete: {covered}/{total}")
queue=data.get("visual_queue") or {}
missing=int(queue.get("without_suggestion") or 0)
if missing:
    raise SystemExit(f"EDU-003 incomplete: {missing} candidates still have no suggestion")
if data.get("policy") != "source_grounded_only_no_visual_auto_approval":
    raise SystemExit(f"Unexpected maintenance policy: {data.get('policy')}")
print(json.dumps(data,ensure_ascii=False,indent=2))
print("Manual EDU maintenance gates passed. Human visual review is still required.")
PY

echo "Evidence saved to: $EVIDENCE_DIR"
echo "Canonical production was NOT promoted or modified by this runner."
