import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mentionRemarkPlugin, mentionUrlTransform, nextPickerIndex, pickerIndex, rankMentionTargets, type MentionTarget } from "./mentions.ts";

/** The subset of an mdast node these tests build by hand. */
type Node = { type: string; value?: string; url?: string; identifier?: string; children?: Node[] };

const text = (value: string): Node => ({ type: "text", value });
const doc = (...children: Node[]): Node => ({ type: "root", children });
const para = (...children: Node[]): Node => ({ type: "paragraph", children });

/** Mentions the plugin produced, in document order. */
function mentionsOf(tree: Node, out: string[] = []): string[] {
  for (const child of tree.children ?? []) {
    if (child.type === "link" && child.url === "mention:") out.push(child.children?.[0]?.value ?? "");
    mentionsOf(child, out);
  }
  return out;
}

/** Every text left outside a mention, so a rewrite cannot drop or reorder text. */
function textOf(tree: Node, out: string[] = []): string[] {
  for (const child of tree.children ?? []) {
    if (child.type === "link" && child.url === "mention:") continue;
    if (child.type === "text") out.push(child.value ?? "");
    textOf(child, out);
  }
  return out;
}

const target = (label: string): MentionTarget => ({ id: label, type: "user", label });
const labelsOf = (targets: MentionTarget[]) => targets.map((t) => t.label);
const LABELS = ["Zoe Andrews", "Ann", "Ann Lee", "Annabelle", "Bruno", "Annie", "Jo Ann Smith", "ann"].map(target);

describe("mentionRemarkPlugin", () => {
  const transformer = mentionRemarkPlugin(["Ann", "Ann Lee", "Zoë"])();

  it("rewrites a mention in a text node and keeps the rest of the text", () => {
    const tree = para(text("hi @Ann, ping @Ann Lee"));
    transformer(tree);
    assert.deepEqual(mentionsOf(tree), ["@Ann", "@Ann Lee"]);
    assert.equal(textOf(tree).join(""), "hi , ping ");
  });

  it("leaves non-text node types alone", () => {
    const tree = doc(
      para(text("@Ann"), { type: "inlineCode", value: "@Ann" }),
      { type: "code", value: "@Ann" },
      { type: "link", url: "/u/@Ann", children: [text("@Ann")] },
      { type: "linkReference", identifier: "ref", children: [text("@Ann")] },
      { type: "image", url: "@Ann" },
    );
    transformer(tree);
    assert.deepEqual(mentionsOf(tree), ["@Ann"]);
  });

  it("rejects a longer word after the name", () => {
    const tree = para(text("@Annabelle"));
    transformer(tree);
    assert.deepEqual(mentionsOf(tree), []);
  });

  it("rejects an address, a URL path or a URL query string before the name", () => {
    for (const source of [
      "bob@Ann",
      "bobé@Ann",
      "中文@Ann",
      "/u/@Ann",
      "a.b/@Ann",
      "https://x.com/@Ann",
      "https://x.com/?u=@Ann",
      "https://x.com/?a=1&to=@Ann",
    ]) {
      const tree = para(text(source));
      transformer(tree);
      assert.deepEqual(mentionsOf(tree), [], source);
    }
  });

  it("accepts a mention after punctuation or a space", () => {
    const tree = para(text("(@Ann) @Ann; @Ann? @Ann! @Ann."));
    transformer(tree);
    assert.deepEqual(mentionsOf(tree), ["@Ann", "@Ann", "@Ann", "@Ann", "@Ann"]);
  });

  it("matches a name containing regex metacharacters", () => {
    const tree = para(text("ping @Ann+Bob and @Zoë"));
    mentionRemarkPlugin(["Ann+Bob", "Zoë"])()(tree);
    assert.deepEqual(mentionsOf(tree), ["@Ann+Bob", "@Zoë"]);
  });
  it("does nothing for an empty name list", () => {
    const tree = para(text("@Ann"));
    mentionRemarkPlugin([])()(tree);
    assert.deepEqual(mentionsOf(tree), []);
  });

  it("is reusable across trees, so one instance can serve every bubble", () => {
    // The Inbox hoists a single plugin instance; lastIndex must not leak
    // between the trees it walks.
    const first = para(text("@Ann and @Ann"));
    const second = para(text("@Ann"));
    transformer(first);
    transformer(second);
    assert.deepEqual(mentionsOf(first), ["@Ann", "@Ann"]);
    assert.deepEqual(mentionsOf(second), ["@Ann"]);
  });
});

describe("rankMentionTargets", () => {
  it("ranks exact, then prefix, then substring matches", () => {
    assert.deepEqual(labelsOf(rankMentionTargets(LABELS, "ann")), [
      "Ann",
      "ann",
      "Ann Lee",
      "Annabelle",
      "Annie",
      "Jo Ann Smith",
    ]);
    // "Zoe Andrews" only holds the query inside the label, so it ranks last.
    assert.deepEqual(labelsOf(rankMentionTargets([target("Zoe Andrews"), target("Ann")], "an")), [
      "Ann",
      "Zoe Andrews",
    ]);
  });

  it("ignores case and surrounding whitespace", () => {
    assert.deepEqual(labelsOf(rankMentionTargets(LABELS, "  AN  ")), labelsOf(rankMentionTargets(LABELS, "an")));
  });

  it("keeps the input order within a bucket", () => {
    assert.deepEqual(labelsOf(rankMentionTargets(LABELS, "zz")), []);
    assert.deepEqual(labelsOf(rankMentionTargets([target("Jo"), target("Bo")], "o")), ["Jo", "Bo"]);
  });

  it("caps an empty query, which matches everyone", () => {
    const many = Array.from({ length: 20 }, (_, i) => target(`Member ${i}`));
    assert.equal(rankMentionTargets(many, "").length, 8);
    assert.equal(rankMentionTargets(many, "member").length, 8);
  });

  it("returns nothing when no label matches", () => {
    assert.deepEqual(rankMentionTargets(LABELS, "zz"), []);
  });
});

describe("mentionUrlTransform", () => {
  it("keeps the mention marker and defers every other scheme to react-markdown", () => {
    assert.equal(mentionUrlTransform("mention:"), "mention:");
    for (const url of ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,x", "vbscript:x"]) {
      assert.equal(mentionUrlTransform(url), "", url);
    }
  });
});

describe("pickerIndex", () => {
  it("selects the first row once the query has picked the list", () => {
    assert.equal(pickerIndex(null, LABELS, "an"), 0);
  });

  it("selects nothing for a blank query the user has not arrowed into", () => {
    assert.equal(pickerIndex(null, LABELS, ""), -1);
    assert.equal(pickerIndex(null, LABELS, "   "), -1);
  });

  it("keeps the picked person highlighted when the list re-ranks under a new query", () => {
    // The review's H1: arrowing to "User T." and then typing one character
    // re-ranked the list and made Enter name "User O." instead. Selection is
    // an id, so it follows the person rather than the slot.
    const before = [target("Admin U."), target("User O."), target("User T.")];
    const after = [target("User O."), target("User T."), target("Admin U.")];
    assert.equal(pickerIndex(before[2].id, before, ""), 2);
    assert.equal(pickerIndex(before[2].id, after, "U"), 1);
  });

  it("selects nothing once the picked person is gone from the list", () => {
    assert.equal(pickerIndex("Gone", [target("Ann"), target("Bo")], "an"), -1);
  });

  it("selects nothing with no rows to select", () => {
    assert.equal(pickerIndex(null, [], "an"), -1);
    assert.equal(pickerIndex("Ann", [], ""), -1);
  });
});

describe("nextPickerIndex", () => {
  it("passes every key through on an empty list", () => {
    // The review's untested branch: the empty-list early return. Even the
    // arrows must reach the editor — there is no row to move to.
    for (const key of ["ArrowUp", "ArrowDown", "Enter", "Tab", "Escape"]) {
      assert.equal(nextPickerIndex(key, -1, []), -1, key);
    }
  });

  it("passes Enter and Tab through when nothing is highlighted", () => {
    // The review's untested branch: a bare Enter after `@` must reach the
    // editor and insert a newline, not insert whoever happens to be first.
    assert.equal(nextPickerIndex("Enter", -1, LABELS), -1);
    assert.equal(nextPickerIndex("Tab", -1, LABELS), -1);
  });

  it("picks the highlighted row on Enter and Tab", () => {
    for (const key of ["Enter", "Tab"]) {
      assert.equal(nextPickerIndex(key, 0, LABELS), 0, key);
      assert.equal(nextPickerIndex(key, 2, LABELS), 2, key);
    }
  });

  it("wraps the arrows around the ends of the list", () => {
    assert.equal(nextPickerIndex("ArrowUp", -1, LABELS), LABELS.length - 1);
    assert.equal(nextPickerIndex("ArrowUp", 0, LABELS), LABELS.length - 1);
    assert.equal(nextPickerIndex("ArrowUp", 1, LABELS), 0);
    assert.equal(nextPickerIndex("ArrowDown", -1, LABELS), 0);
    assert.equal(nextPickerIndex("ArrowDown", LABELS.length - 1, LABELS), 0);
    assert.equal(nextPickerIndex("ArrowDown", 1, LABELS), 2);
  });

  it("passes every other key through", () => {
    for (const key of ["Escape", "a", "Home", "ArrowLeft"]) {
      assert.equal(nextPickerIndex(key, 0, LABELS), -1, key);
      assert.equal(nextPickerIndex(key, -1, LABELS), -1, key);
    }
  });

  it("composes with pickerIndex the way the editor wires it", () => {
    // Blank query after `@`: nothing highlighted, so Enter inserts a newline;
    // one typed character highlights row 0, so Enter picks it.
    assert.equal(nextPickerIndex("Enter", pickerIndex(null, LABELS, ""), LABELS), -1);
    assert.equal(nextPickerIndex("Enter", pickerIndex(null, LABELS, "an"), LABELS), 0);
  });
});
