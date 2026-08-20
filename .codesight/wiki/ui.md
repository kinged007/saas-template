# UI

> **Navigation aid.** Component inventory and prop signatures extracted via AST. Read the source files before adding props or modifying component logic.

**26 components** (react)

## Client Components

- **CreateButton** — props: resource — `apps/web/src/components/refine-ui/buttons/create.tsx`
- **DeleteButton** — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/delete.tsx`
- **EditButton** — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/edit.tsx`
- **InputPassword** — props: className — `apps/web/src/components/refine-ui/form/input-password.tsx`
- **PageHeader** — props: resource, title, subtitle, actions, className, headerClassName — `apps/web/src/components/refine-ui/layout/page-header.tsx`
- **ThemeProvider** — props: defaultTheme, storageKey — `apps/web/src/components/refine-ui/theme/theme-provider.tsx`
- **ThemeSelect** — `apps/web/src/components/refine-ui/theme/theme-select.tsx`
- **ThemeToggle** — props: className — `apps/web/src/components/refine-ui/theme/theme-toggle.tsx`
- **ListView** — props: className — `apps/web/src/components/refine-ui/views/list-view.tsx`

## Components

- **App** — `apps/web/src/App.tsx`
- **AppLayout** — `apps/web/src/components/AppLayout.tsx`
- **NotificationCenter** — `apps/web/src/components/NotificationCenter.tsx`
- **UndoableNotification** — props: message, description, undoableTimeout, cancelMutation, onClose — `apps/web/src/components/refine-ui/notification/undoable-notification.tsx`
- **StatusBadge** — props: status — `apps/web/src/components/ui.tsx`
- **WorkspaceProvider** — `apps/web/src/contexts/WorkspaceContext.tsx`
- **MOBILE_BREAKPOINT** — `apps/web/src/hooks/use-mobile.tsx`
- **ApiKeysPage** — `apps/web/src/pages/ApiKeysPage.tsx`
- **DashboardPage** — `apps/web/src/pages/DashboardPage.tsx`
- **InboxPage** — `apps/web/src/pages/InboxPage.tsx`
- **LoginPage** — `apps/web/src/pages/LoginPage.tsx`
- **MembersPage** — `apps/web/src/pages/MembersPage.tsx`
- **NotificationsPage** — `apps/web/src/pages/NotificationsPage.tsx`
- **ReceivedInvitationsPage** — `apps/web/src/pages/ReceivedInvitationsPage.tsx`
- **RegisterPage** — `apps/web/src/pages/RegisterPage.tsx`
- **RolesPage** — `apps/web/src/pages/RolesPage.tsx`
- **WorkspaceCreatePage** — `apps/web/src/pages/WorkspaceCreatePage.tsx`

---
_Back to [overview.md](./overview.md)_