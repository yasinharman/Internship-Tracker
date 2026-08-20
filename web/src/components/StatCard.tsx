import { ArrowDown, ArrowUp, Minus, type LucideIcon } from "lucide-react";
import type { Delta } from "../lib/types";
import { fmtCompact } from "../lib/format";

/**
 * KPI card. Number and delta share a baseline-aligned row, exactly as the
 * reference does - the delta sits on the big number's baseline rather than
 * centred against it, which is what stops it looking like a subtitle.
 *
 * Tighter than the reference's card on purpose, because it does not get a
 * row of its own: these sit in the filter bar, in the gap between the last
 * chip and the note at its right end. The card has to ride in a row of 32px
 * controls, so it is about two thirds of the reference's height.
 */

const ARROWS = { up: ArrowUp, down: ArrowDown, flat: Minus };

interface Props {
  label: string;
  icon: LucideIcon;
  value: number;
  delta?: Delta | null;
  /** Turns the value amber. Only used by the unclassified card, and only when
   *  the count is above zero - see DashboardPage. */
  warn?: boolean;
  hint?: string;
}

export function StatCard({ label, icon: Icon, value, delta, warn = false, hint }: Props) {
  const Arrow = delta ? ARROWS[delta.direction] : null;
  const deltaTone =
    delta?.direction === "flat" ? "text-muted-2" : warn ? "text-warn" : "text-accent-soft";

  return (
    <div className="border border-line bg-white/[0.02] px-3 py-2.5 transition-colors hover:bg-white/[0.04]" title={hint}>
      <div className="mb-1 flex items-center justify-between text-muted">
        <span className="truncate text-[11px] font-medium whitespace-nowrap">{label}</span>
        <Icon size={12} strokeWidth={2} className={`ml-2 shrink-0 ${warn ? "text-warn" : ""}`} />
      </div>
      <div className="flex items-baseline gap-2">
        <span
          className={`text-lg leading-none font-medium tracking-tight tabular-nums ${warn ? "text-warn" : "text-ink"}`}
        >
          {fmtCompact(value)}
        </span>
        {delta && Arrow && (
          <span className={`flex items-center text-[11px] font-medium ${deltaTone}`}>
            <Arrow size={10} strokeWidth={2} className="mr-0.5" />
            {delta.label}
          </span>
        )}
      </div>
    </div>
  );
}
