import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const layout = readFileSync(new URL("./UserSettingsLayout.tsx", import.meta.url), "utf8");

/** Comments blanked but newlines kept, so offsets still map to line numbers. */
const code = layout.replace(
  /\/\*[\s\S]*?\*\/|\/\/.*$/gm,
  (comment) => comment.replace(/[^\n]/g, " "),
);

const START = "export function UserSettingsLayout()";
const GUARD = "if (isLoading";

/** The line number of an offset in the source, 1-based, for a failure message. */
const lineAt = (index: number) => layout.slice(0, index).split("\n").length;

/** The offset just past the block that opens at `start`. */
const blockEnd = (start: number) => {
  let depth = 0;
  for (let end = code.indexOf("{", start); ; end += 1) {
    if (code[end] === "{") depth += 1;
    else if (code[end] === "}") depth -= 1;
    if (depth === 0) return end;
  }
};

/**
 * `node --test` cannot render a `.tsx` component here (no jsdom), so the source
 * is read the way `card-title-classes.test.ts` reads `card.tsx`.
 *
 * The `isLoading || !identity` guard returns early, so a hook below it is
 * skipped on the loading render and called on the resolved one — React rejects
 * that hook list. The guard gates a return, not hooks, so all of them stay above.
 */
test("every hook in UserSettingsLayout runs above the loading guard", () => {
  const start = code.indexOf(START);
  assert.notEqual(start, -1, `${START} must stay in this file`);

  const component = code.slice(start, blockEnd(start));
  const guard = component.indexOf(GUARD);
  assert.notEqual(
    guard,
    -1,
    `the loading guard must stay in the component, on ${JSON.stringify(GUARD)}`,
  );

  const below = [...component.matchAll(/\buse[A-Z]\w*\s*\(/g)]
    .map((match) => ({
      name: match[0].replace(/\s*\($/, ""),
      index: start + match.index,
    }))
    .filter((hook) => hook.index > start + guard);

  assert.deepEqual(
    below.map((hook) => `${hook.name} (line ${lineAt(hook.index)})`),
    [],
    `hooks must be called above the guard on line ${lineAt(start + guard)}`,
  );
});
