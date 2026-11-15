// Shared sorter normaliser for both list dialects.
// These are the `sort[]`/`order[]` admin lists and the simple-rest
// `_sort`/`_order` lists. simple-rest's `generateSort` pushes `item.order`
// unconditionally. A sorter with no direction serialises `_order=undefined`.
// The API's asc|desc check then 422s the whole list. `parse_query` pairs
// directions with their column by position. It pads only at the end.
// Dropping a direction would shift every later direction onto the wrong
// column. Send the API default (`asc`) when a direction is empty or
// whitespace-only. Use `||`, not `??`. The parser drops an empty direction
// the same way it drops an omitted one. A whitespace-only direction trims to
// empty and degrades the same way. It never reaches the wire as a value the
// API strips to an invalid `""`. The generic keeps each caller's sorter type.
// Refine's `CrudSort` stays `CrudSort`, so no call site needs a cast. This
// module has no runtime imports. `node --test` loads it directly.

export type SorterInput = { field?: string; order?: string | null };

type Normalized<T extends SorterInput> = Omit<T, "order"> & {
  order: Exclude<T["order"], null | undefined> | "asc";
};

export const normalizeSorters = <T extends SorterInput>(
  sorters: readonly T[] | undefined,
): Normalized<T>[] =>
  (sorters ?? []).map((s) => ({
    ...s,
    order: (String(s.order ?? "").trim() || "asc") as Normalized<T>["order"],
  }));
