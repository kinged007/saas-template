// Refine resource name → backend route when the two differ (hyphenated resource
// names are not valid backend route prefixes, and a resource can live under a
// sub-collection: the webhooks router serves subscriptions at
// `webhooks/subscriptions`, with nothing at its own prefix).
// `readById: false` marks a collection the API has no GET-by-id route for —
// the admin workspaces and audit lists have no detail route (the admin
// surface is list-only) — so `getOne` refuses them instead of firing a
// doomed request. GET /webhooks/subscriptions/{id} exists, so webhooks is
// not in that list.
const RESOURCES: Record<string, { path: string; readById?: false }> = {
  "admin-audit": { path: "admin/audit", readById: false },
  "admin-users": { path: "admin/users" },
  "admin-workspaces": { path: "admin/workspaces", readById: false },
  webhooks: { path: "webhooks/subscriptions" },
};

export const resourcePath = (resource: string) => RESOURCES[resource]?.path ?? resource;

export const hasReadById = (resource: string) => RESOURCES[resource]?.readById !== false;
