// Everything the board prints goes through here. Turkish formatting is not
// cosmetic: 1.204 and 1,204 mean different numbers on either side of the
// locale, and the reference's tables are full of both.

const TZ = "Europe/Istanbul";

const number = new Intl.NumberFormat("tr-TR");
const dateTime = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: TZ,
});
const dayMonth = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", timeZone: TZ });

/**
 * created_at arrives as a naive UTC timestamp (the scraper writes
 * datetime.utcnow()), so it has no trailing Z and Date would otherwise read
 * it as local time - three hours off, every row.
 */
export function parseUtc(value: string): Date {
  return new Date(/[Zz]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`);
}

export const fmtNumber = (value: number) => number.format(value);

/** 142.4M / 12,4B for the KPI numbers, which have a fixed width to live in. */
export function fmtCompact(value: number): string {
  if (Math.abs(value) < 10_000) return number.format(value);
  if (Math.abs(value) < 1_000_000) return `${number.format(Math.round(value / 100) / 10)}B`;
  return `${number.format(Math.round(value / 100_000) / 10)}M`;
}

export const fmtDateTime = (value: string) => dateTime.format(parseUtc(value));
export const fmtDayMonth = (value: string) => dayMonth.format(parseUtc(value));

/**
 * "3 dk önce" / "2 sa önce" / "5 g önce".
 *
 * Intl.RelativeTimeFormat would give "3 dakika önce", which is correct
 * Turkish but too wide for the right-aligned mono column the reference puts
 * timestamps in.
 */
export function fmtRelative(value: string | null): string {
  if (!value) return "—";
  const seconds = (Date.now() - parseUtc(value).getTime()) / 1000;
  if (seconds < 60) return "az önce";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} dk önce`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} sa önce`;
  if (seconds < 2_592_000) return `${Math.floor(seconds / 86_400)} g önce`;
  return fmtDayMonth(value);
}

export const RANGE_LABELS: Record<string, string> = {
  "24h": "24S",
  "7d": "7G",
  "30d": "30G",
  all: "Tümü",
};

export const RANGE_DESCRIPTIONS: Record<string, string> = {
  "24h": "son 24 saat",
  "7d": "son 7 gün",
  "30d": "son 30 gün",
  all: "tüm zamanlar",
};

/**
 * A stable colour per source, so the same site reads the same way in the
 * table, the ranked list and the sources page. The reference tints its METHOD
 * column this way (GET/POST/DELETE each have their own), and source_site is
 * the column that plays that role here.
 */
export function sourceTone(site: string): string {
  switch (site) {
    case "kariyer.net":
      return "text-accent-soft";
    case "techcareer.net":
      return "text-ink-3";
    default:
      return "text-muted";
  }
}
