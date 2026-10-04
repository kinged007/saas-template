// Refine resource name → backend path when they differ (hyphenated resource
// names are not valid backend route prefixes, and a resource can live under a
// sub-collection: the webhooks router serves subscriptions at
// `webhooks/subscriptions`, with nothing at its own prefix).
const RESOURCE_PATHS: Record<string, string> = {
  "admin-users": "admin/users",
  webhooks: "webhooks/subscriptions",
};

export const resourcePath = (resource: string) => RESOURCE_PATHS[resource] ?? resource;

// The webhooks router has no GET /subscriptions/{id} — only PATCH, DELETE,
// rotate-secret and deliveries — so `getOne` on it answers 405. Refuse the read
// in the client instead of sending the request: fetch the collection through
// `custom` (GET /webhooks/subscriptions) and filter until the route exists.
const WITHOUT_READ_BY_ID = new Set(["webhooks"]);

export const hasReadById = (resource: string) => !WITHOUT_READ_BY_ID.has(resource);