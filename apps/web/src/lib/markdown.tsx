import * as React from "react";
import type { Components } from "react-markdown";
import { cn } from "./utils";

/**
 * Strip markdown syntax so the preview shows only plain text.
 * Keeps link/image alt text, removes formatting markers.
 */
export function stripMarkdown(text: string | undefined | null): string {
  if (!text) return "";
  let t = String(text);

  // Fenced code blocks: keep inner content, drop fences + language
  t = t.replace(/```[\s\S]*?```/g, (match) => {
    const inner = match.replace(/^```[^\n]*\n?/, "").replace(/\n?```\s*$/, "");
    return ` ${inner.trim()} `;
  });

  // Inline code
  t = t.replace(/`([^`]+)`/g, "$1");

  // Images: ![alt](url) -> alt
  t = t.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");

  // Links: [text](url) -> text
  t = t.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");

  // Autolinks <https://...>
  t = t.replace(/<([^>\s]+)>/g, "$1");

  // ATX headings: ### Heading -> Heading
  t = t.replace(/^#{1,6}\s+/gm, "");

  // Blockquotes: > quote -> quote
  t = t.replace(/^>\s?/gm, "");

  // Horizontal rules: ---, *** , ___
  t = t.replace(/^(\s*[-*_]){3,}\s*$/gm, "");

  // Unordered list markers: - , * , + at line start
  t = t.replace(/^[\t ]*[-*+]\s+/gm, "");

  // Ordered list markers: 1. , 2. etc. at line start
  t = t.replace(/^[\t ]*\d+\.\s+/gm, "");

  // Bold+italic ***text*** before ** and *
  t = t.replace(/\*\*\*([^\*]+)\*\*\*/g, "$1");
  t = t.replace(/\*\*([^\*]+)\*\*/g, "$1");
  t = t.replace(/\*([^\*]+)\*/g, "$1");
  t = t.replace(/__([^_]+)__/g, "$1");
  t = t.replace(/_([^_]+)_/g, "$1");
  t = t.replace(/~~([^~]+)~~/g, "$1");

  // Escaped markdown chars: \* -> *
  t = t.replace(/\\([*_`\[\]()#+\-.!{}\\>])/g, "$1");

  // Collapse remaining whitespace/newlines into single spaces
  t = t.replace(/\n+/g, " ");
  t = t.replace(/\s+/g, " ").trim();

  return t;
}

/**
 * Components for react-markdown that give messages proper typography
 * even without @tailwindcss/typography (prose) installed.
 * Handles code blocks, inline code, blockquotes, lists, links with target=_blank.
 */
function LinkBase({
  href,
  children,
  className,
  ...rest
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & { children?: React.ReactNode; className?: string }) {
  // react-markdown injects `node` prop which must not be spread to DOM
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { node: _node, ...domProps } = rest as any;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className} {...domProps}>
      {children}
    </a>
  );
}

/** Protocol marker `highlightMentions` emits; `a` overrides turn it into a span. */
const MENTION_SCHEME = "mention:";

/**
 * Rewrite `@Name` occurrences of known people into a marker link so the `a`
 * overrides can style them. The message body itself stays plain markdown —
 * other clients read the raw text.
 *
 * ponytail: plain string replacement, so a name that also appears inside a
 * fenced code block or a URL gets highlighted too. Replace with an AST pass if
 * that ever matters.
 */
export function highlightMentions(markdown: string, names: string[]): string {
  // One pass, so a replacement can never be re-matched by a later name.
  const unique = [...new Set(names.filter(Boolean))].sort((a, b) => b.length - a.length);
  if (unique.length === 0) return markdown;
  // Longest first so "Ann Lee" wins over "Ann" at the same position.
  const alternation = unique.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  return markdown.replace(
    new RegExp(`@(${alternation})`, "g"),
    (_match, name: string) => `[@${name}](${MENTION_SCHEME})`,
  );
}

/** Shared render for a highlighted mention; not a real link. */
function MentionSpan({ children, inverted }: { children?: React.ReactNode; inverted?: boolean }) {
  return (
    <span
      className={cn(
        "rounded px-1 py-0.5 font-medium",
        inverted ? "bg-white/20 text-primary-foreground" : "bg-primary/10 text-primary"
      )}
    >
      {children}
    </span>
  );
}

export const markdownComponents: Components = {
  a(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, href, node: _node, ...rest } = props as any;
    if (typeof href === "string" && href.startsWith(MENTION_SCHEME)) {
      return <MentionSpan>{children}</MentionSpan>;
    }
    return (
      <LinkBase href={href} className="text-primary underline underline-offset-4 hover:text-primary/80" {...(rest as any)}>
        {children}
      </LinkBase>
    );
  },
  code(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { inline, className, children, node: _node, ...rest } = props as any;
    const isInline = inline ?? !String(className ?? "").includes("language-");
    if (isInline) {
      return (
        <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-[0.85em] break-words" {...rest}>
          {children}
        </code>
      );
    }
    return (
      <code className="font-mono text-sm" {...rest}>
        {children}
      </code>
    );
  },
  pre(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <pre className="bg-muted my-2 overflow-x-auto rounded-md p-3 font-mono text-sm leading-relaxed" {...rest}>
        {children}
      </pre>
    );
  },
  blockquote(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <blockquote className="border-muted-foreground/30 my-2 border-l-4 pl-4 italic" {...rest}>
        {children}
      </blockquote>
    );
  },
  ul(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <ul className="my-2 ml-6 list-disc space-y-1" {...rest}>
        {children}
      </ul>
    );
  },
  ol(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <ol className="my-2 ml-6 list-decimal space-y-1" {...rest}>
        {children}
      </ol>
    );
  },
  li(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <li className="leading-relaxed" {...rest}>
        {children}
      </li>
    );
  },
  p(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <p className="my-1.5 leading-relaxed" {...rest}>
        {children}
      </p>
    );
  },
  hr(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { node: _node, ...rest } = props as any;
    return <hr className="border-border my-3" {...(rest as any)} />;
  },
  h1(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <h1 className="mt-4 text-xl font-semibold" {...rest}>
        {children}
      </h1>
    );
  },
  h2(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <h2 className="mt-3 text-lg font-semibold" {...rest}>
        {children}
      </h2>
    );
  },
  h3(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <h3 className="mt-2 text-base font-semibold" {...rest}>
        {children}
      </h3>
    );
  },
};

/**
 * Variant for messages rendered on a primary (blue) bubble — links need
 * foreground contrast (white) instead of primary blue-on-blue.
 * Code blocks also need inverted bg so white-on-light doesn't wash out.
 */
export const markdownComponentsInverted: Components = {
  ...markdownComponents,
  a(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, href, node: _node, ...rest } = props as any;
    if (typeof href === "string" && href.startsWith(MENTION_SCHEME)) {
      return <MentionSpan inverted>{children}</MentionSpan>;
    }
    return (
      <LinkBase href={href} className="text-primary-foreground underline decoration-primary-foreground/60 underline-offset-4 hover:opacity-90" {...(rest as any)}>
        {children}
      </LinkBase>
    );
  },
  code(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { inline, className, children, node: _node, ...rest } = props as any;
    const isInline = inline ?? !String(className ?? "").includes("language-");
    if (isInline) {
      return (
        <code className="border-white/20 bg-white/20 rounded px-1.5 py-0.5 font-mono text-[0.85em] break-words text-primary-foreground" {...rest}>
          {children}
        </code>
      );
    }
    return (
      <code className="font-mono text-sm text-primary-foreground" {...rest}>
        {children}
      </code>
    );
  },
  pre(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <pre className="bg-white/15 border-white/20 my-2 overflow-x-auto rounded-md border p-3 font-mono text-sm leading-relaxed text-primary-foreground" {...rest}>
        {children}
      </pre>
    );
  },
  blockquote(props) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { children, node: _node, ...rest } = props as any;
    return (
      <blockquote className="border-white/40 my-2 border-l-4 pl-4 italic text-primary-foreground/90" {...rest}>
        {children}
      </blockquote>
    );
  },
};

export function truncate(text: string | undefined | null, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "…" : text;
}
