// Refine resource name → backend route when the two differ (hyphenated resource
// names are not valid backend route prefixes, and a resource can live under a
// sub-collection: the webhooks router serves subscriptions at
// `webhooks/subscriptions`, with nothing at its own prefix).
// `readById: false` marks a collection the API has no GET-by-id route for —
// the admin audit list has no detail route (that surface is list-only) — so
// `getOne` refuses them instead of firing a doomed request.
// GET /admin/workspaces/{id} exists, so admin-workspaces reads by id;
// GET /webhooks/subscriptions/{id} exists, so webhooks is not in that list.
const RESOURCES: Record<string, { path: string; readById?: false }> = {
  "admin-audit": { path: "admin/audit", readById: false },
  "admin-users": { path: "admin/users" },
  "admin-workspaces": { path: "admin/workspaces" },
  webhooks: { path: "webhooks/subscriptions" },
};

export const resourcePath = (resource: string) => RESOURCES[resource]?.path ?? resource;

export const hasReadById = (resource: string) => RESOURCES[resource]?.readById !== false;
