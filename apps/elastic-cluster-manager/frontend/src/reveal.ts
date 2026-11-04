import { useEffect } from "react";

/**
 * Scroll reveals for leaf groups marked data-reveal="rise|slide|media".
 * CSS keeps every element visible by default. Only elements still below the viewport get a
 * paused animation, which plays once when the element approaches the viewport and is then released.
 * Optional data-reveal-delay (ms, keep it at 240 or less) staggers siblings.
 */
export function installReferenceReveals(root: ParentNode = document): () => void {
  const reduced = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  const animations = new Map<HTMLElement, Animation>();
  const elements = [...root.querySelectorAll<HTMLElement>("[data-reveal]")];

  const finish = (element: HTMLElement) => {
    element.dataset.revealPlayed = "true";
    animations.get(element)?.cancel();
    animations.delete(element);
  };

  const observer =
    typeof IntersectionObserver === "function"
      ? new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              const element = entry.target as HTMLElement;
              if (!entry.isIntersecting) {
                // Scrolled past without ever entering: show it instead of leaving it hidden above the viewport.
                if (entry.boundingClientRect.bottom <= 0) { observer?.unobserve(element); finish(element); }
                continue;
              }
              observer?.unobserve(element);
              element.dataset.revealPlayed = "true";
              if (reduced?.matches || document.visibilityState === "hidden" || entry.boundingClientRect.bottom <= 0)
                finish(element);
              else animations.get(element)?.play();
            }
          },
          { threshold: 0, rootMargin: "0px 0px 96px 0px" },
        )
      : undefined;

  // An element can jump from below the viewport to above it inside one frame, which the observer never reports.
  // A throttled sweep releases any pending element that is now above the viewport, so nothing stays invisible.
  let frame = 0;
  const sweep = () => {
    frame = 0;
    for (const [element] of animations) {
      if (element.getBoundingClientRect().bottom <= 0) { observer?.unobserve(element); finish(element); }
    }
  };
  const onScroll = () => { if (!frame) frame = requestAnimationFrame(sweep); };
  addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", onScroll);

  const stop = () => {
    observer?.disconnect();
    elements.forEach(finish);
  };
  const onPreference = () => {
    if (reduced?.matches) stop();
  };
  reduced?.addEventListener("change", onPreference);

  for (const element of elements) {
    if (element.dataset.revealPlayed === "true") continue;
    const rect = element.getBoundingClientRect();
    // Never hide content that is already visible after first paint or a restored scroll position.
    if (
      reduced?.matches ||
      !observer ||
      typeof element.animate !== "function" ||
      rect.top < innerHeight ||
      document.visibilityState === "hidden"
    ) {
      finish(element);
      continue;
    }
    const kind = element.dataset.reveal;
    const transform = kind === "media" ? "scale(1.025)" : kind === "slide" ? "translateX(-12px)" : "translateY(8px)";
    const animation = element.animate(
      [
        { opacity: 0, transform },
        { opacity: 1, transform: "none" },
      ],
      {
        duration: 560,
        delay: Math.min(240, Number(element.dataset.revealDelay ?? 0)),
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "backwards",
      },
    );
    animation.pause();
    animation.onfinish = () => finish(element);
    animations.set(element, animation);
    observer.observe(element);
  }

  return () => {
    stop();
    removeEventListener("scroll", onScroll);
    removeEventListener("resize", onScroll);
    if (frame) cancelAnimationFrame(frame);
    reduced?.removeEventListener("change", onPreference);
  };
}

/** Installs reveals once the marked elements exist. The microtask-free timeout keeps StrictMode remounts clean. */
export function useReveals(ready: boolean) {
  useEffect(() => {
    if (!ready) return;
    let cleanup: (() => void) | undefined;
    const timer = window.setTimeout(() => { cleanup = installReferenceReveals(); }, 0);
    return () => {
      window.clearTimeout(timer);
      cleanup?.();
    };
  }, [ready]);
}
