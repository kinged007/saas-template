"use client";

import * as React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { getAvatarSrc, getInitials, getInitialsFromNames } from "@/lib/avatar";
import { cn } from "@/lib/utils";

export type UserAvatarProps = {
  /** Display name shown in tooltip and used for fallback initials. */
  name: string;
  /** Email shown in tooltip (second line). */
  email?: string | null;
  /** Avatar URL – when empty, fallback initials are shown. */
  avatarUrl?: string | null;
  /** Tailwind size classes, e.g. "h-5 w-5" */
  sizeClassName?: string;
  /** Additional className for the Avatar root */
  className?: string;
  /** Class for the fallback text */
  fallbackClassName?: string;
  /** When false, renders without tooltip (useful for static contexts) */
  withTooltip?: boolean;
  /** Alternative: derive initials from first/last name fields */
  firstName?: string | null;
  lastName?: string | null;
};

/**
 * Canonical user avatar component.
 *
 * - Uses the central avatar helpers in `src/lib/avatar.ts` for src/initials.
 * - Wraps the avatar in a refine-theme Tooltip that shows name + email on hover.
 *
 * All avatar render sites should use this component instead of raw
 * `Avatar` + `AvatarImage` + `AvatarFallback` to keep display logic single-sourced.
 */
export function UserAvatar({
  name,
  email,
  avatarUrl,
  sizeClassName,
  className,
  fallbackClassName,
  withTooltip = true,
  firstName,
  lastName,
}: UserAvatarProps) {
  const displayName = (name ?? "").trim() || "U";
  const initials = React.useMemo(() => {
    if (firstName || lastName) {
      return getInitialsFromNames(firstName, lastName, displayName);
    }
    return getInitials(displayName);
  }, [firstName, lastName, displayName]);

  const src = getAvatarSrc(avatarUrl);

  const avatar = (
    <Avatar className={cn(sizeClassName, className)}>
      <AvatarImage src={src} alt={displayName} />
      <AvatarFallback className={cn(fallbackClassName)}>{initials}</AvatarFallback>
    </Avatar>
  );

  if (!withTooltip) return avatar;

  // TooltipProvider can be nested; keep it local so callers don't need to wrap pages.
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex shrink-0 cursor-default">{avatar}</span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[240px]">
          <div className="flex flex-col text-xs">
            <span className="font-medium leading-tight">{displayName}</span>
            {email ? <span className="opacity-80 leading-tight truncate">{email}</span> : null}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/** Alias that matches the "user profile class get avatar helper" phrasing */
export const UserProfileAvatarComponent = UserAvatar;
