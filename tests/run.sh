#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
temporary_dir=$(mktemp -d "${TMPDIR:-/tmp}/pi-agent-patch-test.XXXXXX")
trap 'rm -rf "$temporary_dir"' EXIT

version=${PI_TEST_VERSION:-$(npm view --offline @earendil-works/pi-coding-agent version)}
echo "Testing cached @earendil-works/pi-coding-agent@$version"
tarball=$(npm pack --offline --silent --pack-destination "$temporary_dir" \
  "@earendil-works/pi-coding-agent@$version")
tar -xzf "$temporary_dir/$tarball" -C "$temporary_dir"
package_dir="$temporary_dir/package"

# npm resolves devDependencies even with --omit=dev. They are irrelevant to an
# installed package and may not all be cached, so remove them before installing.
node - "$package_dir/package.json" <<'NODE'
const fs = require("node:fs");
const path = process.argv[2];
const packageJson = JSON.parse(fs.readFileSync(path, "utf8"));
delete packageJson.devDependencies;
delete packageJson.scripts;
fs.writeFileSync(path, `${JSON.stringify(packageJson, null, 2)}\n`);
NODE
(
  cd "$package_dir"
  npm install --offline --ignore-scripts --no-audit --no-fund --loglevel=error
)

provider="$package_dir/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js"
apply_patch() {
  "$root_dir/src/apply-patch.sh" "$package_dir" "$root_dir/patches/$1.patch" "$2"
}
find_bundle_provider() {
  local marker=$1 matches count
  matches=$(grep -RFl --include='*.js' "$marker" "$package_dir/dist/bundle/chunks" || true)
  count=$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l | tr -d ' ')
  if [[ "$count" != 1 ]]; then
    echo "Expected one bundled provider containing '$marker'; found $count" >&2
    printf '%s\n' "$matches" >&2
    exit 1
  fi
  printf '%s\n' "$matches"
}
run_profile() {
  local profile=$1 bundled_provider=$2 mode candidate
  for candidate in "$provider" "$bundled_provider"; do
    node "$root_dir/tests/bearer-auth.mjs" "$candidate"
    for mode in \
      server-error top-level-server-error rate-limit partial-output explicit-anchor \
      client-error stream-incomplete operation-in-progress owner-unavailable repeated-server-error
    do
      node "$root_dir/tests/recovery.mjs" "$candidate" "$mode" "$profile"
    done
  done
}

# First test the bearer workaround plus the general retry in isolation.
apply_patch bearer-auth 'function tryExtractAccountId('
apply_patch transient-retry 'function isRetryableCodexServerError('
node --check "$provider"
node "$root_dir/src/rebuild-bundle.mjs" "$package_dir"
general_bundle_provider=$(find_bundle_provider 'isRetryableCodexServerError')
run_profile general "$general_bundle_provider"

# Then layer owner migration on top and exercise the combined behavior.
apply_patch owner-migration 'const codexSessionAliases = new Map();'
node --check "$provider"
node "$root_dir/src/rebuild-bundle.mjs" "$package_dir"
combined_bundle_provider=$(find_bundle_provider 'codexSessionAliases')
run_profile combined "$combined_bundle_provider"

# The public command must be safe to rerun and leave a working CLI.
"$root_dir/reapply" --package "$package_dir"
actual_version=$(node "$package_dir/dist/bundle/cli.js" --version)
[[ "$actual_version" == "$version" ]] || {
  echo "Expected Pi $version after rebuild; got $actual_version" >&2
  exit 1
}

echo "All source-patch and rebuilt-bundle tests passed for Pi $version."
