import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return <section className="mx-auto max-w-lg p-8 text-center"><h1 className="text-2xl font-semibold">页面未找到</h1><p className="mt-2 text-slate-600">请从当前应用入口重新进入。</p><Link className="mt-5 inline-block text-blue-700 underline" to="/quote">返回销售前台</Link></section>;
}
