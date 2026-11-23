import { useEffect } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { clampPage, totalPages } from "./list-pager";

/**
 * Previous / Page n of N / Next with the row range it covers. Renders nothing
 * when the list fits one page, so a short list carries no pager.
 */
export function ListPager({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const pages = totalPages(total, pageSize);
  const clamped = clampPage(page, total, pageSize);
  // A page that outlives the list (rows deleted from another tab) would fetch an
  // empty page and leave the reader stranded with no Next and no Previous to
  // walk out of, so the page falls back to the last one holding rows.
  useEffect(() => {
    if (clamped !== page) onPageChange(clamped);
  }, [page, clamped, onPageChange]);

  if (total <= pageSize) return null;

  return (
    <div className="flex items-center justify-between gap-2">
      <p className="text-muted-foreground text-sm">
        Showing {(clamped - 1) * pageSize + 1}–{Math.min(clamped * pageSize, total)} of {total}
      </p>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={clamped <= 1}
          onClick={() => onPageChange(Math.max(1, clamped - 1))}
        >
          <ChevronLeft className="h-4 w-4" />
          Previous
        </Button>
        <span className="text-muted-foreground px-2 text-sm">
          Page {clamped} of {pages}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={clamped >= pages}
          onClick={() => onPageChange(Math.min(pages, clamped + 1))}
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
