/**
 * The job pages render a failed fetch in-body and pass `errorNotification: false`
 * so refine does not toast the same refusal. The body gets the FastAPI `detail`
 * the dataProvider copied onto `message` — "you are not a member of this
 * workspace", not a status code. `undefined` means the query did not fail and
 * the page keeps its own not-found copy.
 */
export const jobFetchError = (error: unknown): string | undefined => {
  const { message } = (error ?? {}) as { message?: unknown };
  return typeof message === "string" && message ? message : undefined;
};