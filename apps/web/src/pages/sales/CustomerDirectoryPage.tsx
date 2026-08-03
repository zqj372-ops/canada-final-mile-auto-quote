import { useState } from "react";
import { Link } from "react-router-dom";
import CustomerNameField from "../../features/customers/CustomerNameField";

export default function CustomerDirectoryPage() {
  const [name, setName] = useState("");
  return <section className="mx-auto grid max-w-5xl gap-6 p-6"><header><h1 className="text-2xl font-semibold">客户目录</h1><p className="mt-2 text-sm text-slate-600">客户档案只保存客户名称；报价、发送和跟进记录归属于报价记录。</p></header><CustomerNameField value={name} onChange={setName} onCreate={() => undefined} /><div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600"><p>暂无客户</p><Link className="mt-3 inline-block text-blue-700 underline" to="/quote/records">查看报价记录</Link></div></section>;
}
