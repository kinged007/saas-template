import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

// Source-scan: the component is .tsx, which node --test cannot load, so its
// wiring is asserted on the text instead (same style as SecuritySection.test.ts).
const source = readFileSync(
  fileURLToPath(new URL("./CopyButton.tsx", import.meta.url)),
  "utf8",
);

test("icon size is the default a call site can override", () => {
  // The icon-only control renders a square icon box by construction (#1223);
  // shadcn/ui's `sm` / `lg` still win when a call site passes them.
  assert.match(source, /\bsize\s*=\s*"icon"/);
});

test("the doc comment does not claim the Omit enforces aria-label", () => {
  // TypeScript does not check hyphenated JSX attributes against the props
  // type, so `aria-label` still compiles through any Omit (#1221): the
  // comment must credit the runtime ordering (spread first, forced last)
  // instead of the Omit.
  const comment = source.slice(0, source.indexOf("export function CopyButton"));
  const omitLine = comment.split("\n").find((l) => /\bOmit\b/.test(l));
  assert.ok(omitLine, "comment no longer explains the Omit");
  assert.ok(
    !omitLine.includes("aria-label"),
    `comment still claims aria-label is Omit-enforced: ${omitLine.trim()}`,
  );
});
