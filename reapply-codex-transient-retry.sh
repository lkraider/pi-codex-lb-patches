#!/usr/bin/env bash
# Apply the minimal general Codex transient-retry patch to installed Pi.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PATCHER="$SCRIPT_DIR/patch-codex-transient-retry.py"
PKG="${1:-$(npm root -g)/@earendil-works/pi-coding-agent}"

[[ -d "$PKG" ]] || { echo "ERROR: Pi package not found: $PKG" >&2; exit 1; }
[[ -f "$PATCHER" ]] || { echo "ERROR: patcher not found: $PATCHER" >&2; exit 1; }

CHUNK="$(grep -l 'PREVIOUS_RESPONSE_NOT_FOUND_CODE' "$PKG"/dist/bundle/chunks/*.js 2>/dev/null | head -1 || true)"
[[ -n "$CHUNK" ]] || { echo "ERROR: Codex Responses bundle not found" >&2; exit 1; }
API="$PKG/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js"
ARGS=(--bundle "$CHUNK")
[[ ! -f "$API" ]] || ARGS+=(--readable "$API")

python3 "$PATCHER" "${ARGS[@]}"
grep -q 'retriedCodexServerError' "$CHUNK"
node --check "$CHUNK"
if [[ -f "$API" ]]; then
  grep -q 'retriedCodexServerError' "$API"
  node --check "$API"
fi

echo "General Codex transient retry applied."
