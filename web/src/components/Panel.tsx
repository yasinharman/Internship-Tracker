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
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`border border-line bg-white/[0.01] ${flush ? "" : "p-6"} ${className}`}>
      {title && (
        <div
          className={
            flush
              ? "flex items-center justify-between border-b border-line p-6"
              : "mb-6 flex items-center justify-between"
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
