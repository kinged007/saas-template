import { AuditLogCard, AuditLogTable } from "@/components/AuditLogTable";

export function AuditLogSection() {
  return (
    <AuditLogCard
      title="Audit Log"
      description="Immutable trail of workspace actions (workspace edits, member changes, role/invitation/api-key events). Search matches user name/email/id, action, or resource id — only 20 rows load per page. Click a row for full details."
    >
      <AuditLogTable
        resource="audit"
        searchPlaceholder="Search user, action…"
        searchEnabled
        showWorkspace={false}
      />
    </AuditLogCard>
  );
}
