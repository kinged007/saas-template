const configuredName = import.meta.env.VITE_APP_NAME?.trim();
const configuredSlug = import.meta.env.VITE_APP_SLUG?.trim();
const configuredLogo = import.meta.env.VITE_LOGO_URL?.trim();

export const APP_NAME = configuredName || "SaaS Template";
export const APP_SLUG = configuredSlug || "saas-template";
export const LOGO_URL = configuredLogo || "/logo.svg";
