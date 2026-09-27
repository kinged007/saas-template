import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mentionRemarkPlugin } from "./markdown";
import { rankMentionTargets, type MentionTarget } from "@/components/inbox/TiptapEditor";

/** The subset of an mdast node these tests build by hand. */
type Node = { type: string; value?: string; url?: string; children?: Node[] };

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

  it("rejects an address or a URL path before the name, ASCII or not", () => {
    for (const source of ["bob@Ann", "bobé@Ann", "中文@Ann", "/u/@Ann", "a.b/@Ann"]) {
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
