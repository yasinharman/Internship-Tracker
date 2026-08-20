import type { Meta } from "./types";
import type { Query } from "./api";

/** What App hands every page: the one /api/meta and the URL-backed filters. */
export interface PageProps {
  meta: Meta | undefined;
  query: Query;
  update: (patch: Partial<Query>) => void;
  reset: () => void;
  touched: boolean;
}
