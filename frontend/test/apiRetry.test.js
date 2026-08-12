import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/api.js", import.meta.url), "utf8");

test("read-only API calls retry temporary Render gateway failures", () => {
  assert.match(source, /502, 503, 504/);
  assert.match(source, /options\.method \|\| "GET"/);
  assert.match(source, /attempts = .*\? 3 : 1/);
});

