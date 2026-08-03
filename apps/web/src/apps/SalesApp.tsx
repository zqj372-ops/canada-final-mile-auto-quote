import { Route, Routes } from "react-router-dom";
import SalesShell from "../layouts/SalesShell";

function Placeholder({ title }: { title: string }) {
  return <section className="mx-auto max-w-7xl p-6"><h1 className="text-2xl font-semibold">{title}</h1></section>;
}

export default function SalesApp() {
  return <SalesShell><Routes>
    <Route path="/" element={<Placeholder title="工作台" />} />
    <Route path="/records" element={<Placeholder title="客户与报价" />} />
    <Route path="/follow-ups" element={<Placeholder title="待办跟进" />} />
    <Route path="/new/final-mile" element={<Placeholder title="新建加拿大末端报价" />} />
    <Route path="/new/fcl" element={<Placeholder title="新建 FCL 整柜报价" />} />
    <Route path="*" element={<Placeholder title="销售页面未找到" />} />
  </Routes></SalesShell>;
}
