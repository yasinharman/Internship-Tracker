import { useEffect, useRef } from "react";
import { Menu, RotateCw, Search } from "lucide-react";

/**
 * The reference's topbar: breadcrumb left, 256px search and a round button
 * right. The button was a notification bell; here it refetches, because on a
 * board fed by a scheduled crawl "is this current?" is the question that
 * actually gets asked. Its dot means there are postings the classifier has
 * not looked at yet - the same signal Streamlit put in a sidebar warning.
 */

interface Props {
  group: string;
  page: string;
  search: string;
  onSearch: (value: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
  unclassified: number;
  onOpenMenu: () => void;
}

export function Topbar({
  group,
  page,
  search,
  onSearch,
  onRefresh,
  refreshing,
  unclassified,
  onOpenMenu,
}: Props) {
  const input = useRef<HTMLInputElement>(null);

  // "/" focuses the search, as the reference's kbd hint promises. Ignored
  // while typing somewhere else, otherwise the shortcut would eat the slash
  // in a URL someone is pasting into another field.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        input.current?.focus();
      }
      if (event.key === "Escape" && document.activeElement === input.current) {
        input.current?.blur();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between border-b border-line bg-bg-alt/90 px-6 backdrop-blur-xl lg:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onOpenMenu}
          aria-label="Menüyü aç"
          className="flex size-8 items-center justify-center border border-line bg-white/[0.02] text-muted transition-colors hover:bg-white/[0.05] lg:hidden"
        >
          <Menu size={14} strokeWidth={2} />
        </button>
        <div className="flex min-w-0 items-center gap-2 text-[13px] text-muted">
          <span className="hidden sm:inline">{group}</span>
          <span className="hidden sm:inline">/</span>
          <span className="truncate font-medium text-ink">{page}</span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="group hidden w-64 items-center border border-line bg-white/[0.03] px-3 py-1.5 transition-colors focus-within:border-line-strong sm:flex">
          <Search size={14} strokeWidth={2} className="mr-2 shrink-0 text-muted-2" />
          <input
            ref={input}
            type="text"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Başlık veya şirket ara..."
            className="w-full border-none bg-transparent text-[13px] text-ink-2 outline-none placeholder:text-muted-3"
          />
          <span className="ml-2 shrink-0 border border-line px-1.5 py-0.5 text-[10px] font-medium text-muted-2">
            /
          </span>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          title={
            unclassified > 0
              ? `${unclassified} ilan henüz sınıflandırılmadı`
              : "Verileri yenile"
          }
          aria-label="Verileri yenile"
          className="relative flex size-8 items-center justify-center border border-line bg-white/[0.02] transition-colors hover:bg-white/[0.05]"
        >
          {unclassified > 0 && (
            <span className="absolute -top-px -right-px size-2 border-2 border-bg-alt bg-warn" />
          )}
          <RotateCw
            size={14}
            strokeWidth={2}
            className={`text-muted ${refreshing ? "animate-spin" : ""}`}
          />
        </button>
      </div>
    </header>
  );
}
