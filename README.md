# Pi codex-lb patches

Readable, local patches for Pi issue [#7444](https://github.com/earendil-works/pi/issues/7444) and codex-lb account failover.

## Changes

The three changes remain separate under `patches/`:

- `bearer-auth.patch` accepts opaque bearer keys while preserving ChatGPT account headers for JWTs.
- `transient-retry.patch` retries one `server_error` or `rate_limit_exceeded` with the same session.
- `owner-migration.patch` handles `Previous response owner account is unavailable; retry later.` by rotating session affinity and resending history. It is layered after the transient retry patch.

Retries fail closed after output starts, with an explicit `previous_response_id`, when the prior operation may still be running, or when duplicate side effects are possible.

| Error | Result |
|---|---|
| Temporary `server_error` | Retry once with the same session |
| `rate_limit_exceeded` | Retry once with the same session |
| Previous owner unavailable | Retry once with new session affinity |
| Partial output or explicit response anchor | Stop |
| Ambiguous operation or duplicate side effect | Stop |
| Client, authentication, permission, or policy error | Stop |

## Apply

Start with a clean upstream Pi installation, then run:

```sh
cd ~/Desktop/gen-ai/pi-agent-patch
./reapply
```

Use another installation with:

```sh
./reapply --package /path/to/@earendil-works/pi-coding-agent
```

Restart existing Pi processes afterward. Re-run the command after Pi updates or reinstalls. It is safe to run repeatedly, but patches that no longer apply cleanly stop with an error rather than guessing.

`reapply` applies standard unified diffs to the readable `pi-ai/dist` provider. `src/rebuild-bundle.mjs` then uses the installed package's esbuild to recreate Pi's complete minified bundle using Pi's upstream build configuration. This replaces fragile handwritten edits to content-hashed chunks. The rebuilt provider chunk is located and checked by a stable source marker.

## GPT-6 Astra model

A codex-lb provider can include:

```json
{
  "id": "gpt-6-astra",
  "name": "GPT-6 Astra",
  "reasoning": true,
  "thinkingLevelMap": {
    "minimal": "low",
    "xhigh": "xhigh",
    "max": "max"
  },
  "input": ["text", "image"],
  "cost": {
    "input": 10,
    "output": 50,
    "cacheRead": 1,
    "cacheWrite": 12.5,
    "tiers": [{
      "inputTokensAbove": 272000,
      "input": 20,
      "output": 75,
      "cacheRead": 2,
      "cacheWrite": 25
    }]
  },
  "contextWindow": 272000,
  "maxTokens": 128000
}
```

## Test

```sh
./tests/run.sh
```

The test runner takes the latest Pi tarball from npm's local cache, installs dependencies offline in a temporary directory, and tests:

- each patch stage and reapplication;
- both readable and rebuilt/minified providers;
- general retry and combined owner migration behavior;
- opaque bearer authentication and fail-closed cases;
- the rebuilt Pi CLI.

Set `PI_TEST_VERSION` to test a specific cached release.

## Layout

```text
patches/  readable unified diffs
src/      patch application and upstream-compatible bundle rebuild
tests/    offline package and behavior tests
reapply   public entry point
```
