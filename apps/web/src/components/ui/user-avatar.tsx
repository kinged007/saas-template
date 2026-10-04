"use client";

import * as React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { getInitials, getInitialsFromNames } from "@/lib/avatar";
import { useAvatarSrc } from "@/hooks/useAvatarSrc";
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
  /** Optional click handler (e.g. to open user profile) */
  onClick?: (e: React.MouseEvent<HTMLElement>) => void;
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
  onClick,
}: UserAvatarProps) {
  const displayName = (name ?? "").trim() || "U";
  const initials = React.useMemo(() => {
    if (firstName || lastName) {
      return getInitialsFromNames(firstName, lastName, displayName);
    }
    return getInitials(displayName);
  }, [firstName, lastName, displayName]);

  const src = useAvatarSrc(avatarUrl);

  const avatar = (
    <Avatar className={cn(sizeClassName, className)}>
      <AvatarImage src={src} alt={displayName} />
      <AvatarFallback className={cn(fallbackClassName)}>{initials}</AvatarFallback>
    </Avatar>
  );

  const clickable = !!onClick;

  if (!withTooltip) {
    // ponytail: no TooltipTrigger wrapper here to avoid stacking native components under Tooltip internals; add when avatar needs non-clickable outside-tooltip a11y.
    return clickable ? (
      <button
        type="button"
        aria-label={`Open profile for ${displayName}`}
        onClick={(e) => {
          e.stopPropagation();
          onClick!(e);
        }}
        className="inline-flex shrink-0 cursor-pointer rounded-full transition-opacity hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1"
      >
        {avatar}
      </button>
    ) : (
      <span className="inline-flex shrink-0 cursor-default">{avatar}</span>
    );
  }

  // TooltipTrigger defaults to a <button>; use asChild with a span because
  // avatars render inside native <button> rows (conversation list).
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            {...(clickable
              ? {
                  role: "button",
                  tabIndex: 0,
                  "aria-label": `Open profile for ${displayName}`,
                  onClick: (e: React.MouseEvent<HTMLSpanElement>) => {
                    e.stopPropagation();
                    onClick!(e);
                  },
                  onKeyDown: (e: React.KeyboardEvent<HTMLSpanElement>) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.stopPropagation();
                      e.preventDefault();
                      onClick!(e as unknown as React.MouseEvent<HTMLSpanElement>);
                    }
                  },
                }
              : {})}
            className={
              clickable
                ? "inline-flex shrink-0 cursor-pointer rounded-full transition-opacity hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1"
                : "inline-flex shrink-0 cursor-default"
            }
          >
            {avatar}
          </span>
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
