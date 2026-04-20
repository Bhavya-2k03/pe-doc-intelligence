import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, Monitor, ArrowLeft } from 'lucide-react';
import { startSession, evaluate } from '../api';
import StatusBar from '../components/shared/StatusBar';
import TickerBar from '../components/shared/TickerBar';
import EmailList from '../components/inbox/EmailList';
import EvalPanel from '../components/evaluation/EvalPanel';
import ResultsPanel from '../components/shared/ResultsPanel';
import TimelineModal from '../components/timeline/TimelineModal';
import PackageSelector from '../components/inbox/PackageSelector';
import AttachmentViewer from '../components/inbox/AttachmentViewer';

function MobileGate({ onBack }) {
  return (
    <div className="min-h-screen bg-[#06070b] flex flex-col items-center justify-center px-6 text-center">
      <div className="max-w-[360px]">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-cyan-500/10 border border-cyan-500/20 mb-5">
          <Monitor size={20} className="text-cyan-400" />
        </div>
        <div className="text-[10px] font-bold text-cyan-400 uppercase tracking-[0.25em] mb-3">truefee</div>
        <h1 className="text-[26px] font-semibold text-white tracking-tight mb-4 leading-tight">
          Built for desktop
        </h1>
        <p className="text-[14px] text-slate-500 leading-relaxed mb-7">
          The demo is a multi-panel workspace modeled on a Bloomberg terminal and needs more room than a phone screen.
          Open <span className="text-slate-300 font-mono">truefee.io</span> on a laptop to try it.
        </p>
        <button onClick={onBack}
          className="h-10 px-5 bg-white text-[#0a0a0f] text-[14px] font-medium rounded-md
            hover:bg-slate-200 transition active:scale-[0.97] inline-flex items-center gap-2">
          <ArrowLeft size={15} /> Read the overview
        </button>
      </div>
    </div>
  );
}

export default function Demo() {
  const navigate = useNavigate();
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches
  );
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)');
    const onChange = (e) => setIsMobile(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  const [sessionId, setSessionId] = useState(null);
  const [selectedPackage, setSelectedPackage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [emails, setEmails] = useState([]);
  const [selectedEmailId, setSelectedEmailId] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [result, setResult] = useState(null);
  const [showTimelines, setShowTimelines] = useState(false);
  const [viewerAttachment, setViewerAttachment] = useState(null);
  const [progressLog, setProgressLog] = useState([]);
  const [evalError, setEvalError] = useState(null);

  // ── Package selection → start session ───────────────────────────
  const handlePackageSelect = useCallback(async (packageId) => {
    setLoading(true);
    setError(null);
    setSelectedPackage(packageId);
    try {
      const data = await startSession(packageId);
      setSessionId(data.session_id);
      setEmails(data.emails || []);
      // Clear any stale localStorage dev data
      localStorage.removeItem('test_emails');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const [emailsModified, setEmailsModified] = useState(false);
  const updateEmail = useCallback((id, u) => { setEmails(p => p.map(e => e._id === id ? { ...e, ...u } : e)); setEmailsModified(true); }, []);
  const deleteEmail = useCallback((id) => { setEmails(p => p.filter(e => e._id !== id)); if (selectedEmailId === id) setSelectedEmailId(null); setEmailsModified(true); }, [selectedEmailId]);
  const addEmail = useCallback((e) => { setEmails(p => [...p, e]); setEmailsModified(true); }, []);

  const handleEvaluate = useCallback(async (evalDate, lpAdmission, gpFee) => {
    if (!sessionId) return;
    setEvaluating(true); setResult(null); setProgressLog([]); setEvalError(null);
    try {
      const res = await evaluate(sessionId, {
        evaluation_date: evalDate, lp_admission_date: lpAdmission || null,
        gp_claimed_fee: gpFee || null, email_dataset: emails,
      }, (p) => setProgressLog(prev => {
        const last = prev[prev.length - 1];
        return (last?.stage === p.stage) ? [...prev.slice(0, -1), p] : [...prev, p];
      }));
      setResult(res);
    } catch (e) { setEvalError(e.message); }
    finally { setEvaluating(false); }
  }, [sessionId, emails]);

  // Keyboard shortcut: Escape to close timeline modal
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape' && showTimelines) setShowTimelines(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showTimelines]);

  // ── Mobile gate ─────────────────────────────────────────────────
  if (isMobile) return <MobileGate onBack={() => navigate('/')} />;

  // ── Error state ─────────────────────────────────────────────────
  if (error) return (
    <div className="min-h-screen flex items-center justify-center bg-[#06070b]">
      <div className="text-center">
        <div className="text-[13px] text-red-400 font-mono mb-2">CONNECTION ERROR</div>
        <div className="text-[12px] text-slate-600">{error}</div>
        <button onClick={() => { setError(null); setSelectedPackage(null); }}
          className="mt-4 bb-btn-ghost">Retry</button>
      </div>
    </div>
  );

  // ── Package selection (before session starts) ──────────────────
  if (!sessionId) return (
    <div className="h-screen bg-[#06070b] flex flex-col overflow-hidden">
      <StatusBar sessionId={null} evaluating={false} onBack={() => navigate('/')} />
      <div className="flex-1 flex items-center justify-center">
        {loading ? (
          <div className="flex flex-col items-center gap-3">
            <Loader2 size={16} className="animate-spin text-cyan-500" />
            <span className="text-[13px] text-slate-500 font-mono uppercase tracking-wider">Loading scenario</span>
          </div>
        ) : (
          <PackageSelector onSelect={handlePackageSelect} loading={loading} />
        )}
      </div>
      <TickerBar />
    </div>
  );

  // ── Main workspace ─────────────────────────────────────────────
  return (
    <div className="h-screen bg-[#06070b] flex flex-col overflow-hidden">
      {/* Status Bar */}
      <StatusBar sessionId={sessionId} evaluating={evaluating} onBack={() => navigate('/')} />

      {/* Main 3-panel workspace. Panel widths step up at 2xl (\u22651536px).
          Below 2xl (e.g. 1280px laptops) we use narrower panels so the
          center evaluation panel keeps enough breathing room. */}
      <div className="flex flex-1 min-h-0">
        {/* Left: Documents */}
        <div className="w-[272px] 2xl:w-[320px] panel-solid border-r border-white/[0.05] flex flex-col shrink-0">
          <EmailList emails={emails} selectedId={selectedEmailId}
            onSelect={setSelectedEmailId} onUpdate={updateEmail}
            onDelete={deleteEmail} onAdd={addEmail}
            onOpenAttachment={setViewerAttachment} />
        </div>

        {/* Center: Evaluation Engine */}
        <div className="flex-1 min-w-0 overflow-y-auto panel-bg">
          <EvalPanel onEvaluate={handleEvaluate} evaluating={evaluating}
            result={result} progressLog={progressLog} evalError={evalError}
            selectedPackage={selectedPackage} emailsModified={emailsModified}
            onShowTimelines={() => setShowTimelines(true)} />
        </div>

        {/* Right: Analysis & Results */}
        <div className="w-[400px] 2xl:w-[480px] panel-solid border-l border-white/[0.05] flex flex-col shrink-0 overflow-hidden">
          <ResultsPanel result={result} onShowTimelines={() => setShowTimelines(true)} />
        </div>
      </div>

      {/* LPA Ticker Bar */}
      <TickerBar />

      {/* Timeline Modal (fullscreen) */}
      {showTimelines && result?.timelines && (
        <TimelineModal timelines={result.timelines} constraints={result.constraints}
          fundTermEndDate={result.fund_term_end_date} onClose={() => setShowTimelines(false)} />
      )}

      {/* Attachment Viewer Modal */}
      <AttachmentViewer attachment={viewerAttachment} onClose={() => setViewerAttachment(null)} />
    </div>
  );
}
