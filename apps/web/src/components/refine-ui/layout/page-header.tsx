"use client";

import type { PropsWithChildren, ReactNode } from "react";

import { useResourceParams, useUserFriendlyName } from "@refinedev/core";
import { Breadcrumb } from "@/components/refine-ui/layout/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

type PageHeaderProps = PropsWithChildren<{
  resource?: string;
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
  headerClassName?: string;
}>;

export const PageHeader = ({
  children,
  resource: resourceFromProps,
  title: titleFromProps,
  subtitle,
  actions,
  className,
  headerClassName,
}: PageHeaderProps) => {
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

  const rightContent = actions ?? children;

  return (
    <div className={cn("flex flex-col", "gap-4", className)}>
      <div className="flex items-center relative gap-2">
        <div className="bg-background z-[2] pr-4">
          <Breadcrumb />
        </div>
        <Separator className={cn("absolute", "left-0", "right-0", "z-[1]")} />
      </div>
      <div className={cn("flex", "items-center", "justify-between", "gap-4", headerClassName)}>
        <div>
          <h2 className="text-2xl font-bold">{title}</h2>
          {/* Deliberate && (see #731): JSX children drop "", unlike the inspected RoleCapNotice return fixed in #711. */}
          {subtitle && <p className="text-muted-foreground mt-1">{subtitle}</p>}
        </div>
        {rightContent && (
          <div className="flex items-center gap-2">{rightContent}</div>
        )}
      </div>
    </div>
  );
};

PageHeader.displayName = "PageHeader";
