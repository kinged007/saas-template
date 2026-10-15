import { defaultUrlTransform } from "react-markdown";

/** Protocol marker `mentionRemarkPlugin` emits; the `a` overrides turn it into a span. */
export const MENTION_SCHEME = "mention:";

/**
 * An entity the `@` picker can insert. This array is the extension point:
 * adding agents or any other mentionable later means appending entries, not
 * changing the picker.
 */
export type MentionTarget = {
  id: string;
  type: string;
  label: string;
  email?: string | null;
  avatar_url?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  role?: string | null;
};

/** Rows the picker renders; the list box is sized to show exactly this many. */
export const MENTION_PICKER_LIMIT = 8;

/**
 * Rank candidates for the `@` query: exact match, then a label starting with
 * the query, then any other label containing it. Each bucket keeps the order
 * the editor was handed, so equally-ranked names stay in that order. The
 * result is capped, so the list stays usable as the mentionable set grows.
 */
export function rankMentionTargets(targets: MentionTarget[], query: string): MentionTarget[] {
  const q = query.trim().toLowerCase();
  // An empty query lists everyone, so it needs the cap just as much.
  if (!q) return targets.slice(0, MENTION_PICKER_LIMIT);
  const exact: MentionTarget[] = [];
  const wordPrefix: MentionTarget[] = [];
  const other: MentionTarget[] = [];
  for (const target of targets) {
    const label = target.label.toLowerCase();
    if (label === q) exact.push(target);
    else if (label.startsWith(q)) wordPrefix.push(target);
    else if (label.includes(q)) other.push(target);
  }
  return [...exact, ...wordPrefix, ...other].slice(0, MENTION_PICKER_LIMIT);
}

/**
 * The row the picker highlights, or -1 when there is nothing to highlight.
 *
 * The selection is an id, not a position: a query change re-ranks the list, and
 * an index carried across it would land on whoever moved into that slot and
 * name a person the user did not pick. An id that is no longer in the list
 * highlights nothing rather than a substitute.
 *
 * With nothing picked yet, a blank query lists everyone so it highlights
 * nothing until the user arrows in — a bare Enter after `@` must not insert
 * whoever happens to be first — while a real query has one obvious first match.
 */
export function pickerIndex(selectedId: string | null, items: MentionTarget[], query: string): number {
  if (items.length === 0) return -1;
  if (selectedId !== null) return items.findIndex((i) => i.id === selectedId);
  return query.trim() ? 0 : -1;
}

/**
 * The row the picker's key handler acts on, or -1 when the key must pass
 * through to the editor: an empty list has no row to act on, `Enter`/`Tab`
 * with nothing highlighted must not be swallowed (a bare Enter after `@`
 * still has to insert a newline), and every other key belongs to the editor.
 */
export function nextPickerIndex(key: string, index: number, items: MentionTarget[]): number {
  if (items.length === 0) return -1;
  if (key === "ArrowUp") return index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length;
  if (key === "ArrowDown") return index < 0 ? 0 : (index + 1) % items.length;
  if (key === "Enter" || key === "Tab") return index;
  return -1;
}

/**
 * react-markdown's default `urlTransform` drops any href without a known
 * scheme, which turns the mention marker into an empty `href` before the `a`
 * override sees it. Keep the marker and defer every other decision to the
 * default transform so javascript:/data: links stay blocked.
 */
export function mentionUrlTransform(url: string): string {
  if (url.startsWith(MENTION_SCHEME)) return url;
  return defaultUrlTransform(url);
}

/** The subset of an mdast/hast node this plugin needs to walk. */
type TreeNode = { type: string; value?: string; url?: string; children?: TreeNode[] };

/**
 * A remark plugin that rewrites `@Name` occurrences of known people into a
 * marker link so the `a` overrides can style them. The message body itself
 * stays plain markdown — other clients read the raw text.
 *
 * It runs on the parsed tree, so only `text` nodes are considered: a name
 * inside a fenced block, an inline code span or a URL is left alone. Both
 * boundaries are Unicode-aware: a trailing `\p{L}\p{N}_` keeps `@Ann` from
 * matching `@Annabelle`, and a leading lookbehind keeps it from matching the
 * `@` inside an address (`bob@Ann.com`, `bobé@Ann.com`) or anywhere in a URL —
 * a path (`/u/@Ann`) or a query string (`?u=@Ann`), since `remark-gfm` is not
 * enabled and a bare URL is parsed as one `text` node.
 *
 * Markdown `link` and `linkReference` nodes are skipped as well: a mention
 * inside a link label would nest one anchor inside another.
 */
export function mentionRemarkPlugin(names: string[]) {
  // One pass, so a match can never be re-matched by a later name.
  const unique = [...new Set(names.filter(Boolean))].sort((a, b) => b.length - a.length);
  if (unique.length === 0) return function noopPlugin() { return function noop() {}; };
  // Longest first so "Ann Lee" wins over "Ann" at the same position.
  const alternation = unique.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  // ponytail: the lookbehind needs Safari 16.4+ (Mar 2023). If that floor is
  // too high, rewrite the leading guard as a captured-prefix check.
  const re = new RegExp(`(?<![\\p{L}\\p{N}_.~%+\\-/?&=])@(${alternation})(?![\\p{L}\\p{N}_])`, "gu");
  return function attacher() {
    return function transformer(tree: TreeNode) {
      const children = tree.children;
      if (!Array.isArray(children)) return;
      for (let i = 0; i < children.length; i++) {
        const child = children[i];
        if (child.type === "text" && typeof child.value === "string") {
          const replaced = splitText(child.value);
          if (replaced) {
            children.splice(i, 1, ...replaced);
            i += replaced.length - 1;
          }
          continue;
        }
        if (child.type !== "code" && child.type !== "inlineCode" && child.type !== "image" && child.type !== "link" && child.type !== "linkReference") {
          transformer(child);
        }
      }
    };
  };
  function splitText(value: string): TreeNode[] | null {
    re.lastIndex = 0;
    if (!re.test(value)) return null;
    re.lastIndex = 0;
    const out: TreeNode[] = [];
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(value)) !== null) {
      if (m.index > last) out.push({ type: "text", value: value.slice(last, m.index) });
      // The `@` is kept in the label so the mention renders as `@Name`, the
      // same as the plain-text form the editor writes.
      out.push({ type: "link", url: MENTION_SCHEME, children: [{ type: "text", value: m[0] }] });
      last = m.index + m[0].length;
    }
    if (last < value.length) out.push({ type: "text", value: value.slice(last) });
    return out;
  }
}
