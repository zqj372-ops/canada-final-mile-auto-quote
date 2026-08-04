import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const links = [
  ["/quote", "工作台"],
  ["/quote/records", "客户与报价"],
  ["/quote/follow-ups", "待办跟进"],
] as const;

export default function SalesShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <Link className="text-lg font-semibold text-blue-800" to="/quote">AI 报价销售前台</Link>
          <nav aria-label="销售导航" className="flex flex-wrap gap-2 text-sm font-medium">
            {links.map(([href, label]) => <Link className="rounded px-3 py-2 hover:bg-slate-100" key={href} to={href}>{label}</Link>)}
          </nav>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}
