import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webDirectory = resolve(scriptDirectory, "..");
const repositoryDirectory = resolve(webDirectory, "..");
const cloudflareEnvPath = join(webDirectory, ".env.cloudflare.local");
const viewerTokenPath = join(
  repositoryDirectory,
  "data/private/viewer-dev-access-token.json",
);
const generatedConfigPath = join(webDirectory, "dist/server/wrangler.json");
const viewerApiBaseUrl = "https://mcp-server.marygenai.com";

function parseEnvFile(source) {
  const values = {};
  for (const line of source.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separator = trimmed.indexOf("=");
    if (separator < 1) continue;
    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

function run(command, args, environment = process.env) {
  const result = spawnSync(command, args, {
    cwd: webDirectory,
    env: environment,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}`);
  }
}

const mode = process.argv[2] ?? "--dry-run";
if (!new Set(["--dry-run", "--upload"]).has(mode)) {
  throw new Error("Usage: node scripts/cloudflare-preview.mjs [--dry-run|--upload]");
}

const cloudflareEnv = parseEnvFile(await readFile(cloudflareEnvPath, "utf8"));
const workerName = cloudflareEnv.MARYGENAI_CLOUDFLARE_WORKER;
if (!workerName) {
  throw new Error(
    "MARYGENAI_CLOUDFLARE_WORKER is required in .env.cloudflare.local",
  );
}
if (!/^[0-9a-f]{32}$/i.test(cloudflareEnv.CLOUDFLARE_ACCOUNT_ID ?? "")) {
  throw new Error("CLOUDFLARE_ACCOUNT_ID is missing or invalid");
}
if (!cloudflareEnv.CLOUDFLARE_API_TOKEN) {
  throw new Error("CLOUDFLARE_API_TOKEN is required");
}

const viewerTokenDocument = JSON.parse(await readFile(viewerTokenPath, "utf8"));
if (typeof viewerTokenDocument.token !== "string" || !viewerTokenDocument.token) {
  throw new Error("The ignored Viewer token file does not contain a token");
}

console.log(`Building Cloudflare Worker ${workerName}...`);
run("npm", ["run", "build"], {
  ...process.env,
  MARYGENAI_CLOUDFLARE_WORKER: workerName,
  MARYGENAI_VIEWER_API_BASE_URL: viewerApiBaseUrl,
});

const generatedConfig = JSON.parse(await readFile(generatedConfigPath, "utf8"));
if (generatedConfig.name !== workerName) {
  throw new Error(`Generated Worker name is ${generatedConfig.name}, expected ${workerName}`);
}
if (generatedConfig.vars?.MARYGENAI_VIEWER_API_BASE_URL !== viewerApiBaseUrl) {
  throw new Error("Generated Worker config is missing the Viewer API base URL");
}
if (!generatedConfig.compatibility_flags?.includes("nodejs_compat")) {
  throw new Error("Generated Worker config is missing nodejs_compat");
}

const temporaryDirectory = await mkdtemp(join(tmpdir(), "marygenai-worker-"));
const secretsPath = join(temporaryDirectory, "secrets.json");
try {
  await writeFile(
    secretsPath,
    `${JSON.stringify({
      MARYGENAI_VIEWER_API_BEARER_TOKEN: viewerTokenDocument.token,
    })}\n`,
    { mode: 0o600 },
  );

  const wranglerArguments = [
    "versions",
    "upload",
    "--config",
    generatedConfigPath,
    "--env-file",
    cloudflareEnvPath,
    "--secrets-file",
    secretsPath,
    "--preview-alias",
    "marygenai-viewer",
    "--message",
    "MaryGenAI authenticated Viewer proxy preview",
  ];
  if (mode === "--dry-run") wranglerArguments.push("--dry-run");

  console.log(
    mode === "--dry-run"
      ? "Validating the Worker package without uploading it..."
      : "Uploading a preview version without changing production traffic...",
  );
  run(join(webDirectory, "node_modules/.bin/wrangler"), wranglerArguments, {
    ...process.env,
    WRANGLER_WRITE_LOGS: "false",
    WRANGLER_LOG_PATH: join(webDirectory, ".wrangler/wrangler.log"),
  });
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
