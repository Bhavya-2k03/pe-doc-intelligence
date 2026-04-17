import { AlertCircle } from 'lucide-react';

const fmt = v => v == null ? '—' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 2
}).format(v);

const fmtDate = d => {
  if (!d) return '—';
  const dt = new Date(d + 'T00:00:00');
  const m = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const y = String(dt.getFullYear()).slice(2);
  return `${m} '${y}`;
};

// Abbreviate basis labels to fit narrow panels
const fmtBasis = b => {
  if (!b) return '—';
  const map = {
    'committed_capital': 'Committed',
    'invested_capital': 'Invested',
    'unfunded_commitment': 'Unfunded',
    'net_asset_value': 'NAV',
    'net_contributed_capital': 'Net Contrib.',
  };
  return map[b] || b.replace(/_/g, ' ');
};

function Table({ subPeriods, label, total }) {
  return (
    <div className="mb-3">
      <div className="flex justify-between items-center mb-2">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{label}</span>
        <span className="text-[14px] font-bold font-mono text-cyan-400">{fmt(total)}</span>
      </div>
      {(!subPeriods?.length) ? (
        <div className="px-3 py-2 rounded bg-white/[0.015] border border-white/[0.03] text-[11px] text-slate-700 text-center">
          No billable periods
        </div>
      ) : (
        <div className="rounded border border-white/[0.05] overflow-hidden">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-white/[0.02]">
                <th className="text-left text-[9px] font-bold text-slate-400 uppercase tracking-wider px-3 py-1.5">Period</th>
                <th className="text-right text-[9px] font-bold text-slate-400 uppercase tracking-wider px-2 py-1.5">Days</th>
                <th className="text-right text-[9px] font-bold text-slate-400 uppercase tracking-wider px-2 py-1.5">Rate</th>
                <th className="text-left text-[9px] font-bold text-slate-400 uppercase tracking-wider px-2 py-1.5">Basis</th>
                <th className="text-right text-[9px] font-bold text-slate-400 uppercase tracking-wider px-3 py-1.5">Fee</th>
              </tr>
            </thead>
            <tbody>
              {subPeriods.map((sp, i) => (
                <tr key={i} className="border-t border-white/[0.03] hover:bg-white/[0.015] transition">
                  <td className="px-3 py-2 text-[11px] text-slate-400 font-mono whitespace-nowrap">
                    {fmtDate(sp.start)}{' – '}{fmtDate(sp.end)}
                  </td>
                  <td className="px-2 py-2 text-[11px] text-slate-400 font-mono text-right">{sp.days}</td>
                  <td className="px-2 py-2 text-[11px] text-cyan-400 font-mono font-bold text-right">{sp.annual_rate}%</td>
                  <td className="px-2 py-2 text-[11px] text-slate-400">{fmtBasis(sp.basis_label)}</td>
                  <td className="px-3 py-2 text-[11px] text-slate-200 font-mono font-bold text-right whitespace-nowrap">{fmt(sp.fee_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function FeeBreakdown({ fee }) {
  if (!fee) return null;
  const assumptions = fee.assumptions || [];

  return (
    <div>
      {/* Period info line */}
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400 mb-2 font-mono">
        <span>{fmtDate(fee.billing_period_start)}{' → '}{fmtDate(fee.billing_period_end)}</span>
        <span className="doc-badge bg-white/[0.04] text-slate-400">
          {fee.billing_cadence?.replace('_', ' ')}
        </span>
        <span className="doc-badge bg-white/[0.04] text-slate-400">
          {fee.day_count_convention || 'actual/365'}
        </span>
      </div>

      {assumptions.length > 0 && (
        <div className="mb-3 px-3 py-2 rounded bg-amber-500/[0.03] border border-amber-500/[0.08]">
          {assumptions.map((a, i) => (
            <div key={i} className="text-[11px] text-amber-500/70 flex items-start gap-1.5 leading-relaxed">
              <AlertCircle size={10} className="shrink-0 mt-0.5" /> {a}
            </div>
          ))}
        </div>
      )}

      {fee.catchup && <Table subPeriods={fee.catchup.sub_periods} label="Catch-up" total={fee.catchup.total_fee} />}
      <Table subPeriods={fee.current_period?.sub_periods} label="Current Period" total={fee.current_period?.total_fee} />
    </div>
  );
}
