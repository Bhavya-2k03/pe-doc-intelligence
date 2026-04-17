import { FileStack, Link2, Layers, PenLine, ArrowRight } from 'lucide-react';

const PACKAGES = [
  {
    id: 'mfn_flow',
    title: 'MFN Election Chain',
    icon: Link2,
    emails: 4,
    description: 'GP disclosure, LP election, GP confirmation. A full confirmation chain with fee impact and GATE deferral.',
  },
  {
    id: 'side_letter_flow',
    title: 'Side Letter Amendment',
    icon: FileStack,
    emails: 4,
    description: 'Side letter with deferred terms, plus fund updates arriving years later. Shows conditions resolving as the fund matures.',
  },
  {
    id: 'multi_amendment',
    title: 'Multi-Amendment',
    icon: Layers,
    emails: 4,
    description: 'Three documents spanning years, where a later extension silently stretches an earlier fee waiver. Shows hidden cross-document linkages the system catches.',
  },
  {
    id: 'custom',
    title: 'Start Fresh',
    icon: PenLine,
    emails: 0,
    description: 'Empty inbox. Add your own emails and attachments to test any scenario.',
  },
];

export default function PackageSelector({ onSelect, loading }) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[640px]">

        {/* Header */}
        <div className="mb-10">
          <h2 className="text-[28px] font-semibold text-white tracking-tight leading-tight mb-3">
            Load sample data
          </h2>
          <p className="text-[14px] text-slate-500 leading-relaxed">
            Pick a pre-built set of fund documents to explore the system, or start empty and add your own.
            You can edit everything after loading.
          </p>
        </div>

        {/* Package list — vertical cards */}
        <div className="space-y-3">
          {PACKAGES.map(pkg => {
            const Icon = pkg.icon;
            const isCustom = pkg.id === 'custom';

            return (
              <button
                key={pkg.id}
                onClick={() => onSelect(pkg.id)}
                disabled={loading}
                className={`w-full text-left group rounded-lg border transition-all duration-200 h-[88px]
                  ${isCustom
                    ? 'bg-transparent border-white/[0.06] border-dashed hover:border-white/[0.12]'
                    : 'bg-white/[0.02] border-white/[0.06] hover:border-white/[0.14] hover:bg-white/[0.03]'
                  }
                  ${loading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer active:scale-[0.995]'}
                `}
              >
                <div className="flex gap-4 px-5 py-4">
                  {/* Icon */}
                  <div className={`w-9 h-9 rounded-md flex items-center justify-center shrink-0 mt-0.5
                    ${isCustom ? 'bg-white/[0.03]' : 'bg-white/[0.04]'}`}>
                    <Icon size={16} className="text-slate-500 group-hover:text-slate-400 transition" />
                  </div>

                  {/* Text */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between mb-1">
                      <span className="text-[14px] font-medium text-white">{pkg.title}</span>
                      <div className="flex items-center gap-3 shrink-0 ml-4">
                        {pkg.emails > 0 && (
                          <span className="text-[10px] font-mono text-slate-600">
                            {pkg.emails} emails
                          </span>
                        )}
                        <ArrowRight size={14}
                          className="text-slate-700 group-hover:text-slate-500 group-hover:translate-x-0.5
                            transition-all" />
                      </div>
                    </div>
                    <p className="text-[12px] text-slate-600 leading-relaxed">
                      {pkg.description}
                    </p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export { PACKAGES };
