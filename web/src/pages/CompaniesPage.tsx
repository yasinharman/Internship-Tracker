import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { api } from "../lib/api";
import type { PageProps } from "../lib/shared";
import type { Company, RangeKey } from "../lib/types";
import { RANGE_DESCRIPTIONS, fmtDateTime, fmtNumber, fmtRelative } from "../lib/format";
import { PageHeader } from "../components/PageHeader";
import { RangeToggle } from "../components/RangeToggle";
import { FilterBar } from "../components/FilterBar";
import { Panel } from "../components/Panel";
import { RankedList, type Row } from "../components/RankedList";
import { DataTable, type Column } from "../components/DataTable";
import { EmptyState, ErrorState, SkeletonBlock, SkeletonRows } from "../components/States";

const COLUMNS: Column<Company>[] = [
  {
    key: "company",
    header: "Şirket",
    render: (row) => (
      <span className="flex items-center gap-2 text-xs text-ink-3">
        {row.company}
        {row.watched && (
          <Bell
            size={11}
            strokeWidth={2}
            className="shrink-0 text-warn"
            aria-label="İzleme listesinde"
          />
        )}
      </span>
    ),
  },
  {
    key: "count",
    header: "İlan",
    width: "1%",
    render: (row) => (
      <span className="font-mono text-xs tabular-nums text-accent-soft">{fmtNumber(row.count)}</span>
    ),
  },
  {
    key: "sources",
    header: "Kaynaklar",
    render: (row) => <span className="font-mono text-xs text-muted">{row.sources.join(" · ")}</span>,
  },
  {
    key: "last",
    header: "Son ilan",
    align: "right",
    width: "1%",
    render: (row) => (
      <span className="font-mono text-xs whitespace-nowrap text-muted-2" title={fmtDateTime(row.last_seen)}>
        {fmtRelative(row.last_seen)}
      </span>
    ),
  },
];

export function CompaniesPage({ meta, query, update, reset, touched }: PageProps) {
  const companies = useQuery({
    queryKey: ["companies", query],
    queryFn: () => api.companies(query, 200),
    enabled: Boolean(meta),
  });

  const rows = companies.data?.rows ?? [];
  const top: Row[] = (() => {
    const max = Math.max(...rows.map((r) => r.count), 1);
    return rows.slice(0, 8).map((row) => ({
      key: row.company,
      label: row.company,
      value: fmtNumber(row.count),
      fraction: row.count / max,
      // The watchlist is the one thing on this page worth being flagged: it
      // is what triggers a Telegram ping, so seeing which companies are on it
      // next to how much they post is the reason to look.
      tone: row.watched ? ("warn" as const) : ("accent" as const),
    }));
  })();

  return (
    <>
      <PageHeader
        title="Şirketler"
        status={`${fmtNumber(companies.data?.total ?? 0)} şirket · ${RANGE_DESCRIPTIONS[query.range]}`}
      >
        <RangeToggle value={query.range} onChange={(next: RangeKey) => update({ range: next })} />
      </PageHeader>

      {meta && <FilterBar meta={meta} query={query} update={update} reset={reset} touched={touched} />}

      {companies.isError ? (
        <ErrorState error={companies.error} />
      ) : (
        <>
          <Panel title="En Çok İlan Veren Şirketler" className="flex flex-col">
            {companies.isPending ? (
              <SkeletonBlock className="h-64" />
            ) : (
              <RankedList rows={top} empty="Bu filtreye uyan şirket yok." />
            )}
          </Panel>

          <Panel flush title="Tüm Şirketler">
            {companies.isPending ? (
              <SkeletonRows rows={10} />
            ) : rows.length === 0 ? (
              <EmptyState
                title={meta?.total === 0 ? "Henüz veri yok" : "Bu filtreye uyan şirket yok"}
                detail="Zaman aralığını genişletin veya filtreleri temizleyin."
              />
            ) : (
              <DataTable columns={COLUMNS} rows={rows} rowKey={(row) => row.company} />
            )}
          </Panel>
        </>
      )}
    </>
  );
}
