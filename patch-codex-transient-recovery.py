#!/usr/bin/env python3
"""Patch Pi's Codex provider for safe transient server-error recovery."""

from __future__ import annotations

import argparse
from pathlib import Path

PATCH_MARKER = "isRetryableCodexServerError"
LEGACY_PATCH_MARKER = "isPreviousResponseOwnerUnavailableError"
COMMON_PATCH_MARKERS = (
    "originalCacheSessionId",
    "retriedCodexServerError",
    "codexApiErrorType",
    "isRetryableCodexServerError",
    "codexSessionAliases",
    "closeWebSocketSessionEntries",
)


def is_complete_patch(text: str, kind: str) -> bool:
    if PATCH_MARKER not in text:
        return False
    output_guard = "output.content.length === 0" if kind == "readable" else "output.content.length===0"
    rate_limit_guard = 'error.code === "rate_limit_exceeded"' if kind == "readable" else 'error.code==="rate_limit_exceeded"'
    missing = [marker for marker in (*COMMON_PATCH_MARKERS, output_guard, rate_limit_guard) if marker not in text]
    if missing:
        raise RuntimeError(f"{kind}: partial transient-recovery patch; missing {', '.join(missing)}")
    return True


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one upstream marker, found {count}")
    return text.replace(old, new, 1)

READABLE_SERVER_ERROR_CLASSIFIER = '''function codexApiErrorType(error) {
    const payload = error.payload;
    if (!payload || typeof payload !== "object")
        return undefined;
    const errorType = payload.type === "response.failed"
        ? payload.response?.error?.type
        : payload.type === "error" && payload.error && typeof payload.error === "object"
            ? payload.error.type
            : undefined;
    return typeof errorType === "string" ? errorType : undefined;
}
function isRetryableCodexServerError(error) {
    if (!(error instanceof CodexApiError))
        return false;
    if (error.code === PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE || error.code === "rate_limit_exceeded" ||
        /Previous response owner account is unavailable/i.test(error.message))
        return true;
    if (error.code === "stream_incomplete" || error.code === "previous_response_operation_in_progress" ||
        /previous response operation may still be running|Suppressed duplicate side-effect tool call/i.test(error.message))
        return false;
    return codexApiErrorType(error) === "server_error";
}'''

MINIFIED_SERVER_ERROR_CLASSIFIER = 'function codexApiErrorType(error){let payload=error.payload;if(!payload||typeof payload!=="object")return;let errorType=payload.type==="response.failed"?payload.response?.error?.type:payload.type==="error"&&payload.error&&typeof payload.error==="object"?payload.error.type:void 0;return typeof errorType==="string"?errorType:void 0}function isRetryableCodexServerError(error){return error instanceof CodexApiError?error.code===PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE||error.code==="rate_limit_exceeded"||/Previous response owner account is unavailable/i.test(error.message)?!0:error.code==="stream_incomplete"||error.code==="previous_response_operation_in_progress"||/previous response operation may still be running|Suppressed duplicate side-effect tool call/i.test(error.message)?!1:codexApiErrorType(error)==="server_error":!1}'


def migrate_legacy_patch(text: str, kind: str) -> str:
    if LEGACY_PATCH_MARKER not in text:
        return text
    text = text.replace("retriedPreviousResponseOwnerUnavailable", "retriedCodexServerError")
    text = text.replace("previousResponseOwnerUnavailable", "retryableCodexServerError")
    text = text.replace("isPreviousResponseOwnerUnavailableError", "isRetryableCodexServerError")
    if kind == "readable":
        old = '''function isRetryableCodexServerError(error) {
    return error instanceof CodexApiError &&
        (error.code === PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE ||
            /Previous response owner account is unavailable/i.test(error.message));
}'''
        new = READABLE_SERVER_ERROR_CLASSIFIER
    else:
        old = 'function isRetryableCodexServerError(error){return error instanceof CodexApiError&&(error.code===PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE||/Previous response owner account is unavailable/i.test(error.message))}'
        new = MINIFIED_SERVER_ERROR_CLASSIFIER
    return replace_once(text, old, new, f"{kind} legacy classifier migration")


def upgrade_generic_patch(text: str, kind: str) -> str:
    if PATCH_MARKER not in text:
        return text
    if kind == "readable" and 'error.code === "rate_limit_exceeded"' not in text:
        return replace_once(
            text,
            "error.code === PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE ||\n        /Previous response owner account",
            'error.code === PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE || error.code === "rate_limit_exceeded" ||\n        /Previous response owner account',
            "readable rate-limit upgrade",
        )
    if kind == "bundle" and 'error.code==="rate_limit_exceeded"' not in text:
        return replace_once(
            text,
            "error.code===PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE||/Previous response owner account",
            'error.code===PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE||error.code==="rate_limit_exceeded"||/Previous response owner account',
            "bundle rate-limit upgrade",
        )
    return text


def patch_readable(text: str) -> str:
    text = upgrade_generic_patch(migrate_legacy_patch(text, "readable"), "readable")
    if is_complete_patch(text, "readable"):
        return text

    text = replace_once(
        text,
        'const PREVIOUS_RESPONSE_NOT_FOUND_CODE = "previous_response_not_found";',
        'const PREVIOUS_RESPONSE_NOT_FOUND_CODE = "previous_response_not_found";\n'
        'const PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE = "previous_response_owner_unavailable";',
        "readable error constant",
    )
    text = replace_once(
        text,
        '''            const cacheSessionId = options?.cacheRetention === "none" ? undefined : options?.sessionId;
            const codexSessionId = clampOpenAIPromptCacheKey(cacheSessionId);
            let body = buildRequestBody(model, context, options, codexSessionId, grammarToolInputProperties);
            const nextBody = await options?.onPayload?.(body, model);
            if (nextBody !== undefined) {
                body = nextBody;
            }
            const websocketRequestId = codexSessionId || uuidv7();
            const sseHeaders = buildSSEHeaders(model.headers, options?.headers, accountId, apiKey, codexSessionId);
            const websocketHeaders = buildWebSocketHeaders(model.headers, options?.headers, accountId, apiKey, websocketRequestId);
            const bodyJson = JSON.stringify(body);''',
        '''            const originalCacheSessionId = options?.cacheRetention === "none" ? undefined : options?.sessionId;
            let cacheSessionId = resolveCodexSessionAlias(originalCacheSessionId);
            let codexSessionId = clampOpenAIPromptCacheKey(cacheSessionId);
            let body = buildRequestBody(model, context, options, codexSessionId, grammarToolInputProperties);
            const nextBody = await options?.onPayload?.(body, model);
            if (nextBody !== undefined) {
                body = nextBody;
            }
            let websocketRequestId = codexSessionId || uuidv7();
            let sseHeaders = buildSSEHeaders(model.headers, options?.headers, accountId, apiKey, codexSessionId);
            let websocketHeaders = buildWebSocketHeaders(model.headers, options?.headers, accountId, apiKey, websocketRequestId);
            let bodyJson = JSON.stringify(body);''',
        "readable mutable session state",
    )
    text = replace_once(
        text,
        "                let retriedMissingWebSocketContinuation = false;",
        "                let retriedMissingWebSocketContinuation = false;\n"
        "                let retriedCodexServerError = false;",
        "readable retry flag",
    )
    text = replace_once(
        text,
        '''                        const previousResponseNotFound = isPreviousResponseNotFoundError(error);
                        if (!aborted && previousResponseNotFound && !retriedMissingWebSocketContinuation) {''',
        '''                        const previousResponseNotFound = isPreviousResponseNotFoundError(error);
                        const retryableCodexServerError = isRetryableCodexServerError(error);
                        if (!aborted && retryableCodexServerError && !retriedCodexServerError &&
                            output.content.length === 0 && originalCacheSessionId && body.previous_response_id == null) {
                            const previousCodexSessionId = codexSessionId;
                            cacheSessionId = rotateCodexSessionAlias(originalCacheSessionId, cacheSessionId);
                            codexSessionId = clampOpenAIPromptCacheKey(cacheSessionId);
                            if (body.prompt_cache_key === previousCodexSessionId) {
                                body = { ...body, prompt_cache_key: codexSessionId };
                            }
                            websocketRequestId = codexSessionId || uuidv7();
                            sseHeaders = buildSSEHeaders(model.headers, options?.headers, accountId, apiKey, codexSessionId);
                            websocketHeaders = buildWebSocketHeaders(model.headers, options?.headers, accountId, apiKey, websocketRequestId);
                            bodyJson = JSON.stringify(body);
                            retriedCodexServerError = true;
                            continue;
                        }
                        if (!aborted && previousResponseNotFound && !retriedMissingWebSocketContinuation) {''',
        "readable server-error retry",
    )
    text = replace_once(
        text,
        '''function isPreviousResponseNotFoundError(error) {
    return error instanceof CodexApiError && error.code === PREVIOUS_RESPONSE_NOT_FOUND_CODE;
}''',
        '''function isPreviousResponseNotFoundError(error) {
    return error instanceof CodexApiError && error.code === PREVIOUS_RESPONSE_NOT_FOUND_CODE;
}
''' + READABLE_SERVER_ERROR_CLASSIFIER,
        "readable server-error classifier",
    )
    text = replace_once(
        text,
        '''const websocketSessionCache = new Map();
const websocketDebugStats = new Map();
const websocketSseFallbackSessions = new Set();''',
        '''const websocketSessionCache = new Map();
const websocketDebugStats = new Map();
const websocketSseFallbackSessions = new Set();
const codexSessionAliases = new Map();
function resolveCodexSessionAlias(sessionId) {
    return sessionId ? (codexSessionAliases.get(sessionId) ?? sessionId) : undefined;
}
function rotateCodexSessionAlias(sessionId, failedSessionId) {
    const currentSessionId = resolveCodexSessionAlias(sessionId);
    if (!sessionId || !currentSessionId)
        return failedSessionId;
    if (currentSessionId !== failedSessionId)
        return currentSessionId;
    closeWebSocketSessionEntries(failedSessionId);
    websocketSseFallbackSessions.delete(failedSessionId);
    const replacementSessionId = uuidv7();
    codexSessionAliases.set(sessionId, replacementSessionId);
    return replacementSessionId;
}''',
        "readable alias registry",
    )
    text = replace_once(
        text,
        '''export function closeOpenAICodexWebSocketSessions(sessionId) {
    const closeEntry = (entry) => {
        if (entry.idleTimer)
            clearTimeout(entry.idleTimer);
        closeWebSocketSilently(entry.socket, 1000, "debug_close");
    };
    if (sessionId) {
        for (const entry of websocketSessionCache.get(sessionId)?.values() ?? [])
            closeEntry(entry);
        websocketSessionCache.delete(sessionId);
        return;
    }
    for (const accountEntries of websocketSessionCache.values()) {
        for (const entry of accountEntries.values())
            closeEntry(entry);
    }
    websocketSessionCache.clear();
}''',
        '''function closeWebSocketSessionEntries(sessionId) {
    const closeEntry = (entry) => {
        if (entry.idleTimer)
            clearTimeout(entry.idleTimer);
        closeWebSocketSilently(entry.socket, 1000, "debug_close");
    };
    for (const entry of websocketSessionCache.get(sessionId)?.values() ?? [])
        closeEntry(entry);
    websocketSessionCache.delete(sessionId);
}
export function closeOpenAICodexWebSocketSessions(sessionId) {
    if (sessionId) {
        const aliasedSessionId = codexSessionAliases.get(sessionId);
        closeWebSocketSessionEntries(sessionId);
        if (aliasedSessionId && aliasedSessionId !== sessionId)
            closeWebSocketSessionEntries(aliasedSessionId);
        codexSessionAliases.delete(sessionId);
        return;
    }
    for (const cachedSessionId of [...websocketSessionCache.keys()])
        closeWebSocketSessionEntries(cachedSessionId);
    codexSessionAliases.clear();
}''',
        "readable cleanup",
    )
    return text


def patch_minified(text: str) -> str:
    text = upgrade_generic_patch(migrate_legacy_patch(text, "bundle"), "bundle")
    if is_complete_patch(text, "bundle"):
        return text

    text = replace_once(
        text,
        'PREVIOUS_RESPONSE_NOT_FOUND_CODE="previous_response_not_found",CODEX_RESPONSE_STATUSES',
        'PREVIOUS_RESPONSE_NOT_FOUND_CODE="previous_response_not_found",PREVIOUS_RESPONSE_OWNER_UNAVAILABLE_CODE="previous_response_owner_unavailable",CODEX_RESPONSE_STATUSES',
        "bundle error constant",
    )
    text = replace_once(
        text,
        'cacheSessionId=options?.cacheRetention==="none"?void 0:options?.sessionId,codexSessionId=clampOpenAIPromptCacheKey(cacheSessionId),body=buildRequestBody(model,context,options,codexSessionId,grammarToolInputProperties)',
        'originalCacheSessionId=options?.cacheRetention==="none"?void 0:options?.sessionId,cacheSessionId=resolveCodexSessionAlias(originalCacheSessionId),codexSessionId=clampOpenAIPromptCacheKey(cacheSessionId),body=buildRequestBody(model,context,options,codexSessionId,grammarToolInputProperties)',
        "bundle session alias",
    )
    # The declaration is already a comma-separated `let`; bodyJson remains mutable.
    text = replace_once(
        text,
        'retriedMissingWebSocketContinuation=!1;for(;;)',
        'retriedMissingWebSocketContinuation=!1,retriedCodexServerError=!1;for(;;)',
        "bundle retry flag",
    )
    text = replace_once(
        text,
        'previousResponseNotFound=isPreviousResponseNotFoundError(error);if(!aborted&&previousResponseNotFound&&!retriedMissingWebSocketContinuation)',
        'previousResponseNotFound=isPreviousResponseNotFoundError(error),retryableCodexServerError=isRetryableCodexServerError(error);if(!aborted&&retryableCodexServerError&&!retriedCodexServerError&&output.content.length===0&&originalCacheSessionId&&body.previous_response_id==null){let previousCodexSessionId=codexSessionId;cacheSessionId=rotateCodexSessionAlias(originalCacheSessionId,cacheSessionId),codexSessionId=clampOpenAIPromptCacheKey(cacheSessionId),body.prompt_cache_key===previousCodexSessionId&&(body={...body,prompt_cache_key:codexSessionId}),websocketRequestId=codexSessionId||uuidv7(),sseHeaders=buildSSEHeaders(model.headers,options?.headers,accountId,apiKey,codexSessionId),websocketHeaders=buildWebSocketHeaders(model.headers,options?.headers,accountId,apiKey,websocketRequestId),bodyJson=JSON.stringify(body),retriedCodexServerError=!0;continue}if(!aborted&&previousResponseNotFound&&!retriedMissingWebSocketContinuation)',
        "bundle server-error retry",
    )
    text = replace_once(
        text,
        'function isPreviousResponseNotFoundError(error){return error instanceof CodexApiError&&error.code===PREVIOUS_RESPONSE_NOT_FOUND_CODE}',
        'function isPreviousResponseNotFoundError(error){return error instanceof CodexApiError&&error.code===PREVIOUS_RESPONSE_NOT_FOUND_CODE}' + MINIFIED_SERVER_ERROR_CLASSIFIER,
        "bundle server-error classifier",
    )
    text = replace_once(
        text,
        'websocketSessionCache=new Map,websocketDebugStats=new Map,websocketSseFallbackSessions=new Set;',
        'websocketSessionCache=new Map,websocketDebugStats=new Map,websocketSseFallbackSessions=new Set,codexSessionAliases=new Map;function resolveCodexSessionAlias(sessionId){return sessionId?codexSessionAliases.get(sessionId)??sessionId:void 0}function rotateCodexSessionAlias(sessionId,failedSessionId){let currentSessionId=resolveCodexSessionAlias(sessionId);if(!sessionId||!currentSessionId)return failedSessionId;if(currentSessionId!==failedSessionId)return currentSessionId;closeWebSocketSessionEntries(failedSessionId),websocketSseFallbackSessions.delete(failedSessionId);let replacementSessionId=uuidv7();return codexSessionAliases.set(sessionId,replacementSessionId),replacementSessionId}',
        "bundle alias registry",
    )
    text = replace_once(
        text,
        'function closeOpenAICodexWebSocketSessions(sessionId){let closeEntry=entry=>{entry.idleTimer&&clearTimeout(entry.idleTimer),closeWebSocketSilently(entry.socket,1e3,"debug_close")};if(sessionId){for(let entry of websocketSessionCache.get(sessionId)?.values()??[])closeEntry(entry);websocketSessionCache.delete(sessionId);return}for(let accountEntries of websocketSessionCache.values())for(let entry of accountEntries.values())closeEntry(entry);websocketSessionCache.clear()}',
        'function closeWebSocketSessionEntries(sessionId){let closeEntry=entry=>{entry.idleTimer&&clearTimeout(entry.idleTimer),closeWebSocketSilently(entry.socket,1e3,"debug_close")};for(let entry of websocketSessionCache.get(sessionId)?.values()??[])closeEntry(entry);websocketSessionCache.delete(sessionId)}function closeOpenAICodexWebSocketSessions(sessionId){if(sessionId){let aliasedSessionId=codexSessionAliases.get(sessionId);closeWebSocketSessionEntries(sessionId),aliasedSessionId&&aliasedSessionId!==sessionId&&closeWebSocketSessionEntries(aliasedSessionId),codexSessionAliases.delete(sessionId);return}for(let cachedSessionId of[...websocketSessionCache.keys()])closeWebSocketSessionEntries(cachedSessionId);codexSessionAliases.clear()}',
        "bundle cleanup",
    )
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readable", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    if not args.readable and not args.bundle:
        parser.error("provide --readable and/or --bundle")

    plans = []
    for path, kind in ((args.readable, "readable"), (args.bundle, "bundle")):
        if not path:
            continue
        original = path.read_text()
        patched = patch_readable(original) if kind == "readable" else patch_minified(original)
        plans.append((path, original, patched))

    # Validate every requested target before changing either installed copy.
    for path, original, patched in plans:
        if patched != original:
            path.write_text(patched)
        print(f"{path}: {'patched' if patched != original else 'already patched'}")


if __name__ == "__main__":
    main()
