import type { UserProfile } from "@/types";

/** Row fields a call site can offer so the dialog renders something useful. */
export type UserProfileFallback = Pick<
  UserProfile,
  "first_name" | "last_name" | "display_name" | "email" | "avatar_url"
> & { preloaded?: UserProfile | null };

export type UserProfileDialogBodyState = "loading" | "empty" | "dead-end" | "profile";

/**
 * Which body `UserProfileDialog` renders.
 *
 * A failed load is only a dead end when nothing at all can be shown: preloaded
 * data and partial row fields keep rendering alongside the retry affordance.
 */
export function profileBodyState(input: {
  isLoading: boolean;
  isError: boolean;
  profile: UserProfile | null | undefined;
  fallback?: UserProfileFallback | null;
}): UserProfileDialogBodyState {
  if (input.isLoading) return "loading";
  if (input.profile || input.fallback) return "profile";
  return input.isError ? "dead-end" : "empty";
}
