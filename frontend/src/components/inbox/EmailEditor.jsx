import { useState, useRef, useEffect } from 'react';
import { X, Mail, Send, Upload, FileText, Trash2, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { fileToBase64 } from '../../api';

export default function EmailEditor({ email, onSave, onClose }) {
  const isNew = !email;
  const [subject, setSubject] = useState(email?.subject || '');
  const [body, setBody] = useState(email?.body || '');
  const [date, setDate] = useState(email?.date ? email.date.split('T')[0] : new Date().toISOString().split('T')[0]);
  const [direction, setDirection] = useState(email?.direction || 'received');
  const [attachments, setAttachments] = useState(email?.attachments || []);
  const [uploading, setUploading] = useState(false);
  const [justAdded, setJustAdded] = useState(null);
  // `attempted` flips to true on first Save click; after that, empty-field
  // errors render inline and block save until the user fills both fields.
  const [attempted, setAttempted] = useState(false);
  const scrollRef = useRef(null);

  const subjectError = attempted && !subject.trim() ? 'Subject is required' : null;
  const bodyError = attempted && !body.trim() ? 'Body is required' : null;

  const handleSave = () => {
    setAttempted(true);
    if (!subject.trim() || !body.trim()) return;
    onSave({ subject, body, date: date + 'T00:00:00Z', direction, attachments });
  };

  // Auto-scroll modal to bottom when a new attachment is added
  useEffect(() => {
    if (justAdded != null && scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [justAdded]);

  const handleUpload = async () => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.pdf';
    input.onchange = async (e) => {
      const file = e.target.files[0]; if (!file) return;
      setUploading(true);
      try {
        const b64 = await fileToBase64(file);
        setAttachments(prev => {
          const newIdx = prev.length;
          setJustAdded(newIdx);
          setTimeout(() => setJustAdded(null), 2000);
          return [...prev, {
            name: file.name, attachment_index: newIdx,
            file_id: null, file_data: b64,
          }];
        });
      } finally {
        setUploading(false);
      }
    };
    input.click();
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-[#0c0d13] border border-white/[0.08] rounded w-full max-w-md shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.05]">
          <span className="section-label section-label-cyan">{isNew ? 'New Document' : 'Edit Document'}</span>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/5 text-slate-600">
            <X size={14} />
          </button>
        </div>

        <div ref={scrollRef} className="p-4 space-y-3.5 max-h-[65vh] overflow-y-auto">
          {/* Direction */}
          <div>
            <label className="block text-[9px] font-bold text-slate-600 uppercase tracking-wider mb-1.5">Direction</label>
            <div className="flex gap-2">
              {[['received', Mail, 'Received (GP\u2192LP)'], ['sent', Send, 'Sent (LP\u2192GP)']].map(([d, Icon, label]) => (
                <button key={d} type="button" onClick={() => setDirection(d)}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded text-[12px] font-medium transition ${
                    direction === d
                      ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/25'
                      : 'bg-white/[0.02] text-slate-600 border border-white/[0.05] hover:border-white/10'
                  }`}>
                  <Icon size={12} /> {label}
                </button>
              ))}
            </div>
          </div>

          {/* Subject */}
          <div>
            <label className="block text-[9px] font-bold text-slate-600 uppercase tracking-wider mb-1.5">Subject</label>
            <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Document subject..."
              className={`bb-input w-full ${subjectError ? 'border-red-500/50' : ''}`} />
            {subjectError && (
              <p className="mt-1 text-[11px] text-red-400 flex items-center gap-1">
                <AlertCircle size={11} /> {subjectError}
              </p>
            )}
          </div>

          {/* Date */}
          <div>
            <label className="block text-[9px] font-bold text-slate-600 uppercase tracking-wider mb-1.5">Date</label>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
              className="bb-input w-full" />
          </div>

          {/* Body */}
          <div>
            <label className="block text-[9px] font-bold text-slate-600 uppercase tracking-wider mb-1.5">Body</label>
            <textarea value={body} onChange={e => setBody(e.target.value)} rows={5} placeholder="Email body..."
              className={`bb-input w-full h-auto py-2 resize-none leading-relaxed ${bodyError ? 'border-red-500/50' : ''}`}
              style={{ height: 'auto' }} />
            {bodyError && (
              <p className="mt-1 text-[11px] text-red-400 flex items-center gap-1">
                <AlertCircle size={11} /> {bodyError}
              </p>
            )}
          </div>

          {/* LLM hint */}
          <div className="px-3 py-2.5 rounded bg-cyan-500/[0.05] border border-cyan-500/[0.12] text-[11px] text-slate-300 leading-relaxed">
            <span className="text-cyan-400 font-bold">Tip:</span> Use PE-standard language for best results.
            Subjects like <span className="text-slate-100 font-medium">"Side Letter Amendment"</span> or <span className="text-slate-100 font-medium">"Fee Terms Update"</span> help
            the system identify document intent. Body text with governing language
            (<span className="text-slate-100 font-medium">"shall be"</span>, <span className="text-slate-100 font-medium">"effective from"</span>, <span className="text-slate-100 font-medium">"is hereby amended"</span>) ensures
            clauses are correctly extracted.
          </div>

          {/* Attachments */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[9px] font-bold text-slate-600 uppercase tracking-wider">Attachments</label>
              <button type="button" onClick={handleUpload} disabled={uploading} className="bb-btn-ghost h-6 text-[9px] px-2">
                {uploading
                  ? <><Loader2 size={10} className="animate-spin text-cyan-500" /> Processing</>
                  : <><Upload size={10} className="text-cyan-500" /> PDF</>
                }
              </button>
            </div>
            {attachments.length === 0
              ? <p className="text-[11px] text-slate-700">No attachments</p>
              : <div className="space-y-1">
                  {attachments.map((a, i) => (
                    <div key={i} className={`flex items-center gap-2 px-2.5 py-1.5 rounded text-[11px] transition-all duration-500 ${
                      justAdded === i
                        ? 'bg-cyan-500/10 border border-cyan-500/25'
                        : 'bg-white/[0.02] border border-white/[0.04]'
                    }`}>
                      {justAdded === i
                        ? <CheckCircle size={12} className="text-cyan-500 shrink-0" />
                        : <FileText size={12} className="text-slate-600 shrink-0" />
                      }
                      <span className="flex-1 text-slate-400 truncate">{a.name}</span>
                      <button type="button" onClick={() => setAttachments(p => p.filter((_, j) => j !== i))}
                        className="text-slate-700 hover:text-red-400 transition"><Trash2 size={11} /></button>
                    </div>
                  ))}
                </div>
            }
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-white/[0.05] flex justify-end gap-2">
          <button onClick={onClose} className="bb-btn-ghost">Cancel</button>
          <button onClick={handleSave} className="bb-btn-primary">
            {isNew ? 'Add' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
