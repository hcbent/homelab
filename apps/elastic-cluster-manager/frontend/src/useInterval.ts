import { useEffect, useRef } from "react";

export function useInterval(fn: () => void, seconds: number) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (seconds <= 0) return;
    const t = setInterval(() => saved.current(), seconds * 1000);
    return () => clearInterval(t);
  }, [seconds]);
}
