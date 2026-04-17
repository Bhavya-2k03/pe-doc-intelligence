import { useState, useEffect, useMemo, useRef } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { X, ChevronLeft, ChevronRight, FileText, Loader2, AlertCircle } from 'lucide-react';
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import { attachmentUrl } from '../../api';

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

function base64ToUint8Array(b64) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

export default function AttachmentViewer({ attachment, onClose }) {
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [loadError, setLoadError] = useState(null);
  const [pageWidth, setPageWidth] = useState(800);
  const bodyRef = useRef(null);

  // Reset state when attachment changes
  useEffect(() => {
    setNumPages(null);
    setPageNumber(1);
    setLoadError(null);
  }, [attachment]);

  // Esc to close
  useEffect(() => {
    if (!attachment) return;
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight' && numPages && pageNumber < numPages) {
        setPageNumber(p => p + 1);
      } else if (e.key === 'ArrowLeft' && pageNumber > 1) {
        setPageNumber(p => p - 1);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [attachment, numPages, pageNumber, onClose]);

  // Fit page to container width
  useEffect(() => {
    if (!bodyRef.current) return;
    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        // leave 40px padding
        setPageWidth(Math.max(200, Math.floor(w - 40)));
      }
    });
    observer.observe(bodyRef.current);
    return () => observer.disconnect();
  }, [attachment]);

  // Memoize source so react-pdf doesn't re-fetch on every render
  const source = useMemo(() => {
    if (!attachment) return null;
    if (attachment.file_id) return attachmentUrl(attachment.file_id);
    if (attachment.file_data) return { data: base64ToUint8Array(attachment.file_data) };
    return null;
  }, [attachment]);

  if (!attachment) return null;

  return (
    <div
      className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-[#0a0b10] border border-white/[0.08] rounded w-full max-w-5xl max-h-[90vh] flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/[0.05] shrink-0 gap-4">
          <div className="flex items-center gap-2 min-w-0">
            <FileText size={14} className="text-slate-500 shrink-0" />
            <span className="text-[13px] text-slate-300 truncate font-mono">{attachment.name}</span>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {numPages && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPageNumber(p => Math.max(1, p - 1))}
                  disabled={pageNumber <= 1}
                  className="p-1 rounded hover:bg-white/5 text-slate-500 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <ChevronLeft size={14} />
                </button>
                <span className="text-[11px] text-slate-500 font-mono tabular-nums">
                  {pageNumber} / {numPages}
                </span>
                <button
                  onClick={() => setPageNumber(p => Math.min(numPages, p + 1))}
                  disabled={pageNumber >= numPages}
                  className="p-1 rounded hover:bg-white/5 text-slate-500 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            )}
            <span className="text-[10px] text-slate-400 font-mono font-semibold uppercase tracking-wider hidden sm:inline">
              Esc to close
            </span>
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-white/5 text-slate-500 hover:text-slate-300"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div ref={bodyRef} className="flex-1 overflow-y-auto bg-[#06070b] flex flex-col items-center py-5">
          {loadError ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <AlertCircle size={20} className="text-red-400" />
              <span className="text-[13px] text-red-400 font-mono">Failed to load PDF</span>
              <span className="text-[11px] text-slate-600">{loadError}</span>
            </div>
          ) : (
            <Document
              file={source}
              onLoadSuccess={({ numPages: n }) => setNumPages(n)}
              onLoadError={(err) => setLoadError(err?.message || 'Unknown error')}
              loading={
                <div className="flex flex-col items-center gap-2 py-16">
                  <Loader2 size={16} className="animate-spin text-cyan-500" />
                  <span className="text-[11px] text-slate-600 font-mono uppercase tracking-wider">Loading</span>
                </div>
              }
              error={null}
            >
              <Page
                pageNumber={pageNumber}
                width={pageWidth}
                renderTextLayer
                renderAnnotationLayer={false}
              />
            </Document>
          )}
        </div>
      </div>
    </div>
  );
}
