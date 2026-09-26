/** Rebrand the app by setting VITE_APP_NAME / VITE_STORAGE_PREFIX in apps/web/.env. */
export const APP_NAME = import.meta.env.VITE_APP_NAME || "SaaS Template";

// localStorage key prefix. Changing it drops existing browser state
// (identity, workspace selection, onboarding hints) — it does not sign users out.
export const STORAGE_PREFIX = import.meta.env.VITE_STORAGE_PREFIX || "tf";
