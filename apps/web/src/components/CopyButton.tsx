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
  const name = copied ? "Copied" : label;
  return (
    <Button
      {...props}
      type={type}
      variant="outline"
      onClick={onClick}
      title={name}
      aria-label={name}
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </Button>
  );
}
