import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useGetIdentity, useNavigation } from "@refinedev/core";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDeleteAccount, useExportProfile, useProfile, useTargetUserId, useUpdateProfile } from "@/hooks/useProfile";
import type { Identity, UserProfile } from "@/types";
import { getProfileField } from "@/types";
import { errorMessage } from "@/utils/errorMessage";

const profileSchema = z.object({
  first_name: z.string().max(100, "Max 100 characters").optional().or(z.literal("")),
  last_name: z.string().max(100, "Max 100 characters").optional().or(z.literal("")),
  bio: z.string().max(1000, "Max 1000 characters").optional().or(z.literal("")),
  phone_number: z.string().max(30, "Max 30 characters").optional().or(z.literal("")),
  timezone: z.string().max(50, "Max 50 characters").optional().or(z.literal("")),
  locale: z.string().max(10, "Max 10 characters").optional().or(z.literal("")),
  date_of_birth: z.string().optional().or(z.literal("")),
  website_url: z
    .string()
    .max(500)
    .optional()
    .or(z.literal(""))
    .refine(
      (val) => !val || val === "" || (() => { try { new URL(val); return true; } catch { return false; } })(),
      { message: "Must be a valid URL" }
    ),
  location: z.string().max(200, "Max 200 characters").optional().or(z.literal("")),
  avatar_url: z
    .string()
    .max(500)
    .optional()
    .or(z.literal(""))
    .refine(
      (val) => !val || val === "" || (() => { try { new URL(val); return true; } catch { return false; } })(),
      { message: "Must be a valid URL" }
    ),
});

type ProfileFormData = z.infer<typeof profileSchema>;

/** The PATCH body: the only profile fields this form is allowed to send. */
const PROFILE_FIELDS: (keyof ProfileFormData)[] = [
  "first_name",
  "last_name",
  "bio",
  "phone_number",
  "timezone",
  "locale",
  "date_of_birth",
  "website_url",
  "location",
  "avatar_url",
];

// Developer-defined custom_data keys are not user-editable. The backend Merge Patch
// remains available for forks that add first-class custom fields via code (types.ts
// + dedicated inputs), but the generic key-value editor is intentionally removed.

// Locale options — English only for now (easy to extend).
const LOCALE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "en", label: "English" },
];

// Timezone options: prefer Intl.supportedValuesOf, fallback to curated common list.
function getTimezoneOptions(): string[] {
  try {
    const maybe = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
    if (typeof maybe === "function") {
      const all = maybe.call(Intl, "timeZone");
      if (Array.isArray(all) && all.length > 0) return all;
    }
  } catch {
    // ignore
  }
  // Fallback curated list covers major regions; detected timezone will be appended if missing.
  return [
    "UTC",
    "Pacific/Midway",
    "Pacific/Honolulu",
    "America/Anchorage",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "America/Sao_Paulo",
    "Atlantic/Azores",
    "Europe/London",
    "Europe/Lisbon",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Moscow",
    "Africa/Cairo",
    "Africa/Lagos",
    "Asia/Dubai",
    "Asia/Karachi",
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Australia/Sydney",
    "Pacific/Auckland",
  ];
}

function getDetectedTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

export function GeneralSection() {
  const { data: identity } = useGetIdentity<Identity>();
  // Set when routed as `users/:id/settings/general` (a caller holding
  // profile:update editing someone else); null on the self-service page.
  const targetId = useTargetUserId();
  const profileHook = useProfile(targetId);
  // For a target, never fall back to identity.profile: that is the signed-in
  // user, and showing their fields in the member editor is a data leak.
  const profile = (profileHook.data as UserProfile | undefined) ?? (targetId ? undefined : identity?.profile);
  const { mutate, mutation: updateMutation } = useUpdateProfile(targetId);
  const isSaving = updateMutation.isPending;
  const { exportMyData } = useExportProfile();
  const { mutate: deleteAccount, mutation: deleteMutation } = useDeleteAccount();
  const isDeleting = deleteMutation.isPending;
  const { list } = useNavigation();

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deletePassword, setDeletePassword] = useState("");

  const detectedTimezone = getDetectedTimezone();
  const tzOptions = getTimezoneOptions();
  // Ensure detected timezone is selectable even if fallback list is used.
  const allTimezones = detectedTimezone && !tzOptions.includes(detectedTimezone) ? [detectedTimezone, ...tzOptions] : tzOptions;

  // react-hook-form reads `defaultValues` once, on mount; `values` resyncs the
  // form whenever the profile query resolves, so no reset-on-first-render latch
  // (which used to close on the not-yet-loaded profile and blank the form).
  const values = useMemo<ProfileFormData>(
    () => ({
      first_name: (getProfileField(profile, "first_name", "") as string) || "",
      last_name: (getProfileField(profile, "last_name", "") as string) || "",
      bio: (getProfileField(profile, "bio", "") as string) || "",
      phone_number: (getProfileField(profile, "phone_number", "") as string) || "",
      timezone: (getProfileField(profile, "timezone", "") as string) || detectedTimezone || "",
      locale: (getProfileField(profile, "locale", "") as string) || "en",
      date_of_birth: (getProfileField(profile, "date_of_birth", "") as string) || "",
      website_url: (getProfileField(profile, "website_url", "") as string) || "",
      location: (getProfileField(profile, "location", "") as string) || "",
      // The delegated GET returns the target's avatar_url; identity.avatar_url
      // is the signed-in user's and is only a fallback for the self profile.
      avatar_url:
        (getProfileField(profile, "avatar_url", "") as string) ||
        (targetId ? "" : identity?.avatar_url || ""),
    }),
    [profile, identity?.avatar_url, detectedTimezone, targetId],
  );

  // `values` still runs a full reset, so a profile that arrives after the user
  // has started typing must not wipe what they typed: the fetch lands late
  // precisely when the embedded profile was blank.
  const form = useForm<ProfileFormData>({
    resolver: zodResolver(profileSchema),
    defaultValues: values,
    values,
    resetOptions: { keepDirtyValues: true },
  });

  const onSubmit = (data: ProfileFormData) => {
    const payload: Record<string, unknown> = {};
    for (const f of PROFILE_FIELDS) {
      const val = data[f];
      if (val !== undefined) {
        if (val === "") {
          payload[f] = null;
        } else {
          payload[f] = val;
        }
      }
    }

    // No generic custom_data editor — custom_data is developer-defined and
    // rendered via dedicated inputs that map to getProfileField keys in forks.
    // For the base template we do not send custom_data at all.

    // The mutation's own successNotification owns the "Profile updated" toast.
    mutate(payload, {
      isPut: false,
      onError: (err: unknown) => {
        toast.error(errorMessage(err));
      },
    });
  };

  const handleExport = async () => {
    try {
      await exportMyData();
      toast.success("Export downloaded");
    } catch (e: unknown) {
      toast.error(errorMessage(e));
    }
  };

  const handleDelete = () => {
    const payload: Record<string, unknown> = { confirm: confirmText };
    if (deletePassword) payload["password"] = deletePassword;

    deleteAccount(payload as { confirm: string; password?: string }, {
      onSuccess: () => {
        toast.success("Account deleted");
        window.location.assign("/login");
      },
      onError: (err: unknown) => {
        toast.error(errorMessage(err));
      },
    });
  };

  if (!profile && profileHook.isLoading) {
    return <p className="text-muted-foreground p-4 text-sm">Loading profile…</p>;
  }

  // A failed fetch with nothing embedded would paint an empty form whose submit
  // nulls every stored field. Say so instead of offering it.
  if (profileHook.isError && PROFILE_FIELDS.every((f) => !getProfileField(profile, f, ""))) {
    return <p className="text-muted-foreground p-4 text-sm">Could not load your profile — reload to try again.</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{targetId ? "Member Information" : "Personal Information"}</CardTitle>
          <CardDescription>Common profile fields and avatar URL.</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="first_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>First name</FormLabel>
                      <FormControl>
                        <Input placeholder="Ada" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="last_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Last name</FormLabel>
                      <FormControl>
                        <Input placeholder="Lovelace" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="bio"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Bio</FormLabel>
                    <FormControl>
                      <Textarea placeholder="Tell us about yourself" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="phone_number"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Phone number</FormLabel>
                      <FormControl>
                        <Input placeholder="+1 555 …" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="timezone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Timezone</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Select timezone">
                              {field.value ?? ""}
                            </SelectValue>
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent className="max-h-64">
                          {allTimezones.map((tz) => (
                            <SelectItem key={tz} value={tz}>
                              {tz}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="locale"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Locale</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Select locale">
                              {LOCALE_OPTIONS.find((o) => o.value === field.value)?.label ?? field.value ?? ""}
                            </SelectValue>
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {LOCALE_OPTIONS.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {opt.label} — {opt.value}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="date_of_birth"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Date of birth</FormLabel>
                      <FormControl>
                        <Input type="date" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="website_url"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Website URL</FormLabel>
                    <FormControl>
                      <Input placeholder="https://example.com" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="location"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Location</FormLabel>
                    <FormControl>
                      <Input placeholder="Berlin, DE" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="avatar_url"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Avatar URL</FormLabel>
                    <FormControl>
                      <Input placeholder="https://example.com/avatar.jpg" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="flex justify-end gap-2 pt-4">
                <Button type="button" variant="outline" onClick={() => list(targetId ? "members" : "workspaces")}>
                  Cancel
                </Button>
                <Button type="submit" disabled={isSaving}>
                  {isSaving ? "Saving…" : "Save changes"}
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      {/* Export and account deletion act on the signed-in user only. */}
      {!targetId && (
      <Card>
        <CardHeader>
          <CardTitle>Data &amp; Account</CardTitle>
          <CardDescription>Export or delete your account. Deletion is permanent.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Export my data</p>
              <p className="text-muted-foreground text-sm">Download a JSON bundle with your profile, workspaces and counts.</p>
            </div>
            <Button variant="outline" onClick={handleExport}>
              Export
            </Button>
          </div>
          <Separator />
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium text-destructive">Delete account</p>
              <p className="text-muted-foreground text-sm">Hard-delete your user, profile, tokens and memberships.</p>
            </div>
            <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              Delete account
            </Button>
          </div>
        </CardContent>
      </Card>
      )}

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete account</DialogTitle>
            <DialogDescription>
              This action cannot be undone. Type <code>DELETE</code> to confirm. If your account has a password, you must also provide it.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <Label htmlFor="confirm">Confirm</Label>
            <Input
              id="confirm"
              placeholder="DELETE"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
            <Label htmlFor="password">Password (if set)</Label>
            <Input
              id="password"
              type="password"
              placeholder="Your password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== "DELETE" || (isDeleting as boolean)}
              onClick={handleDelete}
            >
              {(isDeleting as boolean) ? "Deleting…" : "Delete my account"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
