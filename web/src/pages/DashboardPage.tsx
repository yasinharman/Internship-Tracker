import { Link } from "react-router-dom";
import { useEffect, useRef } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { PageProps } from "../lib/shared";
import { RANGE_DESCRIPTIONS, fmtNumber, fmtRelative } from "../lib/format";
import type { RangeKey } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import { RangeToggle } from "../components/RangeToggle";
import { FilterBar } from "../components/FilterBar";
import { Panel } from "../components/Panel";
import { JobCard, JOB_GRID } from "../components/JobCard";
import { EmptyState, ErrorState, SkeletonBlock, SkeletonCards } from "../components/States";
import { DailyFlowChart } from "../components/DailyFlowChart";

// Big enough that the first screenful never needs a second request, small
// enough that a filter change is not a half-megabyte of JSON. Divisible by
// three, so a page never lands with a half-empty last row of cards.
const BOARD_PAGE_SIZE = 51;

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

  // The sentinel sits under the last card; when it comes into view the next
  // page is requested. rootMargin buys a screenful of warning so the cards
  // are already there by the time they are scrolled to.
  //
  // No root any more. The list used to scroll inside its own box and the
  // observer had to be told so; now it scrolls with the page, and the
  // viewport - the default - is the right frame to measure against.
  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = jobs;

  useEffect(() => {
    const target = sentinel.current;
    if (!target || !hasNextPage) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isFetchingNextPage) fetchNextPage();
      },
      { rootMargin: "300px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const kpis = stats.data?.kpis;
  const unclassified = kpis?.unclassified ?? 0;

  // The database being empty and the current filter matching nothing are
  // different problems with different fixes, so they get different messages.
  // Streamlit only ever said "Henüz veri yok", which sent you to check the
  // scraper when the real answer was a filter you had set two clicks earlier.
  const databaseEmpty = meta?.total === 0;

  // Defined once, placed twice: in the channel between the header's columns
  // where there is room for it, and as a plain row under the header where
  // there is not. Only one is ever displayed - the other is display:none, so
  // it is out of the accessibility tree too - because a grid cannot move
  // between two different parents with CSS alone.
  //
  // Three of them, in one row. The unclassified count is not among them any
  // more; the square on the status line still turns amber for it, and every
  // unclassified posting carries its own badge in the table.

  /*
    THE CHART SITS IN THE HEADER ROW, BETWEEN THE FILTERS AND THE RANGE
    ===================================================================
    It is the channel the KPI cards used to claim, and the argument for
    putting the chart in it is the same one that put them there: the row
    already reserves that width for something, and a chart is the only thing
    left on this page that is not a posting.

    Narrower than the full column on purpose - roughly 530px at 1600 against
    the 1280 it had - which is what the series can afford. It is a shape over
    time, not a table of values, and the y ticks carry the numbers for anyone
    who wants them.

    `dense`, not the Panel default: at this height 24px of padding on both
    sides plus a heading carrying 24px of margin leaves the canvas less room
    than the frame around it.
  */
  const chart = (
    <Panel
      dense
      title="Günlük İlan Akışı"
      className="flex h-full flex-col"
      action={
        stats.data?.series_truncated ? (
          <span className="text-[11px] text-muted-2">son 90 gün</span>
        ) : undefined
      }
    >
      <div className="relative h-full min-h-0 w-full flex-1">
        {stats.isPending ? (
          <SkeletonBlock className="h-full" />
        ) : (
          stats.data && <DailyFlowChart stats={stats.data} />
        )}
      </div>
    </Panel>
  );
  const showChart = !databaseEmpty && !stats.isError;

  return (
    <>
      {/*
        THREE COLUMNS AGAIN, AND THE CHART IS THE MIDDLE ONE
        ====================================================
        Grid rather than the flex row this was: a grid cell is a position the
        chart can be moved INTO at a breakpoint, so there is one canvas that
        changes place. Two flex children with a `hidden` between them would
        have meant two, mounted at once, drawing the same series twice.

        Below 1500px the grid collapses to one column and `order-last` drops
        the chart under the filters at full width, which is where it was
        before it moved up here.

        col-start pins the toggle to the third column instead of letting it
        auto-place: with an empty database the chart is not rendered at all,
        and without the pin the toggle would slide into the gap it left.
      */}
      {/* 34rem, measured: the filter row wants 529px for its four controls and
          the rule after them, and a 32rem cap wrapped "Kapananlar" onto a
          second line. The 32px come out of the chart, which has them. */}
      <div className="grid items-stretch gap-4 min-[1500px]:grid-cols-[minmax(0,34rem)_minmax(0,1fr)_auto]">
        <div className="flex min-w-0 flex-col gap-4">
          <PageHeader
            title="Güncel İlanlar"
            tone={databaseEmpty ? "idle" : unclassified > 0 ? "warn" : "ok"}
            status={
              databaseEmpty
                ? "Veritabanı boş"
                : `${meta?.sources.length ?? 0} kaynak · ${RANGE_DESCRIPTIONS[query.range]} · son ilan ${fmtRelative(meta?.last_crawl_at ?? null)}`
            }
          />
          {meta && !databaseEmpty && (
            <FilterBar
              meta={meta}
              query={query}
              update={update}
              reset={reset}
              touched={touched}
              showNote={false}
            />
          )}
        </div>

        {showChart && (
          <div className="order-last min-h-[180px] min-w-0 min-[1500px]:order-none min-[1500px]:col-start-2">
            {chart}
          </div>
        )}

        <div className="justify-self-end min-[1500px]:col-start-3">
          <RangeToggle value={query.range} onChange={(next: RangeKey) => update({ range: next })} />
        </div>
      </div>

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
          {/*
            THE SUMMARY MOVED ABOVE THE BOARD
            =================================
            The postings used to sit here in a 30.4rem scroll box, so that the
            chart and the source split underneath stayed reachable however
            long the list got. That box holds two rows of cards and a
            scrollbar, and nesting a scroller inside the page's own to show
            two rows is worse than either arrangement it compromises between.

            So the summary goes first and the board flows down the page below
            it. Nothing is buried by a list that has nothing under it, and the
            order now reads the way the page is used: how the crawl is doing,
            then what it found.
          */}
          {/* A bare heading rather than a Panel around the grid: every card
              draws its own hairline, and a frame full of frames adds a rule
              and 24px of padding without separating anything from anything.
              The empty and error states keep theirs - a single centred
              message does need something to sit in. */}
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-ink">Son İlanlar</h2>
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
          </div>

          {jobs.isPending ? (
            <SkeletonCards cards={9} />
          ) : jobs.isError ? (
            <ErrorState error={jobs.error} />
          ) : rows.length === 0 ? (
            <Panel>
              <EmptyState
                title="Bu filtreye uyan ilan yok"
                detail="Zaman aralığını genişletin veya filtreleri temizleyin."
              />
            </Panel>
          ) : (
            <>
              <div className={JOB_GRID}>
                {rows.map((job) => (
                  <JobCard key={job.id} job={job} />
                ))}
              </div>
              <div ref={sentinel} />
              {jobs.isFetchingNextPage && (
                <p className="text-center text-[11px] text-muted-2">yükleniyor...</p>
              )}
              {!jobs.hasNextPage && rows.length > BOARD_PAGE_SIZE && (
                <p className="text-center text-[11px] text-muted-3">listenin sonu</p>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
