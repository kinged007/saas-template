"use client";

import type { PropsWithChildren, ReactNode } from "react";

import { useResourceParams, useUserFriendlyName } from "@refinedev/core";
import { Breadcrumb } from "@/components/refine-ui/layout/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

type TabbedPageHeaderProps = PropsWithChildren<{
  resource?: string;
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  tabs?: ReactNode;
  className?: string;
  headerClassName?: string;
}>;

export const TabbedPageHeader = ({
  children,
  resource: resourceFromProps,
  title: titleFromProps,
  subtitle,
  actions,
  tabs,
  className,
  headerClassName,
}: TabbedPageHeaderProps) => {
  const getUserFriendlyName = useUserFriendlyName();

  const { resource, identifier } = useResourceParams({
    resource: resourceFromProps,
  });

  const title =
    titleFromProps ??
    getUserFriendlyName(
      resource?.meta?.label ?? identifier ?? resource?.name,
      "plural",
    );

  const rightActions = actions ?? children;

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <div className="flex items-center relative gap-2">
        <div className="bg-background z-[2] pr-4">
          <Breadcrumb />
        </div>
        <Separator className={cn("absolute", "left-0", "right-0", "z-[1]")} />
      </div>
      <div className={cn("flex flex-col gap-3", headerClassName)}>
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-2xl font-bold truncate">{title}</h2>
            {/* Deliberate && below (see #731): JSX children drop "", unlike the inspected RoleCapNotice return fixed in #711. */}
            {subtitle && <p className="text-muted-foreground mt-1">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {tabs && <div className="hidden sm:flex items-center">{tabs}</div>}
            {rightActions && <div className="flex items-center gap-2">{rightActions}</div>}
          </div>
        </div>
        {tabs && <div className="sm:hidden flex w-full [&>div]:w-full [&>div]:flex-1">{tabs}</div>}
      </div>
    </div>
  );
};

TabbedPageHeader.displayName = "TabbedPageHeader";
