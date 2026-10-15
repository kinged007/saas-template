// refine builds every error title as "<what happened> (status code: N)" from
// `err.statusCode`, so the title always ends in the parenthetical — even when
// the request never produced a response, in which case `statusCode` is the 0
// sentinel (see dataProvider `normalizeError`) or undefined. The real
// invariant: a three-digit 100-599 token is a real HTTP status and is kept;
// anything else is not a status, so drop the whole parenthetical instead of
// showing a code that never existed. (#397: `@refinedev/core@5.0.12` ships a
// useCreateMany/useUpdateMany title template missing its closing paren, so
// STATUS_SUFFIX never matches and such titles pass through unchanged — an
// upstream bug, not ours.)
const STATUS_SUFFIX = /^(.*) \(status code: (\S+)\)$/;

export const errorTitle = (message: string) => {
  const match = STATUS_SUFFIX.exec(message);
  return match && !/^[1-5]\d\d$/.test(match[2]) ? match[1] : message;
};
