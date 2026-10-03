import { useEditor, EditorContent, ReactRenderer } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import Mention from "@tiptap/extension-mention";
import type { SuggestionProps, SuggestionKeyDownProps } from "@tiptap/suggestion";
import TurndownService from "turndown";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/components/ui/user-avatar";
import { Bold, Italic, Code2, SquareCode, List, ListOrdered, Link2, Quote } from "lucide-react";
import { cn } from "@/lib/utils";
import { pickerIndex, rankMentionTargets, type MentionTarget } from "@/lib/mentions";

const turndownService = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
});

// A mention is an inline atom node, so the markdown body has to be recovered
// from the node itself — otherwise it serialises to an empty span.
turndownService.addRule("mention", {
  filter: (node) => node.nodeName === "SPAN" && node.getAttribute("data-type") === "mention",
  replacement: (_content, node) => `@${node.getAttribute("data-label") ?? ""}`,
});

type MentionListRef = {
  onKeyDown: (props: SuggestionKeyDownProps) => boolean;
};

const MentionList = forwardRef<MentionListRef, SuggestionProps<MentionTarget>>(function MentionList(
  props,
  ref,
) {
  // The picked person, not their position: a keystroke re-ranks the list, and
  // a position would land on whoever moved into that slot.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const items = props.items;
  const index = pickerIndex(selectedId, items, props.query);

  const select = (i: number) => {
    const item = items[i];
    if (item) props.command({ id: item.id, label: item.label, type: item.type });
  };

  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (items.length === 0) return false;
      if (event.key === "ArrowUp") {
        setSelectedId(items[index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length].id);
        return true;
      }
      if (event.key === "ArrowDown") {
        setSelectedId(items[index < 0 ? 0 : (index + 1) % items.length].id);
        return true;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        // Nothing to highlight: pass the key on to the editor rather than
        // swallowing it, so Enter still inserts a newline.
        if (index < 0) return false;
        select(index);
        return true;
      }
      return false;
    },
  }));

  if (items.length === 0) {
    return (
      <div className="bg-popover text-popover-foreground rounded-md border p-3 text-sm shadow-md">
        No one to mention here.
      </div>
    );
  }

  return (
    <div className="bg-popover text-popover-foreground overflow-hidden rounded-md border shadow-md">
      {/* max-h-72 is 288px, so all MENTION_PICKER_LIMIT (8) rows of 32px fit. */}
      <ul className="max-h-72 overflow-y-auto p-1">
        {items.map((item, i) => (
          <li key={item.id}>
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm",
                i === index ? "bg-accent text-accent-foreground" : "hover:bg-accent/60"
              )}
              // onMouseDown so the click lands before the editor loses focus.
              onMouseDown={(e) => {
                e.preventDefault();
                select(i);
              }}
            >
              <UserAvatar
                name={item.label}
                email={item.email ?? null}
                avatarUrl={item.avatar_url ?? null}
                sizeClassName="h-5 w-5"
                fallbackClassName="text-[9px]"
                firstName={item.first_name ?? null}
                lastName={item.last_name ?? null}
                withTooltip={false}
              />
              <span className="truncate font-medium">{item.label}</span>
              {item.email && <span className="text-muted-foreground truncate text-xs">{item.email}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
});

type Props = {
  value: string;
  onChange: (markdown: string, html: string) => void;
  placeholder?: string;
  className?: string;
  minHeight?: string;
  /** Omit (or pass []) to turn the `@` picker off. */
  mentions?: MentionTarget[];
  /** Ids of the users currently mentioned in the draft, in document order. */
  onMention?: (userIds: string[]) => void;
};

export function TiptapEditor({ value, onChange, placeholder = "Write a message…", className, minHeight = "80px", mentions, onMention }: Props) {
  const mentionKey = useMemo(() => (mentions ?? []).map((m) => m.id).join(","), [mentions]);
  // The picker reads the latest list without the extension being rebuilt for it.
  const mentionsRef = useRef(mentions);
  mentionsRef.current = mentions;

  // Which formatting control holds the toolbar's single tab stop.
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [toolbarIndex, setToolbarIndex] = useState(0);

  const editor = useEditor(
    {
      extensions: [
        StarterKit.configure({
          heading: false,
          // StarterKit bundles Link; the explicitly configured Link below wins.
          link: false,
          // StarterKit includes codeBlock/bulletList/orderedList/blockquote/code etc.
        }),
        Placeholder.configure({ placeholder }),
        Link.configure({
          openOnClick: false,
          autolink: true,
          linkOnPaste: true,
          HTMLAttributes: { rel: "noopener noreferrer", target: null },
        }),
        Mention.configure({
          HTMLAttributes: { class: "mention" },
          renderText: ({ node }) => `@${node.attrs.label}`,
          renderHTML: ({ node }) => [
            "span",
            { "data-type": "mention", "data-id": node.attrs.id, "data-label": node.attrs.label, class: "mention" },
            `@${node.attrs.label}`,
          ],
          suggestion: {
            char: "@",
            items: ({ query }) => rankMentionTargets(mentionsRef.current ?? [], query),
            render: () => {
              let component: ReactRenderer<MentionListRef> | null = null;
              let unmount: (() => void) | null = null;
              return {
                onStart: (props: SuggestionProps<MentionTarget>) => {
                  component = new ReactRenderer(MentionList, { props, editor: props.editor });
                  component.element.classList.add("z-50");
                  // TipTap mounts into document.body and keeps it anchored to the
                  // caret, repositioning on scroll/resize.
                  unmount = props.mount(component.element);
                },
                onUpdate: (props: SuggestionProps<MentionTarget>) => {
                  component?.updateProps(props);
                },
                onKeyDown: (props: SuggestionKeyDownProps) => {
                  if (props.event.key === "Escape") {
                    unmount?.();
                    component?.destroy();
                    component = null;
                    unmount = null;
                    return true;
                  }
                  return component?.ref?.onKeyDown(props) ?? false;
                },
                onExit: () => {
                  unmount?.();
                  component?.destroy();
                  component = null;
                  unmount = null;
                },
              };
            },
          },
        }),
      ],
      content: value ? `<p>${escapeHtml(value)}</p>` : "",
      onUpdate: ({ editor }) => {
        const html = editor.getHTML();
        let markdown: string;
        try {
          markdown = turndownService.turndown(html);
        } catch {
          markdown = editor.getText();
        }
        // turndown leaves extra newlines; trim
        markdown = markdown.trim();
        onChange(markdown, html);
        const userIds: string[] = [];
        editor.state.doc.descendants((node) => {
          if (node.type.name === "mention" && typeof node.attrs.id === "string") {
            userIds.push(node.attrs.id);
          }
          return true;
        });
        onMention?.(userIds);
      },
    },
    // Rebuild when the mentionable set changes; the picker closes over it.
    [mentionKey],
  );

  // Sync external value if needed (e.g., reset after send)
  useEffect(() => {
    if (!editor) return;
    const currentMarkdown = (() => {
      try {
        return turndownService.turndown(editor.getHTML()).trim();
      } catch {
        return editor.getText();
      }
    })();
    if (value !== currentMarkdown) {
      if (!value) {
        editor.commands.clearContent();
      } else {
        // Avoid loop: only set if drastically different
        const html = `<p>${escapeHtml(value)}</p>`;
        const editorHtml = editor.getHTML();
        if (html !== editorHtml) {
          // For markdown initial value, we treat it as plain text for now
          // If value contains markdown syntax, render as text
        }
      }
    }
  }, [value, editor]);

  if (!editor) return null;

  const toolbarButtons = () => Array.from(toolbarRef.current?.querySelectorAll("button") ?? []);

  /** The toolbar control the event came from, or -1 when it came from the container. */
  const toolbarIndexOf = (target: EventTarget | null) =>
    target instanceof HTMLButtonElement ? toolbarButtons().indexOf(target) : -1;

  /**
   * APG toolbar: one tab stop for the whole group, arrow keys move inside it.
   * The tab stop follows whatever control last took focus.
   */
  const onToolbarKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const buttons = toolbarButtons();
    const current = toolbarIndexOf(e.target);
    const last = buttons.length - 1;
    const next =
      e.key === "ArrowRight" ? (current + 1) % buttons.length
      : e.key === "ArrowLeft" ? (current === 0 ? last : current - 1)
      : e.key === "Home" ? 0
      : e.key === "End" ? last
      : -1;
    if (current < 0 || next < 0) return;
    e.preventDefault();
    buttons[next].focus();
  };

  const onToolbarFocus = (e: React.FocusEvent<HTMLDivElement>) => {
    const index = toolbarIndexOf(e.target);
    if (index >= 0) setToolbarIndex(index);
  };

  return (
    // Every control below keeps the editor's focus by eating mousedown and
    // acting on `click`, the one event a keyboard activation fires too.
    <div className={cn("rounded-md border bg-background", className)}>
      <div
        ref={toolbarRef}
        role="toolbar"
        aria-label="Formatting"
        className="flex flex-wrap items-center gap-1 border-b p-1"
        onKeyDown={onToolbarKeyDown}
        onFocus={onToolbarFocus}
      >
        <Button
          type="button"
          variant={editor.isActive("bold") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Bold"
          aria-label="Bold"
          aria-pressed={editor.isActive("bold")}
          tabIndex={toolbarIndex === 0 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            editor.chain().focus().toggleBold().run();
          }}
        >
          <Bold className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant={editor.isActive("italic") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Italic"
          aria-label="Italic"
          aria-pressed={editor.isActive("italic")}
          tabIndex={toolbarIndex === 1 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            editor.chain().focus().toggleItalic().run();
          }}
        >
          <Italic className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant={editor.isActive("code") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Inline code"
          aria-label="Inline code"
          aria-pressed={editor.isActive("code")}
          tabIndex={toolbarIndex === 2 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            editor.chain().focus().toggleCode().run();
          }}
        >
          <Code2 className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant={editor.isActive("codeBlock") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Code block"
          aria-label="Code block"
          aria-pressed={editor.isActive("codeBlock")}
          tabIndex={toolbarIndex === 3 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            editor.chain().focus().toggleCodeBlock().run();
          }}
        >
          <SquareCode className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant={editor.isActive("bulletList") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Bullet list"
          aria-label="Bullet list"
          aria-pressed={editor.isActive("bulletList")}
          tabIndex={toolbarIndex === 4 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            editor.chain().focus().toggleBulletList().run();
          }}
        >
          <List className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant={editor.isActive("orderedList") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Ordered list"
          aria-label="Ordered list"
          aria-pressed={editor.isActive("orderedList")}
          tabIndex={toolbarIndex === 5 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            editor.chain().focus().toggleOrderedList().run();
          }}
        >
          <ListOrdered className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant={editor.isActive("blockquote") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Quote"
          aria-label="Quote"
          aria-pressed={editor.isActive("blockquote")}
          tabIndex={toolbarIndex === 6 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            editor.chain().focus().toggleBlockquote().run();
          }}
        >
          <Quote className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          // Link is an action, not a toggle: it prompts for a URL, so it has no pressed state.
          variant={editor.isActive("link") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          title="Link"
          aria-label="Link"
          tabIndex={toolbarIndex === 7 ? 0 : -1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            const prev = editor.getAttributes("link").href as string | undefined;
            const url = window.prompt("Enter URL", prev || "https://");
            if (url === null) return;
            if (url === "") {
              editor.chain().focus().unsetLink().run();
            } else {
              editor.chain().focus().setLink({ href: url }).run();
            }
          }}
        >
          <Link2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      <EditorContent
        editor={editor}
        className={cn(
          "prose prose-sm dark:prose-invert max-w-none p-3 focus-within:outline-none",
          "[&_.tiptap]:outline-none [&_.tiptap]:min-h-[80px]",
          "[&_.tiptap_p.is-editor-empty:first-child::before]:text-muted-foreground [&_.tiptap_p.is-editor-empty:first-child::before]:content-[attr(data-placeholder)] [&_.tiptap_p.is-editor-empty:first-child::before]:float-left [&_.tiptap_p.is-editor-empty:first-child::before]:h-0 [&_.tiptap_p.is-editor-empty:first-child::before]:pointer-events-none",
          // Link visibly blue + underline
          "[&_.tiptap_a]:text-primary [&_.tiptap_a]:underline [&_.tiptap_a]:underline-offset-4 [&_.tiptap_a]:decoration-primary/50 hover:[&_.tiptap_a]:text-primary/80",
          // Blockquote visible left border
          "[&_.tiptap_blockquote]:border-l-4 [&_.tiptap_blockquote]:border-muted-foreground/30 [&_.tiptap_blockquote]:pl-4 [&_.tiptap_blockquote]:italic [&_.tiptap_blockquote]:my-2 [&_.tiptap_blockquote]:py-1",
          // Lists with visible markers (tailwind resets need re-added)
          "[&_.tiptap_ul]:list-disc [&_.tiptap_ul]:ml-6 [&_.tiptap_ul]:my-2 [&_.tiptap_ul]:space-y-1",
          "[&_.tiptap_ol]:list-decimal [&_.tiptap_ol]:ml-6 [&_.tiptap_ol]:my-2 [&_.tiptap_ol]:space-y-1",
          "[&_.tiptap_li_p]:m-0",
          // Inline code visibly distinct
          "[&_.tiptap_code]:bg-muted [&_.tiptap_code]:rounded [&_.tiptap_code]:px-1.5 [&_.tiptap_code]:py-0.5 [&_.tiptap_code]:font-mono [&_.tiptap_code]:text-[0.9em] [&_.tiptap_code]:border",
          // Mention node, same treatment the rendered message gets
          "[&_.tiptap_.mention]:bg-primary/10 [&_.tiptap_.mention]:text-primary [&_.tiptap_.mention]:rounded [&_.tiptap_.mention]:px-1 [&_.tiptap_.mention]:py-0.5 [&_.tiptap_.mention]:font-medium",
          // Code block distinct from inline (pre wraps code)
          "[&_.tiptap_pre]:bg-muted [&_.tiptap_pre]:rounded-md [&_.tiptap_pre]:p-3 [&_.tiptap_pre]:my-2 [&_.tiptap_pre]:overflow-x-auto [&_.tiptap_pre]:font-mono [&_.tiptap_pre]:text-sm [&_.tiptap_pre]:border",
          "[&_.tiptap_pre_code]:bg-transparent [&_.tiptap_pre_code]:p-0 [&_.tiptap_pre_code]:border-0 [&_.tiptap_pre_code]:rounded-none"
        )}
        style={{ minHeight } as React.CSSProperties}
      />
    </div>
  );
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function htmlToMarkdown(html: string): string {
  try {
    return turndownService.turndown(html).trim();
  } catch {
    return html;
  }
}
