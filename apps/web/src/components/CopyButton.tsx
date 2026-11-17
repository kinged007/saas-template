import { Check, Copy } from "lucide-react";

import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * Icon-only copy button. The confirmation is announced through a visually
 * hidden `role="status"` region (an implicit polite live region): the button
 * keeps DOM focus across the copy, and a screen reader announces an
 * accessible-name change on a focused element only opportunistically, while
 * text entering a live region is announced reliably (#1075). The button keeps
 * its `title` + `aria-label` pair at `label` (#332) — `title` paints the hover
 * tooltip, `aria-label` is what a screen reader announces, and one derived
 * binding keeps them from drifting apart — and the icon still flips to a check
 * while `copied` holds, as a purely visual confirmation.
 *
 * The clipboard write and the copied timeout stay with the caller.
 *
 * The Omit enforces `title`, `variant` and `children` so the pair this
 * component exists to keep cannot be overridden by a call site that silently
 * loses its value. `aria-label` does NOT hold: TypeScript does not check
 * hyphenated JSX attribute names against the props type, so it still compiles
 * through on any `<CopyButton>`. What keeps the pair authoritative is the
 * runtime ordering below — `{...props}` spreads first and `title={label}` /
 * `aria-label={label}` are forced last, so a stray attribute is overwritten and
 * the derived name always wins.
 *
 * `type` defaults to `button`; `ui/button.tsx` sets no default, so a bare
 * `<button>` inside a form would submit it. `size` defaults to `icon` for the
 * same reason: the control is a 16 px glyph, not a text button (#1223); a call
 * site that wants another box passes its own `size`.
 */
export function CopyButton({
  copied,
  label,
  onClick,
  type = "button",
  size = "icon",
  ...props
}: Omit<ButtonProps, "title" | "aria-label" | "variant" | "children"> & {
  copied: boolean;
  label: string;
}) {
  const subject = label.replace(/^Copy\s+/i, "");
  // `label` falls back for degenerate labels (e.g. bare "Copy") so the note
  // never hands a screen reader an empty subject.
  const note = copied
    ? subject
      ? subject.charAt(0).toUpperCase() + subject.slice(1) + " copied"
      : label
    : "";
  return (
    <>
      <Button
        {...props}
        type={type}
        size={size}
        variant="outline"
        onClick={onClick}
        title={label}
        aria-label={label}
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </Button>
      {/* Always mounted: a live region has to be in the tree before its text
          change is announced. Empty while `copied` is false. */}
      <span role="status" className="sr-only">
        {note}
      </span>
    </>
  );
}
