import type { ReactNode } from "react";

/**
 * The reference's "Recent API Anomalies" table, generalised: uppercase
 * tracked header, 24px/16px cells, hairline row dividers that stop before the
 * last row, and the whole thing inside its own horizontal scroller so a wide
 * table never makes the page scroll sideways.
 */

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  /** Held at its natural width; only used for the narrow mono columns. */
  width?: string;
  /**
   * A floor for the column, in CSS units.
   *
   * `width` alone is only a hint under `table-layout: auto` - the browser
   * still sizes columns from their content, so a column of long prose
   * (the classifier's reasoning) wins space from a column of short titles
   * and wraps the titles to three lines. A min-width is not a hint.
   */
  minWidth?: string;
  render: (row: T) => ReactNode;
}

/**
 * `dense` trades the reference's 24px cell padding for 16px.
 *
 * The reference table has five columns and 24px is right for them. The
 * postings table has eight, and 24px on both sides of each is nearly 400px
 * spent on whitespace - enough to push the date column off the side at a
 * normal desktop width, so every reader has to scroll to see it. Same table,
 * more columns, tighter gutters.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty = "Kayıt yok.",
  dense = false,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  empty?: string;
  dense?: boolean;
}) {
  const pad = dense ? "px-4 py-3.5" : "px-6 py-4";

  if (rows.length === 0) {
    return <p className="px-6 py-12 text-center text-[13px] text-muted-2">{empty}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                style={{ width: column.width, minWidth: column.minWidth }}
                className={`border-b border-line ${pad} text-xs font-medium tracking-wider whitespace-nowrap text-muted-2 uppercase ${
                  column.align === "right" ? "text-right" : ""
                }`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row)}
              className={`transition-colors hover:bg-white/[0.02] ${
                index === rows.length - 1 ? "" : "border-b border-line-soft"
              }`}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  style={{ minWidth: column.minWidth }}
                  className={`${pad} align-top ${column.align === "right" ? "text-right" : ""}`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
