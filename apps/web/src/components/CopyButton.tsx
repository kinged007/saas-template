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
 * `title`, `aria-label`, `variant` and `children` are Omitted so the pair this
 * component exists to keep cannot be overridden by a call site that silently
 * loses its value. `type` defaults to `button`; `ui/button.tsx` sets no default,
 * so a bare `<button>` inside a form would submit it.
 */
export function CopyButton({
  copied,
  label,
  onClick,
  type = "button",
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
