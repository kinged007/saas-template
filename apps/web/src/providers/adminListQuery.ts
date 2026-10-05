// Query string for the virtual `admin-workspaces` / `admin-audit` lists
// (superuser-only GET /admin/*): offset/limit plus one parameter per filter and
// per sorter. Free of runtime imports so `node --test` can assert the serialised
// request itself instead of scanning `dataProvider.ts` for source text.

export type AdminListQueryInput = {
  currentPage?: number;
  pageSize?: number;
  filters?: readonly Record<string, unknown>[];
  sorters?: readonly { field?: string; order?: string }[];
};

export const adminListQuery = ({
  currentPage = 1,
  pageSize = 10,
  filters,
  sorters,
}: AdminListQueryInput): URLSearchParams => {
  const params = new URLSearchParams({
    offset: String((currentPage - 1) * pageSize),
    limit: String(pageSize),
  });
  for (const f of filters ?? []) {
    if (typeof f.field !== "string") continue;
    // `q` is the cross-field search term (backend `?q=`), not a column.
    params.append(f.field === "q" ? "q" : `${f.field}_like`, String(f.value));
  }
  for (const s of sorters ?? []) {
    if (!s.field) continue;
    params.append("sort[]", s.field);
    // `parse_query` pairs `sort[]` with `order[]` by position and pads only at
    // the end, so dropping a direction would shift every later direction onto
    // the wrong column. Send the API default (`asc`) instead — and `||`, not
    // `??`, because the parser drops an empty direction the same way it drops
    // an omitted one.
    params.append("order[]", s.order || "asc");
  }
  return params;
};