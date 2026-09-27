import { AuditLogCard, AuditLogTable } from "@/components/AuditLogTable";

export function AuditSection() {
  return (
    <AuditLogCard
      title="Audit Log"
      description="Immutable trail of actions across all workspaces. Search matches workspace name/id, user name/email/id, action, or resource id — only 20 rows load per page. Click a row for full details."
    >
      <AuditLogTable
        resource="admin-audit"
        searchPlaceholder="Search workspace, user, action…"
        searchEnabled
        showWorkspace
      />
    </AuditLogCard>
  );
}
