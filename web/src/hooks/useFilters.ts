import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Meta, RangeKey } from "../lib/types";
import type { Query } from "../lib/api";

const RANGES: RangeKey[] = ["24h", "7d", "30d", "all"];

/**
 * Filter state lives in the URL, not in React state.
 *
 * Streamlit's widgets kept theirs in a session, so a filtered board could not
 * be sent to anyone - the link opened on the defaults. Here every selection is
 * a query parameter, which makes the browser's back button work as an undo
 * and a copied address reproduce exactly what was on screen.
 *
 * `meta` supplies the defaults, so an untouched URL shows Internship +
 * Part-Time in it + general_program - the same opening view app.py had.
 */
export function useFilters(meta: Meta | undefined) {
  const [params, setParams] = useSearchParams();

  const query: Query = useMemo(() => {
    const list = (key: string, fallback: string[]) => {
      const raw = params.get(key);
      if (raw === null) return fallback;
      return raw ? raw.split(",").filter(Boolean) : [];
    };
    const range = params.get("range");
    return {
      range: RANGES.includes(range as RangeKey) ? (range as RangeKey) : (meta?.defaults.range ?? "7d"),
      sources: list("sources", []),
      types: list("types", meta?.defaults.types ?? []),
      categories: list("categories", meta?.defaults.categories ?? []),
      q: params.get("q") ?? "",
    };
  }, [params, meta]);

  const update = useCallback(
    (patch: Partial<Query>) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(patch)) {
            // An explicitly empty multi-select must survive a reload as
            // "nothing selected", which is different from "not set" (the
            // defaults). "" in the URL is how that difference is written down.
            if (Array.isArray(value)) next.set(key, value.join(","));
            else if (value) next.set(key, String(value));
            else next.delete(key);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const reset = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams]);

  const touched = useMemo(
    () => ["range", "sources", "types", "categories", "q"].some((key) => params.has(key)),
    [params],
  );

  return { query, update, reset, touched };
}
