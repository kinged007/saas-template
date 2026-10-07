import { Check, Copy } from "lucide-react";

import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * Icon-only copy button. The icon flips to a check while `copied` holds, so the
 * accessible name follows; the pair it keeps is `title` + `aria-label`, equal to
 * each other (#332) — `title` paints the hover tooltip, `aria-label` is what a
 * screen reader announces, and one derived binding keeps them from drifting
 * apart. Both are required: without either the control is announced as a bare
 * "button", and with only one a sighted mouse user and a screen reader user are
 * told different things.
 *
 * The clipboard write and the copied timeout stay with the caller.
 *
 * The Omit enforces `title`, `variant` and `children` so the pair this
 * component exists to keep cannot be overridden by a call site that silently
 * loses its value. `aria-label` does NOT hold: TypeScript does not check
 * hyphenated JSX attribute names against the props type, so it still compiles
 * through on any `<CopyButton>`. What keeps the pair authoritative is the
 * runtime ordering below — `{...props}` spreads first and `title={name}` /
 * `aria-label={name}` are forced last, so a stray attribute is overwritten and
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
  const name = copied ? "Copied" : label;
  return (
    <Button
      {...props}
      type={type}
      size={size}
      variant="outline"
      onClick={onClick}
      title={name}
      aria-label={name}
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </Button>
  );
}
