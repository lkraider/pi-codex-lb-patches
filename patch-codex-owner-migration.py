#!/usr/bin/env python3
"""Add codex-lb owner-account migration to Pi's transient retry patch."""

from __future__ import annotations

import argparse
from pathlib import Path

GENERAL_MARKER = "isRetryableCodexServerError"
OWNER_MARKERS = (
    "retriedPreviousResponseOwnerUnavailable",
    "codexSessionAliases",
    "rotateCodexSessionAlias",
    "closeWebSocketSessionEntries",
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one general-patch marker, found {count}")
    return text.replace(old, new, 1)


def already_patched(text: str) -> bool:
    found = [marker for marker in OWNER_MARKERS if marker in text]
    if not found:
        return False
    missing = [marker for marker in OWNER_MARKERS if marker not in text]
    if missing:
        raise RuntimeError(f"partial owner-migration patch; missing {', '.join(missing)}")
    return True


def require_general_patch(text: str) -> None:
    if GENERAL_MARKER not in text:
        raise RuntimeError("general transient-retry patch must be applied first")


def patch_readable(text: str) -> str:
    require_general_patch(text)
    if already_patched(text):
        return text
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
        "readable session state",
    )
    text = replace_once(
        text,
        "                let retriedCodexServerError = false;",
        "                let retriedCodexServerError = false;\n"
        "                let retriedPreviousResponseOwnerUnavailable = false;",
        "readable owner retry flag",
    )
    text = replace_once(
        text,
        '''                        const retryableCodexServerError = isRetryableCodexServerError(error);
                        if (!aborted && retryableCodexServerError && !retriedCodexServerError &&''',
        '''                        const retryableCodexServerError = isRetryableCodexServerError(error);
                        const previousResponseOwnerUnavailable = isPreviousResponseOwnerUnavailableError(error);
                        if (!aborted && previousResponseOwnerUnavailable && !retriedPreviousResponseOwnerUnavailable &&
                            output.content.length === 0 && originalCacheSessionId && body.previous_response_id == null) {
                            const previousCodexSessionId = codexSessionId;
                            cacheSessionId = rotateCodexSessionAlias(originalCacheSessionId, cacheSessionId);
                            codexSessionId = clampOpenAIPromptCacheKey(cacheSessionId);
                            if (body.prompt_cache_key === previousCodexSessionId)
                                body = { ...body, prompt_cache_key: codexSessionId };
                            websocketRequestId = codexSessionId || uuidv7();
                            sseHeaders = buildSSEHeaders(model.headers, options?.headers, accountId, apiKey, codexSessionId);
                            websocketHeaders = buildWebSocketHeaders(model.headers, options?.headers, accountId, apiKey, websocketRequestId);
                            bodyJson = JSON.stringify(body);
                            retriedPreviousResponseOwnerUnavailable = true;
                            continue;
                        }
                        if (!aborted && retryableCodexServerError && !retriedCodexServerError &&''',
        "readable owner retry branch",
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
    if (!sessionId || !currentSessionId || currentSessionId !== failedSessionId)
        return currentSessionId ?? failedSessionId;
    closeWebSocketSessionEntries(failedSessionId);
    websocketSseFallbackSessions.delete(failedSessionId);
    const replacementSessionId = uuidv7();
    codexSessionAliases.set(sessionId, replacementSessionId);
    return replacementSessionId;
}''',
        "readable aliases",
    )
    return replace_once(
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


def patch_minified(text: str) -> str:
    require_general_patch(text)
    if already_patched(text):
        return text
    text = replace_once(
        text,
        'cacheSessionId=options?.cacheRetention==="none"?void 0:options?.sessionId,codexSessionId=clampOpenAIPromptCacheKey(cacheSessionId),body=buildRequestBody(model,context,options,codexSessionId,grammarToolInputProperties)',
        'originalCacheSessionId=options?.cacheRetention==="none"?void 0:options?.sessionId,cacheSessionId=resolveCodexSessionAlias(originalCacheSessionId),codexSessionId=clampOpenAIPromptCacheKey(cacheSessionId),body=buildRequestBody(model,context,options,codexSessionId,grammarToolInputProperties)',
        "bundle session state",
    )
    text = replace_once(
        text,
        'retriedCodexServerError=!1;for(;;)',
        'retriedCodexServerError=!1,retriedPreviousResponseOwnerUnavailable=!1;for(;;)',
        "bundle owner retry flag",
    )
    text = replace_once(
        text,
        'retryableCodexServerError=isRetryableCodexServerError(error);if(!aborted&&retryableCodexServerError&&!retriedCodexServerError&&',
        'retryableCodexServerError=isRetryableCodexServerError(error),previousResponseOwnerUnavailable=isPreviousResponseOwnerUnavailableError(error);if(!aborted&&previousResponseOwnerUnavailable&&!retriedPreviousResponseOwnerUnavailable&&output.content.length===0&&originalCacheSessionId&&body.previous_response_id==null){let previousCodexSessionId=codexSessionId;cacheSessionId=rotateCodexSessionAlias(originalCacheSessionId,cacheSessionId),codexSessionId=clampOpenAIPromptCacheKey(cacheSessionId),body.prompt_cache_key===previousCodexSessionId&&(body={...body,prompt_cache_key:codexSessionId}),websocketRequestId=codexSessionId||uuidv7(),sseHeaders=buildSSEHeaders(model.headers,options?.headers,accountId,apiKey,codexSessionId),websocketHeaders=buildWebSocketHeaders(model.headers,options?.headers,accountId,apiKey,websocketRequestId),bodyJson=JSON.stringify(body),retriedPreviousResponseOwnerUnavailable=!0;continue}if(!aborted&&retryableCodexServerError&&!retriedCodexServerError&&',
        "bundle owner retry branch",
    )
    text = replace_once(
        text,
        'websocketSessionCache=new Map,websocketDebugStats=new Map,websocketSseFallbackSessions=new Set;',
        'websocketSessionCache=new Map,websocketDebugStats=new Map,websocketSseFallbackSessions=new Set,codexSessionAliases=new Map;function resolveCodexSessionAlias(sessionId){return sessionId?codexSessionAliases.get(sessionId)??sessionId:void 0}function rotateCodexSessionAlias(sessionId,failedSessionId){let currentSessionId=resolveCodexSessionAlias(sessionId);if(!sessionId||!currentSessionId||currentSessionId!==failedSessionId)return currentSessionId??failedSessionId;closeWebSocketSessionEntries(failedSessionId),websocketSseFallbackSessions.delete(failedSessionId);let replacementSessionId=uuidv7();return codexSessionAliases.set(sessionId,replacementSessionId),replacementSessionId}',
        "bundle aliases",
    )
    return replace_once(
        text,
        'function closeOpenAICodexWebSocketSessions(sessionId){let closeEntry=entry=>{entry.idleTimer&&clearTimeout(entry.idleTimer),closeWebSocketSilently(entry.socket,1e3,"debug_close")};if(sessionId){for(let entry of websocketSessionCache.get(sessionId)?.values()??[])closeEntry(entry);websocketSessionCache.delete(sessionId);return}for(let accountEntries of websocketSessionCache.values())for(let entry of accountEntries.values())closeEntry(entry);websocketSessionCache.clear()}',
        'function closeWebSocketSessionEntries(sessionId){let closeEntry=entry=>{entry.idleTimer&&clearTimeout(entry.idleTimer),closeWebSocketSilently(entry.socket,1e3,"debug_close")};for(let entry of websocketSessionCache.get(sessionId)?.values()??[])closeEntry(entry);websocketSessionCache.delete(sessionId)}function closeOpenAICodexWebSocketSessions(sessionId){if(sessionId){let aliasedSessionId=codexSessionAliases.get(sessionId);closeWebSocketSessionEntries(sessionId),aliasedSessionId&&aliasedSessionId!==sessionId&&closeWebSocketSessionEntries(aliasedSessionId),codexSessionAliases.delete(sessionId);return}for(let cachedSessionId of[...websocketSessionCache.keys()])closeWebSocketSessionEntries(cachedSessionId);codexSessionAliases.clear()}',
        "bundle cleanup",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readable", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    if not args.readable and not args.bundle:
        parser.error("provide --readable and/or --bundle")

    plans = []
    for path, patch in ((args.readable, patch_readable), (args.bundle, patch_minified)):
        if path:
            original = path.read_text()
            plans.append((path, original, patch(original)))
    for path, original, patched in plans:
        if patched != original:
            path.write_text(patched)
        print(f"{path}: {'patched' if patched != original else 'already patched'}")


if __name__ == "__main__":
    main()
