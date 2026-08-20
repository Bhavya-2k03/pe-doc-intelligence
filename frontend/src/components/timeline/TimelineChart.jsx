import { useRef, useEffect, useState } from 'react';
import * as d3 from 'd3';

const COLORS = ['#22d3ee', '#a78bfa', '#34d399', '#fbbf24', '#fb7185', '#60a5fa', '#f472b6', '#2dd4bf', '#818cf8', '#f59e0b'];

// Rates and percentages arrive as plain numbers (2.0 means 2%), indistinguishable
// on the wire from currency amounts. Only the field name separates them, so
// formatting is keyed off it \u2014 otherwise a 2% fee rate renders as "$2".
const isPercentField = name => /(_rate$|_rate_|percentage|_pct)/.test(name || '');

// Drop trailing zeros after fixing decimals: 2.05 -> "2.05", 2.20 -> "2.2", 10.00 -> "10"
const trimZeros = s => (s.includes('.') ? s.replace(/\.?0+$/, '') : s);

// Abbreviate to at most `dp` decimals.
// Fixed 1-decimal rounding misreported values: 2,050,000 rendered as "$2.0M"
// (2.05 is 2.0499\u2026 in binary floating point, so toFixed(1) rounds DOWN) and
// 1,250,000 as "$1.3M". Amounts here are fee inputs \u2014 a label must not state
// a number the engine did not compute.
function abbrCurrency(v, dp) {
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  const [div, unit] = abs >= 1e6 ? [1e6, 'M'] : [1e3, 'K'];
  return `${sign}$${trimZeros((abs / div).toFixed(dp))}${unit}`;
}

function fmtNumber(v, fieldName) {
  if (isPercentField(fieldName)) return `${trimZeros(v.toFixed(4))}%`;
  if (Math.abs(v) >= 1e3) return abbrCurrency(v, 2);
  const sign = v < 0 ? '-' : '';
  return `${sign}$${Math.abs(v).toLocaleString('en-US')}`;
}

function fmtVal(v, fieldName) {
  if (v == null) return '\u2014';
  if (typeof v === 'number') return fmtNumber(v, fieldName);
  // Returned in full. Fitting to the space available is the caller's job \u2014
  // a fixed character cap clipped values like "committed_capital" even on a
  // bar hundreds of pixels wide.
  return String(v);
}

// Approximate advance width of JetBrains Mono, used to decide whether a label
// fits inside its bar. Monospace, so character count times this is accurate
// enough to avoid measuring text in the DOM.
const MONO_CHAR_W = 0.6;

function fitToWidth(label, pxAvailable, fontPx) {
  const maxChars = Math.floor(pxAvailable / (fontPx * MONO_CHAR_W));
  if (label.length <= maxChars) return label;
  if (maxChars < 2) return '';
  return label.slice(0, maxChars - 1) + '\u2026';
}

// Exact, unabbreviated \u2014 used where there is room to show the true number.
function fmtExact(v, fieldName) {
  if (v == null) return '\u2014';
  if (typeof v === 'number') {
    if (isPercentField(fieldName)) return `${trimZeros(v.toFixed(4))}%`;
    const sign = v < 0 ? '-' : '';
    return `${sign}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  }
  return String(v);
}

function resolveTimeline(entries) {
  if (!entries?.length) return entries;

  const dateSet = new Set();
  entries.forEach(e => {
    dateSet.add(e.date);
    if (e.end_date) dateSet.add(e.end_date);
  });
  const dates = [...dateSet].sort();

  const resolved = [];
  for (let i = 0; i < dates.length - 1; i++) {
    const start = dates[i];
    const end = dates[i + 1];

    let winner = null;
    let winnerOrder = -1;
    entries.forEach((e, idx) => {
      if (e.date <= start && (e.end_date == null || e.end_date > start)) {
        if (idx >= winnerOrder) {
          winner = e;
          winnerOrder = idx;
        }
      }
    });

    if (winner == null) continue;

    const prev = resolved[resolved.length - 1];
    if (
      prev &&
      String(prev.value) === String(winner.value) &&
      prev.end_date === start &&
      (prev.source || '') === (winner.source || '')
    ) {
      prev.end_date = end;
    } else {
      resolved.push({
        date: start,
        end_date: end,
        value: winner.value,
        source: winner.source,
        as_of_label: winner.as_of_label ?? null,
        is_observation: winner.is_observation ?? false,
      });
    }
  }

  const lastEntry = entries[entries.length - 1];
  if (lastEntry && !lastEntry.end_date) {
    const prev = resolved[resolved.length - 1];
    if (prev && String(prev.value) === String(lastEntry.value) && (prev.source || '') === (lastEntry.source || '')) {
      prev.end_date = null;
    } else if (!prev || prev.end_date != null) {
      resolved.push({
        date: lastEntry.date > (prev?.end_date || '') ? lastEntry.date : prev?.end_date || lastEntry.date,
        end_date: null,
        value: lastEntry.value,
        source: lastEntry.source,
        as_of_label: lastEntry.as_of_label ?? null,
        is_observation: lastEntry.is_observation ?? false,
      });
    }
  }

  return resolved;
}

export default function TimelineChart({ entries, fieldName, constraints = [], globalMinDate, globalMaxDate }) {
  const ref = useRef();
  const [tip, setTip] = useState(null);

  useEffect(() => {
    if (!entries?.length) return;
    const resolved = resolveTimeline(entries);
    if (!resolved?.length) return;

    const svg = d3.select(ref.current);
    svg.selectAll('*').remove();

    const barH = 24;
    const m = { top: 4, right: 12, bottom: 22, left: 12 };
    const w = ref.current.clientWidth;
    const iw = w - m.left - m.right;

    const parsed = resolved.map(e => ({
      ...e, d: new Date(e.date + 'T00:00:00'),
      ed: e.end_date ? new Date(e.end_date + 'T00:00:00') : null,
    }));

    const autoMin = d3.min(parsed, d => d.d);
    const autoMax = parsed[parsed.length - 1].ed || d3.timeYear.offset(parsed[parsed.length - 1].d, 2);
    const minD = globalMinDate ? new Date(globalMinDate + 'T00:00:00') : autoMin;
    const maxD = globalMaxDate ? new Date(globalMaxDate + 'T00:00:00') : autoMax;
    const x = d3.scaleTime().domain([minD, maxD]).range([0, iw]);
    const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`);

    const vals = [...new Set(parsed.map(d => String(d.value)))];
    const cm = {}; vals.forEach((v, i) => cm[v] = COLORS[i % COLORS.length]);

    // Map date → effective_value (what you actually pay after CAP/FLOOR)
    const effectiveMap = {};
    (entries || []).forEach(e => {
      if (e.effective_value != null) effectiveMap[e.date] = e.effective_value;
    });

    // ── Render entry bars ─────────────────────────────────────────
    // Labels for bars too narrow to hold text are drawn above the bar. Track
    // what has been placed so adjacent narrow bars (e.g. consecutive quarterly
    // observations) stagger onto a second row instead of overprinting each
    // other. Anything that still cannot fit is dropped — the tooltip has it.
    const placedLabels = [];
    const LABEL_ROWS = 2;

    parsed.forEach((e, i) => {
      if (e.d >= maxD) return;
      const s = x(e.d);
      let ed = e.ed || (parsed[i + 1] ? parsed[i + 1].d : maxD);
      if (ed > maxD) ed = maxD;
      const ew = Math.max(x(ed) - s, 2);
      const c = cm[String(e.value)];
      const effectiveVal = effectiveMap[e.date];

      g.append('rect').attr('x', s).attr('y', 0).attr('width', ew).attr('height', barH)
        .attr('rx', 2).attr('fill', c).attr('opacity', 0.75)
        .style('cursor', 'pointer')
        .on('mouseenter', ev => {
          d3.select(ev.target).attr('opacity', 1);
          setTip({
            x: ev.clientX, y: ev.clientY, value: e.value,
            date: e.date, endDate: e.end_date, source: e.source,
            effectiveValue: effectiveVal ?? null,
            asOfLabel: e.as_of_label ?? null,
            isObservation: e.is_observation ?? false,
          });
        })
        .on('mousemove', ev => setTip(p => p ? { ...p, x: ev.clientX, y: ev.clientY } : null))
        .on('mouseleave', ev => { d3.select(ev.target).attr('opacity', 0.75); setTip(null); });

      const label = fmtVal(e.value, fieldName);

      // Inside the bar when the label actually fits, otherwise above it.
      // The fit is MEASURED, not estimated from character count: an estimate
      // that is even slightly pessimistic pushes short labels like "$7.4M"
      // out of bars they comfortably fit in.
      const inside = g.append('text')
        .attr('x', s + ew / 2).attr('y', barH / 2).attr('dy', '0.35em')
        .attr('text-anchor', 'middle').attr('fill', '#06070b')
        .attr('font-size', '11px').attr('font-weight', '700')
        .attr('font-family', 'JetBrains Mono, monospace')
        .attr('pointer-events', 'none').text(label);

      // 2px of breathing room per side; anything tighter reads as touching.
      const insideW = inside.node().getComputedTextLength();

      if (insideW > ew - 4) {
        inside.remove();
        // Above the bar, so the bar's width does not constrain it — only the
        // chart's does. Bounded by the plot width so a long value can never
        // push past the axis.
        const above = fitToWidth(label, iw, 9);
        const halfW = (above.length * 9 * MONO_CHAR_W) / 2;
        // Keep the label inside the plot even when its bar sits at an edge.
        const cx = Math.min(Math.max(s + ew / 2, halfW), Math.max(iw - halfW, halfW));
        const x0 = cx - halfW;
        const x1 = cx + halfW;

        let row = 0;
        while (
          row < LABEL_ROWS &&
          placedLabels.some(p => p.row === row && x0 < p.x1 + 4 && x1 > p.x0 - 4)
        ) row++;

        if (row < LABEL_ROWS) {
          placedLabels.push({ x0, x1, row });
          g.append('text').attr('x', cx).attr('y', -3 - row * 10)
            .attr('text-anchor', 'middle').attr('fill', c)
            .attr('font-size', '9px').attr('font-weight', '700')
            .attr('font-family', 'JetBrains Mono, monospace')
            .attr('pointer-events', 'none').text(above);
        }
      }
    });

    // ── Render constraints as edge markers on the bars ────────────
    // CAP = line at top of bar, FLOOR = line at bottom of bar
    constraints.forEach(c => {
      const isCap = c.type === 'CAP';
      const color = isCap ? '#fb7185' : '#4ade80';
      const yLine = isCap ? 1 : barH - 1;

      const fromD = c.active_from ? new Date(c.active_from + 'T00:00:00') : minD;
      const toD = c.active_until ? new Date(c.active_until + 'T00:00:00') : maxD;
      if (fromD >= maxD) return;

      const x1 = Math.max(x(fromD), 0);
      const x2 = Math.min(x(toD), iw);

      // Thin solid line at top (cap) or bottom (floor) of bar
      g.append('line')
        .attr('x1', x1).attr('y1', yLine)
        .attr('x2', x2).attr('y2', yLine)
        .attr('stroke', color)
        .attr('stroke-width', 2)
        .attr('opacity', 0.8);

      // Small tag at the start of the constraint
      const tagW = 52;
      const tagH = 14;
      const tagY = isCap ? yLine - tagH - 1 : yLine + 1;

      g.append('rect')
        .attr('x', x1).attr('y', tagY)
        .attr('width', tagW).attr('height', tagH)
        .attr('rx', 2)
        .attr('fill', color).attr('opacity', 0.15);

      g.append('rect')
        .attr('x', x1).attr('y', tagY)
        .attr('width', tagW).attr('height', tagH)
        .attr('rx', 2)
        .attr('fill', 'none').attr('stroke', color).attr('stroke-width', 0.5).attr('opacity', 0.4);

      const arrow = isCap ? '\u25BC' : '\u25B2';
      g.append('text')
        .attr('x', x1 + tagW / 2).attr('y', tagY + tagH / 2).attr('dy', '0.35em')
        .attr('text-anchor', 'middle')
        .attr('fill', color).attr('font-size', '8px').attr('font-weight', '700')
        .attr('font-family', 'JetBrains Mono, monospace')
        .attr('pointer-events', 'none')
        .text(`${arrow} ${c.type} ${fmtVal(c.bound, fieldName)}`);
    });

    // ── X axis ────────────────────────────────────────────────────
    const ax = d3.axisBottom(x).ticks(d3.timeYear.every(1)).tickFormat(d3.timeFormat('%Y')).tickSize(3);
    g.append('g').attr('transform', `translate(0,${barH + 2})`).call(ax)
      .selectAll('text').attr('fill', '#94a3b8').attr('font-size', '10px').attr('font-weight', '500').attr('font-family', 'JetBrains Mono, monospace');
    g.selectAll('.domain').attr('stroke', '#475569');
    g.selectAll('.tick line').attr('stroke', '#475569');
  }, [entries, constraints]);

  return (
    <div className="relative">
      <svg ref={ref} className="w-full" height={50} style={{ overflow: 'visible' }} />
      {tip && (
        <div className="fixed z-[100] px-3 py-2 bg-[#12131a] border border-white/10 text-[11px] rounded shadow-xl pointer-events-none max-w-xs"
          style={{ left: tip.x + 12, top: tip.y - 10, transform: 'translateY(-100%)' }}>
          <div className="font-bold text-cyan-400 font-mono text-[13px] mb-0.5">{fmtExact(tip.value, fieldName)}</div>
          <div className="text-slate-500 space-y-0.5">
            {/* A reported observation and a clause-set value mean different
                things. An observation is measured AT a date and stands as the
                last known figure until the next report — "From/Until" would
                overclaim it as a period of validity. A clause genuinely does
                set a value across a window, so it keeps From/Until. */}
            {tip.isObservation ? (
              <>
                {tip.asOfLabel && (
                  <div>Reported as of: <span className="text-cyan-300 font-mono">{tip.asOfLabel}</span></div>
                )}
                <div>Observed: <span className="text-slate-400 font-mono">{tip.date}</span></div>
                {tip.endDate && <div>Superseded: <span className="text-slate-400 font-mono">{tip.endDate}</span></div>}
              </>
            ) : (
              <>
                <div>From: <span className="text-slate-400 font-mono">{tip.date}</span></div>
                {tip.endDate && <div>Until: <span className="text-slate-400 font-mono">{tip.endDate}</span></div>}
              </>
            )}
            {tip.source && <div className="mt-1 pt-1 border-t border-white/[0.06] text-slate-450 italic leading-relaxed">{tip.source.slice(0, 100)}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
