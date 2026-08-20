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
   * it are the ones the controls on either side change. Below 1440px it
   * drops to its own line rather than squeezing - see the layout note below.
   */
  stats?: ReactNode;
  children?: ReactNode;
}) {
  const dot = tone === "warn" ? "bg-warn" : tone === "idle" ? "bg-muted-2" : "bg-accent";
  return (
    /*
      Three things want this row: the title, the stats, and the controls.

      1440px, not a named breakpoint, because the number is measured rather
      than chosen. The title needs 333px, the toggle 221px, and three cards
      whose widest label ("Bugün Eklenen") wants 148px of inner width need
      468px with their gaps; add the 64px that separates the groups and the
      content area has to be 1086px, which a 256px sidebar and 64px of page
      padding turn into 1406px of window. xl (1280) left the cards at 101px
      and truncated their labels; 2xl (1536) would have given up the layout
      on a 1440px screen, which is where it was asked for.

      Under that the title and the controls still share a line and the cards
      drop under them, three across, with room to spare. `display: contents`
      is what lets that happen without rendering the controls twice: the
      wrapper dissolves at the breakpoint so its two children become items of
      the outer row, and order-last sends the controls past the cards to the
      far right.
    */
    <div className="mb-2 flex flex-col gap-4 min-[1440px]:flex-row min-[1440px]:items-center min-[1440px]:justify-between">
      <div className="flex items-center justify-between gap-4 min-[1440px]:contents">
        <div className="min-w-0">
          <h1 className="mb-1 text-2xl font-medium tracking-tight text-ink">{title}</h1>
          <div className="flex items-center gap-2 text-[13px] text-muted">
            <span className={`size-2 shrink-0 ${dot}`} />
            <span className="truncate">{status}</span>
          </div>
        </div>
        {children && (
          <div className="flex shrink-0 items-center gap-3 min-[1440px]:order-last">{children}</div>
        )}
      </div>

      {/* flex-1 so the cards take the whole band rather than clustering at one
          end of it; min-w-0 so they shrink instead of pushing the toggle off. */}
      {stats && <div className="min-w-0 min-[1440px]:flex-1 min-[1440px]:px-8">{stats}</div>}
    </div>
  );
}
