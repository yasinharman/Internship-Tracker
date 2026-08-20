import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, RotateCcw, X } from "lucide-react";
import type { Meta, Option } from "../lib/types";
import type { Query } from "../lib/api";

/**
 * Streamlit put these in the sidebar; the reference uses that space for
 * navigation, so the filters became a horizontal bar under the page title.
 *
 * Every change goes through useFilters into the URL, so the bar has no state
 * of its own beyond which dropdown is open.
 */

function Dropdown({
  label,
  options,
  selected,
  onChange,
  note,
}: {
  label: string;
  options: Option[];
  selected: string[];
  onChange: (next: string[]) => void;
  /** Footnote inside the panel, for a rule that applies to this filter. */
  note?: string;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const toggle = (value: string) =>
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);

  // Empty and full mean the same thing - no narrowing - because that is what
  // the server does with an empty list. Showing "hiçbiri" for an empty
  // selection promised zero results and then returned everything.
  const all = selected.length === 0 || selected.length === options.length;

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={options.length === 0}
        aria-expanded={open}
        className="flex items-center gap-2 border border-line bg-white/[0.03] px-3 py-1.5 text-[13px] font-medium text-muted transition-colors hover:text-ink-2 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <span>{label}</span>
        <span className="tabular-nums text-muted-2">{all ? "tümü" : selected.length}</span>
        <ChevronDown size={14} strokeWidth={2} className="text-muted-2" />
      </button>

      {open && (
        <div className="absolute top-full left-0 z-30 mt-1 max-h-72 w-60 overflow-y-auto border border-line bg-bg-alt shadow-2xl">
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <button
              type="button"
              onClick={() => onChange(options.map((o) => o.value))}
              className="text-[11px] font-medium text-muted transition-colors hover:text-ink"
            >
              Tümünü seç
            </button>
            <button
              type="button"
              onClick={() => onChange([])}
              className="text-[11px] font-medium text-muted transition-colors hover:text-ink"
            >
              Filtreyi kaldır
            </button>
          </div>
          {options.map((option) => {
            const active = selected.includes(option.value);
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => toggle(option.value)}
                className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-white/5"
              >
                <span
                  className={`flex size-4 shrink-0 items-center justify-center border ${
                    active ? "border-line-strong bg-white/10" : "border-line"
                  }`}
                >
                  {active && <Check size={11} strokeWidth={3} className="text-ink" />}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink-2">{option.label}</span>
                <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-2">
                  {option.count}
                </span>
              </button>
            );
          })}
          {note && (
            <p className="border-t border-line px-3 py-2 text-[11px] leading-relaxed text-muted-2">
              {note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function FilterBar({
  meta,
  query,
  update,
  reset,
  touched,
  trailing,
}: {
  meta: Meta;
  query: Query;
  update: (patch: Partial<Query>) => void;
  reset: () => void;
  touched: boolean;
  /**
   * Dropped into the gap at the right end of this row, before the note.
   *
   * The row is `items-center`, so whatever goes here sets the row's height
   * and the controls centre themselves against it rather than sitting on its
   * top edge.
   */
  trailing?: ReactNode;
}) {
  const chips: { key: string; label: string; clear: () => void }[] = [];
  if (query.q) {
    chips.push({ key: "q", label: `arama: "${query.q}"`, clear: () => update({ q: "" }) });
  }
  // A narrowed multi-select gets a chip; a full one does not, because "all"
  // is not a filter anyone needs reminding of.
  const narrowed = (
    key: "sources" | "types" | "categories",
    label: string,
    options: Option[],
  ) => {
    if (query[key].length === 0 || query[key].length === options.length) return;
    const names = query[key]
      .map((value) => options.find((o) => o.value === value)?.label ?? value)
      .join(", ");
    chips.push({
      key,
      label: `${label}: ${names || "hiçbiri"}`,
      clear: () => update({ [key]: [] } as Partial<Query>),
    });
  };
  narrowed("sources", "Kaynak", meta.sources);
  narrowed("types", "Tip", meta.types);
  narrowed("categories", "Alan", meta.categories);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Dropdown
        label="Kaynak"
        options={meta.sources}
        selected={query.sources}
        onChange={(next) => update({ sources: next })}
      />
      <Dropdown
        label="Tip"
        options={meta.types}
        selected={query.types}
        onChange={(next) => update({ types: next })}
      />
      {/*
        The rule about unclassified rows used to be a sentence at the right end
        of this row. It is about this filter and nothing else, so it moved
        inside it - which is both where someone would look for it and the
        224px the cards needed to fit on one line.
      */}
      <Dropdown
        label="Alan"
        options={meta.categories}
        selected={query.categories}
        onChange={(next) => update({ categories: next })}
        note="Sınıflandırılmamış ilanlar bu filtreden bağımsız olarak her zaman gösterilir."
      />

      <div className="mx-1 h-5 w-px bg-line" />

      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={chip.clear}
          className="flex items-center gap-1.5 border border-line bg-white/[0.02] px-2 py-1 text-[11px] font-medium text-muted transition-colors hover:text-ink"
        >
          <span className="max-w-56 truncate">{chip.label}</span>
          <X size={11} strokeWidth={2.5} className="shrink-0" />
        </button>
      ))}

      {touched && (
        <button
          type="button"
          onClick={reset}
          className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-medium text-muted-2 transition-colors hover:text-ink"
        >
          <RotateCcw size={11} strokeWidth={2.5} />
          Varsayılana dön
        </button>
      )}

      {trailing && <div className="ml-auto">{trailing}</div>}
    </div>
  );
}
