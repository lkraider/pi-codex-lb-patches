#!/usr/bin/env bash
# Reapply Pi's codex-lb previous-response owner failover workaround.
#
# Usage:
#   ./reapply-codex-owner-failover.sh
#   ./reapply-codex-owner-failover.sh /path/to/@earendil-works/pi-coding-agent
#
# Run after every `pi update`, reinstall, or asdf Node version change.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PATCHER="$SCRIPT_DIR/patch-codex-owner-failover.py"
PKG="${1:-$(npm root -g)/@earendil-works/pi-coding-agent}"

if [[ ! -d "$PKG" ]]; then
  echo "ERROR: pi package not found at: $PKG" >&2
  echo "Find the active package root with: npm root -g && asdf which pi" >&2
  exit 1
fi
if [[ ! -f "$PATCHER" ]]; then
  echo "ERROR: companion patcher not found: $PATCHER" >&2
  exit 1
fi

CHUNK="$(grep -l 'PREVIOUS_RESPONSE_NOT_FOUND_CODE' "$PKG"/dist/bundle/chunks/*.js 2>/dev/null | head -1 || true)"
if [[ -z "$CHUNK" ]]; then
  echo "ERROR: could not locate Pi's openai-codex-responses bundle chunk." >&2
  exit 1
fi

API="$PKG/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js"
ARGS=(--bundle "$CHUNK")
if [[ -f "$API" ]]; then
  ARGS+=(--readable "$API")
else
  echo "NOTE: pi-ai dist copy not found; patching the CLI bundle only."
fi

echo "Patching: $PKG"
echo "Bundle chunk: $(basename "$CHUNK")"
python3 "$PATCHER" "${ARGS[@]}"

grep -q 'PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE' "$CHUNK" || {
  echo "ERROR: owner-failover marker missing from CLI bundle." >&2
  exit 1
}
node --check "$CHUNK"
if [[ -f "$API" ]]; then
  grep -q 'PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE' "$API" || {
    echo "ERROR: owner-failover marker missing from pi-ai dist copy." >&2
    exit 1
  }
  node --check "$API"
fi

echo "Done: owner-unavailable affinity rotation is patched and syntax-valid."
