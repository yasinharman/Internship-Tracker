import { AlertTriangle, DatabaseZap, Inbox } from "lucide-react";
import { ApiError } from "../lib/api";
import { JOB_GRID } from "./JobCard";

/**
 * Loading, empty and error, kept together because the board must have an
 * honest answer for all three. Streamlit's version had exactly one of these -
 * "Henüz veri yok" - and showed a stack trace for everything else.
 */

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="animate-pulse space-y-3 p-6">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="h-4 bg-white/[0.04]" style={{ width: `${95 - index * 7}%` }} />
      ))}
    </div>
  );
}

/**
 * The card grid's loading state. Shaped like JobCard - logo tile, two lines
 * of company, two of title - because a skeleton that is not the shape of what
 * follows it makes the page jump when the data lands.
 */
export function SkeletonCards({ cards = 6 }: { cards?: number }) {
  return (
    <div className={JOB_GRID}>
      {Array.from({ length: cards }).map((_, index) => (
        <div key={index} className="animate-pulse border border-line bg-white/[0.01] p-4">
          <div className="flex gap-3">
            <div className="size-14 shrink-0 bg-white/[0.06]" />
            <div className="flex-1 space-y-2 pt-1.5">
              <div className="h-3 w-2/3 bg-white/[0.05]" />
              <div className="h-2.5 w-1/2 bg-white/[0.03]" />
            </div>
          </div>
          <div className="mt-4 space-y-2">
            <div className="h-3 w-full bg-white/[0.04]" />
            <div className="h-3 w-4/5 bg-white/[0.04]" />
          </div>
          <div className="mt-5 h-4 w-24 bg-white/[0.03]" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonBlock({ className = "h-[286px]" }: { className?: string }) {
  return <div className={`animate-pulse bg-white/[0.03] ${className}`} />;
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <Inbox size={24} strokeWidth={1.5} className="text-muted-2" />
      <p className="text-sm font-medium text-ink">{title}</p>
      {detail && <p className="max-w-md text-[13px] text-muted">{detail}</p>}
    </div>
  );
}

/**
 * 503 means the database is not answering and the `detail` the server sent is
 * written to be read by a person - it names .env, Coolify and the url format.
 * Showing it verbatim is the whole point; replacing it with a generic message
 * would throw away the only thing that says how to fix the deployment.
 */
export function ErrorState({ error }: { error: unknown }) {
  const isApi = error instanceof ApiError;
  const unreachable = isApi && error.status === 503;
  const message = isApi
    ? error.message
    : "Sunucuya ulaşılamadı. API çalışıyor mu?";

  return (
    <div className="flex flex-col items-center gap-3 border border-amber-500/20 bg-amber-500/5 px-6 py-12 text-center">
      {unreachable ? (
        <DatabaseZap size={24} strokeWidth={1.5} className="text-warn" />
      ) : (
        <AlertTriangle size={24} strokeWidth={1.5} className="text-warn" />
      )}
      <p className="text-sm font-medium text-ink">
        {unreachable ? "Veritabanına ulaşılamıyor" : "Veri alınamadı"}
      </p>
      <p className="max-w-xl text-[13px] leading-relaxed text-muted">{message}</p>
    </div>
  );
}
