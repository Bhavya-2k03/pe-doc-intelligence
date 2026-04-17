import { useState, useEffect } from 'react';
import { Activity, Wifi, ArrowLeft } from 'lucide-react';

export default function StatusBar({ sessionId, evaluating, onBack }) {
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const fmt = (d) => d.toLocaleDateString('en-US', {
    day: '2-digit', month: 'short', year: 'numeric'
  }).toUpperCase();

  const time = clock.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  });

  return (
    <header className="h-9 bg-[#08090d] border-b border-white/[0.05] flex items-center px-4 shrink-0 z-40 select-none">
      {/* Left: nav + brand */}
      <button onClick={onBack}
        className="text-[11px] text-slate-700 hover:text-slate-400 transition flex items-center gap-1 mr-3 uppercase tracking-wider font-bold">
        <ArrowLeft size={12} /> Exit
      </button>
      <div className="h-3 w-px bg-white/[0.06] mr-3" />
      <span className="text-[13px] font-semibold text-white tracking-tight">PE Doc <span className="text-cyan-500">Intelligence</span></span>

      <div className="flex-1" />

      {/* Center: pipeline status */}
      {evaluating && (
        <div className="flex items-center gap-1.5 px-3 py-0.5 rounded bg-cyan-500/[0.06] border border-cyan-500/[0.12] mr-4">
          <Activity size={11} className="text-cyan-400 status-pulse" />
          <span className="text-[11px] font-bold text-cyan-400 uppercase tracking-wider">Pipeline Active</span>
        </div>
      )}

      {/* Right: session + clock */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <Wifi size={10} className="text-emerald-500" />
          <span className="text-[11px] text-emerald-500/70 font-bold uppercase tracking-wider">Live</span>
        </div>
        <div className="h-3 w-px bg-white/[0.06]" />
        <span className="text-[11px] text-slate-600 font-mono">
          {sessionId ? sessionId.slice(0, 8) : '--------'}
        </span>
        <div className="h-3 w-px bg-white/[0.06]" />
        <span className="text-[11px] text-slate-500 font-mono font-bold">{fmt(clock)}</span>
        <span className="text-[11px] text-cyan-500/60 font-mono">{time}</span>
      </div>
    </header>
  );
}
