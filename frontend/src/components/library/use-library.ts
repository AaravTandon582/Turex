"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  isProcessing,
  papers,
  type LibraryStats,
  type PaperQuery,
  type PaperSummary,
} from "@/lib/papers";

const PAGE_SIZE = 24;
const POLL_INTERVAL_MS = 1500;

interface LibraryState {
  items: PaperSummary[];
  total: number;
  stats: LibraryStats | null;
  loading: boolean;
  error: string | null;
}

/**
 * Loads a page of the library and keeps it current.
 *
 * While any paper on screen is still being read, the list re-fetches on a short interval so
 * progress bars advance and a finished paper becomes clickable without a manual refresh.
 * Polling stops as soon as nothing is in flight — an idle library makes no requests.
 */
export function useLibrary(query: PaperQuery) {
  const [state, setState] = useState<LibraryState>({
    items: [],
    total: 0,
    stats: null,
    loading: true,
    error: null,
  });

  // Serialised so the effect depends on the query's value, not its identity.
  const queryKey = JSON.stringify(query);
  // Guards against a slow earlier request resolving after a newer one and overwriting it.
  const requestId = useRef(0);

  const load = useCallback(
    async ({ silent = false }: { silent?: boolean } = {}) => {
      const id = ++requestId.current;
      if (!silent) setState((current) => ({ ...current, loading: true, error: null }));

      try {
        const [page, stats] = await Promise.all([
          papers.list({ ...query, limit: query.limit ?? PAGE_SIZE }),
          papers.stats(),
        ]);
        if (id !== requestId.current) return;
        setState({
          items: page.items,
          total: page.total,
          stats,
          loading: false,
          error: null,
        });
      } catch (caught) {
        if (id !== requestId.current) return;
        setState((current) => ({
          ...current,
          loading: false,
          error:
            caught instanceof ApiError
              ? caught.message
              : "Atlas couldn't load your library. Try again.",
        }));
      }
    },
    // `query` is captured through queryKey; depending on the object itself would re-create
    // this callback on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryKey],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const anyProcessing = state.items.some(isProcessing);

  useEffect(() => {
    if (!anyProcessing) return;
    const timer = setInterval(() => void load({ silent: true }), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [anyProcessing, load]);

  return {
    ...state,
    pageSize: query.limit ?? PAGE_SIZE,
    reload: load,
  };
}
