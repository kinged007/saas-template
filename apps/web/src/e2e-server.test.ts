import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { e2eServer } from "../e2e/server.ts";

test("claims its own port and refuses to reuse a foreign server by default", () => {
  assert.deepEqual(e2eServer({}), {
    port: 5317,
    baseURL: "http://127.0.0.1:5317",
    reuse: false,
  });
});

test("E2E_PORT moves the port and baseURL together", () => {
  const { port, baseURL } = e2eServer({ E2E_PORT: "5417" });
  assert.equal(port, 5417);
  assert.equal(baseURL, "http://127.0.0.1:5417");
});

test("an unusable E2E_PORT falls back to the default", () => {
  assert.equal(e2eServer({ E2E_PORT: "not-a-port" }).port, 5317);
});

test("E2E_REUSE_SERVER opts into attaching to an already running server", () => {
  assert.equal(e2eServer({ E2E_REUSE_SERVER: "1" }).reuse, true);
  assert.equal(e2eServer({}).reuse, false);
});

test("playwright.config.ts resolves its server through e2eServer()", () => {
  const config = readFileSync(new URL("../playwright.config.ts", import.meta.url), "utf8");
  assert.match(config, /e2eServer\(/);
  assert.doesNotMatch(config, /const PORT/);
});