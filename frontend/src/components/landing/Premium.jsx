/**
 * Premium landing-page primitives.
 *
 * Thin-line SVG / CSS animations, triggered once when content enters
 * the viewport. Tied to product story: scanning documents, drawing
 * section rhythms, and connecting the extract → interpret → verify
 * pipeline.
 *
 * All motion respects prefers-reduced-motion via CSS in index.css.
 */
import { useEffect, useRef, useState } from 'react';

/* ── useReveal ──────────────────────────────────────────────────────────
 * Returns [ref, revealed]. `revealed` flips true the first time the
 * target intersects the viewport, then the observer disconnects.
 */
export function useReveal({ threshold = 0.2, rootMargin = '0px 0px -8% 0px' } = {}) {
  const ref = useRef(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || revealed) return;

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setRevealed(true);
          io.disconnect();
        }
      },
      { threshold, rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [revealed, threshold, rootMargin]);

  return [ref, revealed];
}

/* ── HeroScanGrid ───────────────────────────────────────────────────────
 * Ambient background for the hero: a thin 64px grid that fades toward
 * the edges, plus a slow vertical scan band that descends over ~16s.
 * Evokes a system quietly reading documents without any flash.
 */
export function HeroScanGrid() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden"
    >
      {/* Thin-line grid, masked to fade toward edges */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.022) 1px, transparent 1px), ' +
            'linear-gradient(90deg, rgba(255,255,255,0.022) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
          WebkitMaskImage:
            'radial-gradient(ellipse 70% 60% at 50% 40%, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.5) 55%, transparent 90%)',
          maskImage:
            'radial-gradient(ellipse 70% 60% at 50% 40%, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.5) 55%, transparent 90%)',
        }}
      />
      {/* Descending scan band */}
      <div className="premium-scan-sweep" />
    </div>
  );
}

/* ── SectionLabel ───────────────────────────────────────────────────────
 * Drop-in replacement for "THE PROBLEM" / "THE IMPACT" etc. labels.
 * A 40px tracer rule draws in before the text when the label first
 * becomes visible.
 */
export function SectionLabel({ children, className = '' }) {
  const [ref, revealed] = useReveal();
  return (
    <div ref={ref} className={`flex items-center gap-3 mb-4 ${className}`}>
      <span
        aria-hidden="true"
        className="premium-tracer"
        data-revealed={revealed ? 'true' : 'false'}
      />
      <p className="text-[13px] text-cyan-500 font-semibold uppercase tracking-wider">
        {children}
      </p>
    </div>
  );
}

/* ── PipelineThread ─────────────────────────────────────────────────────
 * Horizontal connector that sits above the Extract / Interpret / Verify
 * cards. Three nodes at the card centers, two line segments that trace
 * in sequentially when the section enters the viewport.
 *
 * Expects to be placed inside a parent with `position: relative` and
 * `grid grid-cols-3`. Lives behind the cards (negative margin below).
 */
export function PipelineThread() {
  const [ref, revealed] = useReveal();
  return (
    <div
      ref={ref}
      className="pointer-events-none col-span-3 relative h-6 -mb-2"
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 900 24"
        preserveAspectRatio="none"
        className="absolute inset-0 w-full h-full overflow-visible"
      >
        {/* Left segment — card 1 → card 2 */}
        <line
          x1="150" y1="12" x2="450" y2="12"
          stroke="rgba(34, 211, 238, 0.28)"
          strokeWidth="1"
          strokeDasharray="300"
          strokeDashoffset={revealed ? 0 : 300}
          style={{
            transition:
              'stroke-dashoffset 1.1s cubic-bezier(0.22, 1, 0.36, 1) 0.25s',
          }}
        />
        {/* Right segment — card 2 → card 3 */}
        <line
          x1="450" y1="12" x2="750" y2="12"
          stroke="rgba(34, 211, 238, 0.28)"
          strokeWidth="1"
          strokeDasharray="300"
          strokeDashoffset={revealed ? 0 : 300}
          style={{
            transition:
              'stroke-dashoffset 1.1s cubic-bezier(0.22, 1, 0.36, 1) 0.85s',
          }}
        />
        {/* Three nodes — card centers */}
        {[150, 450, 750].map((cx, i) => (
          <g key={i}>
            <circle
              cx={cx} cy="12" r="4"
              fill="#0a0a0f"
              stroke="rgba(34, 211, 238, 0.55)"
              strokeWidth="1"
              style={{
                opacity: revealed ? 1 : 0,
                transition: `opacity 0.4s ease ${0.15 + i * 0.3}s`,
              }}
            />
            <circle
              cx={cx} cy="12" r="1.5"
              fill="rgba(34, 211, 238, 0.55)"
              style={{
                opacity: revealed ? 1 : 0,
                transition: `opacity 0.4s ease ${0.25 + i * 0.3}s`,
              }}
            />
          </g>
        ))}
      </svg>
    </div>
  );
}

/* ── StatBaseline ───────────────────────────────────────────────────────
 * Thin accent rule that expands left-to-right synchronized with a counter.
 * Placed between a stat number and its label.
 */
export function StatBaseline({ active, duration = 2000 }) {
  return (
    <div
      aria-hidden="true"
      className="h-px mb-2.5 origin-left"
      style={{
        background:
          'linear-gradient(90deg, rgba(34, 211, 238, 0.4) 0%, rgba(34, 211, 238, 0.1) 60%, transparent 100%)',
        transform: active ? 'scaleX(1)' : 'scaleX(0)',
        transformOrigin: 'left center',
        transition: `transform ${duration}ms cubic-bezier(0.22, 1, 0.36, 1)`,
      }}
    />
  );
}
