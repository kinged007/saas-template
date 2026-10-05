// Shared sorter normaliser for both list dialects (the `sort[]`/`order[]`
// admin lists and the simple-rest `_sort`/`_order` lists). simple-rest's
// `generateSort` pushes `item.order` unconditionally, so a sorter with no
// direction serialises `_order=undefined` and the API's asc|desc check 422s
// the whole list. `parse_query` pairs directions with their column by
// position and pads only at the end, so dropping a direction would shift
// every later direction onto the wrong column. Send the API default (`asc`)
// instead — and `||`, not `??`, because the parser drops an empty direction
// the same way it drops an omitted one. The generic keeps each caller's
// sorter type (refine's `CrudSort` stays `CrudSort`), so no call site needs
// a cast. Free of runtime imports so `node --test` can load it.

export type SorterInput = { field?: string; order?: string | null };

type Normalized<T extends SorterInput> = Omit<T, "order"> & {
  order: Exclude<T["order"], null | undefined> | "asc";
};

export const normalizeSorters = <T extends SorterInput>(
  sorters: readonly T[] | undefined,
): Normalized<T>[] =>
  (sorters ?? []).map((s) => ({ ...s, order: s.order || "asc" }) as Normalized<T>);
