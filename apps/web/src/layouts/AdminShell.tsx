import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const links = [
  ["/admin", "运营工作台"],
  ["/admin/reviews", "报价复核"],
  ["/admin/quotes", "报价记录"],
  ["/admin/pricing", "规则与价格"],
  ["/admin/management", "管理数据"],
  ["/admin/users", "用户与权限"],
] as const;

export default function AdminShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <Link className="text-lg font-semibold text-blue-800" to="/admin">AI 报价管理后台</Link>
          <nav aria-label="后台导航" className="flex flex-wrap gap-2 text-sm font-medium">
            {links.map(([href, label]) => <Link className="rounded px-3 py-2 hover:bg-slate-100" key={href} to={href}>{label}</Link>)}
          </nav>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}
