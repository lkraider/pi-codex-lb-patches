#!/usr/bin/env bash
# Add codex-lb owner-account migration after the general retry patch.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PATCHER="$SCRIPT_DIR/patch-codex-owner-migration.py"
PKG="${1:-$(npm root -g)/@earendil-works/pi-coding-agent}"

[[ -d "$PKG" ]] || { echo "ERROR: Pi package not found: $PKG" >&2; exit 1; }
[[ -f "$PATCHER" ]] || { echo "ERROR: patcher not found: $PATCHER" >&2; exit 1; }

CHUNK="$(grep -l 'isRetryableCodexServerError' "$PKG"/dist/bundle/chunks/*.js 2>/dev/null | head -1 || true)"
[[ -n "$CHUNK" ]] || { echo "ERROR: apply reapply-codex-transient-retry.sh first" >&2; exit 1; }
API="$PKG/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js"
ARGS=(--bundle "$CHUNK")
[[ ! -f "$API" ]] || ARGS+=(--readable "$API")

python3 "$PATCHER" "${ARGS[@]}"
grep -q 'codexSessionAliases' "$CHUNK"
node --check "$CHUNK"
if [[ -f "$API" ]]; then
  grep -q 'codexSessionAliases' "$API"
  node --check "$API"
fi

echo "codex-lb owner-account migration applied."
