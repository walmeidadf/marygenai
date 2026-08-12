import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workerUrl = new URL("../dist/server/index.js", import.meta.url);

async function request(path) {
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the public project website with accurate trust language", async () => {
  const response = await request("/");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Find the study/);
  assert.match(html, /3,149/);
  assert.match(html, /AI candidate/);
  assert.match(html, /not reviewed clinical truth/i);
  assert.match(html, /No software or data license has been published/i);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/i);
});

test("server-renders the Dataset Viewer and synthetic-demo boundary", async () => {
  const response = await request("/dataset");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Dataset Viewer/);
  assert.match(html, /Read-only candidate retrieval/);
  assert.match(html, /Synthetic demonstration/);
  assert.match(html, /not scientific publications or clinical claims/i);
});

test("demo API supports deterministic search, filters, and pagination", async () => {
  const response = await request("/api/viewer/studies?cannabinoid=Cannabidiol&page=1&pageSize=2");
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.mode, "demo");
  assert.equal(payload.pageSize, 2);
  assert.ok(payload.total >= 2);
  assert.ok(payload.results.every((study) => study.cannabinoids.includes("Cannabidiol")));
  assert.match(payload.zeroResultMessage, /does not establish absence/i);
});

test("original-study links open safely in a new browser tab", async () => {
  const source = await readFile(new URL("../app/dataset/DatasetViewer.tsx", import.meta.url), "utf8");
  assert.match(source, /target="_blank"/);
  assert.match(source, /rel="noopener noreferrer"/);
  assert.match(source, /Open original study in a new tab/);
});
