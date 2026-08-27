import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { PageProps } from "../lib/shared";
import type { RangeKey, Watchlist } from "../lib/types";
import { RANGE_DESCRIPTIONS, fmtDateTime, fmtNumber, fmtRelative } from "../lib/format";
import { PageHeader } from "../components/PageHeader";
import { RangeToggle } from "../components/RangeToggle";
import { Panel } from "../components/Panel";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { EmptyState, ErrorState, SkeletonRows } from "../components/States";

type Entry = Watchlist["entries"][number];

/**
 * config/watched_companies.yml, with what each entry actually caught.
 *
 * "Bildirilen" is notified_at being set, which means pipeline/notify_watchlist.py
 * handed the posting to the Hermes webhook successfully. A watched company
 * with postings but nothing notified is the visible symptom of the webhook
 * being wrong or unreachable - it is not otherwise visible anywhere.
 */
const COLUMNS: Column<Entry>[] = [
  {
    key: "name",
    header: "Şirket",
    render: (row) => <span className="text-xs text-ink-3">{row.name}</span>,
  },
  {
    key: "count",
    header: "Eşleşen ilan",
    width: "1%",
    render: (row) => (
      <span
        className={`font-mono text-xs tabular-nums ${row.count > 0 ? "text-accent-soft" : "text-muted-3"}`}
      >
        {fmtNumber(row.count)}
      </span>
    ),
  },
  {
    key: "notified",
    header: "Bildirilen",
    width: "1%",
    render: (row) => {
      if (row.count === 0) return <span className="font-mono text-xs text-muted-3">—</span>;
      if (row.notified === 0) {
        return <Badge tone="warn">hiçbiri bildirilmedi</Badge>;
      }
      return (
        <span className="font-mono text-xs tabular-nums text-muted">
          {fmtNumber(row.notified)} / {fmtNumber(row.count)}
        </span>
      );
    },
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

export function WatchlistPage({ meta, query, update }: PageProps) {
  const watchlist = useQuery({
    queryKey: ["watchlist", query],
    queryFn: () => api.watchlist(query),
    enabled: Boolean(meta),
  });

  const entries = watchlist.data?.entries ?? [];
  const matched = entries.filter((entry) => entry.count > 0).length;

  return (
    <>
      <PageHeader
        title="İzleme Listesi"
        tone={watchlist.data?.configured === false ? "warn" : matched > 0 ? "ok" : "idle"}
        status={
          watchlist.data?.configured === false
            ? "config/watched_companies.yml boş veya yok"
            : `${entries.length} şirket izleniyor · ${matched} tanesi ${RANGE_DESCRIPTIONS[query.range]} içinde ilan verdi`
        }
      >
        <RangeToggle value={query.range} onChange={(next: RangeKey) => update({ range: next })} />
      </PageHeader>

      <p className="max-w-3xl text-[13px] leading-relaxed text-muted-2">
        Bu liste <span className="font-mono text-muted">config/watched_companies.yml</span> dosyasından okunur.
        Eşleşen ilanlar her taramadan sonra Hermes webhook'una gönderilir ve Telegram'a düşer.
        Listeyi değiştirmek için dosyayı düzenleyip yeniden deploy edin.
      </p>

      {watchlist.isError ? (
        <ErrorState error={watchlist.error} />
      ) : (
        <Panel flush title="İzlenen Şirketler">
          {watchlist.isPending ? (
            <SkeletonRows rows={6} />
          ) : entries.length === 0 ? (
            <EmptyState
              title="İzlenen şirket yok"
              detail="config/watched_companies.yml içindeki 'companies' listesine şirket adı ekleyin. Eşleşme büyük/küçük harf duyarsız ve kısmi yapılır."
            />
          ) : (
            <DataTable columns={COLUMNS} rows={entries} rowKey={(row) => row.name} />
          )}
        </Panel>
      )}
    </>
  );
}
