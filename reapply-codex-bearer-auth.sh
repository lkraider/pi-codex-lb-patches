#!/usr/bin/env bash
# Reapply the codex-lb bearer-auth workaround to the installed pi-coding-agent.
#
# Why this script exists:
#   pi's CLI (dist/bundle/cli.js) is a self-contained esbuild bundle. It does NOT
#   load node_modules/@earendil-works/pi-ai at runtime — the codex stream code is
#   inlined into dist/bundle/chunks/openai-codex-responses-<hash>.js. Patching
#   only pi-ai's dist (as the original patch did) fixes SDK/library consumers but
#   NOT the CLI. The chunk file name contains a content hash and changes on every
#   release, so a unified-diff patch cannot be reapplied reliably. This script
#   locates the chunk by content markers instead, and is idempotent.
#
# Usage:
#   ./reapply-codex-bearer-auth.sh                 # uses `npm root -g`
#   ./reapply-codex-bearer-auth.sh /path/to/@earendil-works/pi-coding-agent
#
# Run it after every `pi update` / reinstall / asdf node version change.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

PKG="${1:-}"
if [[ -z "$PKG" ]]; then
  PKG="$(npm root -g)/@earendil-works/pi-coding-agent"
fi
if [[ ! -d "$PKG" ]]; then
  echo "ERROR: pi package not found at: $PKG" >&2
  echo "Find the active package root with: npm root -g && asdf which pi" >&2
  exit 1
fi
echo "Patching: $PKG"

# ---------------------------------------------------------------------------
# 1) The CLI bundle chunk (the part that actually matters for `pi`).
# ---------------------------------------------------------------------------
CHUNK="$(grep -l 'let accountId=extractAccountId(apiKey)' "$PKG"/dist/bundle/chunks/*.js 2>/dev/null | head -1 || true)"
if [[ -z "$CHUNK" ]]; then
  echo "NOTE: no codex-responses chunk found in dist/bundle/chunks (maybe already patched or build changed)."
  CHUNK="$(grep -l 'extractAccountId(apiKey)' "$PKG"/dist/bundle/chunks/*.js 2>/dev/null | head -1 || true)"
  if [[ -z "$CHUNK" ]]; then
    echo "ERROR: could not locate the codex-responses bundle chunk." >&2
    exit 1
  fi
fi
echo "Bundle chunk: $(basename "$CHUNK")"

if grep -q 'catch{return void 0}' "$CHUNK"; then
  echo "  extractAccountId: already non-throwing"
elif grep -q 'catch{throw new Error("Failed to extract accountId from token")}' "$CHUNK"; then
  sed -i '' 's/catch{throw new Error("Failed to extract accountId from token")}/catch{return void 0}/' "$CHUNK"
  grep -q 'catch{return void 0}' "$CHUNK" || { echo "ERROR: failed to patch extractAccountId" >&2; exit 1; }
  echo "  extractAccountId: now returns undefined instead of throwing"
else
  echo "ERROR: extractAccountId implementation has changed; refusing to claim it was patched." >&2
  exit 1
fi

if grep -q 'accountId&&headers.set("chatgpt-account-id",accountId)' "$CHUNK"; then
  echo "  chatgpt-account-id header: already conditional"
elif grep -q 'headers.set("chatgpt-account-id",accountId)' "$CHUNK"; then
  sed -i '' 's/headers.set("chatgpt-account-id",accountId)/accountId\&\&headers.set("chatgpt-account-id",accountId)/' "$CHUNK"
  grep -q 'accountId&&headers.set("chatgpt-account-id",accountId)' "$CHUNK" || { echo "ERROR: failed to make chatgpt-account-id conditional" >&2; exit 1; }
  echo "  chatgpt-account-id header: now only set when an accountId exists"
else
  echo "ERROR: chatgpt-account-id header implementation has changed; refusing to claim it was patched." >&2
  exit 1
fi

node --check "$CHUNK"
echo "  syntax OK"

# ---------------------------------------------------------------------------
# 2) pi-ai dist copy (used when pi-ai is consumed as a library, e.g. SDK).
#    Apply the original patch file if present, skip when already applied.
# ---------------------------------------------------------------------------
API="$PKG/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js"
PATCH_FILE="$SCRIPT_DIR/pi-agent-codex-bearer-auth.patch"
if [[ ! -f "$API" ]]; then
  echo "NOTE: pi-ai dist copy not found; CLI bundle is patched, but SDK copy was skipped."
elif [[ ! -f "$PATCH_FILE" ]]; then
  echo "ERROR: companion patch file not found: $PATCH_FILE" >&2
  exit 1
elif grep -q 'tryExtractAccountId(apiKey)' "$API"; then
  echo "pi-ai dist: already patched"
else
  (cd "$PKG" && patch -p1 < "$PATCH_FILE")
  echo "pi-ai dist: patched"
fi

echo "Done. Verify with:"
echo "  pi --list-models codex-lb"
echo "  pi --provider codex-lb --model gpt-5.5 --thinking low --no-tools --no-session -p \"Reply with exactly: ok\""
