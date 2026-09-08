# Pi Agent Codex Transient Recovery Patch

## Problem

Pi's `openai-codex-responses` WebSocket loop hard-stops most in-band `response.failed` and top-level `error` frames because they become `CodexApiError` instances. The outer coding-agent retry layer only receives the formatted message and cannot classify the retained Responses error type.

This is the gap described in [earendil-works/pi#7444](https://github.com/earendil-works/pi/issues/7444). Its concrete codex-lb example is:

```json
{
  "type": "response.failed",
  "response": {
    "error": {
      "type": "server_error",
      "code": "upstream_unavailable",
      "message": "Previous response owner account is unavailable; retry later."
    }
  }
}
```

codex-lb may be unable to move a continuation inside a tool-call/tool-result turn even when another account is healthy. A manual retry also reuses Pi's original `session-id`, leaving the request pinned to the unavailable owner.

## Recovery Boundary

The patch inspects the original event retained in `CodexApiError.payload`. It classifies both `response.failed` and top-level `error` frames whose semantic error type is `server_error`, plus the explicit transient code `rate_limit_exceeded`. The known owner-unavailable code and message remain fallbacks for codex-lb paths that rewrite or omit the type.

A matching error is retried at most once, and only when:

- no assistant output has been emitted,
- Pi's complete request body has no explicit `previous_response_id`, and
- a stable session identity exists to rotate.

Recovery closes the failed WebSocket, generates a replacement `session-id` and matching `prompt_cache_key`, and resends Pi's complete unanchored local history. The replacement identity remains sticky for subsequent turns in the same Pi process.

## Fail-Closed Cases

The patch deliberately does not retry:

- transport/protocol failures such as `Upstream websocket closed before response.completed`,
- `stream_incomplete` or `Suppressed duplicate side-effect tool call`,
- an operation-in-progress/cooldown response,
- client, authentication, permission, policy, and other non-`server_error` failures,
- any failure after assistant output starts, or
- a request with an explicit top-level `previous_response_id`.

This is narrower than retrying every unknown Codex error. In particular, it does not bypass codex-lb's duplicate-side-effect or still-running-operation safeguards.

## Files

- `reapply-codex-transient-recovery.sh` locates the installed Pi package and validates the result.
- `patch-codex-transient-recovery.py` applies guarded transformations to the minified CLI bundle and readable `pi-ai` distribution.
- `test-codex-transient-recovery.mjs` exercises recovery and fail-closed cases with a mock WebSocket.

The bearer-auth workaround remains independent in `reapply-codex-bearer-auth.sh`. The patcher automatically upgrades the earlier owner-only workaround if it is already installed.

## Apply

```sh
cd ~/Desktop/gen-ai/pi-agent-patch
./reapply-codex-transient-recovery.sh
```

Pass an explicit Pi package root when needed:

```sh
./reapply-codex-transient-recovery.sh /path/to/@earendil-works/pi-coding-agent
```

Restart Pi after applying the patch. Reapply it after `pi update`, reinstalling Pi, or changing Node/asdf versions.

## Verification

The patcher is idempotent, validates every requested target before writing, and fails if upstream markers no longer match. The reapply script runs `node --check` against every modified JavaScript file.

Run the mock suite against both installed copies:

```sh
PKG="$(npm root -g)/@earendil-works/pi-coding-agent"
API="$PKG/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js"
CHUNK=$(grep -l 'isRetryableCodexServerError' "$PKG"/dist/bundle/chunks/*.js | head -1)
MODES="server-error top-level-server-error rate-limit owner-fallback partial-output explicit-anchor client-error stream-incomplete operation-in-progress repeated-server-error"

for TARGET in "$API" "$CHUNK"; do
  for MODE in $MODES; do
    ./test-codex-transient-recovery.mjs "$TARGET" "$MODE"
  done
done
```
