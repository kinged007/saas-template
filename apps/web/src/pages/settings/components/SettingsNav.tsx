import { NavLink, useLocation } from "react-router";
import { cn } from "@/lib/utils";
import type { SettingsSection } from "../types";

export function SettingsNav({
  sections,
  basePath,
  label,
}: {
  sections: SettingsSection[];
  basePath: string;
  /** Landmark name, passed by every shell so it matches that shell's <h1>. */
  label: string;
}) {
  // Preserve an entry-point return target (e.g. ?from=/admin/users on the
  // member editor) across tab switches; each tab re-attaches it.
  const { search } = useLocation();
  const from = new URLSearchParams(search).get("from");
  const tabTo = (key: string) =>
    from ? `${basePath}/${key}?from=${encodeURIComponent(from)}` : `${basePath}/${key}`;
  return (
    <nav aria-label={label} className="flex flex-col gap-1">
      {sections.map((section) => {
        const Icon = section.icon;
        return (
          <NavLink
            key={section.key}
            to={tabTo(section.key)}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )
            }
          >
            {Icon && <Icon className="h-4 w-4 shrink-0" />}
            {section.label}
          </NavLink>
        );
      })}
    </nav>
  );
}
