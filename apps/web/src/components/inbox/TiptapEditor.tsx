import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import TurndownService from "turndown";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Bold, Italic, Code2, SquareCode, List, ListOrdered, Link2, Quote } from "lucide-react";
import { cn } from "@/lib/utils";

const turndownService = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
});

type Props = {
  value: string;
  onChange: (markdown: string, html: string) => void;
  placeholder?: string;
  className?: string;
  minHeight?: string;
};

export function TiptapEditor({ value, onChange, placeholder = "Write a message…", className, minHeight = "80px" }: Props) {
  const editor = useEditor({
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
    },
  });

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

  return (
    <div className={cn("rounded-md border bg-background", className)}>
      <div className="flex flex-wrap items-center gap-1 border-b p-1">
        <Button
          type="button"
          variant={editor.isActive("bold") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          onMouseDown={(e) => {
            e.preventDefault();
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
          onMouseDown={(e) => {
            e.preventDefault();
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
          onMouseDown={(e) => {
            e.preventDefault();
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
          onMouseDown={(e) => {
            e.preventDefault();
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
          onMouseDown={(e) => {
            e.preventDefault();
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
          onMouseDown={(e) => {
            e.preventDefault();
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
          onMouseDown={(e) => {
            e.preventDefault();
            editor.chain().focus().toggleBlockquote().run();
          }}
        >
          <Quote className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant={editor.isActive("link") ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7"
          onMouseDown={(e) => {
            e.preventDefault();
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
