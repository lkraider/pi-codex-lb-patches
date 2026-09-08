#!/usr/bin/env node

// Installed-package adaptation of Pi's scripts/build-coding-agent-bundle.mjs.
import { chmodSync, existsSync, mkdirSync, renameSync, rmSync } from "node:fs";
import { createRequire, isBuiltin } from "node:module";
import { dirname, join, relative, resolve } from "node:path";

const packageDir = resolve(process.argv[2] ?? "");
if (!process.argv[2]) {
  console.error("Usage: rebuild-bundle.mjs PACKAGE_DIR");
  process.exit(2);
}

const packageRequire = createRequire(join(packageDir, "package.json"));
const { build } = packageRequire("esbuild");
const aiDistDir = join(packageDir, "node_modules", "@earendil-works", "pi-ai", "dist");
const codingAgentDistDir = join(packageDir, "dist");
const bundleDir = join(codingAgentDistDir, "bundle");
const temporaryBundleDir = join(codingAgentDistDir, `.bundle-patch-${process.pid}`);
const backupBundleDir = join(codingAgentDistDir, `.bundle-backup-${process.pid}`);
const banner = {
  js: 'import { createRequire as __piCreateRequire } from "node:module"; const require = __piCreateRequire(import.meta.url);',
};
const allowedExternalPackages = new Set([
  "@earendil-works/chord",
  "@earendil-works/chord/bundler",
  "@earendil-works/chord/context",
  "@earendil-works/chord/delta",
  "@earendil-works/chord/node",
  "@silvia-odwyer/photon-node",
  "jiti",
  "bufferutil",
  "utf-8-validate",
  "kerberos",
  "supports-color",
]);

const lazyJitiPlugin = {
  name: "lazy-jiti-transform",
  setup(esbuild) {
    esbuild.onResolve({ filter: /^jiti\/static$/ }, () => ({
      namespace: "lazy-jiti",
      path: "jiti/static",
    }));
    esbuild.onLoad({ filter: /.*/, namespace: "lazy-jiti" }, () => ({
      contents: `
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let createJitiImpl;
export function createJiti(...args) {
  createJitiImpl ??= require("jiti").createJiti;
  return createJitiImpl(...args);
}
`,
      loader: "js",
    }));
  },
};

const httpsProxyAgentNamedExportPlugin = {
  name: "https-proxy-agent-named-export",
  setup(esbuild) {
    esbuild.onResolve({ filter: /^https-proxy-agent$/ }, (args) => {
      if (args.kind !== "dynamic-import") return undefined;
      return { namespace: "https-proxy-agent-named-export", path: args.path };
    });
    esbuild.onLoad(
      { filter: /^https-proxy-agent$/, namespace: "https-proxy-agent-named-export" },
      () => ({
        contents: 'export { HttpsProxyAgent } from "https-proxy-agent";',
        loader: "js",
        resolveDir: packageDir,
      }),
    );
  },
};

function commonBuildOptions() {
  return {
    absWorkingDir: packageDir,
    banner,
    bundle: true,
    define: { PI_BUNDLED_NODE: "true" },
    external: ["@earendil-works/chord", "@silvia-odwyer/photon-node"],
    format: "esm",
    legalComments: "none",
    logLevel: "warning",
    metafile: true,
    minifySyntax: true,
    minifyWhitespace: true,
    platform: "node",
    plugins: [lazyJitiPlugin, httpsProxyAgentNamedExportPlugin],
    sourcemap: false,
    target: "node22.19",
    tsconfigRaw: { compilerOptions: {} },
  };
}

function validateExternalImports(metafiles) {
  const unexpected = new Set();
  for (const metafile of metafiles) {
    for (const input of Object.values(metafile.inputs)) {
      for (const imported of input.imports) {
        if (!imported.external || isBuiltin(imported.path) || allowedExternalPackages.has(imported.path)) continue;
        unexpected.add(imported.path);
      }
    }
  }
  if (unexpected.size > 0) {
    throw new Error(`Bundle left unexpected external imports: ${[...unexpected].sort().join(", ")}`);
  }
}

function findContainingOutput(metafile, inputSuffix) {
  const normalizedSuffix = inputSuffix.replaceAll("\\", "/");
  for (const [outputPath, output] of Object.entries(metafile.outputs)) {
    if (Object.keys(output.inputs).some((inputPath) => inputPath.replaceAll("\\", "/").endsWith(normalizedSuffix))) {
      return resolve(packageDir, outputPath);
    }
  }
  throw new Error(`Could not locate bundled output containing ${inputSuffix}`);
}

function outputBytes(metafiles) {
  return metafiles.reduce(
    (total, metafile) => total + Object.values(metafile.outputs).reduce((sum, output) => sum + output.bytes, 0),
    0,
  );
}

const mainEntries = {
  cli: join(codingAgentDistDir, "cli.js"),
  index: join(codingAgentDistDir, "index.js"),
  "rpc-entry": join(codingAgentDistDir, "rpc-entry.js"),
};
const lazyEntries = {
  anthropic: join(aiDistDir, "auth", "oauth", "anthropic.js"),
  "bedrock-converse-stream": join(aiDistDir, "api", "bedrock-converse-stream.js"),
  "github-copilot": join(aiDistDir, "auth", "oauth", "github-copilot.js"),
  "image-resize-worker": join(codingAgentDistDir, "utils", "image-resize-worker.js"),
  "kimi-coding": join(aiDistDir, "auth", "oauth", "kimi-coding.js"),
  "openai-codex": join(aiDistDir, "auth", "oauth", "openai-codex.js"),
  openrouter: join(aiDistDir, "auth", "oauth", "openrouter.js"),
  radius: join(aiDistDir, "auth", "oauth", "radius.js"),
  xai: join(aiDistDir, "auth", "oauth", "xai.js"),
};

for (const entry of [...Object.values(mainEntries), ...Object.values(lazyEntries)]) {
  if (!existsSync(entry)) throw new Error(`Bundle input is missing: ${relative(packageDir, entry)}`);
}

rmSync(temporaryBundleDir, { force: true, recursive: true });
rmSync(backupBundleDir, { force: true, recursive: true });
mkdirSync(temporaryBundleDir, { recursive: true });

try {
  const mainResult = await build({
    ...commonBuildOptions(),
    entryNames: "[name]",
    entryPoints: mainEntries,
    outdir: temporaryBundleDir,
    chunkNames: "chunks/[name]-[hash]",
    splitting: true,
  });

  const bedrockLoaderOutput = findContainingOutput(mainResult.metafile, "dist/api/bedrock-converse-stream.lazy.js");
  const oauthLoaderOutput = findContainingOutput(mainResult.metafile, "dist/auth/oauth/load.js");
  const imageResizeOutput = findContainingOutput(mainResult.metafile, "dist/utils/image-resize.js");
  if (dirname(bedrockLoaderOutput) !== dirname(oauthLoaderOutput)) {
    throw new Error("Bedrock and OAuth lazy loaders were emitted into different directories");
  }

  const lazyResult = await build({
    ...commonBuildOptions(),
    entryNames: "[name]",
    entryPoints: lazyEntries,
    outdir: dirname(bedrockLoaderOutput),
    splitting: false,
  });

  const imageResizeWorkerOutput = resolve(dirname(bedrockLoaderOutput), "image-resize-worker.js");
  if (dirname(imageResizeOutput) !== dirname(imageResizeWorkerOutput)) {
    throw new Error("Image resize implementation and worker were emitted into different directories");
  }

  validateExternalImports([mainResult.metafile, lazyResult.metafile]);
  chmodSync(join(temporaryBundleDir, "cli.js"), 0o755);
  chmodSync(join(temporaryBundleDir, "rpc-entry.js"), 0o755);

  if (existsSync(bundleDir)) renameSync(bundleDir, backupBundleDir);
  try {
    renameSync(temporaryBundleDir, bundleDir);
  } catch (error) {
    if (existsSync(backupBundleDir)) renameSync(backupBundleDir, bundleDir);
    throw error;
  }
  rmSync(backupBundleDir, { force: true, recursive: true });

  const files = new Set([...Object.keys(mainResult.metafile.outputs), ...Object.keys(lazyResult.metafile.outputs)]).size;
  const mib = outputBytes([mainResult.metafile, lazyResult.metafile]) / (1024 * 1024);
  console.log(`Rebuilt ${relative(packageDir, bundleDir)} (${files} files, ${mib.toFixed(1)} MiB)`);
} catch (error) {
  rmSync(temporaryBundleDir, { force: true, recursive: true });
  throw error;
}
