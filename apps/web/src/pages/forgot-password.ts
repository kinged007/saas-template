/** Message the forgot-password form shows for a non-OK response.
 * response is the fetch Response (or null on network failure); Retry-After is read only for 429. */
export const forgotPasswordError = (
  status: number,
  response: { headers: { get(name: string): string | null } } | null = null,
): string => {
  if (status !== 429) return "request failed";
  const seconds = Number(response?.headers.get("Retry-After"));
  if (Number.isFinite(seconds) && seconds > 0) {
    return `Too many attempts — try again in ~${Math.ceil(seconds / 60)} min.`;
  }
  return "Too many attempts — try again later.";
};
