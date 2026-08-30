# UI

> **Navigation aid.** Component inventory and prop signatures extracted via AST. Read the source files before adding props or modifying component logic.

**68 components** (react)

## Client Components

- **CreateButton** — props: resource — `apps/web/src/components/refine-ui/buttons/create.tsx`
- **DeleteButton** — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/delete.tsx`
- **EditButton** — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/edit.tsx`
- **InputPassword** — props: className — `apps/web/src/components/refine-ui/form/input-password.tsx`
- **PageHeader** — props: resource, title, subtitle, actions, className, headerClassName — `apps/web/src/components/refine-ui/layout/page-header.tsx`
- **TabbedPageHeader** — props: resource, title, subtitle, actions, tabs, className, headerClassName — `apps/web/src/components/refine-ui/layout/tabbed-page-header.tsx`
- **ThemeProvider** — props: defaultTheme, storageKey — `apps/web/src/components/refine-ui/theme/theme-provider.tsx`
- **ThemeSelect** — `apps/web/src/components/refine-ui/theme/theme-select.tsx`
- **ThemeToggle** — props: className — `apps/web/src/components/refine-ui/theme/theme-toggle.tsx`
- **CreateView** — props: className — `apps/web/src/components/refine-ui/views/create-view.tsx`
- **ListView** — props: className — `apps/web/src/components/refine-ui/views/list-view.tsx`

## Components

- **App** — `agent/skills/slide-maker/deck-template/src/App.jsx`
- **Background** — `agent/skills/slide-maker/deck-template/src/components/Background.jsx`
- **Diagram** — props: src, alt, id, className — `agent/skills/slide-maker/deck-template/src/components/Diagram.jsx`
- **FORMATS** — `agent/skills/slide-maker/deck-template/src/components/ExportMenu.jsx`
- **GridView** — props: slides, navItems, current, onPick — `agent/skills/slide-maker/deck-template/src/components/GridView.jsx`
- **NotesPanel** — props: notes, label — `agent/skills/slide-maker/deck-template/src/components/NotesPanel.jsx`
- **PresentBar** — props: current, total, onPrev, onNext, tool, onSetTool, onClearInk, onExit, visible — `agent/skills/slide-maker/deck-template/src/components/PresentBar.jsx`
- **PresentMode** — props: tool, clearSignal — `agent/skills/slide-maker/deck-template/src/components/PresentMode.jsx`
- **SlideRail** — props: slides, navItems, current, onGoTo, editOn, onToggleEdit — `agent/skills/slide-maker/deck-template/src/components/SlideRail.jsx`
- **CANVAS_W** — `agent/skills/slide-maker/deck-template/src/components/SlideThumb.jsx`
- **StaggerContainer** — props: className — `agent/skills/slide-maker/deck-template/src/components/SlideTransition.jsx`
- **TopBar** — props: deckName, current, total, gridOpen, onToggleGrid, notesOpen, onToggleNotes, zoom, onZoom, onFit — `agent/skills/slide-maker/deck-template/src/components/TopBar.jsx`
- **TransitionMenu** — props: value, onChange — `agent/skills/slide-maker/deck-template/src/components/TransitionMenu.jsx`
- **HeroMetrics** — `agent/skills/slide-maker/deck-template/src/slides/00-EXAMPLE-hero-metrics.jsx`
- **App** — `agent/skills/slides-generator/assets/template/src/App.jsx`
- **Background** — props: variant, animate, className — `agent/skills/slides-generator/assets/template/src/components/Background.jsx`
- **ExportModal** — props: isOpen, onClose, totalSlides, currentSlide, goToSlide, presentationName — `agent/skills/slides-generator/assets/template/src/components/ExportModal.jsx`
- **Navigation** — props: currentSlide, totalSlides, navItems, onPrev, onNext, onGoTo, onExport — `agent/skills/slides-generator/assets/template/src/components/Navigation.jsx`
- **FadeIn** — props: delay, className — `agent/skills/slides-generator/assets/template/src/components/SlideTransition.jsx`
- **App** — `apps/web/src/App.tsx`
- **AppLayout** — `apps/web/src/components/AppLayout.tsx`
- **NotificationCenter** — `apps/web/src/components/NotificationCenter.tsx`
- **ComposeDialog** — props: open, onOpenChange, onCreated — `apps/web/src/components/inbox/ComposeDialog.tsx`
- **TiptapEditor** — props: value, onChange, placeholder, className, minHeight — `apps/web/src/components/inbox/TiptapEditor.tsx`
- **UndoableNotification** — props: message, description, undoableTimeout, cancelMutation, onClose — `apps/web/src/components/refine-ui/notification/undoable-notification.tsx`
- **StatusBadge** — props: status — `apps/web/src/components/ui.tsx`
- **WorkspaceProvider** — `apps/web/src/contexts/WorkspaceContext.tsx`
- **MOBILE_BREAKPOINT** — `apps/web/src/hooks/use-mobile.tsx`
- **LinkBase** — props: href, className — `apps/web/src/lib/markdown.tsx`
- **ApiKeyCreatePage** — `apps/web/src/pages/ApiKeyCreatePage.tsx`
- **ApiKeysPage** — `apps/web/src/pages/ApiKeysPage.tsx`
- **DashboardPage** — `apps/web/src/pages/DashboardPage.tsx`
- **InboxPage** — `apps/web/src/pages/InboxPage.tsx`
- **JobDetailPage** — `apps/web/src/pages/JobDetailPage.tsx`
- **JobRunPage** — `apps/web/src/pages/JobRunPage.tsx`
- **JobsPage** — `apps/web/src/pages/JobsPage.tsx`
- **LoginPage** — `apps/web/src/pages/LoginPage.tsx`
- **MembersPage** — `apps/web/src/pages/MembersPage.tsx`
- **NotificationsPage** — `apps/web/src/pages/NotificationsPage.tsx`
- **ReceivedInvitationsPage** — `apps/web/src/pages/ReceivedInvitationsPage.tsx`
- **RegisterPage** — `apps/web/src/pages/RegisterPage.tsx`
- **RolesPage** — `apps/web/src/pages/RolesPage.tsx`
- **WorkspaceCreatePage** — `apps/web/src/pages/WorkspaceCreatePage.tsx`
- **AgentCreatePage** — `apps/web/src/pages/agents/AgentCreatePage.tsx`
- **AgentEditPage** — `apps/web/src/pages/agents/AgentEditPage.tsx`
- **AgentsPage** — `apps/web/src/pages/agents/AgentsPage.tsx`
- **ProfileSettingsPage** — `apps/web/src/pages/settings/ProfileSettingsPage.tsx`
- **GenericSettingsLayout** — props: registry, basePath, title, subtitle, can, guard — `apps/web/src/pages/settings/components/GenericSettingsLayout.tsx`
- **SettingsNav** — props: sections, basePath — `apps/web/src/pages/settings/components/SettingsNav.tsx`
- **WorkspaceSettingsLayout** — `apps/web/src/pages/settings/workspace/WorkspaceSettingsLayout.tsx`
- **AgentsGeneralSection** — `apps/web/src/pages/settings/workspace/sections/AgentsGeneralSection.tsx`
- **AgentsSandboxSection** — `apps/web/src/pages/settings/workspace/sections/AgentsSandboxSection.tsx`
- **AuditLogSection** — `apps/web/src/pages/settings/workspace/sections/AuditLogSection.tsx`
- **GeneralSection** — `apps/web/src/pages/settings/workspace/sections/GeneralSection.tsx`
- **JobsSection** — `apps/web/src/pages/settings/workspace/sections/JobsSection.tsx`
- **RolesSection** — `apps/web/src/pages/settings/workspace/sections/RolesSection.tsx`
- **UsersSection** — `apps/web/src/pages/settings/workspace/sections/UsersSection.tsx`

---
_Back to [overview.md](./overview.md)_