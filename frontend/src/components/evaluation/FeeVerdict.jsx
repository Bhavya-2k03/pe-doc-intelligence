import { useEffect, useRef } from 'react';
import { CheckCircle2, XCircle, Shield, ShieldAlert } from 'lucide-react';

const fmt = v => v == null ? '\u2014' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 2
}).format(v);

function CountUp({ value, className }) {
  const ref = useRef(null);
  const prev = useRef(0);

  useEffect(() => {
    if (value == null || !ref.current) return;
    const start = prev.current;
    const end = value;
    const duration = 600;
    const startTime = performance.now();

    function animate(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = start + (end - start) * eased;
      if (ref.current) {
        ref.current.textContent = fmt(current);
      }
      if (progress < 1) requestAnimationFrame(animate);
      else prev.current = end;
    }
    requestAnimationFrame(animate);
  }, [value]);

  return <span ref={ref} className={className}>{fmt(value)}</span>;
}

export default function FeeVerdict({ verdict }) {
  if (!verdict) return null;
  const { match, calculated_fee, gp_claimed_fee, delta } = verdict;
  const hasGp = gp_claimed_fee != null;

  return (
    <div className={`rounded-md overflow-hidden number-appear ${match ? 'verdict-match glow-green' : hasGp ? 'verdict-mismatch glow-red' : 'verdict-match'}`}>
      {/* Status banner */}
      {hasGp && (
        <div className={`px-4 py-2 flex items-center gap-2 ${
          match ? 'bg-emerald-500/[0.08]' : 'bg-red-500/[0.08]'
        }`}>
          {match
            ? <><Shield size={14} className="text-emerald-400" /><span className="text-[12px] font-bold uppercase tracking-wider text-emerald-400">Fee Verified</span></>
            : <><ShieldAlert size={14} className="text-red-400" /><span className="text-[12px] font-bold uppercase tracking-wider text-red-400">Mismatch Detected</span></>
          }
        </div>
      )}

      {/* Main fee display */}
      <div className="px-4 py-4">
        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Calculated Management Fee</div>
        <CountUp value={calculated_fee}
          className="text-[28px] font-bold font-mono text-slate-100 tracking-tight" />

        {/* Comparison row */}
        {hasGp && (
          <div className="grid grid-cols-2 gap-4 mt-3 pt-3 border-t border-white/[0.04]">
            <div>
              <div className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">GP Charged</div>
              <div className="text-[16px] font-bold font-mono text-slate-400">{fmt(gp_claimed_fee)}</div>
            </div>
            <div>
              <div className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">Delta</div>
              <div className={`text-[16px] font-bold font-mono flex items-center gap-1.5 ${
                match ? 'text-emerald-400' : 'text-red-400'
              }`}>
                {match ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                {fmt(delta)}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
