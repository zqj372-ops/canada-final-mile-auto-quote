export default function ChineseFieldLabel({
  label,
  hint,
}: {
  label: string;
  hint?: string;
}) {
  return (
    <span className="block">
      <span className="block text-sm font-semibold text-slate-100">{label}</span>
      {hint && <span className="mt-1 block text-xs leading-5 text-cyan-100/70">{hint}</span>}
    </span>
  );
}
