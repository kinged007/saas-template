// refine builds every error title as "<what happened> (status code: N)" from
// `err.statusCode`, evaluating the template even when no request ever produced
// a response (offline, DNS failure, CORS rejection, abort) — that case carries
// the 0 sentinel. There is no status to report so drop the whole
// parenthetical instead of showing a code that never existed.
const STATUS_SUFFIX = /^(.*) \(status code: (\S+)\)$/;

export const errorTitle = (message: string) => {
  const match = STATUS_SUFFIX.exec(message);
  return match && !/^[1-5]\d\d$/.test(match[2]) ? match[1] : message;
};
