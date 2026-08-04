export default function ResponsiveActionBar({ actions }: { actions: Array<{ key: string; label: string; onClick: () => void; disabled?: boolean }> }) {
  return <div className="flex flex-wrap gap-2" aria-label="可用操作">{actions.map((action) => <button className="min-h-11 rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={action.disabled} key={action.key} onClick={action.onClick} type="button">{action.label}</button>)}</div>;
}
