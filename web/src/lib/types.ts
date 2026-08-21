// Mirrors api/schemas.py. Kept by hand rather than generated: there are nine
// shapes and a generator would be one more build step to keep working.

export type RangeKey = "24h" | "7d" | "30d" | "all";

export interface Option {
  value: string;
  label: string;
  count: number;
}

export interface Meta {
  sources: Option[];
  types: Option[];
  categories: Option[];
  defaults: { range: RangeKey; types: string[]; categories: string[] };
  unclassified_count: number;
  /** Postings a check found gone from their source site - the number on the
   *  "Kapananlar" toggle, so the button says what it would reveal. */
  closed_count: number;
  last_crawl_at: string | null;
  total: number;
}

export interface Delta {
  value: number;
  percent: number | null;
  direction: "up" | "down" | "flat";
  label: string;
}

export interface Stats {
  kpis: {
    total: number;
    today: number;
    companies: number;
    unclassified: number;
    total_delta: Delta | null;
    companies_delta: Delta | null;
  };
  daily: { date: string; count: number; companies: number }[];
  sources: { site: string; label: string; count: number }[];
  range: RangeKey;
  series_truncated: boolean;
}

export interface Job {
  id: number;
  job_title: string;
  company: string | null;
  location: string | null;
  url: string;
  source_site: string;
  source_label: string;
  job_type: string | null;
  job_type_label: string | null;
  job_category: string | null;
  category_label: string | null;
  category_reason: string | null;
  created_at: string;
  /** null = still on offer. Only ever non-null when closed=1 was asked for. */
  closed_at: string | null;
  checked_at: string | null;
  last_seen_at: string | null;
}

export interface JobPage {
  rows: Job[];
  total: number;
  limit: number;
  offset: number;
}

export interface Company {
  company: string;
  count: number;
  sources: string[];
  last_seen: string;
  watched: boolean;
}

export interface CompanyPage {
  rows: Company[];
  total: number;
  limit: number;
  offset: number;
}

export interface Source {
  site: string;
  label: string;
  count: number;
  today: number;
  companies: number;
  last_seen: string | null;
  stale_hours: number | null;
}

export interface Watchlist {
  entries: { name: string; count: number; last_seen: string | null; notified: number }[];
  configured: boolean;
}
