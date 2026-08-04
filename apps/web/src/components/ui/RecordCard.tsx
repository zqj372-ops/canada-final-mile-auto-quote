export default function RecordCard({ fields }: { fields: Array<{ label: string; value: string | number | null }> }) {
  return <dl className="grid gap-2 rounded-lg border border-slate-200 bg-white p-4">{fields.map((field) => <div className="flex justify-between gap-4" key={field.label}><dt className="text-sm text-slate-500">{field.label}</dt><dd className="text-right text-sm font-medium text-slate-900">{field.value ?? "—"}</dd></div>)}</dl>;
}
