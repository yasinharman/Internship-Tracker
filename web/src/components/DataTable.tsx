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
  stickyHeader = false,
  maxHeight,
  scrollRef,
  footer,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  empty?: string;
  dense?: boolean;
  /**
   * For a table inside a scrolling box: the column headers stay put while the
   * rows move under them. Without it a long list loses its labels after the
   * first few rows and the mono columns become unreadable - "1 g önce" and
   * "kariyer.net" only mean something under a heading.
   *
   * The header needs an opaque background or the rows show through it. bg-alt
   * is the main column's colour; the panel sits on it under a 1% white wash,
   * a difference of two values out of 255.
   */
  stickyHeader?: boolean;
  /**
   * Turns the table's own wrapper into a vertical scroll box.
   *
   * It has to be this element rather than one wrapped around the component:
   * `overflow-x: auto` already makes this a scroll container on both axes, so
   * a sticky header sticks to it, not to any outer box. Put the height limit
   * outside and the header scrolls away with the rows - which is exactly what
   * it did before this argument existed.
   */
  maxHeight?: string;
  /** The scrolling element, for an IntersectionObserver that needs it as root. */
  scrollRef?: React.RefObject<HTMLDivElement | null>;
  /** Rendered inside the scroll box, under the last row. */
  footer?: ReactNode;
}) {
  const pad = dense ? "px-4 py-3.5" : "px-6 py-4";
  const headCell = stickyHeader ? "sticky top-0 z-10 bg-bg-alt" : "";

  if (rows.length === 0) {
    return <p className="px-6 py-12 text-center text-[13px] text-muted-2">{empty}</p>;
  }

  return (
    <div
      ref={scrollRef}
      style={maxHeight ? { maxHeight } : undefined}
      className={`overflow-x-auto ${maxHeight ? "overflow-y-auto" : ""}`}
    >
      {/*
        border-separate, not border-collapse.

        In the collapsed model a border belongs to the TABLE rather than to the
        cell that declares it, so it does not travel with a `position: sticky`
        header: measured in Chrome, the rule under a stuck heading simply is
        not painted, and the rows scroll up to touch the labels with nothing
        between them. Separating the borders puts each one back on its own
        cell, where sticky can carry it.

        The cost is that <tr> borders are ignored in this model, so the row
        dividers moved down onto the cells. Backgrounds on a <tr> still paint,
        which is why the row hover did not have to move.
      */}
      <table className="w-full border-separate border-spacing-0 text-left">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                style={{ width: column.width, minWidth: column.minWidth }}
                className={`border-b border-line ${pad} ${headCell} text-xs font-medium tracking-wider whitespace-nowrap text-muted-2 uppercase ${
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
            // Backgrounds on a <tr> still paint in the separated model, so the
            // row hover stays here; only the divider had to move to the cells.
            <tr key={rowKey(row)} className="transition-colors hover:bg-white/[0.02]">
              {columns.map((column) => (
                <td
                  key={column.key}
                  style={{ minWidth: column.minWidth }}
                  className={`${pad} align-top ${
                    index === rows.length - 1 ? "" : "border-b border-line-soft"
                  } ${column.align === "right" ? "text-right" : ""}`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {footer}
    </div>
  );
}
