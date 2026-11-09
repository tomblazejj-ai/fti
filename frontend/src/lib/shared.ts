import { useEffect, useState } from "react";

export interface Shared<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** One shared poll per resource, however many components read it (the top bar, the dashboard and a detail page
 * read the same answer instead of asking the backend three times). */
export function sharedPoll<T>(load: () => Promise<T>, ms: number): () => Shared<T> {
  type S = { data?: T; error?: Error; loading: boolean };
  let state: S = { loading: true };
  let gen = 0;
  let timer: number | undefined;
  const listeners = new Set<(s: S) => void>();
  const emit = () => listeners.forEach((l) => l(state));
  async function run() {
    const g = gen;
    try {
      const data = await load();
      if (g !== gen) return;
      state = { data, loading: false };
    } catch (e) {
      if (g !== gen) return;
      state = { data: state.data, error: e instanceof Error ? e : new Error(String(e)), loading: false };
    }
    emit();
  }
  const reload = () => void run();
  return function useShared(): Shared<T> {
    const [s, setS] = useState<S>(state);
    useEffect(() => {
      listeners.add(setS);
      if (listeners.size === 1) {
        void run();
        timer = window.setInterval(run, ms);
      } else {
        setS(state);
      }
      return () => {
        listeners.delete(setS);
        if (listeners.size === 0) {
          window.clearInterval(timer);
          gen += 1;
          state = { loading: true }; // the next mount starts fresh (also keeps tests isolated)
        }
      };
    }, []);
    return { data: s.data, error: s.error, loading: s.loading, reload };
  };
}
