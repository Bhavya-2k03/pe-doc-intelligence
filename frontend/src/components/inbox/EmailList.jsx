import { useState } from 'react';
import { Plus, Inbox } from 'lucide-react';
import EmailRow from './EmailRow';
import EmailDetail from './EmailDetail';
import EmailEditor from './EmailEditor';

export default function EmailList({ emails, selectedId, onSelect, onUpdate, onDelete, onAdd, onOpenAttachment }) {
  const [showEditor, setShowEditor] = useState(false);
  const [editingEmail, setEditingEmail] = useState(null);
  const sorted = [...emails].sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));
  const selectedEmail = emails.find(e => e._id === selectedId);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-white/[0.05] flex items-center justify-between shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <span className="section-label section-label-cyan">LP Inbox</span>
            <span className="text-[11px] text-slate-700 font-mono">{emails.length}</span>
          </div>
          <p className="text-[10px] text-slate-500 mt-0.5 ml-0.5">GP / LP correspondence</p>
        </div>
        <button onClick={() => { setEditingEmail(null); setShowEditor(true); }}
          className="bb-btn-ghost">
          <Plus size={11} className="text-cyan-500" /> New
        </button>
      </div>

      {selectedEmail ? (
        <EmailDetail email={selectedEmail}
          onBack={() => onSelect(null)}
          onEdit={() => { setEditingEmail(selectedEmail); setShowEditor(true); }}
          onDelete={() => onDelete(selectedEmail._id)}
          onUpdate={(u) => onUpdate(selectedEmail._id, u)}
          onOpenAttachment={onOpenAttachment} />
      ) : (
        <div className="flex-1 overflow-y-auto">
          {sorted.length === 0
            ? (
              <div className="p-6 text-center">
                <Inbox size={24} className="text-slate-800 mx-auto mb-2" />
                <p className="text-[12px] text-slate-700">No documents loaded</p>
              </div>
            )
            : sorted.map(e => <EmailRow key={e._id} email={e}
                onClick={() => onSelect(e._id)}
                onEdit={() => { setEditingEmail(e); setShowEditor(true); }}
                onDelete={() => onDelete(e._id)} />)
          }
        </div>
      )}

      {showEditor && (
        <EmailEditor email={editingEmail}
          onSave={(data) => {
            if (editingEmail) onUpdate(editingEmail._id, data);
            else onAdd({ _id: `new_${Date.now()}`, ...data, attachments: data.attachments || [] });
            setShowEditor(false); setEditingEmail(null);
          }}
          onClose={() => { setShowEditor(false); setEditingEmail(null); }} />
      )}
    </div>
  );
}
