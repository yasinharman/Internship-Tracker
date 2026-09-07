import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { PageProps } from "../lib/shared";
import type { RangeKey } from "../lib/types";
import { RANGE_DESCRIPTIONS, fmtNumber } from "../lib/format";
import { PageHeader } from "../components/PageHeader";
import { RangeToggle } from "../components/RangeToggle";
import { FilterBar } from "../components/FilterBar";
import { Panel } from "../components/Panel";
import { JobCard, JOB_GRID } from "../components/JobCard";
import { EmptyState, ErrorState, SkeletonCards } from "../components/States";

const PAGE_SIZE = 51; // divisible by three, so the last row of the grid is full

/**
 * Every posting the filter matches, as cards rather than rows.
 *
 * The table this replaces showed the same six values in eight columns and
 * read as a database dump, which is what it was. The employer was a string in
 * the second column; here it is the mark at the top left of its own card, and
 * scanning the page is recognising logos rather than reading a column.
 *
 * Nothing was dropped in the move. Location and the classifier's reasoning -
 * the two columns this page had and the board did not - are both on the card.
 */
export function JobsPage({ meta, query, update, reset, touched }: PageProps) {
  const [page, setPage] = useState(0);

  const jobs = useQuery({
    queryKey: ["jobs", query, page],
    queryFn: () => api.jobs(query, PAGE_SIZE, page * PAGE_SIZE),
    enabled: Boolean(meta),
    // Without this the grid blanks to a skeleton on every page turn, which
    // reads as a reload rather than a step through the same list.
    placeholderData: keepPreviousData,
  });

  const total = jobs.data?.total ?? 0;
  const lastPage = Math.max(Math.ceil(total / PAGE_SIZE) - 1, 0);
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min((page + 1) * PAGE_SIZE, total);

  // A filter change can leave you past the end of a shorter result set.
  if (page > lastPage && !jobs.isPending) setPage(0);

  /**
   * Rendered twice: once beside the heading and once under the last row.
   *
   * The table had it in one place because fifty rows are one screenful and a
   * half; fifty cards are five or six, so a reader who has scrolled to the
   * end of a page has left the only control that turns it far behind them.
   */
  const pager =
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
    ) : null;

  return (
    <>
      <PageHeader
        title="İlanlar"
        status={`${fmtNumber(total)} ilan · ${RANGE_DESCRIPTIONS[query.range]}`}
      >
        <RangeToggle value={query.range} onChange={(next: RangeKey) => update({ range: next })} />
      </PageHeader>

      {meta && <FilterBar meta={meta} query={query} update={update} reset={reset} touched={touched} />}

      {/*
        A bare heading rather than a Panel around the grid. Every card already
        draws its own hairline border, and a panel around them is a frame full
        of frames - the outer one adds a rule and 24px of padding without
        separating anything from anything. The empty and error states keep
        theirs, because a single centred message does need something to sit in.
      */}
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-medium text-ink">Tüm İlanlar</h2>
        {pager}
      </div>

      {jobs.isPending ? (
        <SkeletonCards cards={9} />
      ) : jobs.isError ? (
        <ErrorState error={jobs.error} />
      ) : total === 0 ? (
        <Panel>
          <EmptyState
            title={meta?.total === 0 ? "Henüz veri yok" : "Bu filtreye uyan ilan yok"}
            detail={
              meta?.total === 0
                ? "Scraper'ın ilk çalışmasını bekleyin; tamamlandığında bu sayfa otomatik dolar."
                : "Zaman aralığını genişletin veya filtreleri temizleyin."
            }
          />
        </Panel>
      ) : (
        <>
          <div className={JOB_GRID}>
            {(jobs.data?.rows ?? []).map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>
          {pager && <div className="flex justify-end">{pager}</div>}
        </>
      )}
    </>
  );
}
