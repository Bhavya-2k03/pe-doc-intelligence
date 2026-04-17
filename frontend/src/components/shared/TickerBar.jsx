export default function TickerBar() {
  const items = [
    ['FEE RATE', '2.0% → 1.5%'],
    ['BASIS', 'Committed → Invested'],
    ['LP COMMIT', '$10,000,000'],
    ['FUND SIZE', '$50,000,000'],
    ['INIT CLOSE', '2024-01-15'],
    ['FINAL CLOSE', '2024-12-15'],
    ['INV ENDS', '2029-01-15'],
    ['TERM END', '2034-01-15'],
    ['CADENCE', 'Quarterly'],
    ['DAY COUNT', 'Actual/365'],
  ];

  const sep = '<span class="text-white/[0.12] mx-3">│</span>';
  const content = items.map(([k, v]) =>
    `<span class="text-slate-400">${k}</span><span class="text-slate-100 font-mono font-semibold ml-1.5">${v}</span>`
  ).join(sep);

  return (
    <div className="h-7 bg-[#08090d] border-t border-white/[0.05] overflow-hidden flex items-center shrink-0 select-none">
      <div className="flex items-center px-3 shrink-0 border-r border-white/[0.05]">
        <span className="section-label section-label-slate text-[9px] py-0">LPA BASIS</span>
      </div>
      <div className="flex-1 overflow-hidden relative">
        <div className="ticker-scroll whitespace-nowrap inline-flex items-center text-[12px] gap-0"
          dangerouslySetInnerHTML={{
            __html: content + '<span class="mx-8"></span>' + content
          }}
        />
      </div>
    </div>
  );
}
