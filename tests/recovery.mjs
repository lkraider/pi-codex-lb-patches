#!/usr/bin/env node
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const providerPath = process.argv[2];
const mode = process.argv[3] ?? "server-error";
const profile = process.argv[4] ?? "general";
const genericRecoveryModes = new Set(["server-error", "top-level-server-error", "rate-limit"]);
const failClosedModes = new Set(["partial-output", "explicit-anchor", "client-error", "stream-incomplete", "operation-in-progress"]);
const validModes = new Set([...genericRecoveryModes, ...failClosedModes, "owner-unavailable", "repeated-server-error"]);
if (!providerPath || !validModes.has(mode) || !["general", "combined"].includes(profile)) {
  console.error("Usage: recovery.mjs PROVIDER MODE [general|combined]");
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
      const error = {
        type: mode === "client-error" ? "invalid_request_error" : mode === "rate-limit" ? "rate_limit_error" : "server_error",
        code: mode === "stream-incomplete"
          ? "stream_incomplete"
          : mode === "rate-limit"
            ? "rate_limit_exceeded"
            : mode === "operation-in-progress" || mode === "owner-unavailable"
              ? "upstream_unavailable"
              : "temporary_backend_failure",
        message: mode === "owner-unavailable"
          ? "Previous response owner account is unavailable; retry later."
          : mode === "operation-in-progress"
            ? "The previous response operation may still be running; retry after the cooldown."
            : mode === "stream-incomplete"
              ? "Suppressed duplicate side-effect tool call; upstream response cannot be continued safely."
              : "Temporary server failure"
      };
      if (mode === "owner-unavailable")
        delete error.type;
      emit(mode === "top-level-server-error"
        ? { type: "error", error }
        : { type: "response.failed", response: { status: "failed", error } });
      return;
    }
    if (mode === "repeated-server-error") {
      emit({
        type: "response.failed",
        response: {
          status: "failed",
          error: { type: "server_error", code: "temporary_backend_failure", message: "Still failing" }
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
const options = {
  apiKey: "e30.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdF90ZXN0In19.sig",
  sessionId: "original-session",
  transport: "websocket"
};
if (mode === "explicit-anchor")
  options.onPayload = (body) => ({ ...body, previous_response_id: "resp_explicit" });

const events = [];
for await (const event of stream(model, context, options))
  events.push(event);

const shouldRecover = genericRecoveryModes.has(mode) || (profile === "combined" && mode === "owner-unavailable");
if (shouldRecover) {
  assert.equal(sockets.length, 2, `${mode} should open one replacement WebSocket`);
  assert.equal(sentBodies.length, 2, `${mode} should retry exactly once`);
  if (mode === "owner-unavailable")
    assert.notEqual(sockets[0].headers["session-id"], sockets[1].headers["session-id"], "owner migration must change affinity");
  else
    assert.equal(sockets[0].headers["session-id"], sockets[1].headers["session-id"], "general retry must preserve affinity");
  assert.equal(sentBodies[0].previous_response_id, undefined);
  assert.equal(sentBodies[1].previous_response_id, undefined);
  assert.equal(sentBodies[1].prompt_cache_key, sockets[1].headers["session-id"]);
  assert.deepEqual(sentBodies[1].input, sentBodies[0].input);
  assert.equal(events.at(-1)?.type, "done");
} else if (mode === "repeated-server-error") {
  assert.equal(sockets.length, 2, "general retry must stop after one retry");
  assert.equal(sentBodies.length, 2);
  assert.equal(events.at(-1)?.type, "error");
} else {
  assert.equal(sockets.length, 1, `${mode} must not retry for the ${profile} profile`);
  assert.equal(sentBodies.length, 1);
  assert.equal(events.at(-1)?.type, "error");
}
closeOpenAICodexWebSocketSessions("original-session");
console.log(`${providerPath}: ${profile}/${mode} ok`);
