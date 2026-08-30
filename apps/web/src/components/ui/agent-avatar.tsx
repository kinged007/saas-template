"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getInitials, parseAvatarValue } from "@/lib/avatar";
import { cn } from "@/lib/utils";

type Props = {
  value?: string | null;
  name: string;
  sizeClassName?: string;
  className?: string;
};

export function AgentAvatar({ value, name, sizeClassName = "h-8 w-8", className }: Props) {
  const parsed = parseAvatarValue(value);
  if (parsed?.kind === "emoji") {
    return (
      <span
        className={cn(
          "inline-flex items-center justify-center rounded-full bg-muted text-lg",
          sizeClassName,
          className,
        )}
        aria-label={name}
      >
        {parsed.value}
      </span>
    );
  }
  if (parsed?.kind === "url") {
    const initials = getInitials(name);
    return (
      <Avatar className={cn(sizeClassName, className)}>
        <AvatarImage src={parsed.value} alt={name} />
        <AvatarFallback>{initials}</AvatarFallback>
      </Avatar>
    );
  }
  const initials = getInitials(name);
  return (
    <Avatar className={cn(sizeClassName, className)}>
      <AvatarFallback>{initials}</AvatarFallback>
    </Avatar>
  );
}
