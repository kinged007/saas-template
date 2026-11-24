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
  const start = code.search(/^export function useUpdateProfile\b/m);
  if (start < 0) return null;
  const next = code.slice(start + 1).search(/^export /m);
  return code.slice(start, next < 0 ? undefined : start + 1 + next);
}

// The caller object of each `invalidateQueries({ ... })`, balanced so an
// option value that itself contains braces (a block-bodied
// `predicate: (q) => { ... }`) stays inside one call instead of splitting the
// scan. Comments are stripped upstream; braces inside a string literal are not
// balanced, but query keys and invalidateQueries options carry no such braces
// in practice. ponytail: balanced-brace walk, no string-literal tracking.
function invalidateCallBodies(region: string): string[] {
  const bodies: string[] = [];
  const openRe = /invalidateQueries\(\s*\{/g;
  let m: RegExpExecArray | null;
  while ((m = openRe.exec(region)) !== null) {
    const open = m.index + m[0].length - 1; // the matched "{"
    let depth = 0;
    let end = -1;
    for (let i = open; i < region.length; i++) {
      const c = region[i];
      if (c === "{") depth++;
      else if (c === "}") {
        if (--depth === 0) {
          end = i;
          break;
        }
      }
    }
    if (end < 0) break; // unbalanced: no further complete call
    bodies.push(region.slice(open, end + 1));
    openRe.lastIndex = end + 1;
  }
  return bodies;
}

export function countAuthInvalidations(region: string): number {
  // An exact `queryKey: ["auth"]` invalidation counts whether the call carries
  // other options around the key (`refetchType`, `exact`, a block-bodied
  // `predicate`, ...) or not; a longer key that only shares the prefix
  // (`["auth", "identity"]`) does not.
  const AUTH_KEY = /queryKey:\s*\[\s*"auth"\s*\]/;
  return invalidateCallBodies(region).filter((body) => AUTH_KEY.test(body))
    .length;
}
