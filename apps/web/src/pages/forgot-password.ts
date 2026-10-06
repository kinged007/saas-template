/** Message the forgot-password form shows for a non-OK response. */
export const forgotPasswordError = (status: number): string =>
  status === 429 ? "Too many attempts — try again later." : "request failed";
