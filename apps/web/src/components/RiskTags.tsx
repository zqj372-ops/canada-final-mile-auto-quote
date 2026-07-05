interface RiskTagsProps {
  tags: string[];
}

export default function RiskTags({ tags }: RiskTagsProps) {
  if (!tags.length) {
    return <span className="text-sm text-slate-500">无风险标签</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {tags.map((tag) => (
        <span
          key={tag}
          className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900"
        >
          {tag}
        </span>
      ))}
    </div>
  );
}
