import { NavLink } from "react-router-dom";
import { Activity, Bell, Building2, ChevronRight, Database, Globe, LayoutDashboard, List } from "lucide-react";
import { fmtRelative } from "../lib/format";

/**
 * The reference's sidebar: a 64px brand block, two labelled nav groups, and a
 * profile block pinned to the bottom. Same skeleton, real information -
 * "Vercel Eng Team / Production" becomes the database and when it last
 * received a posting, which is the thing you actually want to know is true
 * before trusting the numbers on the right.
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
  {
    label: "Kaynaklar",
    items: [
      { to: "/siteler", label: "Siteler", icon: Globe, end: false },
      { to: "/izleme", label: "İzleme Listesi", icon: Bell, end: false },
    ],
  },
];

interface Props {
  lastCrawlAt: string | null;
  onNavigate?: () => void;
}

export function Sidebar({ lastCrawlAt, onNavigate }: Props) {
  return (
    <div className="flex h-full flex-col border-r border-line bg-bg">
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-line px-6">
        <Activity size={20} strokeWidth={2} className="text-white" />
        <span className="text-sm font-medium tracking-tight text-white">Internship Tracker</span>
      </div>

      <nav className="hide-scrollbar flex-1 space-y-6 overflow-y-auto px-4 py-6">
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
