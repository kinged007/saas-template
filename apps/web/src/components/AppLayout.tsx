import {
  SidebarProvider,
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
  SidebarTrigger,
  SidebarRail,
} from "@/components/ui/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/components/ui/user-avatar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGetIdentity, useLogout } from "@refinedev/core";
import { useWorkspaceCustom } from "../hooks/useWorkspaceQuery";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import {
  Building2,
  ChevronsUpDown,
  CircleUser,
  FileText,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  Mail,
  Plus,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useWorkspace, IDENTITY_QUERY_OPTIONS } from "../contexts/WorkspaceContext";
import { activeWorkspacePermissions } from "../utils/permissions";
import { isManagerRoleName } from "../pages/role-name";
import { ThemeToggle } from "./refine-ui/theme/theme-toggle";
import { NotificationCenter } from "./NotificationCenter";
import { PendingInvitationsBadge } from "./PendingInvitations";
import { cn } from "@/lib/utils";
import type { Identity } from "../types";
import { getDisplayName } from "../types";
import { errorMessage } from "../utils/errorMessage";

type MenuItem = {
  /** React key. Independent of `to`, so re-routing an item keeps its identity. */
  id: string;
  /** Route target. `"#"` renders a dead link that goes nowhere. */
  to: string;
  label: string;
  icon: LucideIcon;
  permission: string | null;
};

/**
 * Sidebar groups, rendered in `position` order with a separator between the
 * two sides. Omit `title` for an unlabelled group. Adding a group is a data
 * change only; `SidebarNav` does not need to know about it.
 */
const SIDEBAR_GROUPS: {
  id: string;
  title?: string;
  position: "primary" | "secondary";
  items: MenuItem[];
}[] = [
  {
    id: "main",
    position: "primary",
    items: [
      { id: "dashboard", to: "/", label: "Dashboard", icon: LayoutDashboard, permission: "workspace:read" },
      { id: "inbox", to: "/inbox", label: "Inbox", icon: Inbox, permission: null },
    ],
  },
  {
    id: "demo",
    title: "Demo",
    position: "primary",
    items: [
      { id: "sample-page", to: "#", label: "Sample page", icon: FileText, permission: null },
      { id: "support", to: "#", label: "Support", icon: LifeBuoy, permission: null },
    ],
  },
  {
    id: "workspace",
    position: "secondary",
    items: [{ id: "members", to: "/members", label: "Members", icon: Users, permission: "member:read" }],
  },
];

function SidebarNav() {
  const location = useLocation();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const { workspace } = useWorkspace();
  const permissions = activeWorkspacePermissions(identity);
  const can = (p: string | null) =>
    p === null || permissions.includes("*") || permissions.includes(p);
  const activeKey = `/${location.pathname.split("/")[1] || ""}`;
  const isActive = (key: string) => (key === "/" ? location.pathname === "/" : activeKey === key);

  const { result: convUnreadResult } = useWorkspaceCustom<{ count: number; unread_conversations: number }>({
    url: "conversations/unread-count",
    method: "get",
    // Badge counter, no in-body surface — it keeps the error toast.
    errorNotification: (error) => ({ type: "error", message: errorMessage(error) }),
    queryOptions: {
      enabled: !!workspace?.id,
    },
  });
  const convUnreadCount =
    (convUnreadResult?.data as { count?: number } | undefined)?.count ?? 0;

  // A group whose items are all filtered out by permissions renders nothing,
  // so a missing permission cannot leave an empty group or a dangling rule.
  const visibleGroups = SIDEBAR_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((i) => can(i.permission)),
  })).filter((group) => group.items.length > 0);

  const renderGroup = (group: (typeof visibleGroups)[number]) => (
    <SidebarGroup key={group.id}>
      {/* The label element is the heading. The sidebar sits beside <main>, so
          a group title is not subordinate to the page heading. */}
      {group.title && (
        <SidebarGroupLabel asChild>
          <h2>{group.title}</h2>
        </SidebarGroupLabel>
      )}
      <SidebarMenu>
        {group.items.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.to);
          const badgeCount = item.id === "inbox" ? convUnreadCount : 0;
          const content = (
            <>
              <span className="relative">
                <Icon className="h-4 w-4 shrink-0" />
                {badgeCount > 0 && (
                  <span className="absolute -right-1.5 -top-1.5 hidden h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-0.5 text-[10px] font-medium leading-none text-destructive-foreground group-data-[collapsible=icon]:flex">
                    {badgeCount > 99 ? "99+" : badgeCount}
                  </span>
                )}
              </span>
              <span>{item.label}</span>
              {badgeCount > 0 && (
                <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-xs font-medium text-destructive-foreground group-data-[collapsible=icon]:hidden">
                  {badgeCount > 99 ? "99+" : badgeCount}
                </span>
              )}
            </>
          );
          return (
            <SidebarMenuItem key={item.id}>
              <SidebarMenuButton asChild isActive={active} tooltip={item.label}>
                {/* A `to` of "#" is a placeholder: a plain anchor keeps the href
                    literal, where `<Link to="#">` resolves to the current
                    pathname (React Router drops a bare "#") and silently
                    no-ops. Real routes keep client-side navigation. */}
                {item.to === "#" ? <a href={item.to}>{content}</a> : <Link to={item.to}>{content}</Link>}
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );

  const primaryGroups = visibleGroups.filter((g) => g.position === "primary");
  const secondaryGroups = visibleGroups.filter((g) => g.position === "secondary");

  // The landmark belongs at the call site, not in the shared shadcn primitive.
  // It takes over the flex classes SidebarContent used to give the groups, so
  // the scroll and collapsed layout are unchanged. Named because the settings
  // pages render a nav of their own.
  return (
    <nav aria-label="Main" className="flex min-h-0 flex-1 flex-col gap-2">
      {primaryGroups.map(renderGroup)}
      {primaryGroups.length > 0 && secondaryGroups.length > 0 && <SidebarSeparator />}
      {secondaryGroups.map(renderGroup)}
    </nav>
  );
}

const CREATE_WORKSPACE_VALUE = "__create_workspace__";

/** Backend SINGLE_WORKSPACE flag from /auth/me — no VITE_ var, no drift. */
function useSingleWorkspace(): boolean {
  const { data: identity } = useGetIdentity<Identity>({
    queryOptions: IDENTITY_QUERY_OPTIONS,
  });
  return identity?.single_workspace === true;
}

function WorkspaceSwitcher({ single }: { single: boolean }) {
  const { workspaces, workspace, setWorkspace } = useWorkspace();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (workspaces.length === 0) return null;
  if (single) {
    return (
      <div className="flex min-w-0 items-center gap-2 overflow-hidden px-2 py-1.5">
        <Building2 className="h-4 w-4 shrink-0" />
        <span className="truncate text-sm font-medium group-data-[collapsible=icon]:hidden">
          {workspace?.name}
        </span>
      </div>
    );
  }
  return (
    <Select
      open={open}
      onOpenChange={setOpen}
      value={workspace?.id}
      onValueChange={(id) => {
        // Radix keeps the popover open when the picked value never becomes
        // the controlled value (the create sentinel), so close it explicitly.
        setOpen(false);
        if (id === CREATE_WORKSPACE_VALUE) {
          navigate("/workspaces/create");
        } else {
          const target = workspaces.find((w) => w.id === id);
          if (target && target.id !== workspace?.id) {
            setWorkspace(target);
            navigate("/");
          }
        }
      }}
    >
      <SelectTrigger className="w-full group-data-[collapsible=icon]:w-8 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:gap-0 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:[&>svg]:hidden">
        <SelectValue placeholder="Select workspace">
          <span className="flex min-w-0 items-center gap-2 overflow-hidden">
            <Building2 className="h-4 w-4 shrink-0" />
            <span className="truncate group-data-[collapsible=icon]:hidden">{workspace?.name}</span>
          </span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {workspaces.map((w) => (
          <SelectItem key={w.id} value={w.id}>
            <span className="flex items-center gap-2">
              <Building2 className="h-3.5 w-3.5" />
              {w.name}
              {w.role && <span className="text-muted-foreground text-xs">({w.role})</span>}
            </span>
          </SelectItem>
        ))}
        <SelectSeparator />
        <SelectItem value={CREATE_WORKSPACE_VALUE}>
          <span className="flex items-center gap-2">
            <Plus className="h-3.5 w-3.5" />
            Create new workspace
          </span>
        </SelectItem>
      </SelectContent>
    </Select>
  );
}

function UserMenu() {
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const { workspace } = useWorkspace();
  const { mutate: logout } = useLogout();
  const navigate = useNavigate();
  const displayName = getDisplayName(identity);
  const permissions = activeWorkspacePermissions(identity);
  const canViewApiKeys = permissions.includes("*") || permissions.includes("apikey:read");

  // Workspace settings — only owners and admins may see this entry, and
  // SINGLE_WORKSPACE hides it entirely. The page itself re-checks the role gate
  // and renders an "Access denied" fallback if the role was downgraded after
  // the menu rendered; hiding the entry leaves the route itself reachable.
  const myRole = identity?.workspaces.find((w) => w.id === workspace?.id)?.role;
  const isWorkspaceAdmin =
    identity?.is_superuser === true ||
    isManagerRoleName(myRole) ||
    permissions.includes("*") ||
    permissions.includes("workspace:update");
  const showWorkspaceSettings = isWorkspaceAdmin && identity?.single_workspace !== true;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-10 w-full justify-start gap-2 px-2 group-data-[collapsible=icon]:h-8 group-data-[collapsible=icon]:w-8 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:gap-0 group-data-[collapsible=icon]:p-0">
          <UserAvatar
            name={displayName}
            email={identity?.email}
            avatarUrl={identity?.avatar_url}
            sizeClassName="h-7 w-7 rounded-lg"
            fallbackClassName="rounded-lg text-xs"
            firstName={identity?.profile?.first_name}
            lastName={identity?.profile?.last_name}
            withTooltip={false}
          />
          <div className="flex flex-1 flex-col items-start text-left group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-medium leading-none">{displayName}</span>
            <span className="text-muted-foreground text-xs leading-tight truncate w-36">
              {identity?.email ?? ""}
            </span>
          </div>
          <ChevronsUpDown className="text-muted-foreground ml-auto h-4 w-4 group-data-[collapsible=icon]:hidden" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" side="top" className="w-56">
        <DropdownMenuLabel className="flex items-center gap-2">
          <CircleUser className="h-4 w-4" />
          {displayName}
        </DropdownMenuLabel>
        <DropdownMenuItem onClick={() => navigate("/settings/profile/security")}>
          <Settings />
          Profile Settings
        </DropdownMenuItem>
        {showWorkspaceSettings && (
          <DropdownMenuItem onClick={() => navigate("/settings/workspace")}>
            <Building2 />
            Workspace Settings
          </DropdownMenuItem>
        )}
        {identity?.is_superuser === true && (
          <DropdownMenuItem onClick={() => navigate("/admin")}>
            <ShieldCheck />
            Administration
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => navigate("/invitations")}>
          <Mail />
          Invitations
          <PendingInvitationsBadge />
        </DropdownMenuItem>
        {canViewApiKeys && (
          <DropdownMenuItem onClick={() => navigate("/api-keys")}>
            <KeyRound />
            API Keys
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => logout()}>
          <LogOut />
          Logout
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppLayout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const { workspaces } = useWorkspace();
  const single = useSingleWorkspace();

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <div className="flex items-center gap-2 px-2 py-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:gap-0 group-data-[collapsible=icon]:px-0">
            <img
              src="/logo.svg"
              alt="SaaS Template"
              className="mx-auto w-[70%] shrink-0 group-data-[collapsible=icon]:hidden"
            />
            <img
              src="/favicon.svg"
              alt="SaaS Template"
              className="hidden w-auto max-w-8 shrink-0 group-data-[collapsible=icon]:block"
            />
          </div>
          <WorkspaceSwitcher single={single} />
        </SidebarHeader>
        <SidebarContent>
          {workspaces.length === 0 ? (
            <div className="flex flex-col gap-3 p-4">
              <p className="text-muted-foreground text-sm">
                You're not a member of any workspace yet.
              </p>
              {/* /workspaces/create redirects home while the flag is set, so the
                  button would navigate nowhere. */}
              {!single && (
                <Button
                  onClick={() => navigate("/workspaces/create")}
                  className="gap-2 justify-start"
                >
                  <Building2 className="h-4 w-4" />
                  Create workspace
                </Button>
              )}
            </div>
          ) : (
            <SidebarNav />
          )}
        </SidebarContent>
        <SidebarFooter>
          <UserMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <SidebarInset>
        <header
          className={cn(
            "sticky top-0 z-40 flex h-16 shrink-0 items-center gap-4",
            "border-b bg-background/95 backdrop-blur px-4",
          )}
        >
          <SidebarTrigger />
          <div className="ml-auto flex items-center gap-2">
            <NotificationCenter />
            <ThemeToggle />
          </div>
        </header>
        <main className="container mx-auto flex min-h-0 flex-1 flex-col gap-4 p-4 md:p-6">
          {/* Global page bottom padding; full-height pages opt out via .page-flush (see InboxPage). */}
          <div className="flex min-h-0 flex-1 flex-col [&>*:not(.page-flush)]:pb-[2em]">{children}</div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
