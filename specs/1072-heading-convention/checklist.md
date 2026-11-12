# Checklist — #1072

- [x] CHK001 Does the plan header say there is no spec and where the requirements come from?
- [x] CHK002 Does the plan name the convention (single `h1` page title owned by the shell, `h2` sections, `h2` landmark/overlay titles), as the routing comment requires?
- [x] CHK003 Does the plan give the order of work, as the routing comment requires?
- [x] CHK004 Is the scope inside the ceiling: refine-ui shells and their consumers, docs plus application in one PR, no new public interface, no dependency?
- [x] CHK005 Is every AC measurable (a tag in a named file, or a Playwright assertion)?
- [x] CHK006 Does every AC have at least one task, and does every task name an AC or a polish purpose?
- [x] CHK007 Are all named files and lines confirmed with `ls`/`grep` (shell files, `components/ui.tsx:35`, JobsPage:166, MembersPage:353, InboxPage:872/1231, WorkspaceSettingsLayout:86/95, AdminLayout:43/55)?
- [x] CHK008 Is the decision not to widen `card-title-classes.test.ts` explained with evidence (JobRunPage:88, JobDetailPage:351)?
- [x] CHK009 Is the landmark test written before the implementation and shown to fail first?
- [x] CHK010 Are existing e2e specs that query headings by level covered by the regression run?
- [x] CHK011 Is the `/jobs` mock-API uncertainty handled with a stated fallback?
- [x] CHK012 Are the quality-gate commands named with their source (CI workflow jobs and root `AGENTS.md`)?
- [x] CHK013 Is the inclusion of #1616 (AC-5) traced to an authorized comment and recorded as an assumption?
- [x] CHK014 Is rollback stated and free of data or config side effects?
