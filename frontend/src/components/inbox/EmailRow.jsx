import { Mail, Send, Pencil, Trash2, Paperclip } from 'lucide-react';

function getDocType(subject) {
  const s = (subject || '').toLowerCase();
  if (s.includes('side letter')) return { label: 'SL', color: 'text-cyan-400 bg-cyan-500/10' };
  if (s.includes('capital call')) return { label: 'CC', color: 'text-amber-400 bg-amber-500/10' };
  if (s.includes('mfn') || s.includes('most favored')) return { label: 'MFN', color: 'text-violet-400 bg-violet-500/10' };
  if (s.includes('subscription')) return { label: 'SUB', color: 'text-emerald-400 bg-emerald-500/10' };
  if (s.includes('report') || s.includes('notice')) return { label: 'RPT', color: 'text-blue-400 bg-blue-500/10' };
  if (s.includes('amendment')) return { label: 'AMD', color: 'text-rose-400 bg-rose-500/10' };
  if (s.includes('confirm')) return { label: 'CNF', color: 'text-emerald-400 bg-emerald-500/10' };
  return { label: 'DOC', color: 'text-slate-400 bg-white/[0.04]' };
}

export default function EmailRow({ email, onClick, onEdit, onDelete }) {
  const isSent = email.direction === 'sent';
  const dateStr = email.date ? new Date(email.date).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: '2-digit'
  }) : '';
  const attCount = (email.attachments || []).length;
  const docType = getDocType(email.subject);

  return (
    <div className="group px-3 py-2.5 border-b border-white/[0.025] hover:bg-white/[0.025] cursor-pointer transition"
      onClick={onClick}>
      <div className="flex items-center gap-2.5">
        {/* Type badge */}
        <span className={`doc-badge ${docType.color} shrink-0 w-8 text-center`}>{docType.label}</span>

        {/* Direction icon */}
        <div className={`w-6 h-6 rounded flex items-center justify-center shrink-0 ${
          isSent ? 'bg-emerald-500/10 text-emerald-500' : 'bg-white/[0.04] text-slate-600'
        }`}>
          {isSent ? <Send size={11} /> : <Mail size={11} />}
        </div>

        {/* Subject + meta */}
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium text-slate-300 truncate leading-tight">
            {email.subject || '(no subject)'}
          </div>
          <div className="flex items-center gap-2 text-[11px] text-slate-600 mt-0.5">
            <span className="font-mono">{dateStr}</span>
            {attCount > 0 && (
              <span className="flex items-center gap-0.5 text-cyan-600">
                <Paperclip size={9} />{attCount}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition shrink-0">
          <button onClick={e => { e.stopPropagation(); onEdit(); }}
            className="p-1 rounded hover:bg-white/10 text-slate-700 hover:text-slate-300 transition">
            <Pencil size={12} />
          </button>
          <button onClick={e => { e.stopPropagation(); onDelete(); }}
            className="p-1 rounded hover:bg-red-500/10 text-slate-700 hover:text-red-400 transition">
            <Trash2 size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}
