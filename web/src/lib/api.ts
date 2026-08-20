import type { CompanyPage, JobPage, Meta, Source, Stats, Watchlist } from "./types";

/**
 * The server answers 503 with a `detail` that is written to be shown to a
 * person - a missing DATABASE_URL names .env and Coolify, an unreachable
 * database says so plainly. Carrying that text through instead of replacing
 * it with "bir hata oluştu" is the whole reason this class exists.
 */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
  }

  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let detail = `Sunucu ${response.status} döndü.`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // A non-JSON error body (a proxy's HTML 502 page, say) leaves the
      // status-code message above, which is still more useful than throwing
      // a parse error over the top of the real failure.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export interface Query {
  range: string;
  sources: string[];
  types: string[];
  categories: string[];
  q: string;
}

/** Multi-selects travel comma-joined so a copied URL stays readable. */
function toParams(query: Query) {
  return {
    range: query.range,
    sources: query.sources.join(","),
    types: query.types.join(","),
    categories: query.categories.join(","),
    q: query.q,
  };
}

export const api = {
  meta: () => get<Meta>("/api/meta"),
  stats: (query: Query) => get<Stats>("/api/stats", toParams(query)),
  jobs: (query: Query, limit = 50, offset = 0, sort = "created_at", direction = "desc") =>
    get<JobPage>("/api/jobs", { ...toParams(query), limit, offset, sort, direction }),
  companies: (query: Query, limit = 50, offset = 0) =>
    get<CompanyPage>("/api/companies", { ...toParams(query), limit, offset }),
  sources: (query: Query) => get<Source[]>("/api/sources", toParams(query)),
  watchlist: (query: Query) => get<Watchlist>("/api/watchlist", toParams(query)),
};
