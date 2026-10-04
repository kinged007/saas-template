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
 */
export function CopyButton({
  copied,
  label,
  onClick,
  ...props
}: ButtonProps & { copied: boolean; label: string }) {
  const name = copied ? "Copied" : label;
  return (
    <Button
      {...props}
      variant="outline"
      onClick={onClick}
      title={name}
      aria-label={name}
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </Button>
  );
}
