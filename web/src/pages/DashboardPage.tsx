import { Link } from "react-router-dom";
import { useEffect, useRef } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Building2, Clock, ExternalLink } from "lucide-react";
import { api } from "../lib/api";
import type { PageProps } from "../lib/shared";
import { RANGE_DESCRIPTIONS, fmtDateTime, fmtNumber, fmtRelative, sourceTone } from "../lib/format";
import type { Job, RangeKey } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import { RangeToggle } from "../components/RangeToggle";
import { FilterBar } from "../components/FilterBar";
import { Panel } from "../components/Panel";
import { StatCard } from "../components/StatCard";
import { RankedList, type Row } from "../components/RankedList";
import { DataTable, type Column } from "../components/DataTable";
import { CategoryBadge } from "../components/Badge";
import { EmptyState, ErrorState, SkeletonBlock, SkeletonRows } from "../components/States";
import { DailyFlowChart } from "../components/DailyFlowChart";

const COLUMNS: Column<Job>[] = [
  {
    key: "title",
    header: "Başlık",
    render: (row) => (
      <a
        href={row.url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-ink-3 underline decoration-white/15 underline-offset-2 transition-colors hover:text-ink hover:decoration-white/60"
      >
        {row.job_title}
      </a>
    ),
  },
  {
    key: "company",
    header: "Şirket",
    render: (row) => <span className="text-xs text-muted">{row.company ?? "—"}</span>,
  },
  {
    key: "category",
    header: "Alan",
    width: "1%",
    render: (row) => (
      <CategoryBadge
        category={row.job_category}
        label={row.category_label}
        reason={row.category_reason}
      />
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
  // The title has always been a link, but nothing said so - it rendered as
  // plain text with only a hover underline, so the way out to the actual
  // posting was invisible until you happened to mouse over it. This is the
  // affordance; the underline on the title is the reminder.
  {
    key: "open",
    header: "",
    align: "right",
    width: "1%",
    render: (row) => (
      <a
        href={row.url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`${row.job_title} ilanını yeni sekmede aç`}
        className="inline-flex items-center gap-1.5 border border-line bg-white/[0.02] px-2.5 py-1 text-[11px] font-medium whitespace-nowrap text-muted transition-colors hover:border-line-strong hover:bg-white/[0.06] hover:text-ink"
      >
        İlana git
        <ExternalLink size={11} strokeWidth={2} />
      </a>
    ),
  },
];

// Big enough that the first screenful never needs a second request, small
// enough that a filter change is not a half-megabyte of JSON.
const BOARD_PAGE_SIZE = 50;

export function DashboardPage({ meta, query, update, reset, touched }: PageProps) {
  const stats = useQuery({
    queryKey: ["stats", query],
    queryFn: () => api.stats(query),
    enabled: Boolean(meta),
  });
  // Every posting the filter matches, fetched a page at a time as the box is
  // scrolled. Eight rows was a preview of a list you then had to go and find;
  // this is the list. Paging rather than one big request because "all" has no
  // ceiling - a year of crawling is thousands of rows, and the API caps a
  // single response at 500 anyway.
  const jobs = useInfiniteQuery({
    queryKey: ["jobs", query, "board"],
    queryFn: ({ pageParam }) => api.jobs(query, BOARD_PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const loaded = last.offset + last.rows.length;
      return loaded < last.total ? loaded : undefined;
    },
    enabled: Boolean(meta),
  });

  const rows = jobs.data?.pages.flatMap((page) => page.rows) ?? [];
  const totalJobs = jobs.data?.pages[0]?.total ?? 0;

  // The sentinel sits below the last row; when it comes into view inside the
  // scroll box, the next page is requested. rootMargin buys a screenful of
  // warning so the rows are already there by the time they are scrolled to.
  const scrollBox = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = jobs;

  useEffect(() => {
    const target = sentinel.current;
    if (!target || !hasNextPage) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isFetchingNextPage) fetchNextPage();
      },
      { root: scrollBox.current, rootMargin: "300px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const kpis = stats.data?.kpis;
  const unclassified = kpis?.unclassified ?? 0;

  const sourceRows: Row[] = (() => {
    const rows = stats.data?.sources ?? [];
    const max = Math.max(...rows.map((r) => r.count), 1);
    return rows.map((row) => ({
      key: row.site,
      label: row.label,
      value: fmtNumber(row.count),
      fraction: row.count / max,
    }));
  })();

  // The database being empty and the current filter matching nothing are
  // different problems with different fixes, so they get different messages.
  // Streamlit only ever said "Henüz veri yok", which sent you to check the
  // scraper when the real answer was a filter you had set two clicks earlier.
  const databaseEmpty = meta?.total === 0;

  return (
    <>
      <PageHeader
        title="Güncel İlanlar"
        tone={databaseEmpty ? "idle" : unclassified > 0 ? "warn" : "ok"}
        status={
          databaseEmpty
            ? "Veritabanı boş"
            : `${meta?.sources.length ?? 0} kaynak · ${RANGE_DESCRIPTIONS[query.range]} · son ilan ${fmtRelative(meta?.last_crawl_at ?? null)}`
        }
      >
        <RangeToggle value={query.range} onChange={(next: RangeKey) => update({ range: next })} />
      </PageHeader>

      {/*
        The stat strip sits between the range toggle in the header above and
        the filters below - both of them change these numbers, so the numbers
        belong between the two controls that drive them rather than under both.
      */}
      {!databaseEmpty && !stats.isError && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Toplam İlan" icon={Activity} value={kpis?.total ?? 0} delta={kpis?.total_delta} />
            <StatCard label="Bugün Eklenen" icon={Clock} value={kpis?.today ?? 0} />
            <StatCard
              label="Farklı Şirket"
              icon={Building2}
              value={kpis?.companies ?? 0}
              delta={kpis?.companies_delta}
            />
            <StatCard
              label="Sınıflandırılmamış"
              icon={AlertTriangle}
              value={unclassified}
              warn={unclassified > 0}
              hint={
                unclassified > 0
                  ? "Sınıflandırıcı bu ilanlara henüz bakmadı. Filtreden bağımsız gösteriliyorlar - LLM adımı başarısız olsa bile pano boş kalmasın diye."
                  : "Tüm ilanlar sınıflandırıldı."
              }
            />
          </div>
      )}

      {meta && !databaseEmpty && (
        <FilterBar meta={meta} query={query} update={update} reset={reset} touched={touched} />
      )}

      {databaseEmpty ? (
        <Panel>
          <EmptyState
            title="Henüz veri yok"
            detail="Scraper'ın ilk çalışmasını bekleyin; tamamlandığında bu sayfa otomatik dolar."
          />
        </Panel>
      ) : stats.isError ? (
        <ErrorState error={stats.error} />
      ) : (
        <>

          <Panel
            flush
            title="Son İlanlar"
            action={
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs tabular-nums text-muted-2">
                  {fmtNumber(rows.length)} / {fmtNumber(totalJobs)}
                </span>
                <Link
                  to="/ilanlar"
                  className="text-xs font-medium text-muted transition-colors hover:text-ink"
                >
                  Tüm ilanlar →
                </Link>
              </div>
            }
          >
            {jobs.isPending ? (
              <SkeletonRows rows={8} />
            ) : jobs.isError ? (
              <ErrorState error={jobs.error} />
            ) : (
              // A fixed-height box rather than a table that grows without
              // limit: the chart and the source split still have to be
              // reachable by scrolling the page, and a thousand rows between
              // them and the top would put them out of reach entirely.
              <DataTable
                stickyHeader
                maxHeight="34rem"
                scrollRef={scrollBox}
                columns={COLUMNS}
                rows={rows}
                rowKey={(row) => row.id}
                empty="Bu filtreye uyan ilan yok. Filtreleri genişletmeyi deneyin."
                footer={
                  <>
                    <div ref={sentinel} />
                    {jobs.isFetchingNextPage && (
                      <p className="py-3 text-center text-[11px] text-muted-2">yükleniyor...</p>
                    )}
                    {!jobs.hasNextPage && rows.length > BOARD_PAGE_SIZE && (
                      <p className="py-3 text-center text-[11px] text-muted-3">listenin sonu</p>
                    )}
                  </>
                }
              />
            )}
          </Panel>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Panel
              title="Günlük İlan Akışı"
              className="flex h-[380px] flex-col lg:col-span-2"
              action={
                stats.data?.series_truncated ? (
                  <span className="text-[11px] text-muted-2">son 90 gün</span>
                ) : undefined
              }
            >
              <div className="relative h-full min-h-0 w-full flex-1">
                {stats.isPending ? <SkeletonBlock /> : stats.data && <DailyFlowChart stats={stats.data} />}
              </div>
            </Panel>

            <Panel title="Kaynak Dağılımı" className="flex flex-col">
              {stats.isPending ? (
                <SkeletonBlock className="h-48" />
              ) : (
                <RankedList rows={sourceRows} empty="Bu filtreye uyan ilan yok." />
              )}
            </Panel>
          </div>

        </>
      )}
    </>
  );
}
