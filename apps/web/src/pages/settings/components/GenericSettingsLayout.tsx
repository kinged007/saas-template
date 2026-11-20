import { Link, Navigate, Outlet, useLocation } from "react-router";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SettingsRegistry } from "../types";
import { SettingsNav } from "./SettingsNav";

/**
 * Generic settings shell — reusable for any entity type.
 *
 * Usage:
 * ```tsx
 * const projectSettings = createSettingsRegistry([...]);
 * <GenericSettingsLayout registry={projectSettings} basePath="/settings/project" title="Project Settings" />
 * ```
 * The route config nests the section components:
 * ```tsx
 * <Route path="settings/project" element={<GenericSettingsLayout ... />}>
 *   {projectSettings.sections.map(s => <Route key={s.key} path={s.key} element={<s.component />} />)}
 * </Route>
 * ```
 * The nav landmark is named after `title`, so it reads as part of this page
 * rather than a generic "Settings" landmark beside a differently named
 * heading. The shell sidebar keeps "Main", so the two stay distinguishable.
 */
export function GenericSettingsLayout({
  registry,
  basePath,
  title,
  subtitle,
  can,
  guard,
}: {
  registry: SettingsRegistry;
  basePath: string;
  title: string;
  subtitle?: string;
  /** Permission check — receives a permission string, returns true if visible. */
  can: (permission?: string) => boolean;
  /** Optional gate — when false shows access-denied instead of the shell. */
  guard?: { allowed: boolean; deniedTitle?: string; deniedMessage?: string };
  className?: string;
}) {
  const location = useLocation();
  const visible = registry.getVisible(can);

  if (guard && !guard.allowed) {
    return (
      <div className="mx-auto max-w-2xl py-12 text-center">
        <h2 className="text-xl font-semibold">{guard.deniedTitle ?? "Access denied"}</h2>
        <p className="text-muted-foreground mt-2 text-sm">
          {guard.deniedMessage ?? "You do not have permission to access these settings."}
        </p>
        <Button variant="outline" asChild className="mt-4">
          <Link to="/">Back to dashboard</Link>
        </Button>
      </div>
    );
  }

  const isIndex = location.pathname === basePath || location.pathname === `${basePath}/`;
  if (isIndex && visible.length > 0) {
    return <Navigate to={visible[0].key} replace />;
  }

  return (
    <div className={cn("mx-auto flex w-full max-w-6xl flex-col gap-6")}>
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="text-muted-foreground text-sm">{subtitle}</p>}
      </div>
      <div className="flex flex-col gap-6 md:flex-row">
        <aside className="w-full shrink-0 md:w-56">
          <SettingsNav sections={visible} basePath={basePath} label={title} />
        </aside>
        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
