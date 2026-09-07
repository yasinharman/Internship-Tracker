import { useState, type ReactNode } from "react";

/**
 * The company's mark, and the thing every card is built around.
 *
 * Three states, one tile:
 *   - a crawled logo url    -> the image itself
 *   - no url, filler on     -> a synthetic mark (preview only, see below)
 *   - no url, filler off    -> the company's initials
 *
 * THE TILE IS LIGHT ON PURPOSE. Job boards serve logos drawn for a white
 * page - dark ink, frequently no transparency - so on this board's #0f0f10 a
 * good third of them would render as an invisible square or a white box with
 * a hard edge. A near-white tile is the one background every logo out there
 * was designed to sit on. #e7e5e4 is the palette's existing light value
 * rather than a new colour, so the wall of tiles still belongs to the page.
 */

/**
 * PREVIEW SCAFFOLDING - DELETE THIS CONST AND ITS BRANCH BELOW
 * ===========================================================
 * Nothing has been crawled into company_logo_url yet. With this off, every
 * card on the board shows the same grey monogram and the layout cannot be
 * judged at all - which is not a question about the design, only about the
 * data not being there.
 *
 * On, each company gets a deterministic mark: a shape and a colour derived
 * from its name, so the same company is the same mark on every card and the
 * grid reads the way it will read once the spiders fill the column.
 *
 * It stands in for a photograph, it is NOT the fallback. The fallback is the
 * monogram below, which is what a company with no logo on its source page
 * gets for real.
 */
export const LOGO_FILLER = true;

/** Stable per name, so a company keeps its mark across pages and reloads. */
function hash(value: string): number {
  let h = 0;
  for (let index = 0; index < value.length; index += 1) {
    h = (h * 31 + value.charCodeAt(index)) | 0;
  }
  return Math.abs(h);
}

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

// Brand-shaped colours rather than the board's neutrals: the point of the
// filler is to stand in for a real logo, and real logos are not grey.
const FILLS = [
  "#f97316", "#e11d48", "#2563eb", "#7c3aed",
  "#0891b2", "#16a34a", "#ca8a04", "#db2777",
];

const MARKS: ReactNode[] = [
  <circle cx="12" cy="12" r="7.5" />,
  <rect x="4.5" y="4.5" width="15" height="15" />,
  <path d="M12 3.5 20.5 20.5 3.5 20.5Z" />,
  <path d="M12 3 21 12 12 21 3 12Z" />,
  <path d="M4 20 12 4 20 20 12 14.5Z" />,
  <g>
    <circle cx="9.5" cy="12" r="6.5" />
    <circle cx="14.5" cy="12" r="6.5" fillOpacity="0.55" />
  </g>,
  <path d="M4 6h16v4H4zM4 14h10v4H4z" />,
  <path d="M12 3l9 5.5v11L12 21 3 19.5v-11z" />,
];

interface Props {
  company: string | null;
  /** As the source site's DOM had it. Absent on every row crawled before the
   *  spiders started reading it, which today is all of them. */
  logoUrl?: string | null;
  /** Tailwind size for the tile. */
  className?: string;
  /** Closed postings: still readable, visibly past. */
  dimmed?: boolean;
}

export function CompanyLogo({ company, logoUrl, className = "size-14", dimmed = false }: Props) {
  const [broken, setBroken] = useState(false);
  const name = company?.trim() ?? "";
  const tile = `flex shrink-0 items-center justify-center overflow-hidden bg-accent ${
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
          // answer the same request without one.
          referrerPolicy="no-referrer"
          // A 404, a hotlink block or a dead CDN falls through to the
          // monogram rather than leaving a broken-image glyph in the grid.
          onError={() => setBroken(true)}
          className="size-full object-contain p-1.5"
        />
      </div>
    );
  }

  if (LOGO_FILLER && name) {
    const seed = hash(name);
    return (
      <div className={tile} aria-hidden>
        <svg viewBox="0 0 24 24" className="size-full p-2.5" fill={FILLS[seed % FILLS.length]}>
          {MARKS[seed % MARKS.length]}
        </svg>
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
