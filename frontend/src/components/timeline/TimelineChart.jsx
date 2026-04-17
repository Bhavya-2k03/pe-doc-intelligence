import { useRef, useEffect, useState } from 'react';
import * as d3 from 'd3';

const COLORS = ['#22d3ee', '#a78bfa', '#34d399', '#fbbf24', '#fb7185', '#60a5fa', '#f472b6', '#2dd4bf', '#818cf8', '#f59e0b'];

function fmtVal(v) {
  if (v == null) return '\u2014';
  if (typeof v === 'number') {
    if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
    return String(v);
  }
  return String(v).length > 16 ? String(v).slice(0, 14) + '\u2026' : String(v);
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
          });
        })
        .on('mousemove', ev => setTip(p => p ? { ...p, x: ev.clientX, y: ev.clientY } : null))
        .on('mouseleave', ev => { d3.select(ev.target).attr('opacity', 0.75); setTip(null); });

      if (ew > 30) {
        g.append('text').attr('x', s + ew / 2).attr('y', barH / 2).attr('dy', '0.35em')
          .attr('text-anchor', 'middle').attr('fill', '#06070b')
          .attr('font-size', '11px').attr('font-weight', '700')
          .attr('font-family', 'JetBrains Mono, monospace')
          .attr('pointer-events', 'none').text(fmtVal(e.value));
      } else {
        g.append('text').attr('x', s + ew / 2).attr('y', -3)
          .attr('text-anchor', 'middle').attr('fill', c)
          .attr('font-size', '9px').attr('font-weight', '700')
          .attr('font-family', 'JetBrains Mono, monospace')
          .attr('pointer-events', 'none').text(fmtVal(e.value));
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
        .text(`${arrow} ${c.type} ${fmtVal(c.bound)}`);
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
          <div className="font-bold text-cyan-400 font-mono text-[13px] mb-0.5">{fmtVal(tip.value)}</div>
          <div className="text-slate-500 space-y-0.5">
            <div>From: <span className="text-slate-400 font-mono">{tip.date}</span></div>
            {tip.endDate && <div>Until: <span className="text-slate-400 font-mono">{tip.endDate}</span></div>}
            {tip.source && <div className="mt-1 pt-1 border-t border-white/[0.06] text-slate-450 italic leading-relaxed">{tip.source.slice(0, 100)}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
