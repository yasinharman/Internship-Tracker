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
  stats,
  children,
}: {
  title: string;
  status: ReactNode;
  tone?: "ok" | "warn" | "idle";
  /**
   * The band between the title and the controls on the right.
   *
   * It is the widest empty space on the page and the numbers that belong in
   * it are the ones the controls on either side change. Below `xl` it drops
   * to its own line rather than squeezing - see the layout note below.
   */
  stats?: ReactNode;
  children?: ReactNode;
}) {
  const dot = tone === "warn" ? "bg-warn" : tone === "idle" ? "bg-muted-2" : "bg-accent";
  return (
    /*
      Three things want this row: the title, the stats, and the controls.
      They only fit side by side from xl up - at lg the content area is
      704px and they need about 780, which wrapped the stats into a column
      that ran into the segmented control.

      Below xl the title and the controls still share a line and the stats
      drop under them. `display: contents` is what lets that happen without
      rendering the controls twice: the wrapper dissolves at xl so its two
      children become items of the outer row, and order-last sends the
      controls past the stats to the far right.
    */
    <div className="mb-2 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
      <div className="flex items-center justify-between gap-4 xl:contents">
        <div className="min-w-0">
          <h1 className="mb-1 text-2xl font-medium tracking-tight text-ink">{title}</h1>
          <div className="flex items-center gap-2 text-[13px] text-muted">
            <span className={`size-2 shrink-0 ${dot}`} />
            <span className="truncate">{status}</span>
          </div>
        </div>
        {children && (
          <div className="flex shrink-0 items-center gap-3 xl:order-last">{children}</div>
        )}
      </div>

      {stats && (
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3 xl:gap-x-10">{stats}</div>
      )}
    </div>
  );
}
