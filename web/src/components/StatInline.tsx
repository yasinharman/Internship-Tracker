import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import type { Delta } from "../lib/types";
import { fmtCompact } from "../lib/format";

/**
 * A stat sized to live in the page header, in the band between the title and
 * the range toggle.
 *
 * It replaced a row of cards. The cards were the reference's shape, and on
 * the reference's page they are the subject - four numbers are what an API
 * monitor is for. Here the posting list is the subject, and a 96px band of
 * bordered card was spending that much of the screen restating three numbers
 * in a much larger typeface than they needed.
 */

const ARROWS = { up: ArrowUp, down: ArrowDown, flat: Minus };

export function StatInline({
  label,
  value,
  delta,
}: {
  label: string;
  value: number;
  delta?: Delta | null;
}) {
  const Arrow = delta ? ARROWS[delta.direction] : null;

  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate text-[11px] font-medium whitespace-nowrap text-muted-2">{label}</span>
      <span className="flex items-baseline gap-1.5">
        <span className="text-lg leading-none font-medium tracking-tight tabular-nums text-ink">
          {fmtCompact(value)}
        </span>
        {delta && Arrow && (
          <span
            className={`flex items-center text-[11px] font-medium ${
              delta.direction === "flat" ? "text-muted-2" : "text-accent-soft"
            }`}
          >
            <Arrow size={10} strokeWidth={2} className="mr-0.5" />
            {delta.label}
          </span>
        )}
      </span>
    </div>
  );
}
