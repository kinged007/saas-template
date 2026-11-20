import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const card = readFileSync(new URL("./card.tsx", import.meta.url), "utf8");
const dashboard = readFileSync(
  new URL("../../pages/DashboardPage.tsx", import.meta.url),
  "utf8",
);

/** The classes `CardTitle` applies, read from the primitive. */
const cardTitleClasses = () => {
  const primitive = card.slice(
    card.indexOf("const CardTitle"),
    card.indexOf("CardTitle.displayName"),
  );
  const classes = primitive.match(/cn\("([^"]+)"/)?.[1];
  assert.ok(classes, 'CardTitle must apply its classes with cn("...")');
  return classes.split(" ");
};

/**
 * Every dashboard card title written as a heading, as `[level, title, classes]`.
 * Scoped to the `CardHeader` blocks so the page title, which carries heading
 * classes of its own, is not read as a card title.
 */
const cardTitleHeadings = () =>
  [...dashboard.matchAll(/<CardHeader>([\s\S]*?)<\/CardHeader>/g)].flatMap(
    ([, block]) =>
      [...block.matchAll(/<h([1-6])\b([^>]*)>([^<]*)</g)].map(
        ([, level, attrs, title]) => [
          level,
          title,
          attrs.match(/className="([^"]*)"/)?.[1] ?? "",
        ],
      ),
  );

/**
 * The dashboard writes its card titles as headings with the classes `CardTitle`
 * applies, because `CardTitle` renders a div. These read the source rather than
 * the DOM: `node --test` cannot render a `.tsx` component here (no jsdom),
 * the same way `single-workspace-subscriber.test.ts` reads `AppLayout.tsx`.
 *
 * A title that stops matching the pattern below drops out of the list, so the
 * first assert fails loudly instead of the second passing on an empty find.
 */
test("every dashboard card title is a heading in outline order", () => {
  assert.deepEqual(
    cardTitleHeadings().map(([level, title]) => [level, title]),
    [
      ["1", "No workspace yet"],
      ["2", "Get set up"],
      ["2", "Members"],
      ["2", "Inbox"],
    ],
    "each dashboard card title must be a heading, under the page h1",
  );
});

test("every dashboard card title carries the classes CardTitle applies", () => {
  const applied = cardTitleClasses();
  for (const [, title, className] of cardTitleHeadings()) {
    for (const token of applied) {
      assert.ok(
        className.split(" ").includes(token),
        `the "${title}" heading is missing CardTitle's "${token}" class`,
      );
    }
  }
});
