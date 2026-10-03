/**
 * Renders a mutation failure as toast text. The dataProvider response interceptor
 * copies a FastAPI `detail` string onto `message`, so an AxiosError always carries
 * readable text; without this, `String(e)` prints "[object Object]".
 */
export const errorMessage = (raw: unknown): string => {
  if (typeof raw === "string" && raw) return raw;
  const { message } = (raw ?? {}) as { message?: unknown };
  return typeof message === "string" && message ? message : "Request failed";
};