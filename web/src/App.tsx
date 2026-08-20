import { useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./lib/api";
import { useFilters } from "./hooks/useFilters";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { ErrorState } from "./components/States";
import { DashboardPage } from "./pages/DashboardPage";
import { JobsPage } from "./pages/JobsPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { SourcesPage } from "./pages/SourcesPage";
import { WatchlistPage } from "./pages/WatchlistPage";

// Breadcrumb reads group / page, mirroring the sidebar's two groups, so the
// crumb says where you are rather than repeating the page name twice.
const PAGES: Record<string, { group: string; title: string }> = {
  "/": { group: "Genel", title: "Panel" },
  "/ilanlar": { group: "Genel", title: "İlanlar" },
  "/sirketler": { group: "Genel", title: "Şirketler" },
  "/siteler": { group: "Kaynaklar", title: "Siteler" },
  "/izleme": { group: "Kaynaklar", title: "İzleme Listesi" },
};

/**
 * The shell.
 *
 * The reference is a mockup embedded in a landing page, so its shell is a
 * fixed 850px-tall bordered card centred at 1400px. A real app wants the
 * viewport: sidebar fixed, main column scrolling, no outer border. Below
 * 1024px the reference simply hides its sidebar with nothing to open it -
 * here the same component slides in as a drawer.
 */
export default function App() {
  const location = useLocation();
  const client = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);

  // One /api/meta for the whole app: it supplies the filter options, the
  // defaults every page starts from, and the "last posting" line in the
  // sidebar. Refetching it per page would make those defaults flicker.
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });
  const { query, update, reset, touched } = useFilters(meta.data);
  const fetching = useIsFetching() > 0;

  const page = PAGES[location.pathname] ?? PAGES["/"];
  const shared = { meta: meta.data, query, update, reset, touched };

  return (
    <div className="relative z-10 flex h-full">
      <aside className="hidden w-64 shrink-0 lg:block">
        <Sidebar lastCrawlAt={meta.data?.last_crawl_at ?? null} />
      </aside>

      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setMenuOpen(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 w-64">
            <Sidebar
              lastCrawlAt={meta.data?.last_crawl_at ?? null}
              onNavigate={() => setMenuOpen(false)}
            />
          </div>
        </div>
      )}

      <main className="flex min-w-0 flex-1 flex-col bg-bg-alt">
        <Topbar
          group={page.group}
          page={page.title}
          search={query.q}
          onSearch={(value) => update({ q: value })}
          onRefresh={() => client.invalidateQueries()}
          refreshing={fetching}
          unclassified={meta.data?.unclassified_count ?? 0}
          onOpenMenu={() => setMenuOpen(true)}
        />

        <div className="hide-scrollbar flex-1 space-y-6 overflow-y-auto p-6 lg:p-8">
          {meta.isError ? (
            <ErrorState error={meta.error} />
          ) : (
            <Routes>
              <Route path="/" element={<DashboardPage {...shared} />} />
              <Route path="/ilanlar" element={<JobsPage {...shared} />} />
              <Route path="/sirketler" element={<CompaniesPage {...shared} />} />
              <Route path="/siteler" element={<SourcesPage {...shared} />} />
              <Route path="/izleme" element={<WatchlistPage {...shared} />} />
              <Route path="*" element={<DashboardPage {...shared} />} />
            </Routes>
          )}
        </div>
      </main>
    </div>
  );
}
