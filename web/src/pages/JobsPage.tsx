import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api } from "../lib/api";
import type { PageProps } from "../lib/shared";
import type { Job, RangeKey } from "../lib/types";
import { RANGE_DESCRIPTIONS, fmtDateTime, fmtNumber, fmtRelative, sourceTone } from "../lib/format";
import { PageHeader } from "../components/PageHeader";
import { RangeToggle } from "../components/RangeToggle";
import { FilterBar } from "../components/FilterBar";
import { Panel } from "../components/Panel";
import { DataTable, type Column } from "../components/DataTable";
import { CategoryBadge, ClosedMark } from "../components/Badge";
import { EmptyState, ErrorState, SkeletonRows } from "../components/States";

const PAGE_SIZE = 50;

/**
 * The full table, with the two columns the board has no room for: location,
 * and the classifier's reasoning in full.
 *
 * category_reason gets its own column here rather than a tooltip because
 * this is the page you come to when a verdict looks wrong, and a reason you
 * have to hover to read is a reason nobody audits.
 */
const COLUMNS: Column<Job>[] = [
  {
    key: "source",
    header: "Kaynak",
    width: "1%",
    render: (row) => (
      <span className={`font-mono text-xs whitespace-nowrap ${sourceTone(row.source_site)}`}>
        {row.source_label}
      </span>
    ),
  },
  {
    key: "title",
    header: "Başlık",
    width: "30%",
    minWidth: "12.5rem",
    render: (row) => (
      <span className="inline-flex flex-wrap items-start gap-x-2 gap-y-1">
        <a
          href={row.url}
          target="_blank"
          rel="noopener noreferrer"
          title={row.closed_at ? "İlan yayından kalkmış - sayfa hâlâ açılabilir" : undefined}
          className={`group inline-flex items-start gap-1.5 text-xs transition-colors hover:text-ink ${
            row.closed_at ? "text-muted-2" : "text-ink-3"
          }`}
        >
          <span className="underline-offset-2 group-hover:underline">{row.job_title}</span>
          <ExternalLink size={11} strokeWidth={2} className="mt-0.5 shrink-0 text-muted-3" />
        </a>
        <ClosedMark closedAt={row.closed_at} when={fmtRelative(row.closed_at)} />
      </span>
    ),
  },
  {
    key: "company",
    header: "Şirket",
    width: "14%",
    minWidth: "9rem",
    render: (row) => <span className="text-xs text-muted">{row.company ?? "—"}</span>,
  },
  {
    key: "location",
    header: "Konum",
    width: "10%",
    render: (row) => <span className="text-xs text-muted">{row.location ?? "—"}</span>,
  },
  {
    key: "category",
    header: "Alan",
    width: "1%",
    render: (row) => (
      <CategoryBadge category={row.job_category} label={row.category_label} reason={row.category_reason} />
    ),
  },
  {
    key: "reason",
    header: "Neden",
    width: "22%",
    render: (row) => (
      <span className="block max-w-xs text-xs leading-relaxed text-muted-2">
        {row.category_reason ?? "—"}
      </span>
    ),
  },
  {
    key: "type",
    header: "Tip",
    width: "1%",
    render: (row) => (
      <span className="font-mono text-xs whitespace-nowrap text-muted">{row.job_type_label ?? "—"}</span>
    ),
  },
  {
    key: "date",
    header: "Tarih",
    align: "right",
    width: "1%",
    render: (row) => (
      <span className="font-mono text-xs whitespace-nowrap text-muted-2" title={fmtDateTime(row.created_at)}>
        {fmtRelative(row.created_at)}
      </span>
    ),
  },
];

export function JobsPage({ meta, query, update, reset, touched }: PageProps) {
  const [page, setPage] = useState(0);

  const jobs = useQuery({
    queryKey: ["jobs", query, page],
    queryFn: () => api.jobs(query, PAGE_SIZE, page * PAGE_SIZE),
    enabled: Boolean(meta),
    // Without this the table blanks to a skeleton on every page turn, which
    // reads as a reload rather than a step through the same list.
    placeholderData: keepPreviousData,
  });

  const total = jobs.data?.total ?? 0;
  const lastPage = Math.max(Math.ceil(total / PAGE_SIZE) - 1, 0);
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min((page + 1) * PAGE_SIZE, total);

  // A filter change can leave you past the end of a shorter result set.
  if (page > lastPage && !jobs.isPending) setPage(0);

  return (
    <>
      <PageHeader
        title="İlanlar"
        status={`${fmtNumber(total)} ilan · ${RANGE_DESCRIPTIONS[query.range]}`}
      >
        <RangeToggle value={query.range} onChange={(next: RangeKey) => update({ range: next })} />
      </PageHeader>

      {meta && <FilterBar meta={meta} query={query} update={update} reset={reset} touched={touched} />}

      <Panel
        flush
        title="Tüm İlanlar"
        action={
          total > PAGE_SIZE ? (
            <div className="flex items-center gap-3">
              <span className="font-mono text-xs tabular-nums text-muted-2">
                {fmtNumber(from)}–{fmtNumber(to)} / {fmtNumber(total)}
              </span>
              <div className="flex border border-line bg-white/[0.03] p-0.5">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(p - 1, 0))}
                  disabled={page === 0}
                  className="px-3 py-1 text-[13px] font-medium text-muted transition-colors hover:text-ink disabled:opacity-30 disabled:hover:text-muted"
                >
                  ←
                </button>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(p + 1, lastPage))}
                  disabled={page >= lastPage}
                  className="px-3 py-1 text-[13px] font-medium text-muted transition-colors hover:text-ink disabled:opacity-30 disabled:hover:text-muted"
                >
                  →
                </button>
              </div>
            </div>
          ) : undefined
        }
      >
        {jobs.isPending ? (
          <SkeletonRows rows={10} />
        ) : jobs.isError ? (
          <ErrorState error={jobs.error} />
        ) : total === 0 ? (
          <EmptyState
            title={meta?.total === 0 ? "Henüz veri yok" : "Bu filtreye uyan ilan yok"}
            detail={
              meta?.total === 0
                ? "Scraper'ın ilk çalışmasını bekleyin; tamamlandığında bu sayfa otomatik dolar."
                : "Zaman aralığını genişletin veya filtreleri temizleyin."
            }
          />
        ) : (
          <DataTable dense columns={COLUMNS} rows={jobs.data?.rows ?? []} rowKey={(row) => row.id} />
        )}
      </Panel>
    </>
  );
}
