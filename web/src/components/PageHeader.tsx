import type { ReactNode } from "react";

/**
 * Big title, a status line with the reference's small square indicator, and
 * a control slot on the right. The indicator is a square because the
 * reference flattens every radius - it renders as one in the screenshot even
 * though its class says rounded-full.
 */
export function PageHeader({
  title,
  status,
  tone = "ok",
  children,
}: {
  title: string;
  status: ReactNode;
  tone?: "ok" | "warn" | "idle";
  children?: ReactNode;
}) {
  const dot = tone === "warn" ? "bg-warn" : tone === "idle" ? "bg-muted-2" : "bg-accent";
  return (
    <div className="mb-2 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
      <div className="min-w-0">
        <h1 className="mb-1 text-2xl font-medium tracking-tight text-ink">{title}</h1>
        <div className="flex items-center gap-2 text-[13px] text-muted">
          <span className={`size-2 shrink-0 ${dot}`} />
          <span className="truncate">{status}</span>
        </div>
      </div>
      {children && <div className="flex shrink-0 items-center gap-3">{children}</div>}
    </div>
  );
}
