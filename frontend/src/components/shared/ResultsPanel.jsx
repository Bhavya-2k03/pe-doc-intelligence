import { useState, useEffect } from 'react';
import { ChevronDown, ChevronRight, Info, AlertTriangle, FileQuestion, BarChart3, Maximize2, Shield } from 'lucide-react';
import FeeVerdict from '../evaluation/FeeVerdict';
import FeeBreakdown from '../evaluation/FeeBreakdown';

function CollapsibleSection({ title, icon: Icon, color, count, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 w-full text-left py-1.5 group">
        {open
          ? <ChevronDown size={12} className="text-slate-600" />
          : <ChevronRight size={12} className="text-slate-600" />
        }
        <Icon size={12} className={color} />
        <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider group-hover:text-slate-400 transition">
          {title}
        </span>
        {count != null && (
          <span className="text-[10px] font-mono text-slate-700 ml-auto">{count}</span>
        )}
      </button>
      {open && <div className="ml-5 mt-1">{children}</div>}
    </div>
  );
}

export default function ResultsPanel({ result, onShowTimelines }) {
  // Pulse the Fullscreen Timelines button for a few seconds after a
  // result arrives — draws reviewer's eye to the in-app timeline view
  // so they don't miss it when scenario card + fee breakdown fill the
  // visible area.
  const [pulseTimelines, setPulseTimelines] = useState(false);
  useEffect(() => {
    if (!result) return;
    setPulseTimelines(true);
    const t = setTimeout(() => setPulseTimelines(false), 4000);
    return () => clearTimeout(t);
  }, [result]);

  if (!result) {
    return (
      <div className="h-full flex flex-col items-center justify-center px-6 text-center">
        <div className="w-12 h-12 rounded-lg bg-white/[0.02] border border-white/[0.05] flex items-center justify-center mb-3">
          <BarChart3 size={20} className="text-slate-700" />
        </div>
        <p className="text-[13px] text-slate-600 font-medium">Analysis Results</p>
        <p className="text-[11px] text-slate-650 mt-1">Run evaluation to see fee verification,<br />breakdowns, and timeline analysis</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-3 space-y-3">
        {/* Section header */}
        <div className="flex items-center justify-between">
          <span className="section-label section-label-emerald">Analysis</span>
        </div>

        {/* Fee Verdict — dominant */}
        {result.fee_verdict && <FeeVerdict verdict={result.fee_verdict} />}

        {/* View Timelines button */}
        <button onClick={onShowTimelines}
          className={`w-full bb-btn-ghost justify-center gap-2 transition-all ${
            pulseTimelines
              ? 'ring-2 ring-cyan-500/60 animate-pulse shadow-[0_0_16px_rgba(34,211,238,0.35)]'
              : ''
          }`}>
          <Maximize2 size={12} className="text-cyan-500" />
          <span>Fullscreen Timelines</span>
        </button>

        <div className="bloomberg-divider" />

        {/* Fee Breakdown */}
        {result.fee_calculation && (
          <CollapsibleSection title="Fee Breakdown" icon={BarChart3} color="text-cyan-500" defaultOpen>
            <FeeBreakdown fee={result.fee_calculation} />
          </CollapsibleSection>
        )}

        <div className="bloomberg-divider" />

        {/* Assumptions */}
        {result.assumptions?.length > 0 && (
          <CollapsibleSection title="Assumptions" icon={Info} color="text-blue-500"
            count={result.assumptions.length} defaultOpen>
            <div className="space-y-1.5">
              {result.assumptions.map((a, i) => (
                <div key={i} className="text-[11px] text-slate-400 flex items-start gap-1.5 leading-relaxed">
                  <div className="w-1 h-1 rounded-full bg-blue-500/40 shrink-0 mt-2" />
                  {a}
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}

        {/* Manual Review */}
        {result.manual_review_items?.length > 0 && (
          <>
            <div className="bloomberg-divider" />
            <CollapsibleSection title="Manual Review" icon={AlertTriangle} color="text-amber-500"
              count={result.manual_review_items.length} defaultOpen>
              <div className="space-y-2">
                {result.manual_review_items.map((m, i) => (
                  <div key={i} className="px-2.5 py-2 rounded bg-amber-500/[0.04] border border-amber-500/[0.08]">
                    <div className="flex items-center gap-1 mb-1">
                      <span className="doc-badge bg-amber-500/10 text-amber-400">{m.affected_field}</span>
                    </div>
                    <p className="text-[11px] text-amber-500/60 leading-relaxed">{m.reason}</p>
                  </div>
                ))}
              </div>
            </CollapsibleSection>
          </>
        )}

        {/* Active Constraints */}
        {result.constraints && Object.keys(result.constraints).length > 0 && (
          <>
            <div className="bloomberg-divider" />
            <CollapsibleSection title="Active Constraints" icon={Shield} color="text-amber-500"
              count={Object.values(result.constraints).reduce((sum, arr) => sum + arr.length, 0)} defaultOpen>
              <div className="space-y-2">
                {Object.entries(result.constraints).map(([field, fieldConstraints]) =>
                  fieldConstraints.map((c, i) => (
                    <div key={`${field}-${i}`} className="px-2.5 py-2 rounded bg-white/[0.02] border border-white/[0.04]">
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className={`doc-badge ${c.type === 'CAP' ? 'bg-red-500/10 text-red-400' : 'bg-green-500/10 text-green-400'}`}>
                          {c.type}
                        </span>
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">
                          {field.replace(/_/g, ' ')}
                        </span>
                        <span className="text-[11px] font-mono text-slate-300 ml-auto font-bold">
                          {typeof c.bound === 'number' && c.bound < 100 ? `${c.bound}%` : c.bound}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-600 space-y-0.5">
                        {c.active_from && <span>From <span className="font-mono text-slate-500">{c.active_from}</span></span>}
                        {c.active_from && c.active_until && <span> to </span>}
                        {c.active_until && <span>Until <span className="font-mono text-slate-500">{c.active_until}</span></span>}
                        {!c.active_from && !c.active_until && <span>Always active</span>}
                      </div>
                      {c.source && (
                        <div className="text-[10px] text-slate-500 italic mt-1 leading-relaxed truncate">{c.source.slice(0, 80)}</div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </CollapsibleSection>
          </>
        )}

        {/* Unconfirmed Documents */}
        {result.unconfirmed_documents?.length > 0 && (
          <>
            <div className="bloomberg-divider" />
            <CollapsibleSection title="Unconfirmed" icon={FileQuestion} color="text-slate-500"
              count={result.unconfirmed_documents.length}>
              <div className="space-y-1.5">
                {result.unconfirmed_documents.map((d, i) => (
                  <div key={i} className="text-[11px] text-slate-400 flex items-start gap-2 leading-relaxed">
                    <div className="w-1 h-1 rounded-full bg-slate-600 shrink-0 mt-2" />
                    <span>{typeof d === 'string' ? d : (d.clause_text || d.subject || '')}</span>
                  </div>
                ))}
              </div>
            </CollapsibleSection>
          </>
        )}
      </div>
    </div>
  );
}
