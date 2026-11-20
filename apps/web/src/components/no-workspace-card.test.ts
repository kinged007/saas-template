import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

const card = read("./NoWorkspaceCard.tsx");
const layout = read("./AppLayout.tsx");
const dashboard = read("../pages/DashboardPage.tsx");
const section = read("../pages/settings/profile/sections/WorkspacesSection.tsx");

// `node --test` cannot render a `.tsx` component here (no jsdom), so these read
// the source the same way `card-title-classes.test.ts` and
// `single-workspace-subscriber.test.ts` do. Playwright covers what renders.

// `assert.match` echoes the whole haystack, which is the whole component. These
// asserts take a message so a red run prints one line.
test("the profile workspaces list offers the same card as the dashboard", () => {
  assert.ok(
    section.includes("<NoWorkspaceCard"),
    "WorkspacesSection must render <NoWorkspaceCard> instead of an empty table",
  );
});

test("the dashboard renders the shared card, not a second copy", () => {
  assert.ok(dashboard.includes("<NoWorkspaceCard"), "DashboardPage must render <NoWorkspaceCard>");
  assert.ok(
    !dashboard.includes("No workspace yet"),
    'DashboardPage must no longer carry the "No workspace yet" copy',
  );
});

test("the no-workspace copy has one home", () => {
  const copies = [dashboard, section, layout, card].filter((s) => s.includes("No workspace yet"));
  assert.equal(copies.length, 1, '"No workspace yet" must be written only in NoWorkspaceCard.tsx');
});

test("the ask-an-admin sentence has one home", () => {
  // Read out of the card so this test never carries a second literal of the
  // sentence it guards, which would drift from a copy change unnoticed.
  const [, sentence] = /export const ASK_AN_ADMIN = "([^"]+)"/.exec(card) ?? [];
  assert.ok(sentence, "NoWorkspaceCard.tsx must export ASK_AN_ADMIN");
  assert.deepEqual(
    [dashboard, section, layout].filter((s) => s.includes(sentence)),
    [],
    `AppLayout.tsx and the pages must import ASK_AN_ADMIN, not inline "${sentence}"`,
  );
});
