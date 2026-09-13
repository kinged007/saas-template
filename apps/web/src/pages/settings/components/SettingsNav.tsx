import { NavLink } from "react-router";
import { cn } from "@/lib/utils";
import type { SettingsSection } from "../types";

export function SettingsNav({
  sections,
  basePath,
}: {
  sections: SettingsSection[];
  basePath: string;
}) {
  return (
    <nav className="flex flex-col gap-1">
      {sections.map((section) => {
        const Icon = section.icon;
        return (
          <NavLink
            key={section.key}
            to={`${basePath}/${section.key}`}
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
