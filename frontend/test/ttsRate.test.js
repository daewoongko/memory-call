import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";

const speechHook = readFileSync(new URL("../src/useSpeech.js", import.meta.url), "utf8");

test("family-call speech uses the approved 0.93 default rate", () => {
  assert.match(speechHook, /rate = 0\.93,/);
  assert.doesNotMatch(speechHook, /rate = 0\.736,/);
});
