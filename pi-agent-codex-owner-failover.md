# Pi Agent codex-lb Owner Failover Patch

## Problem

Pi's `openai-codex-responses` provider keeps a WebSocket continuation and sends a stable `session-id`. codex-lb uses that identity to preserve response continuity on one account.

If the account that owns the previous response becomes unavailable, codex-lb normally fails closed with:

```text
Previous response owner account is unavailable; retry later.
```

codex-lb can move some verified full-history requests to another account, but deliberately rejects ambiguous replay shapes. A common rejected shape is a follow-up inside a tool-call/tool-result turn. Retrying from Pi does not help because Pi reuses the same session affinity identity.

## Behavior

This patch changes Pi's Codex WebSocket path for the typed owner-unavailable failure:

1. Retry at most once and only when no explicit `previous_response_id` was supplied in Pi's full request body.
2. Close the failed cached WebSocket.
3. Generate a replacement `session-id` and matching `prompt_cache_key`.
4. Resend Pi's complete local history without a previous-response anchor.
5. Retain the replacement identity for later turns in the same Pi process, restoring normal sticky WebSocket continuation after recovery.

The exact error code is preferred. The known codex-lb message is also recognized because some codex-lb paths wrap the typed code as `upstream_unavailable`.

## Safety Boundary

The patch does **not** automatically retry these ambiguous failures:

- `Upstream websocket closed before response.completed`
- `The previous response operation may still be running; retry after the cooldown.`
- Any failure after assistant output has been delivered
- A request whose top-level body explicitly contains `previous_response_id`

Those failures can represent an upstream operation whose final state is unknown. They need a separate policy rather than being folded into owner failover.

## Files

- `reapply-codex-owner-failover.sh` — locates the installed Pi package and validates the result.
- `patch-codex-owner-failover.py` — guarded transformations for the minified CLI bundle and readable `pi-ai` distribution.

The bearer-auth workaround remains independent in `reapply-codex-bearer-auth.sh`.

## Apply

```sh
cd ~/Desktop/gen-ai/pi-agent-patch
./reapply-codex-owner-failover.sh
```

Pass an explicit Pi package root when needed:

```sh
./reapply-codex-owner-failover.sh /path/to/@earendil-works/pi-coding-agent
```

Restart Pi after applying the patch. Reapply it after `pi update`, reinstalling Pi, or changing Node/asdf versions.

## Verification

The scripts are idempotent and fail if upstream markers no longer match. The reapply script runs `node --check` against every modified JavaScript file.

Run the mock WebSocket test against the readable provider and CLI bundle:

```sh
PKG="$(npm root -g)/@earendil-works/pi-coding-agent"
for MODE in recover partial-output explicit-anchor; do
  ./test-codex-owner-failover.mjs \
    "$PKG/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js" "$MODE"
done
CHUNK=$(grep -l 'PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE' \
  "$PKG"/dist/bundle/chunks/*.js | head -1)
for MODE in recover partial-output explicit-anchor; do
  ./test-codex-owner-failover.mjs "$CHUNK" "$MODE"
done
```

The tests verify successful affinity rotation and prove that partial-output and explicitly anchored requests remain fail-closed.
