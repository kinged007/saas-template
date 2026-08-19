import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Detects an Okta *admin console* URL (org-admin.okta.com) and returns the
 * org API domain it maps to (e.g. https://acme-admin.okta.com →
 * https://acme.okta.com), or null when the value isn't a console URL. */
export function oktaAdminConsoleFix(value?: string): string | null {
  if (!value) return null;
  const match = /^(https?:\/\/[^/]+?)-admin\.okta\.com/.exec(value);
  if (!match) return null;
  return `${match[1]}.okta.com`;
}
