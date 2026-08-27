import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { PageProps } from "../lib/shared";
import type { RangeKey, Source } from "../lib/types";
import { RANGE_DESCRIPTIONS, fmtDateTime, fmtNumber, fmtRelative } from "../lib/format";
import { PageHeader } from "../components/PageHeader";
import { RangeToggle } from "../components/RangeToggle";
import { Panel } from "../components/Panel";
import { RankedList, type Row } from "../components/RankedList";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { EmptyState, ErrorState, SkeletonBlock, SkeletonRows } from "../components/States";

/**
 * Per-site health, and the one page where the reference's amber/red tiering
 * means what it meant there.
 *
 * A source having fewer postings than another is not a fault - the boards are
 * different sizes. A source that has stopped producing IS one, and it is the
 * failure this project actually hits: docs/sites/ is largely a record of
 * Indeed's spider going quiet for three days because a TLS fingerprint, an
 * exit address and a session have to be right at the same time. So the
 * threshold is on staleness, not volume.
 */
const STALE_WARN_HOURS = 36;
const STALE_BAD_HOURS = 96;

function tone(source: Source): "accent" | "warn" | "bad" {
  if (source.stale_hours === null) return "bad";
  if (source.stale_hours >= STALE_BAD_HOURS) return "bad";
  if (source.stale_hours >= STALE_WARN_HOURS) return "warn";
  return "accent";
}

function StaleBadge({ source }: { source: Source }) {
  const t = tone(source);
  if (t === "accent") return <Badge tone="neutral">çalışıyor</Badge>;
  if (t === "warn") return <Badge tone="warn">yavaşladı</Badge>;
  return <Badge tone="bad">durmuş olabilir</Badge>;
}

const COLUMNS: Column<Source>[] = [
  {
    key: "site",
    header: "Kaynak",
    render: (row) => <span className="font-mono text-xs text-ink-3">{row.label}</span>,
  },
  {
    key: "status",
    header: "Durum",
    width: "1%",
    render: (row) => <StaleBadge source={row} />,
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
    key: "today",
    header: "Bugün",
    width: "1%",
    render: (row) => (
      <span className="font-mono text-xs tabular-nums text-muted">{fmtNumber(row.today)}</span>
    ),
  },
  {
    key: "companies",
    header: "Şirket",
    width: "1%",
    render: (row) => (
      <span className="font-mono text-xs tabular-nums text-muted">{fmtNumber(row.companies)}</span>
    ),
  },
  {
    key: "last",
    header: "Son ilan",
    align: "right",
    width: "1%",
    render: (row) => (
      <span
        className="font-mono text-xs whitespace-nowrap text-muted-2"
        title={row.last_seen ? fmtDateTime(row.last_seen) : undefined}
      >
        {fmtRelative(row.last_seen)}
      </span>
    ),
  },
];

export function SourcesPage({ meta, query, update }: PageProps) {
  const sources = useQuery({
    queryKey: ["sources", query],
    queryFn: () => api.sources(query),
    enabled: Boolean(meta),
  });

  const rows = sources.data ?? [];
  const max = Math.max(...rows.map((r) => r.count), 1);
  const ranked: Row[] = rows.map((row) => ({
    key: row.site,
    label: row.label,
    value: fmtNumber(row.count),
    fraction: row.count / max,
    tone: tone(row),
  }));

  const failing = rows.filter((row) => tone(row) !== "accent").length;

  return (
    <>
      <PageHeader
        title="Kaynak Siteleri"
        tone={failing > 0 ? "warn" : "ok"}
        status={
          rows.length === 0
            ? "Kaynak yok"
            : failing > 0
              ? `${failing} kaynak beklenenden uzun süredir ilan getirmedi`
              : `${rows.length} kaynağın hepsi ilan getiriyor · ${RANGE_DESCRIPTIONS[query.range]}`
        }
      >
        <RangeToggle value={query.range} onChange={(next: RangeKey) => update({ range: next })} />
      </PageHeader>

      <p className="max-w-3xl text-[13px] leading-relaxed text-muted-2">
        Kaynak filtresi bu sayfada bilerek uygulanmaz: filtreyle gizlenmiş bir kaynak, tam da
        durduğunu görmek isteyeceğiniz kaynaktır.
      </p>

      {sources.isError ? (
        <ErrorState error={sources.error} />
      ) : (
        <>
          <Panel title="Kaynak Dağılımı" className="flex flex-col">
            {sources.isPending ? (
              <SkeletonBlock className="h-48" />
            ) : (
              <RankedList rows={ranked} empty="Kaynak yok." />
            )}
          </Panel>

          <Panel flush title="Kaynak Sağlığı">
            {sources.isPending ? (
              <SkeletonRows rows={3} />
            ) : rows.length === 0 ? (
              <EmptyState
                title="Henüz veri yok"
                detail="Scraper'ın ilk çalışmasını bekleyin; tamamlandığında bu sayfa otomatik dolar."
              />
            ) : (
              <DataTable columns={COLUMNS} rows={rows} rowKey={(row) => row.site} />
            )}
          </Panel>
        </>
      )}
    </>
  );
}
