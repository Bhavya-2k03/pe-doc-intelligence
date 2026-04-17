import { ArrowLeft, Pencil, Trash2, Upload, X, FileText } from 'lucide-react';
import { fileToBase64 } from '../../api';

export default function EmailDetail({ email, onBack, onEdit, onDelete, onUpdate, onOpenAttachment }) {
  const handleUpload = async () => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.pdf';
    input.onchange = async (e) => {
      const file = e.target.files[0]; if (!file) return;
      const base64 = await fileToBase64(file);
      onUpdate({ attachments: [...(email.attachments || []), {
        name: file.name, attachment_index: (email.attachments || []).length,
        file_id: null, file_data: base64,
      }]});
    };
    input.click();
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-white/[0.05] flex items-center gap-2 shrink-0">
        <button onClick={onBack} className="p-1 rounded hover:bg-white/5 text-slate-600">
          <ArrowLeft size={14} />
        </button>
        <div className="flex-1 min-w-0">
          <h3 className="text-[13px] font-bold text-slate-300 truncate">{email.subject}</h3>
          <span className="text-[10px] text-slate-600 font-mono">
            {email.direction === 'sent' ? 'SENT' : 'RECV'} {email.date ? new Date(email.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' }) : ''}
          </span>
        </div>
        <button onClick={onEdit} className="p-1 rounded hover:bg-white/5 text-slate-700 hover:text-slate-400">
          <Pencil size={12} />
        </button>
        <button onClick={onDelete} className="p-1 rounded hover:bg-red-500/10 text-slate-700 hover:text-red-400">
          <Trash2 size={12} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="text-[12px] text-slate-500 whitespace-pre-wrap leading-relaxed font-mono">
          {email.body || '(empty)'}
        </div>
      </div>

      {/* Attachments */}
      <div className="px-3 py-2.5 border-t border-white/[0.05] shrink-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">
            Attachments ({(email.attachments || []).length})
          </span>
          <button onClick={handleUpload} className="bb-btn-ghost h-6 text-[9px] px-2">
            <Upload size={10} className="text-cyan-500" /> PDF
          </button>
        </div>
        {(email.attachments || []).length === 0
          ? <p className="text-[11px] text-slate-700">None</p>
          : <div className="space-y-1">
              {(email.attachments || []).map(att => (
                <div key={att.attachment_index}
                  className="group flex items-center gap-2 px-2.5 py-1.5 bg-white/[0.02] border border-white/[0.04] rounded text-[11px]">
                  <FileText size={12} className="text-slate-600 shrink-0" />
                  <button onClick={() => onOpenAttachment?.(att)}
                    className="text-slate-400 hover:text-cyan-400 transition truncate max-w-[160px] text-left">
                    {att.name}
                  </button>
                  <button onClick={() => onUpdate({ attachments: (email.attachments || []).filter(a => a.attachment_index !== att.attachment_index) })}
                    className="p-0.5 rounded text-slate-800 hover:text-red-400 opacity-0 group-hover:opacity-100 transition ml-auto">
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
        }
      </div>
    </div>
  );
}
