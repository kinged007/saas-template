import { UserAvatar } from "@/components/ui/user-avatar";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePublicProfile } from "@/hooks/useProfile";
import { formatDisplayName } from "@/types";
import type { UserProfile } from "@/types";

type UserProfileDialogProps = {
  userId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fallback?: Pick<UserProfile, "first_name" | "last_name" | "display_name" | "email" | "avatar_url"> & { preloaded?: UserProfile | null };
};

function ProfileBody({ userId, fallback }: { userId: string | null; fallback: UserProfileDialogProps["fallback"] }) {
  const { data, isLoading, isError } = usePublicProfile(userId);
  const p: UserProfile | null | undefined = data ?? fallback?.preloaded ?? null;

  const displayName = p
    ? formatDisplayName(p.first_name, p.last_name, (p as unknown as { display_name?: string | null }).display_name ?? (fallback?.display_name as string) ?? (fallback as unknown as { email?: string })?.email ?? "User")
    : formatDisplayName(null, null, (fallback as unknown as { display_name?: string | null })?.display_name ?? (fallback?.email as string) ?? undefined) || "User";
  const email = (p as unknown as { email?: string | null })?.email ?? (fallback as unknown as { email?: string | null })?.email ?? null;
  const avatarUrl = (p as unknown as { avatar_url?: string | null })?.avatar_url ?? fallback?.avatar_url ?? null;

  if (isLoading) {
    return <p className="text-muted-foreground py-8 text-center text-sm">Loading…</p>;
  }
  if (isError) {
    return <p className="text-destructive py-8 text-center text-sm">Could not load profile.</p>;
  }
  if (!p && !fallback) {
    return <p className="text-muted-foreground py-8 text-center text-sm">No profile data.</p>;
  }

  const bio = p?.bio ?? null;
  const location = p?.location ?? null;
  const websiteUrl = p?.website_url ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <UserAvatar
          name={displayName}
          email={email}
          avatarUrl={avatarUrl}
          sizeClassName="h-16 w-16"
          fallbackClassName="text-lg"
          firstName={p?.first_name ?? fallback?.first_name ?? null}
          lastName={p?.last_name ?? fallback?.last_name ?? null}
          withTooltip={false}
        />
        <div className="min-w-0">
          <p className="truncate text-lg font-semibold leading-tight">{displayName}</p>
          {email ? <p className="text-muted-foreground truncate text-sm">{email}</p> : null}
        </div>
      </div>
      {(bio || location || websiteUrl || (p?.created_at ?? fallback)) && (
        <dl className="grid gap-3 text-sm">
          {bio ? (
            <div>
              <dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">Bio</dt>
              <dd className="mt-1 whitespace-pre-wrap break-words">{bio}</dd>
            </div>
          ) : null}
          {location ? (
            <div>
              <dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">Location</dt>
              <dd className="mt-1 break-words">{location}</dd>
            </div>
          ) : null}
          {websiteUrl ? (
            <div>
              <dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">Website</dt>
              <dd className="mt-1 truncate">
                <a href={websiteUrl} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">
                  {websiteUrl}
                </a>
              </dd>
            </div>
          ) : null}
        </dl>
      )}
    </div>
  );
}

export function UserProfileDialog({ userId, open, onOpenChange, fallback }: UserProfileDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Profile</DialogTitle>
        </DialogHeader>
        <ProfileBody userId={userId} fallback={fallback} />
      </DialogContent>
    </Dialog>
  );
}
