import { ArrowDown, ArrowUp, Minus, type LucideIcon } from "lucide-react";
import type { Delta } from "../lib/types";
import { fmtCompact } from "../lib/format";

/**
 * KPI card. Number and delta share a baseline-aligned row, exactly as the
 * reference does - the delta sits on the big number's baseline rather than
 * centred against it, which is what stops it looking like a subtitle.
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
    <div className="border border-line bg-white/[0.02] p-5 transition-colors hover:bg-white/[0.04]" title={hint}>
      <div className="mb-4 flex items-center justify-between text-muted">
        <span className="text-[13px] font-medium">{label}</span>
        <Icon size={16} strokeWidth={2} className={warn ? "text-warn" : undefined} />
      </div>
      <div className="flex items-baseline gap-2">
        <span
          className={`text-3xl font-medium tracking-tight tabular-nums ${warn ? "text-warn" : "text-ink"}`}
        >
          {fmtCompact(value)}
        </span>
        {delta && Arrow && (
          <span className={`flex items-center text-xs font-medium ${deltaTone}`}>
            <Arrow size={12} strokeWidth={2} className="mr-0.5" />
            {delta.label}
          </span>
        )}
      </div>
    </div>
  );
}
