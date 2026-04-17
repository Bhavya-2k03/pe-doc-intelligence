import { X } from 'lucide-react';
import TimelineChart from './TimelineChart';

const FIELDS = [
  'management_fee_rate', 'management_fee_basis', 'management_fee_billing_cadence',
  'carried_interest_rate', 'preferred_return_rate', 'catch_up_rate',
  'organizational_expense_cap', 'fund_investment_end_date', 'fund_term_end_date',
  'fund_initial_closing_date', 'fund_final_closing_date',
];

const label = n => n.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

function getGlobalDateBounds(timelines, fundTermEndDate) {
  let minDate = null;
  let maxDate = fundTermEndDate || null;  // use backend-provided fund_term_end_date

  const icEntries = timelines['fund_initial_closing_date'];
  if (icEntries?.length) {
    const val = icEntries[0].value || icEntries[0].date;
    minDate = typeof val === 'string' ? val : icEntries[0].date;
  }

  // Only fallback to scanning if fundTermEndDate not provided
  if (!maxDate) {
    const teEntries = timelines['fund_term_end_date'];
    if (teEntries?.length) {
      const val = teEntries[teEntries.length - 1].value || teEntries[teEntries.length - 1].date;
      maxDate = typeof val === 'string' ? val : teEntries[teEntries.length - 1].date;
    }
  }

  if (!minDate || !maxDate) {
    Object.values(timelines).forEach(entries => {
      if (!entries) return;
      entries.forEach(e => {
        if (!minDate || e.date < minDate) minDate = e.date;
        if (!maxDate || e.date > maxDate) maxDate = e.date;
      });
    });
  }

  return { minDate, maxDate };
}

export default function TimelineModal({ timelines, constraints, fundTermEndDate, onClose }) {
  const fields = [...FIELDS, ...Object.keys(timelines).filter(f => !FIELDS.includes(f))]
    .filter(f => timelines[f]?.length > 0);

  const bounds = getGlobalDateBounds(timelines, fundTermEndDate);

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-[#0a0b10] border border-white/[0.08] rounded w-full max-w-6xl max-h-[90vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/[0.05] shrink-0">
          <div className="flex items-center gap-3">
            <span className="section-label section-label-violet">Timelines</span>
            <span className="text-[11px] text-slate-400 font-mono font-medium">{fields.length} fields</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[10px] text-slate-400"><span className="kbd">Esc</span> to close</span>
            <button onClick={onClose} className="p-1.5 rounded hover:bg-white/5 text-slate-600">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5 panel-bg">
          {fields.length === 0
            ? <div className="py-16 text-center text-[12px] text-slate-700">No timeline data</div>
            : fields.map(f => (
                <div key={f} className="px-4 py-3 rounded bg-white/[0.01] border border-white/[0.03]">
                  <h3 className="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2">{label(f)}</h3>
                  <TimelineChart entries={timelines[f]} fieldName={f}
                    constraints={constraints?.[f] || []}
                    globalMinDate={bounds.minDate} globalMaxDate={bounds.maxDate} />
                </div>
              ))
          }
        </div>
      </div>
    </div>
  );
}
