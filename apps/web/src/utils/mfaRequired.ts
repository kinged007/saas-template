/**
 * MFA gate contract with the API: workspace-scoped requests from an account
 * without TOTP enrolled fail 403 with exactly this detail (see
 * `require_permission` in apps/api/src/api/deps.py). The response interceptor
 * redirects those failures to the enrollment page; the reason toast is shown
 * from the security page itself, because the redirect is a hard navigation
 * and an in-memory toast would not survive it. The refine notification
 * provider stays silent for the message, so it appears exactly once.
 */
export const MFA_REQUIRED_MESSAGE = "mfa required for this workspace";

/** Self-service enrollment page. */
export const MFA_SETUP_PATH = "/settings/profile/security";

/** sessionStorage flag carrying the notice across the redirect reload. */
export const MFA_NOTICE_KEY = "tf_mfa_required_notice";
