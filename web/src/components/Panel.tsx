import type { ReactNode } from "react";

/**
 * The bordered surface every section on the board sits on. Two paddings in
 * the reference: 24px for a panel that holds a chart or a list, and zero for
 * one that holds a table (whose own cells carry the padding, so the row
 * dividers can run edge to edge).
 */
export function Panel({
  title,
  action,
  children,
  className = "",
  flush = false,
  dense = false,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
  /**
   * A third padding, for a panel short enough that the frame competes with
   * what is inside it. The compact chart is 180px tall: 24px of padding top
   * and bottom plus a heading holding 24px of its own margin leaves the canvas
   * less room than the box around it. 16px and 12px leave it most of them.
   */
  dense?: boolean;
}) {
  const pad = flush ? "" : dense ? "p-4" : "p-6";
  return (
    <section className={`border border-line bg-white/[0.01] ${pad} ${className}`}>
      {title && (
        <div
          className={
            flush
              ? "flex items-center justify-between border-b border-line p-6"
              : `flex items-center justify-between ${dense ? "mb-3" : "mb-6"}`
          }
        >
          <h2 className="text-sm font-medium text-ink">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
