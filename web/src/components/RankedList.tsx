/**
 * The reference's "Highest Latency Endpoints": a label/value row over a thin
 * progress bar, five of them, vertically centred in the panel.
 *
 * Its bars are colour-tiered amber/blue/emerald because a slow endpoint is a
 * problem. A source having fewer postings than another is not, so the default
 * tone here is the neutral accent and amber is left for the sources page,
 * where a crawler that stopped returning rows is a real fault.
 */

export interface Row {
  key: string;
  label: string;
  value: string;
  fraction: number;
  tone?: "accent" | "warn" | "bad";
}

const FILLS = { accent: "bg-accent", warn: "bg-warn", bad: "bg-bad" };
const TEXTS = { accent: "text-accent-soft", warn: "text-warn", bad: "text-bad" };

export function RankedList({ rows, empty = "Gösterilecek veri yok." }: { rows: Row[]; empty?: string }) {
  if (rows.length === 0) {
    return <p className="py-8 text-center text-[13px] text-muted-2">{empty}</p>;
  }

  return (
    <div className="flex flex-1 flex-col justify-center space-y-6">
      {rows.map((row) => {
        const tone = row.tone ?? "accent";
        return (
          <div key={row.key} className="space-y-2">
            <div className="flex items-end justify-between gap-3">
              <span className="truncate font-mono text-xs text-ink-3">{row.label}</span>
              <span className={`shrink-0 font-mono text-xs tabular-nums ${TEXTS[tone]}`}>{row.value}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden bg-white/5">
              <div
                className={`h-full ${FILLS[tone]}`}
                // Never fully zero-width: a source with one posting next to a
                // source with two hundred should still show that it exists.
                style={{ width: `${Math.max(row.fraction * 100, row.fraction > 0 ? 2 : 0)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
