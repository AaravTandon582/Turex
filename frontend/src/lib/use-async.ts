"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export type AsyncStatus = "loading" | "error" | "ready";

/**
 * Values a dependency may be. Deliberately narrow: the dependency list is joined into a key,
 * so an object would compare by identity and re-fire the request on every render. Every call
 * site passes ids and flags, which this covers.
 */
export type Dependency = string | number | boolean | null | undefined;

export interface AsyncResult<T> {
  status: AsyncStatus;
  data: T | null;
  error: string | null;
  /** Re-run the request. Used by the retry button, and after a mutation. */
  reload: () => void;
  /** Replace the data locally, for an update that should not cost a round trip. */
  set: (next: T) => void;
}

/**
 * Load data for a screen, and keep the four possible states apart.
 *
 * The four are *loading*, *failed*, *empty*, and *loaded*, and the reason this exists is that
 * the first three are easy to conflate. Before it, a page whose request failed rendered its
 * empty state — so a server that was down told the reader "you have no projects yet". That is
 * a lie the product cannot afford, given everything else about Atlas rests on not saying
 * things that are not true.
 *
 * `loading` and `error` are tracked here. *Empty* stays with the caller, because only the
 * caller knows whether an empty result means "nothing yet" (a bare list) or "nothing matched"
 * (a search).
 */
export function useAsync<T>(load: () => Promise<T>, deps: readonly Dependency[]): AsyncResult<T> {
  const [state, setState] = useState<{ status: AsyncStatus; data: T | null; error: string | null }>({
    status: "loading",
    data: null,
    error: null,
  });
  const [attempt, setAttempt] = useState(0);

  // The latest-ref pattern. `load` is a new closure on every render, so depending on it
  // directly would re-fire the request every render; the dependency list the caller passes is
  // the contract for when to re-run.
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  const key = deps.join(" ");

  useEffect(() => {
    let active = true;
    setState((current) => ({ ...current, status: "loading", error: null }));

    void loadRef.current().then(
      (data) => {
        if (active) setState({ status: "ready", data, error: null });
      },
      (caught: unknown) => {
        if (active) setState({ status: "error", data: null, error: describe(caught) });
      },
    );

    // Discards a response arriving after the inputs changed or the component went away, so a
    // slow first request cannot overwrite a fast second one.
    return () => {
      active = false;
    };
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((count) => count + 1), []);
  const set = useCallback((next: T) => setState({ status: "ready", data: next, error: null }), []);

  return { ...state, reload, set };
}

/** Turn anything thrown into a sentence worth showing someone. */
export function describe(caught: unknown): string {
  // The API writes `message` for a person, so it is always safe to display and usually better
  // than anything generic invented here.
  if (caught instanceof ApiError) return caught.message;

  // A genuine transport failure. `fetch` rejects with a TypeError and no detail — deliberately,
  // so a page cannot probe the network — so this is the one case where a guess is all there is.
  if (caught instanceof TypeError && /fetch|network|load failed/i.test(caught.message)) {
    return "Atlas couldn't reach the server. Check your connection and try again.";
  }

  // Anything else is a real failure with a real message, and saying "check your connection"
  // over the top of it sends people to look at their wifi. That happened: a Python runtime
  // that failed to start reported itself as a network problem and gave nothing to act on.
  if (caught instanceof Error && caught.message.trim()) return caught.message;

  return "Atlas couldn't complete that. Try again.";
}
