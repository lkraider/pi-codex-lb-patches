#!/usr/bin/env node
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const providerPath = process.argv[2];
if (!providerPath) {
  console.error("Usage: bearer-auth.mjs PROVIDER");
  process.exit(2);
}

let requestHeaders;
class MockWebSocket extends EventTarget {
  constructor(_url, options) {
    super();
    requestHeaders = options?.headers ?? {};
    this.readyState = 0;
    queueMicrotask(() => {
      this.readyState = 1;
      this.dispatchEvent(new Event("open"));
    });
  }

  send() {
    queueMicrotask(() => this.dispatchEvent(new MessageEvent("message", {
      data: JSON.stringify({
        type: "response.completed",
        response: {
          id: "resp_ok",
          status: "completed",
          output: [],
          usage: {
            input_tokens: 1,
            output_tokens: 1,
            input_tokens_details: { cached_tokens: 0 },
            output_tokens_details: { reasoning_tokens: 0 },
            total_tokens: 2,
          },
        },
      }),
    })));
  }

  close() {
    this.readyState = 3;
  }
}

globalThis.WebSocket = MockWebSocket;
const moduleUrl = `${pathToFileURL(providerPath).href}?test=${Date.now()}`;
const { stream, closeOpenAICodexWebSocketSessions } = await import(moduleUrl);
const model = {
  id: "gpt-6-astra",
  name: "GPT-6 Astra",
  api: "openai-codex-responses",
  provider: "codex-lb",
  baseUrl: "http://127.0.0.1:2455/backend-api",
  reasoning: true,
  input: ["text"],
  cost: { input: 10, output: 50, cacheRead: 1, cacheWrite: 12.5 },
  contextWindow: 272000,
  maxTokens: 128000,
};
const context = {
  systemPrompt: "Test",
  messages: [{ role: "user", content: "hello", timestamp: Date.now() }],
};

const events = [];
for await (const event of stream(model, context, {
  apiKey: "opaque-codex-lb-token",
  sessionId: "bearer-test",
  transport: "websocket",
})) events.push(event);

const normalizedHeaders = Object.fromEntries(
  Object.entries(requestHeaders).map(([name, value]) => [name.toLowerCase(), value]),
);
assert.equal(normalizedHeaders.authorization, "Bearer opaque-codex-lb-token");
assert.equal(normalizedHeaders["chatgpt-account-id"], undefined);
assert.equal(events.at(-1)?.type, "done");
closeOpenAICodexWebSocketSessions("bearer-test");
console.log(`${providerPath}: opaque bearer auth ok`);
