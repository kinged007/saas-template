import { useEffect, useState } from "react";
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
import { useDeleteAccount, useExportProfile, useProfile, useUpdateProfile } from "@/hooks/useProfile";
import type { Identity, UserProfile } from "@/types";
import { getProfileField } from "@/types";

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

type CustomEntry = { id: string; key: string; value: string };

function parseValue(raw: string): unknown {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  // Try JSON parse for numbers/booleans/null/objects
  try {
    const parsed = JSON.parse(trimmed);
    // Avoid parsing plain strings without quotes that JSON.parse would fail? Already caught
    // If parsed is string and raw was not quoted, JSON.parse would have thrown for unquoted string
    // So return parsed
    return parsed;
  } catch {
    return raw;
  }
}

function stringifyValue(val: unknown): string {
  if (val === null || val === undefined) return "";
  if (typeof val === "string") return val;
  try {
    return JSON.stringify(val);
  } catch {
    return String(val);
  }
}

export function ProfileSettingsPage() {
  const { data: identity } = useGetIdentity<Identity>();
  const profileHook = useProfile();
  const profile = (profileHook.data as UserProfile | undefined) ?? identity?.profile;
  const { mutate, mutation: updateMutation } = useUpdateProfile();
  const isSaving = updateMutation.isPending;
  const { exportMyData } = useExportProfile();
  const { mutate: deleteAccount, mutation: deleteMutation } = useDeleteAccount();
  const isDeleting = deleteMutation.isPending;
  const { list } = useNavigation();

  const [customEntries, setCustomEntries] = useState<CustomEntry[]>([]);
  const [initialized, setInitialized] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deletePassword, setDeletePassword] = useState("");

  const form = useForm<ProfileFormData>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      first_name: "",
      last_name: "",
      bio: "",
      phone_number: "",
      timezone: "",
      locale: "",
      date_of_birth: "",
      website_url: "",
      location: "",
      avatar_url: "",
    },
  });

  // Initialize form and custom entries when profile loads
  useEffect(() => {
    if (profile && !initialized) {
      form.reset({
        first_name: (getProfileField(profile, "first_name", "") as string) || "",
        last_name: (getProfileField(profile, "last_name", "") as string) || "",
        bio: (getProfileField(profile, "bio", "") as string) || "",
        phone_number: (getProfileField(profile, "phone_number", "") as string) || "",
        timezone: (getProfileField(profile, "timezone", "") as string) || "",
        locale: (getProfileField(profile, "locale", "") as string) || "",
        date_of_birth: (getProfileField(profile, "date_of_birth", "") as string) || "",
        website_url: (getProfileField(profile, "website_url", "") as string) || "",
        location: (getProfileField(profile, "location", "") as string) || "",
        avatar_url: (identity?.avatar_url as string) || "",
      });
      const cd = (profile.custom_data as Record<string, unknown>) || {};
      const entries: CustomEntry[] = Object.entries(cd).map(([k, v]) => ({
        id: Math.random().toString(36).slice(2, 8),
        key: k,
        value: stringifyValue(v),
      }));
      setCustomEntries(entries);
      setInitialized(true);
    }
  }, [profile, identity, initialized, form]);

  const addCustomEntry = () => {
    setCustomEntries((prev) => [...prev, { id: Math.random().toString(36).slice(2, 8), key: "", value: "" }]);
  };

  const updateCustomEntry = (id: string, field: "key" | "value", val: string) => {
    setCustomEntries((prev) => prev.map((e) => (e.id === id ? { ...e, [field]: val } : e)));
  };

  const removeCustomEntry = (id: string) => {
    setCustomEntries((prev) => prev.filter((e) => e.id !== id));
  };

  const onSubmit = (data: ProfileFormData) => {
    // Build payload: only include fields that are not empty? But we need to handle clearing: empty string -> null to clear?
    // For nullable fields, sending empty string should clear? We'll convert "" to null to clear, or omit?
    // Backend treats missing as unchanged, null as clear (set to None). So we should send null for empty string when field was previously set?
    // For simplicity, we send values: if value === "" then null, else value. But for fields where "" is valid to clear, backend will set None.
    const payload: Record<string, unknown> = {};
    const fields: (keyof ProfileFormData)[] = [
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
    for (const f of fields) {
      const val = data[f];
      if (val !== undefined) {
        // Convert empty string to null to clear
        if (val === "") {
          payload[f] = null;
        } else {
          // date_of_birth: keep as string "YYYY-MM-DD" or null
          payload[f] = val;
        }
      }
    }

    // Build custom_data patch for Merge Patch
    const original = (profile?.custom_data as Record<string, unknown>) || {};
    const currentMap: Record<string, unknown> = {};
    for (const e of customEntries) {
      const k = e.key.trim();
      if (!k) continue;
      // If duplicate keys, last wins
      currentMap[k] = parseValue(e.value);
    }
    const patch: Record<string, unknown> = {};
    // Detect deleted keys
    for (const k of Object.keys(original)) {
      if (!(k in currentMap)) {
        patch[k] = null;
      }
    }
    // Detect added/updated
    for (const [k, v] of Object.entries(currentMap)) {
      if (original[k] !== v || !(k in original)) {
        // For simplicity, send all currentMap entries that differ or are new
        // But also need to handle case where value unchanged but we still send - not needed
        // We'll send if different
        // Use JSON string compare for deep equality
        const origStr = JSON.stringify(original[k]);
        const curStr = JSON.stringify(v);
        if (origStr !== curStr) {
          patch[k] = v;
        } else if (!(k in original)) {
          patch[k] = v;
        }
      }
    }
    // For entries that are completely new or updated but not deleted, also need to ensure they are in patch
    // Actually we should send all currentMap where not deleted, but PATCH merge will retain omitted keys, so we must not omit unchanged keys? No, omitted retains, so only need to send changed.
    // However to cover initial case where custom_data was {}, we need to send added keys - which we did.
    // For retained keys that are unchanged, we don't need to send.
    // But if we only send diff, backend will merge correctly (changed + deleted)
    // If patch is empty (no changes), we should not send custom_data at all? Or send empty patch? We'll send only if patch has keys
    if (Object.keys(patch).length > 0) {
      payload["custom_data"] = patch;
    } else {
      // If customEntries maybe have same data but we built empty patch, don't send custom_data to avoid unnecessary audit
      // But if user added new key and we detected, patch will have it
      // If user made no changes, patch empty, we skip
      // Check if number of entries changed vs original size, but if both empty, skip
      const hadCustomData = Object.keys(original).length > 0;
      const hasEntries = customEntries.some((e) => e.key.trim() !== "");
      if (hadCustomData || hasEntries) {
        // If user cleared all custom_data, patch would have null deletes for each original key, so patch not empty
        // So only when both empty we skip
      }
    }

    // If payload only has avatar_url handling? We'll send via profile update
    // Use PATCH (isPut false) with merge semantics
    mutate(payload, {
      isPut: false,
      onSuccess: () => {
        toast.success("Profile updated");
      },
      onError: (err: unknown) => {
        const msg = (err as { message?: string })?.message || String(err);
        toast.error(msg);
      },
    });
  };

  const handleExport = async () => {
    try {
      await exportMyData();
      toast.success("Export downloaded");
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message || String(e);
      toast.error(msg);
    }
  };

  const handleDelete = () => {
    // Determine if password required: if identity has password? We don't know, but backend will return 422 if required.
    // We'll try with or without password
    const values: Record<string, unknown> = { confirm: confirmText };
    if (deletePassword) values["password"] = deletePassword;
    else if (confirmText) values["password"] = undefined;

    // Need to handle password requirement: if user is oauth, password not needed
    // We'll send confirm and password if provided
    const payload: Record<string, unknown> = { confirm: confirmText };
    if (deletePassword) payload["password"] = deletePassword;

    deleteAccount(payload as { confirm: string; password?: string }, {
      onSuccess: () => {
        toast.success("Account deleted");
        window.location.assign("/login");
      },
      onError: (err: unknown) => {
        const msg = (err as { message?: string })?.message || String(err);
        toast.error(msg);
      },
    });
  };

  if (!profile && profileHook.isLoading) {
    return <p className="text-muted-foreground p-4 text-sm">Loading profile…</p>;
  }

  return (
    <div className="mx-auto max-w-3xl flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-2xl font-bold tracking-tight">Profile Settings</h2>
        <p className="text-muted-foreground text-sm">
          Update your personal information and preferences. Changes are visible to workspace members.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Personal Information</CardTitle>
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
                      <FormControl>
                        <Input placeholder="UTC or America/New_York" {...field} />
                      </FormControl>
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
                      <FormControl>
                        <Input placeholder="en-US" {...field} />
                      </FormControl>
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

              <Separator className="my-2" />

              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <Label>Custom data</Label>
                  <Button type="button" variant="outline" size="sm" onClick={addCustomEntry}>
                    Add key
                  </Button>
                </div>
                <p className="text-muted-foreground text-xs">
                  Arbitrary JSON key-values. Use JSON for numbers/booleans (e.g. <code>123</code>, <code>true</code>). Deleting a key sends <code>null</code> (Merge Patch).
                </p>
                {customEntries.length === 0 && (
                  <p className="text-muted-foreground text-sm">No custom data.</p>
                )}
                {customEntries.map((e) => (
                  <div key={e.id} className="flex gap-2">
                    <Input
                      placeholder="key"
                      value={e.key}
                      onChange={(ev) => updateCustomEntry(e.id, "key", ev.target.value)}
                      className="flex-1"
                    />
                    <Input
                      placeholder="value (JSON or string)"
                      value={e.value}
                      onChange={(ev) => updateCustomEntry(e.id, "value", ev.target.value)}
                      className="flex-1"
                    />
                    <Button type="button" variant="ghost" size="sm" onClick={() => removeCustomEntry(e.id)}>
                      Remove
                    </Button>
                  </div>
                ))}
              </div>

              <div className="flex justify-end gap-2 pt-4">
                <Button type="button" variant="outline" onClick={() => list("workspaces")}>
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
