#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 PACKAGE_DIR PATCH_FILE APPLIED_MARKER" >&2
  exit 2
fi

package_dir=$1
patch_file=$2
marker=$3
target="$package_dir/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js"

[[ -f "$target" ]] || { echo "Missing Pi provider: $target" >&2; exit 1; }
[[ -f "$patch_file" ]] || { echo "Missing patch: $patch_file" >&2; exit 1; }

if grep -Fq "$marker" "$target"; then
  printf 'Already applied: %s\n' "$(basename "$patch_file")"
  exit 0
fi

if ! patch --batch --forward --dry-run -F 0 -d "$package_dir" -p1 < "$patch_file" >/dev/null; then
  echo "Patch does not apply cleanly: $patch_file" >&2
  echo "Reinstall a clean, supported Pi version and retry." >&2
  exit 1
fi

patch --batch --forward -F 0 -d "$package_dir" -p1 < "$patch_file" >/dev/null
printf 'Applied: %s\n' "$(basename "$patch_file")"
