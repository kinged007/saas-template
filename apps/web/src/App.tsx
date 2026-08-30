import { Refine, Authenticated } from "@refinedev/core";
import routerProvider from "@refinedev/react-router";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";

import { useNotificationProvider } from "./components/refine-ui/notification/use-notification-provider";
import { Toaster } from "./components/refine-ui/notification/toaster";
import { ThemeProvider } from "./components/refine-ui/theme/theme-provider";
import { dataProvider } from "./providers/dataProvider";
import { authProvider } from "./providers/authProvider";
import { liveProvider } from "./providers/liveProvider";
import { accessControlProvider } from "./providers/accessControlProvider";
import { queryClient } from "./providers/queryClient";
import { WorkspaceProvider } from "./contexts/WorkspaceContext";
import { AppLayout } from "./components/AppLayout";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { WorkspaceCreatePage } from "./pages/WorkspaceCreatePage";
import { MembersPage } from "./pages/MembersPage";
import { ReceivedInvitationsPage } from "./pages/ReceivedInvitationsPage";
import { ApiKeyCreatePage } from "./pages/ApiKeyCreatePage";
import { ApiKeysPage } from "./pages/ApiKeysPage";
import { InboxPage } from "./pages/InboxPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobRunPage } from "./pages/JobRunPage";
import { ProfileSettingsPage } from "./pages/settings/ProfileSettingsPage";
import { WorkspaceSettingsLayout } from "./pages/settings/workspace/WorkspaceSettingsLayout";
import { GeneralSection } from "./pages/settings/workspace/sections/GeneralSection";
import { RolesSection } from "./pages/settings/workspace/sections/RolesSection";
import { JobsSection } from "./pages/settings/workspace/sections/JobsSection";
import { UsersSection } from "./pages/settings/workspace/sections/UsersSection";
import { AuditLogSection } from "./pages/settings/workspace/sections/AuditLogSection";
import { AgentsGeneralSection } from "./pages/settings/workspace/sections/AgentsGeneralSection";
import { AgentsSandboxSection } from "./pages/settings/workspace/sections/AgentsSandboxSection";
import { AgentsPage } from "./pages/agents/AgentsPage";
import { AgentCreatePage } from "./pages/agents/AgentCreatePage";
import { AgentEditPage } from "./pages/agents/AgentEditPage";

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
      <Refine
        dataProvider={dataProvider}
        authProvider={authProvider}
        liveProvider={liveProvider}
        accessControlProvider={accessControlProvider}
        routerProvider={routerProvider}
        notificationProvider={useNotificationProvider()}
        options={{
          syncWithLocation: true,
          liveMode: "auto",
          reactQuery: {
            clientConfig: queryClient,
          },
        }}
        resources={[
          { name: "workspaces", list: "/", create: "/workspaces/create" },
          { name: "members", list: "/members" },
          { name: "roles", list: "/settings/workspace/roles" },
          { name: "api-keys", list: "/api-keys", create: "/api-keys/create" },
          { name: "invitations", list: "/invitations" },
          { name: "notifications", list: "/inbox", meta: { label: "Inbox" } },
          { name: "conversations", list: "/inbox", meta: { hide: true } },
          { name: "messages", list: "/inbox", meta: { hide: true } },
          {
            name: "jobs",
            list: "/settings/workspace/jobs",
            show: "/jobs/:id",
            meta: { label: "Scheduled Jobs" },
          },
          { name: "audit", list: "/audit", meta: { hide: true } },
          { name: "agents", list: "/agents", create: "/agents/create", edit: "/agents/edit/:id" },
        ]}
      >
        <WorkspaceProvider>
          <Routes>
            <Route
              path="/"
              element={
                <Authenticated key="app" fallback={<Navigate to="/login" replace />}>
                  <AppLayout>
                    <Outlet />
                  </AppLayout>
                </Authenticated>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="workspaces/create" element={<WorkspaceCreatePage />} />
              <Route path="members" element={<MembersPage />} />
              <Route path="invitations" element={<ReceivedInvitationsPage />} />
              <Route path="agents/create" element={<AgentCreatePage />} />
              <Route path="agents/edit/:id" element={<AgentEditPage />} />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="api-keys/create" element={<ApiKeyCreatePage />} />
              <Route path="api-keys" element={<ApiKeysPage />} />
              <Route path="inbox" element={<InboxPage />} />
              {/* Jobs detail stays top-level; list moved into workspace settings */}
              <Route path="jobs/:id" element={<JobDetailPage />} />
              <Route path="jobs/:id/runs/:runId" element={<JobRunPage />} />
              <Route path="settings/profile" element={<ProfileSettingsPage />} />
              <Route path="settings/workspace" element={<WorkspaceSettingsLayout />}>
                <Route index element={<Navigate to="general" replace />} />
                <Route path="general" element={<GeneralSection />} />
                <Route path="roles" element={<RolesSection />} />
                <Route path="jobs" element={<JobsSection />} />
                <Route path="users" element={<UsersSection />} />
                <Route path="audit" element={<AuditLogSection />} />
                <Route path="agents-general" element={<AgentsGeneralSection />} />
                <Route path="agents-sandbox" element={<AgentsSandboxSection />} />
              </Route>
              {/* Legacy redirects — keep old URLs working */}
              <Route path="roles" element={<Navigate to="/settings/workspace/roles" replace />} />
              <Route path="jobs" element={<Navigate to="/settings/workspace/jobs" replace />} />
            </Route>
            <Route
              path="/login"
              element={
                <Authenticated key="login" fallback={<LoginPage />}>
                  <Navigate to="/" replace />
                </Authenticated>
              }
            />
            <Route path="/register" element={<RegisterPage />} />
          </Routes>
          <Toaster />
        </WorkspaceProvider>
      </Refine>
      </BrowserRouter>
    </ThemeProvider>
  );
}
