import { RANGE_LABELS } from "../lib/format";
import type { RangeKey } from "../lib/types";

/** The reference's segmented control: a 2px inset track, active pill filled
 *  white/10. 1H/24H/7D there; the ranges a job board is asked about here. */
const RANGES: RangeKey[] = ["24h", "7d", "30d", "all"];

export function RangeToggle({ value, onChange }: { value: string; onChange: (next: RangeKey) => void }) {
  return (
    <div className="flex border border-line bg-white/[0.03] p-0.5">
      {RANGES.map((range) => (
        <button
          key={range}
          type="button"
          onClick={() => onChange(range)}
          aria-pressed={value === range}
          className={`px-3 py-1.5 text-[13px] font-medium transition-colors ${
            value === range ? "bg-white/10 text-ink shadow-sm" : "text-muted hover:text-ink-2"
          }`}
        >
          {RANGE_LABELS[range]}
        </button>
      ))}
    </div>
  );
}
