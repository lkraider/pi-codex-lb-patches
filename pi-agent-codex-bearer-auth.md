# Pi Agent Codex Bearer Auth Patch

## Context

This is a local workaround for using Pi Agent with `codex-lb` through Pi's `openai-codex-responses` API path.

Pi already supports `api: "openai-codex-responses"` in `models.json`, but the provider code assumes the API key is a ChatGPT OAuth JWT and tries to extract `chatgpt_account_id`. `codex-lb` uses a plain bearer key such as `sk-clb-...`, so Pi fails before reaching the proxy with:

```text
Error: Failed to extract accountId from token
```

The workaround makes account-id extraction optional:

- JWT tokens still get `chatgpt-account-id`.
- Non-JWT bearer tokens skip `chatgpt-account-id`.
- `Authorization: Bearer <apiKey>` is still sent.

## Why the old patch stopped working (important)

The original patch only edited `node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js`.
That worked on older releases because the CLI loaded `pi-ai` from `node_modules` at runtime.

**In current releases the `pi` CLI (`dist/bundle/cli.js`) is a self-contained esbuild bundle.** It no longer
loads `pi-ai` from `node_modules` — the codex stream code is inlined into
`dist/bundle/chunks/openai-codex-responses-<hash>.js`. Patching only `pi-ai`'s dist therefore fixes
library/SDK consumers but **not the CLI**, and the error persists.

The bundle chunk also has a content-hash filename that changes on every release, so a fixed
`.patch` file cannot be reapplied reliably after updates.

## Apply

### Recommended: run the reapply script

```sh
~/Desktop/reapply-codex-bearer-auth.sh
```

The script:

- Locates the current codex-responses bundle chunk by content marker (hash-proof).
- Makes `extractAccountId` non-throwing and the `chatgpt-account-id` header conditional, in minified form.
- Also applies the original patch to `pi-ai`'s dist (harmless, keeps SDK consumers working).
- Is idempotent: safe to run after every `pi update`, reinstall, or asdf Node version change.

It resolves the package root via `npm root -g`; pass an explicit path if needed:

```sh
~/Desktop/reapply-codex-bearer-auth.sh /path/to/@earendil-works/pi-coding-agent
```

### Manual one-liners (equivalent)

```sh
cd "$(npm root -g)/@earendil-works/pi-coding-agent"
CHUNK=$(grep -l 'let accountId=extractAccountId(apiKey)' dist/bundle/chunks/*.js | head -1)
sed -i '' 's/catch{throw new Error("Failed to extract accountId from token")}/catch{return void 0}/' "$CHUNK"
sed -i '' 's/headers.set("chatgpt-account-id",accountId)/accountId\&\&headers.set("chatgpt-account-id",accountId)/' "$CHUNK"
```

## Expected models.json Shape

```json
{
  "providers": {
    "codex-lb": {
      "baseUrl": "http://127.0.0.1:2455/backend-api",
      "apiKey": "CODEX_LB_API_KEY",
      "api": "openai-codex-responses",
      "models": [
        {
          "id": "gpt-5.5",
          "reasoning": true,
          "contextWindow": 272000,
          "maxTokens": 128000
        }
      ]
    }
  }
}
```

## Verify

```sh
pi --list-models codex-lb
pi --provider codex-lb --model gpt-5.5 --thinking low --no-tools --no-session -p "Reply with exactly: ok"
```

Expected response:

```text
ok
```

## Notes

- This edits Pi's installed package in the global `node_modules`, so `pi update`, reinstalling Pi, or
  changing Node/asdf versions may overwrite it. Re-run `reapply-codex-bearer-auth.sh` after updates.
- The OAuth module (`dist/bundle/chunks/openai-codex.js`, `dist/auth/oauth/openai-codex.js`) throws the
  same message, but only during real ChatGPT OAuth login/refresh — not for `apiKey`-based providers like
  `codex-lb`. No patch needed there.
