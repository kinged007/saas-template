/**
 * refine raises one generic error toast per failed request, keyed by the hook
 * that failed. A read the page renders in-body would then report the same
 * refusal twice, and the two copies disagree: toast
 * "Error (status code: 403) you are not a member of this workspace" above a
 * body reading "Job not found.". Reads are dropped so the view is the single
 * report; `read-failure.test.ts` re-checks these key templates against the
 * installed @refinedev/core.
 *
 * Mutation keys (`${id}-${identifier}-notification`, `create-…`,
 * `…-updateMany-error-notification`, `${method}-notification` with a write
 * method) keep the toast: an action has no persistent in-body surface, so the
 * toast is the only report.
 */
const READ_HOOK_KEY =
  /(useList|getOne|getMany|useInfiniteList)-notification$|^get-notification$/;

/** True for the error notification refine generates itself for a failed read. */
export const isReadFailure = (notification: {
  type?: string;
  key?: string;
}): boolean =>
  notification.type === "error" &&
  !!notification.key &&
  READ_HOOK_KEY.test(notification.key);