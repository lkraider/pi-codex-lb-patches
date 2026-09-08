# Pi Codex Recovery Patches

Two minimal patches cover separate problems and work together.

## 1. General transient retry

Files:

- `patch-codex-transient-retry.py`
- `reapply-codex-transient-retry.sh`

This implements the core suggestion from [Pi issue #7444](https://github.com/earendil-works/pi/issues/7444).

It retries once, using the same session, for:

- Responses errors marked `server_error`
- `rate_limit_exceeded`

It does not retry owner-account failures. Those are reserved for the second patch so the retry is not wasted on the unavailable account.

It also refuses to retry after output starts, when the request has an explicit `previous_response_id`, when an operation may still be running, or when codex-lb warns about possible duplicate work.

## 2. codex-lb owner-account migration

Files:

- `patch-codex-owner-migration.py`
- `reapply-codex-owner-migration.sh`

This patch requires the general retry patch. It handles only:

```text
Previous response owner account is unavailable; retry later.
```

It changes Pi's session identity, resends the complete conversation, and keeps the new identity for later turns. That allows codex-lb to choose another healthy account.

## Apply both

Start from a clean upstream Pi installation. Older combined or owner-only recovery patches are not upgraded.

The bearer-auth patch remains separate and may be applied independently.

```sh
cd ~/Desktop/gen-ai/pi-agent-patch
./reapply-codex-bearer-auth.sh
./reapply-codex-transient-retry.sh
./reapply-codex-owner-migration.sh
```

Restart Pi afterward. Run the same three scripts after reinstalling or updating Pi. Each script is safe to run again when its own current patch is already present.

## Behavior with both installed

| Error | Result |
|---|---|
| Temporary `server_error` | Retry once with the same session |
| Rate limit | Retry once with the same session |
| Owner account unavailable | Retry once with a new session/account |
| Partial assistant output | Stop |
| Previous operation may still run | Stop |
| Possible duplicate side effect | Stop |
| Client, authentication, permission, or policy error | Stop |

## Tests

`test-codex-transient-retry.mjs` tests both profiles:

- `general` — only the first patch
- `combined` — both patches

The suite covers normal server errors, top-level errors, rate limits, owner loss, repeated failure, partial output, explicit anchors, client errors, incomplete streams, and operations still in progress. Both the readable provider and Pi's bundled provider are tested.
