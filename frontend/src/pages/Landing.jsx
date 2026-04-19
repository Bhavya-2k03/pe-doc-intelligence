import { useNavigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { ArrowRight, FileSearch, Brain, CheckCircle2, ChevronRight, Zap } from 'lucide-react';
import { ProblemFigure, ExtractFigure, InterpretFigure, VerifyFigure } from '../components/landing/Illustrations';
import { HeroScanGrid, SectionLabel, PipelineThread, StatBaseline } from '../components/landing/Premium';

/* ── Terminal mockup ───────────────────────────────────────────────────── */
function TerminalDemo() {
  const lines = [
    { tag: 'PARSE', color: '#22d3ee', text: 'Parsing side_letter_acme_2025.pdf' },
    { tag: 'EXTRACT', color: '#60a5fa', text: '3 fee clauses, 2 date conditions found' },
    { tag: 'INTERPRET', color: '#a78bfa', text: 'SET management_fee_rate = 1.75%' },
    { tag: 'INTERPRET', color: '#a78bfa', text: 'GATE fee reduction POSTPONE to 2029-06-15' },
    { tag: 'RESOLVE', color: '#fbbf24', text: 'ANNIVERSARY(2, fund_final_closing_date) \u2192 2026-12-15' },
    { tag: 'EXECUTE', color: '#fb7185', text: 'management_fee_rate [2024-01-15, 2029-06-15) = 1.75%' },
    { tag: 'CALC', color: '#4ade80', text: '$43,630.14 (91d @ 1.75% on $10M committed)' },
    { tag: 'DONE', color: '#86efac', text: '\u2713 Verified | \u0394 $0.00' },
  ];

  return (
    <div className="rounded-xl border border-white/[0.06] overflow-hidden">
      <div className="bg-[#0c0d12] px-4 py-2.5 flex items-center border-b border-white/[0.04]">
        <div className="flex gap-1.5 mr-3">
          <div className="w-2.5 h-2.5 rounded-full bg-white/[0.06]" />
          <div className="w-2.5 h-2.5 rounded-full bg-white/[0.06]" />
          <div className="w-2.5 h-2.5 rounded-full bg-white/[0.06]" />
        </div>
        <span className="text-[10px] text-slate-700 font-mono">evaluation pipeline</span>
      </div>
      <div className="bg-[#08090d] px-5 py-4 font-mono text-[11px] leading-[22px] text-left">
        {lines.map((line, i) => (
          <div key={i} className="fade-up" style={{ animationDelay: `${0.8 + i * 0.2}s`, opacity: 0 }}>
            <span className="text-slate-800 mr-1">$</span>
            <span className="font-bold" style={{ color: line.color }}>[{line.tag}]</span>
            <span className="text-slate-500"> {line.text}</span>
          </div>
        ))}
        <span className="text-slate-600 cursor-blink">_</span>
      </div>
    </div>
  );
}

/* ── Main Landing ──────────────────────────────────────────────────────── */
export default function Landing() {
  const navigate = useNavigate();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white">

      {/* ═══ Nav ═══ */}
      <nav className={`fixed top-0 w-full z-50 backdrop-blur-xl transition-all duration-300 ease-out
        ${scrolled
          ? 'bg-[#0a0a0f]/85 border-b border-white/[0.05] shadow-[0_1px_0_0_rgba(255,255,255,0.02)]'
          : 'bg-[#0a0a0f]/40 border-b border-transparent'
        }`}>
        <div className="max-w-[1080px] mx-auto px-6 h-14 flex items-center justify-between">
          <span className="text-[15px] font-semibold text-white">PE Doc <span className="text-cyan-500">Intelligence</span></span>
          <button onClick={() => navigate('/demo')}
            className="h-8 px-4 bg-white text-[#0a0a0f] text-[13px] font-medium rounded-md
              hover:bg-slate-200 transition active:scale-[0.97]">
            Get started
          </button>
        </div>
      </nav>

      {/* ═══ Hero ═══ */}
      <section className="relative pt-40 pb-6 px-6 overflow-hidden">
        <HeroScanGrid />
        <div className="relative max-w-[1080px] mx-auto flex gap-16 items-start">
          {/* Left: headline + copy */}
          <div className="flex-1 max-w-[560px]">
            <h1 className="fade-up text-[52px] md:text-[64px] font-semibold tracking-[-0.035em] leading-[1.05]">
              Every side letter read.
              <br />
              <span className="text-slate-500">Every fee verified.</span>
            </h1>
            <p className="fade-up fade-up-delay-1 mt-6 text-[17px] text-slate-400 leading-relaxed max-w-[480px]">
              Your operations team spends hours piecing together side letters, MFN elections,
              and fee amendments to verify a single capital call. This system understands how
              those clauses interact, builds the fee timeline, and computes exactly what the
              GP should be charging.
            </p>
            <div className="fade-up fade-up-delay-2 mt-10 flex items-center gap-4">
              <button onClick={() => navigate('/demo')}
                className="h-10 px-5 bg-white text-[#0a0a0f] text-[14px] font-medium rounded-md
                  hover:bg-slate-200 transition active:scale-[0.97] flex items-center gap-2">
                Try the demo <ArrowRight size={15} />
              </button>
              <span className="text-[13px] text-slate-700">No login required</span>
            </div>
          </div>
          {/* Right: terminal */}
          <div className="flex-1 max-w-[480px] fade-up fade-up-delay-3 hidden lg:block">
            <TerminalDemo />
          </div>
        </div>
      </section>

      {/* Terminal for smaller screens */}
      <section className="pt-8 pb-20 px-6 lg:hidden">
        <div className="max-w-[560px] mx-auto fade-up fade-up-delay-3">
          <TerminalDemo />
        </div>
      </section>

      {/* ═══ Problem statement ═══ */}
      <section className="py-24 px-6 border-t border-white/[0.04]">
        <div className="max-w-[1080px] mx-auto flex gap-12 items-center">
          {/* Left: text */}
          <div className="flex-1 max-w-[520px]">
            <SectionLabel>The problem</SectionLabel>
            <h2 className="text-[32px] font-semibold text-white tracking-tight leading-[1.25] mb-6">
              Reading the document is easy. Knowing what the fee should be is not.
            </h2>
            <p className="text-[16px] text-slate-500 leading-relaxed">
              A side letter reduces the rate to 1.5%. An MFN election overrides the basis,
              but only after the GP confirms it. A fee cap kicks in next fiscal quarter.
              An amendment extends the investment period, which shifts when the rate steps down.
              Now compute the exact management fee for Q3 2027. That is the problem your
              spreadsheets solve slowly and your portfolio systems do not solve at all.
            </p>
          </div>
          {/* Right: isometric illustration */}
          <div className="flex-1 hidden lg:block">
            <ProblemFigure />
          </div>
        </div>
      </section>

      {/* ═══ Why this matters — verifiable public record ═══ */}
      <section className="py-24 px-6 border-t border-white/[0.04]">
        <div className="max-w-[1080px] mx-auto">
          <div className="max-w-[760px] mb-12">
            <SectionLabel>Why this matters</SectionLabel>
            <h2 className="text-[32px] font-semibold text-white tracking-tight leading-[1.25]">
              The fee-tracking problem in private equity is{' '}
              <span className="text-slate-500">
                documented, expensive, and unsolved.
              </span>
            </h2>
          </div>
          <div className="grid grid-cols-3 gap-5">
            <div className="px-6 py-6 rounded-lg bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[36px] font-semibold text-cyan-400 font-mono tracking-tight">
                $120M+
              </div>
              <StatBaseline active={true} duration={1200} />
              <div className="text-[13px] text-slate-400 mt-3 leading-relaxed">
                SEC fines on Blackstone, KKR, and Apollo (2015–2016) for fee-allocation
                and expense-misallocation issues.
              </div>
            </div>
            <div className="px-6 py-6 rounded-lg bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[36px] font-semibold text-cyan-400 font-mono tracking-tight">
                CalPERS, 2015
              </div>
              <StatBaseline active={true} duration={1200} />
              <div className="text-[13px] text-slate-400 mt-3 leading-relaxed">
                Publicly admitted it could not calculate the carried interest it had
                paid across its private-equity portfolio without external reconstruction.
              </div>
            </div>
            <div className="px-6 py-6 rounded-lg bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[36px] font-semibold text-cyan-400 font-mono tracking-tight">
                Tens of bps
              </div>
              <StatBaseline active={true} duration={1200} />
              <div className="text-[13px] text-slate-400 mt-3 leading-relaxed">
                Documented fee dispersion between LPs in the same fund. Often tens
                of basis points, material on any meaningful commitment
                (Begenau &amp; Siriwardane, 2022).
              </div>
            </div>
          </div>
          <div className="mt-6">
            <p className="text-[12px] text-slate-600 leading-relaxed">
              Sources: SEC press releases (2015–2016), CalPERS public disclosures,
              Begenau &amp; Siriwardane (HBS Working Paper, 2022). The ILPA Fee
              Reporting Template exists because tracking these terms is hard enough
              to need industry-wide standardization.
            </p>
          </div>
        </div>
      </section>

      {/* ═══ How it works ═══ */}
      <section className="py-28 px-6 border-t border-white/[0.04]">
        <div className="max-w-[1080px] mx-auto">
          <div className="max-w-[640px] mb-16">
            <SectionLabel>How it works</SectionLabel>
            <h2 className="text-[32px] font-semibold text-white tracking-tight leading-[1.25]">
              Point it at your LP inbox.{' '}
              <span className="text-slate-500">
                It reads every document, interprets the fee clauses, and calculates
                what you actually owe for any billing period.
              </span>
            </h2>
          </div>

          <div className="grid grid-cols-3 gap-5 relative">
            <PipelineThread />
            {[
              {
                icon: FileSearch, num: '01', title: 'Extract',
                figure: ExtractFigure,
                desc: 'Reads emails and PDF attachments. Identifies fee clauses, effective dates, and document relationships across side letters, MFN disclosures, elections, and confirmations.',
              },
              {
                icon: Brain, num: '02', title: 'Interpret',
                figure: InterpretFigure,
                desc: 'Translates each clause into a precise instruction: fee reductions, rate caps, billing changes, timing deferrals, conditional terms. Understands multi-document confirmation chains.',
              },
              {
                icon: CheckCircle2, num: '03', title: 'Verify',
                figure: VerifyFigure,
                desc: 'Builds the complete fee timeline from initial closing. Splits mid-period rate changes. Computes the exact management fee and compares it against the GP\'s capital call.',
              },
            ].map(({ icon: Icon, num, title, figure: Figure, desc }) => (
              <div key={num} className="rounded-lg bg-white/[0.02] border border-white/[0.04] overflow-hidden">
                {/* SVG illustration */}
                <div className="border-b border-white/[0.03]">
                  <Figure />
                </div>
                {/* Text content */}
                <div className="p-6 pt-5">
                  <div className="flex items-center gap-3 mb-3">
                    <div className="text-[11px] text-slate-700 font-mono">{num}</div>
                    <Icon size={16} className="text-slate-600" />
                    <h3 className="text-[17px] font-semibold text-white">{title}</h3>
                  </div>
                  <p className="text-[13px] text-slate-500 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ Capabilities ═══ */}
      <section className="py-28 px-6 border-t border-white/[0.04]">
        <div className="max-w-[1080px] mx-auto">
          <div className="max-w-[640px] mb-16">
            <SectionLabel>Capabilities</SectionLabel>
            <h2 className="text-[32px] font-semibold text-white tracking-tight leading-[1.25]">
              Built for real PE complexity.{' '}
              <span className="text-slate-500">
                Not a generic document reader. Every feature maps to a real operational
                workflow in fund administration.
              </span>
            </h2>
          </div>

          <div className="grid grid-cols-2 auto-rows-fr gap-5">
            {[
              {
                title: 'Side letter fee terms',
                desc: 'Extracts fee reductions, rate caps, basis changes, and billing cadence overrides from side letter PDFs and amendment emails.',
              },
              {
                title: 'MFN election chains',
                desc: 'Tracks the full GP disclosure, LP election, and GP confirmation flow. Elected terms only execute once the chain is complete.',
              },
              {
                title: 'Conditional and deferred terms',
                desc: '"Effective next fiscal quarter." "Deferred until fund realization hits 50%." Resolves dates and conditions against the fund\'s actual calendar and metrics.',
              },
              {
                title: 'Mid-period fee splitting',
                desc: 'When a rate or basis changes mid-quarter, the billing period is split at the transition date. Each sub-period calculated independently with per-day proration.',
              },
              {
                title: 'LP admission and catch-up',
                desc: 'If the LP joined after initial closing, the system prorates the current period and computes catch-up fees for all prior billing periods.',
              },
              {
                title: 'Historical shadow accounting',
                desc: 'Set any past date as the evaluation date to audit what the fee should have been at that point. No additional processing cost. The same pipeline, different snapshot.',
              },
              {
                title: 'Visual fee timelines',
                desc: 'See how the fee rate, basis, and cadence evolve across the entire fund life. Every amendment, constraint, and transition visualized on a single timeline.',
              },
              {
                title: 'Complements your existing systems',
                desc: 'Aladdin, Geneva, and eFront handle structured data. This system handles the unstructured documents they were never designed to process.',
              },
            ].map(({ title, desc }, i) => (
              <div key={i} className="group px-6 py-5 rounded-lg bg-white/[0.02] border border-white/[0.04]
                hover:bg-white/[0.03] hover:border-white/[0.07] transition-all duration-200 flex flex-col">
                <h3 className="text-[15px] font-medium text-white mb-1.5">{title}</h3>
                <p className="text-[13px] text-slate-600 leading-relaxed flex-1">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ Scope ═══ */}
      <section className="py-24 px-6 border-t border-white/[0.04]">
        <div className="max-w-[1080px] mx-auto">
          <div className="max-w-[760px] mb-12">
            <SectionLabel>Scope</SectionLabel>
            <h2 className="text-[32px] font-semibold text-white tracking-tight leading-[1.25]">
              What V1 covers.{' '}
              <span className="text-slate-500">
                And what was deliberately deferred.
              </span>
            </h2>
            <p className="text-[14px] text-slate-500 leading-relaxed mt-5">
              V1 is scoped around information an LP already has in their
              document inbox: LPAs, side letters, amendments, election
              forms, GP notices, capital account statements. Items in the
              right column require data sources beyond documents
              (portfolio-company ledgers, NAV feeds, distribution history)
              and are tracked as V2.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="px-6 py-6 rounded-lg bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[10px] font-bold text-cyan-400 uppercase tracking-wider mb-3">
                Covered
              </div>
              <ul className="space-y-2 text-[13px] text-slate-400 leading-relaxed">
                <li>• Automatic parsing of signed PDF documents (side letters, amendments, MFN forms)</li>
                <li>• Base fee rate and basis; committed → invested switch at IP end</li>
                <li>• Side letter overrides (CAP, FLOOR, step-downs)</li>
                <li>• MFN election chains with GP confirmation</li>
                <li>• Amendments to investment period, fund term, other dates</li>
                <li>• Fee waivers with bounded effective periods</li>
                <li>• Cross-clause dependencies via stability loop</li>
                <li>• Compound date conditions (earlier-of, later-of, Boolean combinations over anniversaries, fiscal-quarter anchors, and fund metrics)</li>
                <li>• Billing-period splitting at rate/basis transitions</li>
                <li>• LP admission proration and catch-up fees for late-closers</li>
                <li>• Ambiguous or unsupported clauses flagged for manual review, never silently ignored</li>
                <li>• GP-claimed fee cross-checked against calculated fee with discrepancy delta</li>
              </ul>
            </div>
            <div className="px-6 py-6 rounded-lg bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[10px] font-bold text-amber-400 uppercase tracking-wider mb-3">
                Deferred to V2
              </div>
              <ul className="space-y-2 text-[13px] text-slate-400 leading-relaxed">
                <li>• Transaction / monitoring fee offsets (needs portfolio-company fee ledger)</li>
                <li>• Carried interest, waterfall, clawback (needs NAV + distribution ledger)</li>
                <li>• Equalization at subsequent closings (needs commitment timing)</li>
                <li>• NAV-adjusted invested-capital basis on write-downs</li>
                <li>• Recallable distribution tracking</li>
                <li>• Successor-fund step-down triggers (external event signal)</li>
                <li>• Organizational expenses, placement fees, wind-down fees</li>
                <li>• Cross-fund side letter inheritance</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ═══ CTA ═══ */}
      <section className="py-32 px-6 border-t border-white/[0.04]">
        <div className="max-w-[560px] mx-auto text-center">
          <h2 className="text-[40px] font-semibold text-white tracking-tight leading-tight mb-5">
            See it verify a real fee
          </h2>
          <p className="text-[16px] text-slate-500 mb-10 leading-relaxed">
            Load a sample fund scenario or add your own side letters.
            Watch the system extract clauses, build timelines, and
            calculate the exact fee.
          </p>
          <button onClick={() => navigate('/demo')}
            className="h-11 px-6 bg-white text-[#0a0a0f] text-[14px] font-medium rounded-md
              hover:bg-slate-200 transition active:scale-[0.97] inline-flex items-center gap-2">
            Launch demo <ArrowRight size={15} />
          </button>
          <div className="mt-3">
            <span className="text-[13px] text-slate-700">No login required</span>
          </div>
        </div>
      </section>

      {/* ═══ Footer ═══ */}
      <footer className="border-t border-white/[0.04] py-8 px-6">
        <div className="max-w-[1080px] mx-auto flex items-center justify-between">
          <span className="text-[13px] text-slate-600">PE Doc <span className="text-cyan-500/60">Intelligence</span></span>
          <span className="text-[12px] text-slate-700">Shadow Accounting Engine</span>
        </div>
      </footer>
    </div>
  );
}
