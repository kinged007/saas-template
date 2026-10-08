export function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/.*$/gm, "");
}

// useUpdateProfile's counted region: from its declaration to the next
// top-level export of any form — `export const useX = ...` and
// `export async function` included — or to EOF when the hook is last.
// Comments are stripped first, so a comment can neither anchor nor widen the
// region nor be counted as an invalidation. null when the declaration itself
// is absent, so the guard fails loudly if the hook stops being a plain
// `export function`.
export function useUpdateProfileWindow(source: string): string | null {
  const code = stripComments(source);
  const start = code.indexOf("export function useUpdateProfile");
  if (start < 0) return null;
  const next = code.slice(start + 1).search(/^export /m);
  return code.slice(start, next < 0 ? undefined : start + 1 + next);
}

export function countAuthInvalidations(region: string): number {
  return (region.match(/invalidateQueries\(\{\s*queryKey:\s*\[\s*"auth"\s*\]\s*\}\)/g) ?? []).length;
}
