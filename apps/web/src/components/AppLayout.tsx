import {
  SidebarProvider,
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
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
  Inbox,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Mail,
  Plus,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";

import { useWorkspace, IDENTITY_QUERY_OPTIONS } from "../contexts/WorkspaceContext";
import { activeWorkspacePermissions } from "../utils/permissions";
import { ThemeToggle } from "./refine-ui/theme/theme-toggle";
import { NotificationCenter } from "./NotificationCenter";
import { cn } from "@/lib/utils";
import type { Identity } from "../types";
import { getDisplayName } from "../types";

const MENU_ITEMS = [
  { key: "/", label: "Dashboard", icon: LayoutDashboard, permission: "workspace:read" },
  { key: "/inbox", label: "Inbox", icon: Inbox, permission: "notification:read" },
  { key: "/members", label: "Members", icon: Users, permission: "member:read" },
];

function AdminMenuItem() {
  const location = useLocation();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  if (identity?.is_superuser !== true) return null;
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={location.pathname.startsWith("/admin")}
        tooltip="Admin"
      >
        <Link to="/admin">
          <ShieldCheck className="h-4 w-4 shrink-0" />
          <span>Admin</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

function SidebarNav() {
  const location = useLocation();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const { workspace } = useWorkspace();
  const permissions = activeWorkspacePermissions(identity);
  const can = (p: string) => permissions.includes("*") || permissions.includes(p);
  const items = MENU_ITEMS.filter((i) => can(i.permission));
  const activeKey = `/${location.pathname.split("/")[1] || ""}`;
  const isActive = (key: string) => (key === "/" ? location.pathname === "/" : activeKey === key);

  const { result: convUnreadResult } = useWorkspaceCustom<{ count: number; unread_conversations: number }>({
    url: "conversations/unread-count",
    method: "get",
    queryOptions: {
      enabled: !!workspace?.id,
    },
  });
  const convUnreadCount =
    (convUnreadResult?.data as { count?: number } | undefined)?.count ?? 0;

  return (
    <SidebarGroup>
      <SidebarMenu>
        {items.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.key);
          const isInbox = item.key === "/inbox";
          const badgeCount = isInbox ? convUnreadCount : 0;
          return (
            <SidebarMenuItem key={item.key}>
              <SidebarMenuButton asChild isActive={active} tooltip={item.label}>
                <Link to={item.key}>
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
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}
        <AdminMenuItem />
      </SidebarMenu>
    </SidebarGroup>
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

function WorkspaceSwitcher() {
  const { workspaces, workspace, setWorkspace } = useWorkspace();
  const single = useSingleWorkspace();
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

  // Workspace settings — only owners and admins may see this entry. The page
  // itself re-checks this gate and renders an "Access denied" fallback if the
  // role was downgraded after the menu rendered.
  const myRole = identity?.workspaces.find((w) => w.id === workspace?.id)?.role;
  const isWorkspaceAdmin =
    identity?.is_superuser === true ||
    (myRole !== undefined && ["owner", "admin"].includes(myRole)) ||
    permissions.includes("*") ||
    permissions.includes("workspace:update");

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
        {isWorkspaceAdmin && (
          <DropdownMenuItem onClick={() => navigate("/settings/workspace")}>
            <Building2 />
            Workspace Settings
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => navigate("/invitations")}>
          <Mail />
          Invitations
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
          <WorkspaceSwitcher />
        </SidebarHeader>
        <SidebarContent>
          {workspaces.length === 0 ? (
            <>
              <div className="flex flex-col gap-3 p-4">
                <p className="text-muted-foreground text-sm">
                  You're not a member of any workspace yet.
                </p>
                <Button
                  onClick={() => navigate("/workspaces/create")}
                  className="gap-2 justify-start"
                >
                  <Building2 className="h-4 w-4" />
                  Create workspace
                </Button>
              </div>
              <SidebarGroup>
                <SidebarMenu>
                  <AdminMenuItem />
                </SidebarMenu>
              </SidebarGroup>
            </>
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
