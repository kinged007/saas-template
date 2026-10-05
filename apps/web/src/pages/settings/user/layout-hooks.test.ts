import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const layout = readFileSync(new URL("./UserSettingsLayout.tsx", import.meta.url), "utf8");

/** The line number of the loading guard, 1-based, for a failure message. */
const lineAt = (index: number) => layout.slice(0, index).split("\n").length;

/**
 * `node --test` cannot render a `.tsx` component here (no jsdom), so the source
 * is read the way `card-title-classes.test.ts` reads `card.tsx`.
 *
 * The `isLoading || !identity` guard returns early, so a hook below it is
 * skipped on the loading render and called on the resolved one — React rejects
 * that hook list. The guard gates a return, not hooks, so all of them stay above.
 */
test("every hook in UserSettingsLayout runs above the loading guard", () => {
  const guard = layout.indexOf("if (isLoading");
  assert.notEqual(guard, -1, "the loading guard must stay in the component");

  const below = [...layout.matchAll(/\buse[A-Z]\w*\s*\(/g)]
    .map((match) => ({ name: match[0].replace(/\s*\($/, ""), index: match.index }))
    .filter((hook) => hook.index > guard);

  assert.deepEqual(
    below.map((hook) => `${hook.name} (line ${lineAt(hook.index)})`),
    [],
    `hooks must be called above the guard on line ${lineAt(guard)}`,
  );
});