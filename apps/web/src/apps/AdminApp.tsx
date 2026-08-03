import { Route, Routes } from "react-router-dom";
import AdminShell from "../layouts/AdminShell";

function Placeholder({ title }: { title: string }) {
  return <section className="mx-auto max-w-7xl p-6"><h1 className="text-2xl font-semibold">{title}</h1></section>;
}

export default function AdminApp() {
  return <AdminShell><Routes>
    <Route path="/" element={<Placeholder title="运营工作台" />} />
    <Route path="/reviews/*" element={<Placeholder title="报价复核" />} />
    <Route path="/quotes/*" element={<Placeholder title="报价记录" />} />
    <Route path="/pricing/*" element={<Placeholder title="规则与价格" />} />
    <Route path="/management" element={<Placeholder title="管理数据" />} />
    <Route path="/users" element={<Placeholder title="用户与权限" />} />
    <Route path="*" element={<Placeholder title="后台页面未找到" />} />
  </Routes></AdminShell>;
}
