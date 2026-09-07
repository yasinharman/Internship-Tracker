import { NavLink } from "react-router-dom";
import { Activity, Building2, ChevronRight, Clock, Database, LayoutDashboard, List } from "lucide-react";
import { fmtNumber, fmtRelative } from "../lib/format";
import type { Stats } from "../lib/types";
import { RankedList, type Row } from "./RankedList";
import { StatCard } from "./StatCard";
import { SkeletonBlock } from "./States";

/**
 * The reference's sidebar: a 64px brand block, two labelled nav groups, and a
 * profile block pinned to the bottom. Same skeleton, real information -
 * "Vercel Eng Team / Production" becomes the database and when it last
 * received a posting, which is the thing you actually want to know is true
 * before trusting the numbers on the right.
 */

/*
  One group now. "Siteler" and "İzleme Listesi" were taken out of the nav;
  their routes in App.tsx still answer, so a bookmark or a typed url still
  opens them - they simply are not offered here any more.
*/
const GROUPS = [
  {
    label: "Genel",
    items: [
      { to: "/", label: "Panel", icon: LayoutDashboard, end: true },
      { to: "/ilanlar", label: "İlanlar", icon: List, end: false },
      { to: "/sirketler", label: "Şirketler", icon: Building2, end: false },
    ],
  },
];

interface Props {
  lastCrawlAt: string | null;
  /**
   * The source split, which used to be a panel on the board.
   *
   * It follows the active filter like everything else, so it belongs to the
   * whole app rather than to one page - which is the argument for it being
   * here: the sidebar is the one part of the shell that every page shares,
   * and "where did these numbers come from" is a question you ask on all of
   * them. It is also the one block on this board that never grows: four
   * sources, four bars, whatever the filter says.
   */
  sources?: Stats["sources"];
  /**
   * The three KPIs, which were a row across the top of the board.
   *
   * Same argument as the split below them: they answer to the filter, not to
   * the page, and they are the numbers you want in view while reading any of
   * the pages rather than only the one they used to live on. Moving them here
   * also gives the board's whole top band back to the chart.
   */
  kpis?: Stats["kpis"];
  /** Only to label the first card: with "Kapananlar" on it stops being the
   *  count of what is still open. Same reasoning the board used. */
  closed?: boolean;
  statsPending?: boolean;
  onNavigate?: () => void;
}

export function Sidebar({
  lastCrawlAt,
  sources,
  kpis,
  closed = false,
  statsPending = false,
  onNavigate,
}: Props) {
  const max = Math.max(...(sources ?? []).map((source) => source.count), 1);
  const ranked: Row[] = (sources ?? []).map((source) => ({
    key: source.site,
    label: source.label,
    value: fmtNumber(source.count),
    fraction: source.count / max,
  }));

  return (
    <div className="flex h-full flex-col border-r border-line bg-bg">
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-line px-6">
        <Activity size={20} strokeWidth={2} className="text-white" />
        <span className="text-sm font-medium tracking-tight text-white">Internship Tracker</span>
      </div>

      {/*
        The nav and the source split scroll together, in one box.

        They used to be two: the nav took the slack and scrolled by itself,
        which meant the split below it could push a nav item out of sight -
        and the nav's scrollbar is hidden, so nothing on screen said the item
        was still there. Measured, the full column needs a 664px window, which
        a 1366x768 laptop does not have.

        One scroller fixes both ends of that. The nav is at the top of it, so
        it is never the part that goes; the split is below and reaches the
        bottom of the column by mt-auto when there is room, or is scrolled to
        when there is not. Nothing is hidden at any height.
      */}
      <div className="hide-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto">
        <nav className="space-y-6 px-4 py-6">
          {GROUPS.map((group) => (
            <div key={group.label}>
              <p className="mb-2 px-3 text-xs font-medium text-muted-2">{group.label}</p>
              <div className="space-y-0.5">
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      [
                        "flex items-center gap-3 px-3 py-2 transition-colors",
                        isActive
                          ? "bg-white/10 text-ink"
                          : "text-muted hover:bg-white/5 hover:text-ink",
                      ].join(" ")
                    }
                  >
                    <item.icon size={16} strokeWidth={2} />
                    <span className="text-[13px] font-medium">{item.label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/*
          my-auto rather than mt-auto: two auto margins split the free space
          instead of piling all of it above, so the cards sit midway between
          the nav and the split below while the split stays at the foot of the
          column. Both resolve to nothing when the box overflows, which is
          what keeps the nav above them whole at every window height.

          No border-t any more. A rule belongs at the edge of a section; this
          block no longer has one - it floats in the middle of the space, and
          the line drifted with it. The gap divides them, and each card draws
          its own border anyway.
        */}
        <div className="my-auto shrink-0 space-y-2 p-4">
          {statsPending ? (
            <SkeletonBlock className="h-[248px]" />
          ) : (
            <>
              <StatCard
                label={closed ? "Aktif + Kapalı" : "Aktif İlan"}
                hint={
                  closed
                    ? "Kaynağında yayından kalkmış ilanlar da sayıya dahil"
                    : "Kaynağında hâlâ yayında olan ilanlar"
                }
                icon={Activity}
                value={kpis?.total ?? 0}
                delta={kpis?.total_delta}
              />
              <StatCard label="Bugün Eklenen" icon={Clock} value={kpis?.today ?? 0} />
              <StatCard
                label="Farklı Şirket"
                icon={Building2}
                value={kpis?.companies ?? 0}
                delta={kpis?.companies_delta}
              />
            </>
          )}
        </div>

        <div className="shrink-0 border-t border-line px-7 py-4">
          <p className="mb-3 text-xs font-medium text-muted-2">Kaynak Dağılımı</p>
          {statsPending ? (
            <SkeletonBlock className="h-24" />
          ) : (
            <RankedList compact rows={ranked} empty="Bu filtreye uyan ilan yok." />
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-line p-4">
        <div className="flex items-center gap-3 p-2">
          <div className="flex size-8 shrink-0 items-center justify-center border border-line bg-white/[0.02]">
            <Database size={14} strokeWidth={2} className="text-muted" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium text-ink-2">Veritabanı</p>
            <p className="truncate text-[11px] text-muted-2">
              {lastCrawlAt ? `Son ilan: ${fmtRelative(lastCrawlAt)}` : "Henüz ilan yok"}
            </p>
          </div>
          <ChevronRight size={14} strokeWidth={2} className="shrink-0 text-muted-2" />
        </div>
      </div>
    </div>
  );
}
