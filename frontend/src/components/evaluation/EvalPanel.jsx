import { useState, useEffect, useRef } from 'react';
import { Play, Loader2, ChevronRight, Keyboard, AlertCircle, HelpCircle } from 'lucide-react';
import TimelineChart from '../timeline/TimelineChart';

function InputTooltip({ text }) {
  const [pos, setPos] = useState(null);
  return (
    <span className="inline-block ml-1 align-middle">
      <HelpCircle size={12} className="text-slate-400 hover:text-cyan-400 cursor-help transition"
        onMouseEnter={e => setPos({ x: e.clientX, y: e.clientY })}
        onMouseLeave={() => setPos(null)} />
      {pos && (
        <div className="fixed z-[200] w-56 px-3 py-2
          bg-[#12131a] border border-white/10 rounded shadow-xl text-[10px] text-slate-400 leading-relaxed
          pointer-events-none"
          style={{ left: pos.x - 112, top: pos.y + 16 }}>
          {text}
        </div>
      )}
    </span>
  );
}

const STAGES = {
  parsing: { l: 'PARSE', c: '#22d3ee' }, layer1: { l: 'EXTRACT', c: '#60a5fa' },
  layer2: { l: 'INTERPRET', c: '#a78bfa' }, layer3: { l: 'RESOLVE', c: '#fbbf24' },
  layer4: { l: 'CONFIRM', c: '#34d399' }, layer5: { l: 'EXECUTE', c: '#fb7185' },
  stability: { l: 'VERIFY', c: '#2dd4bf' }, fees: { l: 'CALC', c: '#4ade80' },
  done: { l: 'DONE', c: '#86efac' },
};

const TIMELINE_FIELDS = [
  'management_fee_rate', 'management_fee_basis', 'management_fee_billing_cadence',
  'carried_interest_rate', 'preferred_return_rate', 'catch_up_rate',
  'organizational_expense_cap', 'fund_investment_end_date', 'fund_term_end_date',
  'fund_initial_closing_date', 'fund_final_closing_date',
];

const fieldLabel = n => n.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

function Terminal({ log, active }) {
  const scrollRef = useRef(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log]);
  if (!log?.length) return null;
  return (
    <div className="rounded border border-white/[0.05] overflow-hidden">
      <div className="bg-[#08090d] px-3 py-1.5 flex items-center border-b border-white/[0.04]">
        <div className="flex gap-1.5 mr-2">
          <div className="w-2 h-2 rounded-full bg-[#ff5f57]" />
          <div className="w-2 h-2 rounded-full bg-[#febc2e]" />
          <div className="w-2 h-2 rounded-full bg-[#28c840]" />
        </div>
        <span className={`flex-1 text-center text-[10px] font-mono font-semibold uppercase tracking-[0.3em] ${active ? 'text-slate-400' : 'text-emerald-400'}`}>
          {active ? 'pipeline' : 'complete'}
        </span>
        {active && <div className="w-2 h-2 rounded-full bg-cyan-500 status-pulse" />}
      </div>
      <div ref={scrollRef} className="bg-[#07080c] max-h-32 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-[20px] scanline-overlay">
        {log.map((e, i) => {
          const last = i === log.length - 1;
          const s = STAGES[e.stage] || { l: '???', c: '#64748b' };
          return (
            <div key={i} className={last && active ? 'text-slate-200' : 'text-slate-400'}>
              <ChevronRight size={8} className="inline mr-0.5" style={{ color: last && active ? '#4ade80' : '#475569' }} />
              <span className="font-bold" style={{ color: s.c }}>[{s.l}]</span>{' '}{e.detail}
            </div>
          );
        })}
        {active && <span className="text-green-500 cursor-blink">_</span>}
      </div>
    </div>
  );
}

function getGlobalBounds(timelines, fundTermEndDate) {
  let minDate = null, maxDate = fundTermEndDate || null;
  const ic = timelines['fund_initial_closing_date'];
  if (ic?.length) { const v = ic[0].value || ic[0].date; minDate = typeof v === 'string' ? v : ic[0].date; }
  if (!maxDate) {
    const te = timelines['fund_term_end_date'];
    if (te?.length) { const v = te[te.length-1].value || te[te.length-1].date; maxDate = typeof v === 'string' ? v : te[te.length-1].date; }
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

function InlineTimelines({ timelines, constraints, fundTermEndDate }) {
  if (!timelines) return null;

  const fields = [...TIMELINE_FIELDS, ...Object.keys(timelines).filter(f => !TIMELINE_FIELDS.includes(f))]
    .filter(f => timelines[f]?.length > 0);

  if (fields.length === 0) return null;

  const bounds = getGlobalBounds(timelines, fundTermEndDate);

  return (
    <div className="rounded border border-white/[0.05] overflow-hidden">
      <div className="bg-[#08090d] px-3 py-1.5 flex items-center border-b border-white/[0.04]">
        <span className="section-label section-label-violet text-[9px] py-0">Timelines</span>
        <span className="text-[10px] text-slate-400 font-mono ml-2">{fields.length} fields</span>
      </div>
      <div className="bg-[#07080c] max-h-[280px] overflow-y-auto px-3 py-3 space-y-4">
        {fields.map(f => (
          <div key={f}>
            <div className="text-[10px] font-bold text-slate-600 uppercase tracking-wider mb-1.5">{fieldLabel(f)}</div>
            <TimelineChart entries={timelines[f]} fieldName={f}
              constraints={constraints?.[f] || []}
              globalMinDate={bounds.minDate} globalMaxDate={bounds.maxDate} />
          </div>
        ))}
      </div>
    </div>
  );
}

const SCENARIO_INFO = {
  mfn_flow: {
    title: 'MFN Election Chain',
    description: 'This inbox contains emails forming a Most Favored Nation election flow: GP disclosure, LP election, and GP confirmation.',
    lookFor: [
      'Elected terms only execute when the evaluation date is on or after the effective date specified in the GP confirmation, not the date the confirmation was sent.',
      'The CONFIRM stage in the terminal resolves the 3-document chain',
      'Fee timeline shifts from LPA baseline to elected terms once the effective date is reached',
      'Try setting the evaluation date before the effective date referenced in the GP confirmation to see elected terms remain unexecuted',
    ],
  },
  side_letter_flow: {
    title: 'Side Letter with Conditional Fee Reduction',
    description: 'A side letter defers the post-investment-period fee reduction until the earlier of (a) the 8th anniversary of final closing or (b) the fund reaching 50% realization. Both conditions resolve after IP end, so the engine holds the rate until one fires.',
    lookFor: [
      'Compound "earlier-of" condition mixing a fixed post-IP-end date and a dynamic fund metric. The engine resolves both and applies whichever fires first.',
      '(a) resolves to 2032-12-15 (2024-12-15 final closing + 8 years). (b) resolves to 2030-12-31 when Q4 2030 realization hits 62%. (b) wins by about two years.',
      'At IP end (2029-01-15), the LPA baseline would drop the rate from 2% to 1.5%. The side letter gates that reduction behind (a) or (b); neither has fired yet, so the engine correctly holds the rate at 2%.',
      'Try evaluation date 2029-06-01 (5 months past IP end, gate still closed, rate stays at 2%) and compare with 2031-02-01 (after (b) fires, gate opens, rate drops to 1.5%).',
    ],
  },
  multi_amendment: {
    title: 'Multi-Amendment Scenario',
    description: 'Three documents issued years apart: a fee cap side letter, a mid-life GP fee accommodation tied to the Investment Period end, and a later Investment Period extension. The extension silently stretches the waiver window, worth material additional savings a human reader could easily miss.',
    lookFor: [
      'Fee timeline shows three phases: 2% baseline, 1% waiver, capped post-IP rate',
      'Stability loop re-evaluates the waiver end date once the IP extension executes',
      'Slide the evaluation date across 2028-06-15 (IP extension signed) to watch the fee impact jump',
    ],
  },
};

function ScenarioCard({ packageId }) {
  const info = SCENARIO_INFO[packageId];
  if (!info) return null;

  return (
    <div className="rounded border border-cyan-500/10 bg-cyan-500/[0.03] px-4 py-3 mb-3">
      <h3 className="text-[10px] font-bold text-cyan-500 uppercase tracking-wider mb-1.5">{info.title}</h3>
      <p className="text-[12px] text-slate-400 leading-relaxed mb-2.5">{info.description}</p>
      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">What to look for</div>
      <ul className="space-y-1.5">
        {info.lookFor.map((item, i) => (
          <li key={i} className="text-[12px] text-slate-400 flex items-start gap-2 leading-relaxed">
            <div className="w-1.5 h-1.5 rounded-full bg-cyan-500/60 shrink-0 mt-1.5" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function InfoCards() {
  return (
    <div className="mt-4 space-y-3">
      <div className="rounded border border-white/[0.05] bg-white/[0.01] px-4 py-3">
        <h3 className="text-[10px] font-bold text-cyan-500 uppercase tracking-wider mb-2">What This Demo Verifies</h3>
        <p className="text-[12px] text-slate-400 leading-relaxed">
          The system reads all documents in the LP inbox, extracts fee-related clauses,
          builds a timeline of management fee changes, and calculates the exact fee for
          the billing period containing your evaluation date. Enter the GP's claimed fee
          to verify if it matches.
        </p>
        <p className="text-[12px] text-slate-400 leading-relaxed mt-2.5">
          Designed to work alongside portfolio management systems (Aladdin, Geneva, eFront) that handle
          structured data like cash flows and capital accounts. This system handles the unstructured
          side: interpreting legal documents that those systems can't process.
        </p>
      </div>

      <div className="rounded border border-white/[0.05] bg-white/[0.01] px-4 py-3">
        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Try It Out</h3>
        <ul className="space-y-1.5">
          {[
            ['Add emails', 'with side letters, fee waivers, or MFN elections to see how they affect fees'],
            ['Edit email content', 'or upload new PDF attachments to test different scenarios'],
            ['Delete documents', 'to see how removing a side letter changes the fee calculation'],
            ['Change the evaluation date', 'to see fees across different billing periods'],
            ['Enter a GP claimed fee', 'to verify whether the GP\'s capital call is correct'],
          ].map(([bold, rest], i) => (
            <li key={i} className="text-[12px] text-slate-500 flex items-start gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-500/50 shrink-0 mt-1.5" />
              <span><span className="text-slate-300 font-medium">{bold}</span> {rest}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded border border-white/[0.05] bg-white/[0.01] px-4 py-3">
        <h3 className="text-[10px] font-bold text-slate-300 uppercase tracking-wider mb-3">Seed Data (LPA Terms)</h3>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1">
          {[
            ['Fee rate (investment period)', '2.0%'],
            ['Fee rate (post investment)', '1.5%'],
            ['Basis (investment period)', 'Committed capital'],
            ['Basis (post investment)', 'Invested capital'],
            ['LP commitment', '$10,000,000'],
            ['Total fund size', '$50,000,000'],
            ['Initial closing', 'Jan 15, 2024'],
            ['Final closing', 'Dec 15, 2024'],
            ['Investment period end', 'Jan 15, 2029'],
            ['Fund term end', 'Jan 15, 2034'],
            ['Billing cadence', 'Quarterly'],
            ['Day count convention', 'Actual / 365'],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between py-0.5 border-b border-white/[0.03]">
              <span className="text-[11px] text-slate-400">{k}</span>
              <span className="text-[11px] text-slate-100 font-mono font-semibold">{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function EvalPanel({ onEvaluate, evaluating, result, progressLog, evalError, selectedPackage, emailsModified, onShowTimelines }) {
  const [evalDate, setEvalDate] = useState('2026-06-01');
  const [lpAdmission, setLpAdmission] = useState('');
  const [gpFee, setGpFee] = useState('');
  const formRef = useRef(null);

  // Ctrl+Enter keyboard shortcut to evaluate
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !evaluating) {
        e.preventDefault();
        onEvaluate(evalDate, lpAdmission || null, gpFee ? parseFloat(gpFee) : null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [evalDate, lpAdmission, gpFee, evaluating, onEvaluate]);

  return (
    <div className="p-4">
      {/* Section label */}
      <div className="flex items-center justify-between mb-3">
        <span className="section-label section-label-cyan">Evaluation Engine</span>
        <div className="flex items-center gap-1 text-[10px] text-slate-400">
          <Keyboard size={11} />
          <span className="kbd">Ctrl</span>+<span className="kbd">Enter</span>
          <span className="ml-1">to evaluate</span>
        </div>
      </div>

      {/* Compact form — single row */}
      <form ref={formRef}
        onSubmit={e => { e.preventDefault(); onEvaluate(evalDate, lpAdmission || null, gpFee ? parseFloat(gpFee) : null); }}
        className={`rounded border overflow-hidden mb-3 ${evaluating ? 'eval-active' : 'border-white/[0.05]'}`}>
        <div className="bg-[#08090d] px-3 py-3 flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-[9px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
              Eval Date
              <InputTooltip text="As-of date for fee verification. Only documents dated on or before this date are processed. Change this to check fees for any billing period." />
            </label>
            <input type="date" value={evalDate} onChange={e => setEvalDate(e.target.value)} required
              className="bb-input w-full" />
          </div>
          <div className="flex-1">
            <label className="block text-[9px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
              LP Admission
              <InputTooltip text="When this LP joined the fund. Leave blank if LP joined at initial closing (most common). Affects fee proration for the first billing period." />
            </label>
            <input type="date" value={lpAdmission} onChange={e => setLpAdmission(e.target.value)}
              className="bb-input w-full" />
          </div>
          <div className="flex-1">
            <label className="block text-[9px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
              GP Fee ($)
              <InputTooltip text="Optional. Enter the fee from the GP's capital call notice. The system calculates the correct fee independently and tells you if the GP's number matches." />
            </label>
            <input type="number" value={gpFee} onChange={e => setGpFee(e.target.value)}
              min="0" step="0.01" placeholder="49,863.01"
              className="bb-input w-full" />
          </div>
          <button type="submit" disabled={evaluating} className="bb-btn-primary shrink-0">
            {evaluating
              ? <><Loader2 size={12} className="animate-spin" /> Running</>
              : <><Play size={12} /> Evaluate</>
            }
          </button>
        </div>
      </form>

      {/* Scenario context card — shown while the inbox matches the seed scenario */}
      {selectedPackage && !emailsModified && (
        <ScenarioCard packageId={selectedPackage} />
      )}

      {/* Terminal */}
      <Terminal log={progressLog} active={evaluating} />

      {/* Evaluation error — inline */}
      {evalError && (
        <div className="mt-3 rounded border border-red-500/20 bg-red-500/[0.05] px-4 py-3">
          <div className="text-[10px] font-bold text-red-400 uppercase tracking-wider mb-1">Pipeline Error</div>
          <div className="text-[12px] text-red-300/80 font-mono leading-relaxed">{evalError}</div>
        </div>
      )}

      {/* Inline timelines — appear after evaluation */}
      {result?.timelines && (
        <div className="mt-3">
          <InlineTimelines timelines={result.timelines} constraints={result.constraints}
            fundTermEndDate={result.fund_term_end_date} />
        </div>
      )}

      {/* Guide + Seed Data — always shown */}
      {!evaluating && <InfoCards />}
    </div>
  );
}
