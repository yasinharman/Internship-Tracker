import { useState } from "react";

/**
 * The company's mark, and the thing every card is built around.
 *
 * Two states, one tile: the logo the crawl found, or the company's initials.
 * There used to be a third - a synthetic coloured shape derived from the
 * company name - which stood in while company_logo_url was not crawled yet.
 * It went the moment the column started arriving: with real logos on the page
 * a reader cannot tell an invented mark from a photographed one, and a board
 * that looks like data while being made up is worse than a grey monogram.
 *
 * THE TILE IS LIGHT ON PURPOSE. Job boards serve logos drawn for a white
 * page - dark ink, frequently no transparency - so on this board's #0f0f10 a
 * good third of them would render as an invisible square or a white box with
 * a hard edge. A near-white tile is the one background every logo out there
 * was designed to sit on. #e7e5e4 is the palette's existing light value
 * rather than a new colour, so the wall of tiles still belongs to the page.
 */

/** Turkish casing: locale-less toUpperCase turns "i" into "I", not "İ". */
function initials(company: string): string {
  const words = company
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return "—";
  const letters = words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[1][0];
  return letters.toLocaleUpperCase("tr-TR");
}

interface Props {
  company: string | null;
  /**
   * As the source site's CDN serves it. Null for a posting the crawl found no
   * logo for, and for every row crawled before the column existed - the scope
   * is the posting, not the employer, so the same company can have one here
   * and not on its neighbour.
   */
  logoUrl?: string | null;
  /** Tailwind size for the tile. */
  className?: string;
  /** Closed postings: still readable, visibly past. */
  dimmed?: boolean;
}

export function CompanyLogo({ company, logoUrl, className = "size-14", dimmed = false }: Props) {
  const [broken, setBroken] = useState(false);
  const name = company?.trim() ?? "";
  // bg-white, not the palette's #e7e5e4. Job boards bake a white background
  // into the asset itself - LinkedIn's company-logo_100_100 is a padded white
  // square - so a warm-grey tile put a visible second square inside the first
  // one, which reads as the logo not fitting its slot. On white the seam
  // disappears and a logo with real transparency still lands on the
  // background it was drawn for.
  const tile = `flex shrink-0 items-center justify-center overflow-hidden bg-white ${
    dimmed ? "opacity-40 saturate-50" : ""
  } ${className}`;

  if (logoUrl && !broken) {
    return (
      <div className={tile}>
        <img
          src={logoUrl}
          alt={name ? `${name} logosu` : "Şirket logosu"}
          loading="lazy"
          // These are hotlinked off the source site's CDN, some of which
          // refuse a request carrying a foreign origin as its referrer and
          // answer the same request without one. Measured 09.09.2026:
          // img-kariyer.mncdn.com does not care either way, but the header
          // costs nothing to withhold.
          referrerPolicy="no-referrer"
          // A 404, a hotlink block or a dead CDN falls through to the
          // initials rather than leaving a broken-image glyph in the grid.
          // This is also what absorbs a logo an employer has since replaced,
          // which is why the crawler is allowed to keep a url it cannot
          // re-confirm - see scraper/pipelines.py.
          onError={() => setBroken(true)}
          // 2px of breathing room, not 6. The assets already carry their
          // own margin - LinkedIn's company-logo_100_100 is a padded square -
          // so ours was being added on top of theirs and the mark sat small
          // in the middle of its tile. A wordmark still letterboxes top and
          // bottom: object-contain will not crop a logo to fill a square, and
          // cropping is the one thing a logo must never have done to it.
          className="size-full object-contain p-0.5"
        />
      </div>
    );
  }

  // The company name is printed next to this tile in every card, so the
  // monogram is decoration and says nothing a reader is not already told.
  return (
    <div className={`${tile} text-sm font-semibold tracking-tight text-[#57534e]`} aria-hidden>
      {name ? initials(name) : "—"}
    </div>
  );
}
