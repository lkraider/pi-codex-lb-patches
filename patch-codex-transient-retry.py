#!/usr/bin/env python3
"""Patch Pi's Codex WebSocket loop with one safe transient retry."""

from __future__ import annotations

import argparse
from pathlib import Path

PATCH_MARKERS = (
    "retriedCodexServerError",
    "codexApiErrorType",
    "isPreviousResponseOwnerUnavailableError",
    "isRetryableCodexServerError",
)

READABLE_CLASSIFIER = '''function codexApiErrorType(error) {
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
function isPreviousResponseOwnerUnavailableError(error) {
    return error instanceof CodexApiError &&
        (error.code === "previous_response_owner_unavailable" ||
            /Previous response owner account is unavailable/i.test(error.message));
}
function isRetryableCodexServerError(error) {
    if (!(error instanceof CodexApiError) || isPreviousResponseOwnerUnavailableError(error))
        return false;
    if (error.code === "stream_incomplete" || error.code === "previous_response_operation_in_progress" ||
        /previous response operation may still be running|Suppressed duplicate side-effect tool call/i.test(error.message))
        return false;
    return error.code === "rate_limit_exceeded" || codexApiErrorType(error) === "server_error";
}'''

MINIFIED_CLASSIFIER = 'function codexApiErrorType(error){let payload=error.payload;if(!payload||typeof payload!=="object")return;let errorType=payload.type==="response.failed"?payload.response?.error?.type:payload.type==="error"&&payload.error&&typeof payload.error==="object"?payload.error.type:void 0;return typeof errorType==="string"?errorType:void 0}function isPreviousResponseOwnerUnavailableError(error){return error instanceof CodexApiError&&(error.code==="previous_response_owner_unavailable"||/Previous response owner account is unavailable/i.test(error.message))}function isRetryableCodexServerError(error){return error instanceof CodexApiError&&!isPreviousResponseOwnerUnavailableError(error)?error.code==="stream_incomplete"||error.code==="previous_response_operation_in_progress"||/previous response operation may still be running|Suppressed duplicate side-effect tool call/i.test(error.message)?!1:error.code==="rate_limit_exceeded"||codexApiErrorType(error)==="server_error":!1}'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one upstream marker, found {count}")
    return text.replace(old, new, 1)


def already_patched(text: str) -> bool:
    found = [marker for marker in PATCH_MARKERS if marker in text]
    if not found:
        return False
    missing = [marker for marker in PATCH_MARKERS if marker not in text]
    if missing:
        raise RuntimeError(f"partial transient-retry patch; missing {', '.join(missing)}")
    return True


def patch_readable(text: str) -> str:
    if already_patched(text):
        return text
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
                            output.content.length === 0 && body.previous_response_id == null) {
                            retriedCodexServerError = true;
                            continue;
                        }
                        if (!aborted && previousResponseNotFound && !retriedMissingWebSocketContinuation) {''',
        "readable retry branch",
    )
    return replace_once(
        text,
        '''function isPreviousResponseNotFoundError(error) {
    return error instanceof CodexApiError && error.code === PREVIOUS_RESPONSE_NOT_FOUND_CODE;
}''',
        '''function isPreviousResponseNotFoundError(error) {
    return error instanceof CodexApiError && error.code === PREVIOUS_RESPONSE_NOT_FOUND_CODE;
}
''' + READABLE_CLASSIFIER,
        "readable classifier",
    )


def patch_minified(text: str) -> str:
    if already_patched(text):
        return text
    text = replace_once(
        text,
        "retriedMissingWebSocketContinuation=!1;for(;;)",
        "retriedMissingWebSocketContinuation=!1,retriedCodexServerError=!1;for(;;)",
        "bundle retry flag",
    )
    text = replace_once(
        text,
        "previousResponseNotFound=isPreviousResponseNotFoundError(error);if(!aborted&&previousResponseNotFound&&!retriedMissingWebSocketContinuation)",
        "previousResponseNotFound=isPreviousResponseNotFoundError(error),retryableCodexServerError=isRetryableCodexServerError(error);if(!aborted&&retryableCodexServerError&&!retriedCodexServerError&&output.content.length===0&&body.previous_response_id==null){retriedCodexServerError=!0;continue}if(!aborted&&previousResponseNotFound&&!retriedMissingWebSocketContinuation)",
        "bundle retry branch",
    )
    return replace_once(
        text,
        "function isPreviousResponseNotFoundError(error){return error instanceof CodexApiError&&error.code===PREVIOUS_RESPONSE_NOT_FOUND_CODE}",
        "function isPreviousResponseNotFoundError(error){return error instanceof CodexApiError&&error.code===PREVIOUS_RESPONSE_NOT_FOUND_CODE}" + MINIFIED_CLASSIFIER,
        "bundle classifier",
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
