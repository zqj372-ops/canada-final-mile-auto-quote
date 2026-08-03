const tones: Record<string, string> = {
  ready_to_send: "border-blue-200 bg-blue-50 text-blue-800",
  sent: "border-slate-200 bg-slate-50 text-slate-700",
  accepted: "border-emerald-200 bg-emerald-50 text-emerald-800",
  rejected: "border-red-200 bg-red-50 text-red-800",
};

export default function StatusBadge({ status, label }: { status: string; label: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[status] ?? "border-amber-200 bg-amber-50 text-amber-800"}`}>{label}</span>;
}
