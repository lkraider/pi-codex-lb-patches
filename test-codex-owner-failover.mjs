#!/usr/bin/env node
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const providerPath = process.argv[2];
const mode = process.argv[3] ?? "recover";
if (!providerPath || !["recover", "partial-output", "explicit-anchor"].includes(mode)) {
  console.error("Usage: test-codex-owner-failover.mjs /path/to/openai-codex-responses.js [recover|partial-output|explicit-anchor]");
  process.exit(2);
}

const sockets = [];
const sentBodies = [];

class MockWebSocket extends EventTarget {
  constructor(_url, options) {
    super();
    this.readyState = 0;
    this.headers = options?.headers ?? {};
    this.index = sockets.length;
    sockets.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.dispatchEvent(new Event("open"));
    });
  }

  send(raw) {
    sentBodies.push(JSON.parse(raw));
    const emit = (event) => queueMicrotask(() => this.dispatchEvent(new MessageEvent("message", {
      data: JSON.stringify(event)
    })));
    if (this.index === 0) {
      if (mode === "partial-output") {
        emit({
          type: "response.output_item.added",
          output_index: 0,
          item: { id: "msg_partial", type: "message", role: "assistant", status: "in_progress", content: [] }
        });
      }
      emit({
        type: "response.failed",
        response: {
          status: "failed",
          error: {
            code: "previous_response_owner_unavailable",
            message: "Previous response owner account is unavailable; retry later."
          }
        }
      });
      return;
    }
    emit({
      type: "response.completed",
      response: {
        id: "resp_recovered",
        status: "completed",
        output: [],
        usage: {
          input_tokens: 10,
          output_tokens: 2,
          input_tokens_details: { cached_tokens: 0 },
          output_tokens_details: { reasoning_tokens: 0 },
          total_tokens: 12
        }
      }
    });
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
  maxTokens: 128000
};
const context = {
  systemPrompt: "Test",
  messages: [{ role: "user", content: "hello", timestamp: Date.now() }]
};

const events = [];
const options = {
  apiKey: "sk-clb-test",
  sessionId: "original-session",
  transport: "websocket"
};
if (mode === "explicit-anchor") {
  options.onPayload = (body) => ({ ...body, previous_response_id: "resp_explicit" });
}
for await (const event of stream(model, context, options)) {
  events.push(event);
}

if (mode === "recover") {
  assert.equal(sockets.length, 2, "owner loss should open one replacement WebSocket");
  assert.equal(sentBodies.length, 2, "owner loss should retry exactly once");
  assert.notEqual(sockets[0].headers["session-id"], sockets[1].headers["session-id"]);
  assert.equal(sentBodies[0].previous_response_id, undefined);
  assert.equal(sentBodies[1].previous_response_id, undefined);
  assert.deepEqual(sentBodies[1].input, sentBodies[0].input, "retry must resend full local history");
  assert.equal(sentBodies[1].prompt_cache_key, sockets[1].headers["session-id"]);
  assert.equal(events.at(-1)?.type, "done");
  assert.equal(events.at(-1)?.message?.responseId, "resp_recovered");
} else {
  assert.equal(sockets.length, 1, `${mode} must not open a replacement WebSocket`);
  assert.equal(sentBodies.length, 1, `${mode} must not retry`);
  assert.equal(events.at(-1)?.type, "error");
  if (mode === "explicit-anchor")
    assert.equal(sentBodies[0].previous_response_id, "resp_explicit");
}
closeOpenAICodexWebSocketSessions("original-session");
console.log(`${providerPath}: ${mode} ok`);
