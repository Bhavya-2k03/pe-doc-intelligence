/**
 * Isometric wireframe illustrations for the landing page.
 * Clean thin white strokes on dark. Animate on hover over geometry only.
 *
 * Also auto-reveal once when the figure first enters the viewport, reusing
 * the same animation vocabulary as hover but with finite iteration counts
 * (one-shot "performance" that settles). Hover still triggers continuous
 * loops after the reveal completes.
 */
import { useReveal } from './Premium';

const C30 = 0.866;
const FONT = 'JetBrains Mono, monospace';
const STK = 'rgba(255,255,255,0.13)';
const DIM = 'rgba(255,255,255,0.06)';

function makeP(scale, ox, oy) {
  return (x, y, z) => [
    ox + (x - y) * C30 * scale,
    oy + (x + y) * 0.5 * scale - z * scale,
  ];
}

function pts(a) {
  return a.map(c => `${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(' ');
}

function boxFaces(p, bx, by, bz, w, d, h) {
  return [
    [p(bx,by,bz+h), p(bx+w,by,bz+h), p(bx+w,by+d,bz+h), p(bx,by+d,bz+h)],
    [p(bx+w,by,bz+h), p(bx+w,by,bz), p(bx+w,by+d,bz), p(bx+w,by+d,bz+h)],
    [p(bx,by+d,bz+h), p(bx+w,by+d,bz+h), p(bx+w,by+d,bz), p(bx,by+d,bz)],
  ];
}

function renderBox(p, bx, by, bz, w, d, h, key, stroke = STK) {
  return boxFaces(p, bx, by, bz, w, d, h).map((face, i) => (
    <polygon key={`${key}-f${i}`} points={pts(face)}
      stroke={stroke} strokeWidth="0.8" fill="none" />
  ));
}

function renderBackEdges(p, bx, by, bz, w, d, h, key) {
  const edges = [
    [p(bx,by,bz), p(bx+w,by,bz)],
    [p(bx,by,bz), p(bx,by+d,bz)],
    [p(bx,by,bz), p(bx,by,bz+h)],
  ];
  return edges.map(([a, b], i) => (
    <line key={`${key}-be${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
      stroke={DIM} strokeWidth="0.6" />
  ));
}


/* ─────────────────────────────────────────────────────────────────────────
 * PROBLEM FIGURE — Large stepped pyramid with extracted floating slice.
 * On hover (geometry only): slice lifts, connectors march, edges brighten.
 * ───────────────────────────────────────────────────────────────────────── */
export function ProblemFigure() {
  const [revealRef, revealed] = useReveal({ threshold: 0.3 });
  const p = makeP(28, 250, 260);

  const layers = [
    { x: 0,   y: 0,   z: 0,   w: 4.2, d: 4.2, h: 1.15 },
    { x: 0.7, y: 0.7, z: 1.15, w: 2.8, d: 2.8, h: 1.15 },
    { x: 1.4, y: 1.4, z: 2.3,  w: 1.4, d: 1.4, h: 1.15 },
  ];

  const slice = { x: 1.4, y: 1.4, z: 4.4, w: 1.4, d: 1.4, h: 0.55 };

  const baseTop = layers[0].z + layers[0].h;
  const bw = layers[0].w, bd = layers[0].d;
  const gridLines = [
    [p(bw / 2, 0, baseTop), p(bw / 2, bd, baseTop)],
    [p(0, bd / 2, baseTop), p(bw, bd / 2, baseTop)],
    [p(bw * 0.25, 0, baseTop), p(bw * 0.25, bd, baseTop)],
    [p(bw * 0.75, 0, baseTop), p(bw * 0.75, bd, baseTop)],
    [p(0, bd * 0.25, baseTop), p(bw, bd * 0.25, baseTop)],
    [p(0, bd * 0.75, baseTop), p(bw, bd * 0.75, baseTop)],
  ];

  const topZ = layers[2].z + layers[2].h;
  const sx = slice.x, sy = slice.y, sw = slice.w, sd = slice.d;
  const connectors = [
    [p(sx, sy, topZ), p(sx, sy, slice.z)],
    [p(sx + sw, sy, topZ), p(sx + sw, sy, slice.z)],
    [p(sx + sw, sy + sd, topZ), p(sx + sw, sy + sd, slice.z)],
    [p(sx, sy + sd, topZ), p(sx, sy + sd, slice.z)],
  ];

  const sliceTop = slice.z + slice.h;
  const contentLines = [
    [p(sx + 0.15, sy + 0.25, sliceTop), p(sx + sw - 0.2, sy + 0.25, sliceTop)],
    [p(sx + 0.15, sy + 0.55, sliceTop), p(sx + sw - 0.4, sy + 0.55, sliceTop)],
    [p(sx + 0.15, sy + 0.85, sliceTop), p(sx + sw - 0.15, sy + 0.85, sliceTop)],
    [p(sx + 0.15, sy + 1.15, sliceTop), p(sx + sw - 0.35, sy + 1.15, sliceTop)],
  ];

  return (
    <svg ref={revealRef} viewBox="0 0 500 420" className="w-full h-auto" fill="none"
      style={{ pointerEvents: 'none' }}>
      <g className="illus-root" data-revealed={revealed ? 'true' : 'false'}
        style={{ pointerEvents: 'all' }}>
        {/* Hit area — tight to geometry */}
        <rect x="142" y="118" width="216" height="260" fill="transparent" rx="4" />

        {layers.map((l, i) => renderBox(p, l.x, l.y, l.z, l.w, l.d, l.h, `L${i}`))}
        {renderBackEdges(p, 0, 0, 0, 4.2, 4.2, 1.15, 'base')}

        {gridLines.map(([a, b], i) => (
          <line key={`grid${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
            stroke={DIM} strokeWidth="0.6" />
        ))}

        {connectors.map(([a, b], i) => (
          <line key={`conn${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
            stroke={DIM} strokeWidth="0.6" strokeDasharray="2,3"
            className="illus-marching" />
        ))}

        <g className="illus-float">
          {renderBox(p, slice.x, slice.y, slice.z, slice.w, slice.d, slice.h, 'slice')}
          {contentLines.map(([a, b], i) => (
            <line key={`cl${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
              stroke={DIM} strokeWidth="0.5" />
          ))}
        </g>
      </g>
    </svg>
  );
}


/* ─────────────────────────────────────────────────────────────────────────
 * FIG 0.1 — EXTRACT
 * ───────────────────────────────────────────────────────────────────────── */
export function ExtractFigure() {
  const [revealRef, revealed] = useReveal({ threshold: 0.4 });
  const p = makeP(16, 130, 175);
  const pw = 4.5, pd = 3.5, ph = 0.35;
  const zLevels = [0, 1.6, 3.2, 4.8, 6.4];

  const corners = [[pw, pd], [pw, 0], [0, pd]];

  const lensZ = zLevels[3] + ph;
  const lensCx = pw / 2, lensCy = pd / 2, lensR = 0.9;
  const lensPoints = Array.from({ length: 20 }, (_, i) => {
    const a = (i / 20) * Math.PI * 2;
    return p(lensCx + lensR * Math.cos(a), lensCy + lensR * Math.sin(a), lensZ);
  });

  const scanA = p(-0.2, pd + 0.2, 0);
  const scanB = p(pw + 0.2, -0.2, 0);

  return (
    <div ref={revealRef} className="w-full flex justify-center" style={{ height: 280 }}>
      <svg viewBox="0 0 280 260" className="w-full h-full" fill="none"
        style={{ pointerEvents: 'none' }}>
        <g className="illus-root" data-revealed={revealed ? 'true' : 'false'}
          style={{ pointerEvents: 'all' }}>
          <rect x="60" y="32" width="140" height="210" fill="transparent" rx="4" />

          <text x="12" y="14" fill="rgba(255,255,255,0.2)" fontSize="7"
            fontFamily={FONT} fontWeight="500" letterSpacing="0.5">FIG 0.1</text>

          {zLevels.map((z, i) =>
            renderBox(p, 0, 0, z, pw, pd, ph, `P${i}`)
          )}

          {zLevels.slice(0, -1).map((z, i) =>
            corners.map(([cx, cy], ci) => {
              const a = p(cx, cy, z + ph);
              const b = p(cx, cy, zLevels[i + 1]);
              return (
                <line key={`vc${i}${ci}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
                  stroke={DIM} strokeWidth="0.6" strokeDasharray="2,3" />
              );
            })
          )}

          {[0.7, 1.4, 2.1, 2.8].map((ly, i) => {
            const z = zLevels[4] + ph;
            const a = p(0.5, ly, z), b = p(3.5 - (i % 2) * 0.8, ly, z);
            return (
              <line key={`txt${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
                stroke={DIM} strokeWidth="0.5" />
            );
          })}

          <polygon points={pts(lensPoints)}
            stroke={STK} strokeWidth="0.7" className="illus-pulsing" />

          <line x1={scanA[0]} y1={scanA[1]} x2={scanB[0]} y2={scanB[1]}
            stroke="rgba(255,255,255,0.09)" strokeWidth="0.5"
            className="illus-scanning" />
        </g>
      </svg>
    </div>
  );
}


/* ─────────────────────────────────────────────────────────────────────────
 * FIG 0.2 — INTERPRET
 * ───────────────────────────────────────────────────────────────────────── */
export function InterpretFigure() {
  const [revealRef, revealed] = useReveal({ threshold: 0.4 });
  const p = makeP(16, 130, 130);

  const cubes = [
    { x: 0.8, y: 0.8, z: 0,   w: 2.2, d: 2.2, h: 2.2 },
    { x: 3.3, y: 0.3, z: 0,   w: 1.5, d: 1.5, h: 1.5 },
    { x: 0,   y: 3.3, z: 0,   w: 1.5, d: 1.5, h: 1.5 },
    { x: 3.3, y: 3.0, z: 0,   w: 1.7, d: 1.7, h: 1.7 },
    { x: 1.3, y: 1.3, z: 2.5, w: 1.3, d: 1.3, h: 1.3 },
  ];

  const peak = { x: 1.7, y: 0.5, z: 4.1, w: 0.8, d: 0.8, h: 0.8 };

  return (
    <div ref={revealRef} className="w-full flex justify-center" style={{ height: 280 }}>
      <svg viewBox="0 0 280 260" className="w-full h-full" fill="none"
        style={{ pointerEvents: 'none' }}>
        <g className="illus-root" data-revealed={revealed ? 'true' : 'false'}
          style={{ pointerEvents: 'all' }}>
          <rect x="42" y="38" width="175" height="185" fill="transparent" rx="4" />

          <text x="12" y="14" fill="rgba(255,255,255,0.2)" fontSize="7"
            fontFamily={FONT} fontWeight="500" letterSpacing="0.5">FIG 0.2</text>

          {cubes.map((c, i) =>
            renderBox(p, c.x, c.y, c.z, c.w, c.d, c.h, `C${i}`)
          )}

          {renderBackEdges(p, 0.8, 0.8, 0, 2.2, 2.2, 2.2, 'ctr')}

          <g className="illus-float">
            {renderBox(p, peak.x, peak.y, peak.z, peak.w, peak.d, peak.h, 'C5')}
          </g>
        </g>
      </svg>
    </div>
  );
}


/* ─────────────────────────────────────────────────────────────────────────
 * FIG 0.3 — VERIFY
 * ───────────────────────────────────────────────────────────────────────── */
export function VerifyFigure() {
  const [revealRef, revealed] = useReveal({ threshold: 0.4 });
  const p = makeP(13, 95, 185);

  const bars = [
    { x: 0,   h: 5.8 },
    { x: 1.3, h: 5.0 },
    { x: 2.6, h: 4.2 },
    { x: 3.9, h: 3.3 },
    { x: 5.2, h: 2.4 },
    { x: 6.5, h: 1.6 },
  ];
  const barW = 1.0, barD = 2.2;

  const ground = [p(0, 0, 0), p(7.5, 0, 0), p(7.5, barD, 0), p(0, barD, 0)];

  return (
    <div ref={revealRef} className="w-full flex justify-center" style={{ height: 280 }}>
      <svg viewBox="0 0 280 260" className="w-full h-full" fill="none"
        style={{ pointerEvents: 'none' }}>
        <g className="illus-root" data-revealed={revealed ? 'true' : 'false'}
          style={{ pointerEvents: 'all' }}>
          <rect x="50" y="68" width="140" height="170" fill="transparent" rx="4" />

          <text x="12" y="14" fill="rgba(255,255,255,0.2)" fontSize="7"
            fontFamily={FONT} fontWeight="500" letterSpacing="0.5">FIG 0.3</text>

          <polygon points={pts(ground)}
            stroke={DIM} strokeWidth="0.6" />

          {bars.map((b, i) => (
            <g key={`bar${i}`} className="illus-bar"
              style={{ transitionDelay: `${i * 0.04}s` }}>
              {renderBox(p, b.x, 0, 0, barW, barD, b.h, `B${i}`)}
            </g>
          ))}

          {bars.slice(0, -1).map((b, i) => {
            const next = bars[i + 1];
            const a = p(b.x + barW, 0, b.h);
            const mid = p(next.x, 0, b.h);
            const c = p(next.x, 0, next.h);
            return (
              <polyline key={`step${i}`}
                points={`${a[0].toFixed(1)},${a[1].toFixed(1)} ${mid[0].toFixed(1)},${mid[1].toFixed(1)} ${c[0].toFixed(1)},${c[1].toFixed(1)}`}
                stroke={DIM} strokeWidth="0.6" fill="none" />
            );
          })}
        </g>
      </svg>
    </div>
  );
}
