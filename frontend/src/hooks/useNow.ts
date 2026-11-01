import { useEffect, useState } from "react";

/** Current time, ticking — for the live countdowns. */
export function useNow(ms = 15000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}
