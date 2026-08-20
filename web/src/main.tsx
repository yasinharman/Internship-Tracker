import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

/**
 * staleTime 60s is the descendant of Streamlit's @st.cache_data(ttl=600).
 * Ten minutes was too long to notice a finished crawl and there was no way to
 * ask for fresh data short of a reload; a minute plus the topbar's refresh
 * button covers both, and the crawl runs on a schedule measured in hours
 * anyway.
 *
 * retry: 1 because the errors worth showing here (no DATABASE_URL, database
 * unreachable) do not fix themselves on a second attempt - retrying three
 * times only delays the message that says what to go and fix.
 */
const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
