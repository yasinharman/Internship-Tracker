import { AlertTriangle, DatabaseZap, Inbox } from "lucide-react";
import { ApiError } from "../lib/api";

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
