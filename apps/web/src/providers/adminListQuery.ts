// Query string for the virtual `admin-workspaces` / `admin-audit` lists
// (superuser-only GET /admin/*): offset/limit plus one parameter per filter and
// per sorter. Free of runtime imports so `node --test` can assert the serialised
// request itself instead of scanning `dataProvider.ts` for source text.
import { normalizeSorters, type SorterInput } from "./sorters.ts";

export type AdminListQueryInput = {
  currentPage?: number;
  pageSize?: number;
  filters?: readonly Record<string, unknown>[];
  sorters?: readonly SorterInput[];
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
  // Normalised up front (see sorters.ts): a missing direction is the API
  // default (`asc`), never a dropped entry that would shift every later
  // direction onto the wrong column.
  for (const s of normalizeSorters(sorters)) {
    if (!s.field) continue;
    params.append("sort[]", s.field);
    params.append("order[]", s.order);
  }
  return params;
};