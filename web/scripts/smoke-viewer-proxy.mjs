import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webDirectory = resolve(scriptDirectory, "..");
const viewerTokenPath = resolve(
  webDirectory,
  "../data/private/viewer-dev-access-token.json",
);
const workerPath = resolve(webDirectory, "dist/server/index.js");
const viewerApiBaseUrl = "https://mcp-server.marygenai.com";

const viewerTokenDocument = JSON.parse(await readFile(viewerTokenPath, "utf8"));
assert.equal(typeof viewerTokenDocument.token, "string");
assert.ok(viewerTokenDocument.token.length > 0);

process.env.MARYGENAI_VIEWER_API_BASE_URL = viewerApiBaseUrl;
process.env.MARYGENAI_VIEWER_API_BEARER_TOKEN = viewerTokenDocument.token;

const workerUrl = pathToFileURL(workerPath);
workerUrl.searchParams.set("smoke", `${Date.now()}`);
const { default: worker } = await import(workerUrl.href);
const workerEnv = {
  ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
};
const executionContext = {
  waitUntil() {},
  passThroughOnException() {},
};

async function request(path) {
  return worker.fetch(
    new Request(`https://preview.marygenai.invalid${path}`),
    workerEnv,
    executionContext,
  );
}

const metaResponse = await request("/api/viewer/meta");
assert.equal(metaResponse.status, 200);
assert.equal(metaResponse.headers.get("cache-control"), "private, no-store");
const metaText = await metaResponse.text();
assert.ok(!metaText.includes(viewerTokenDocument.token));
const meta = JSON.parse(metaText);
assert.equal(meta.mode, "index");
assert.equal(meta.documentCount, 3437);

const searchResponse = await request(
  "/api/viewer/studies?query=cannabidiol&page=1&pageSize=1",
);
assert.equal(searchResponse.status, 200);
assert.equal(searchResponse.headers.get("cache-control"), "private, no-store");
const searchText = await searchResponse.text();
assert.ok(!searchText.includes(viewerTokenDocument.token));
const search = JSON.parse(searchText);
assert.equal(search.mode, "index");
assert.ok(search.total > 0);
assert.equal(search.results.length, 1);

const selectedStudy = search.results[0];
const detailResponse = await request(
  `/api/viewer/studies/${encodeURIComponent(selectedStudy.documentId)}`,
);
assert.equal(detailResponse.status, 200);
assert.equal(detailResponse.headers.get("cache-control"), "private, no-store");
const detailText = await detailResponse.text();
assert.ok(!detailText.includes(viewerTokenDocument.token));
const detail = JSON.parse(detailText);
assert.equal(detail.documentId, selectedStudy.documentId);
assert.match(detail.preferredAccessUrl, /^https:\/\//);

console.log(
  `Viewer proxy smoke passed: ${meta.documentCount} candidates, ${search.total} cannabidiol matches, study ${detail.documentId}.`,
);
