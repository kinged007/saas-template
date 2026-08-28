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
import { RolesPage } from "./pages/RolesPage";
import { ApiKeyCreatePage } from "./pages/ApiKeyCreatePage";
import { ApiKeysPage } from "./pages/ApiKeysPage";
import { InboxPage } from "./pages/InboxPage";
import { JobsPage } from "./pages/JobsPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobRunPage } from "./pages/JobRunPage";

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
          { name: "roles", list: "/roles" },
          { name: "api-keys", list: "/api-keys", create: "/api-keys/create" },
          { name: "invitations", list: "/invitations" },
          { name: "notifications", list: "/inbox", meta: { label: "Inbox" } },
          { name: "conversations", list: "/inbox", meta: { hide: true } },
          { name: "messages", list: "/inbox", meta: { hide: true } },
          {
            name: "jobs",
            list: "/jobs",
            show: "/jobs/:id",
            meta: { label: "Scheduled Jobs" },
          },
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
              <Route path="roles" element={<RolesPage />} />
              <Route path="api-keys/create" element={<ApiKeyCreatePage />} />
              <Route path="api-keys" element={<ApiKeysPage />} />
              <Route path="inbox" element={<InboxPage />} />
              <Route path="jobs" element={<JobsPage />} />
              <Route path="jobs/:id" element={<JobDetailPage />} />
              <Route path="jobs/:id/runs/:runId" element={<JobRunPage />} />
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
