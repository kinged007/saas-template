/**
 * Project-owned entity types for the web extension seams.
 *
 * Everything a derived project adds lives here (or in sibling files under
 * `src/project/`), never in the template-owned `src/types.ts`. This module
 * carries types only — no runtime imports — so it stays free of backend,
 * store, or component dependencies.
 */
export type ProjectDemoStatus = "active" | "archived";

export type ProjectDemoItem = {
  id: string;
  name: string;
  status: ProjectDemoStatus;
  description: string;
};
