import { useState } from 'react';
import { ChevronDown, ChevronRight, Info, AlertTriangle, FileQuestion } from 'lucide-react';

function Section({ icon: Icon, title, items, color, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);

  if (!items || items.length === 0) return null;

  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full text-left group"
      >
        {open ? (
          <ChevronDown size={14} className="text-slate-400" />
        ) : (
          <ChevronRight size={14} className="text-slate-400" />
        )}
        <Icon size={13} className={color} />
        <span className="text-xs font-medium text-slate-600 group-hover:text-slate-900 transition-colors">
          {title}
        </span>
        <span className="text-[10px] text-slate-300 ml-1">({items.length})</span>
      </button>
      {open && (
        <ul className="mt-1.5 ml-7 space-y-1">
          {items.map((item, i) => (
            <li key={i} className="text-xs text-slate-500 leading-relaxed">
              {typeof item === 'string' ? item : (
                <>
                  {item.clause_text && (
                    <span className="font-medium text-slate-600">{item.clause_text.slice(0, 60)}...</span>
                  )}
                  {item.reason && <span className="text-slate-400 ml-1">- {item.reason}</span>}
                  {item.affected_field && (
                    <span className="ml-1 text-xs bg-slate-100 px-1.5 py-0.5 rounded text-slate-500">
                      {item.affected_field}
                    </span>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Assumptions({ assumptions, manualReview, unconfirmed, stats }) {
  return (
    <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/30">
      <Section
        icon={Info}
        title="Assumptions"
        items={assumptions}
        color="text-blue-500"
        defaultOpen
      />
      <Section
        icon={AlertTriangle}
        title="Manual Review Required"
        items={manualReview}
        color="text-amber-500"
      />
      <Section
        icon={FileQuestion}
        title="Unconfirmed Documents"
        items={unconfirmed}
        color="text-slate-400"
      />
    </div>
  );
}
