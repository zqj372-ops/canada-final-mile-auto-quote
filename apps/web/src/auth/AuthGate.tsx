import type { ReactNode } from "react";
import type { CurrentActor, UserRole } from "../api/client";

export default function AuthGate({ actor, allowedRoles, children }: { actor: CurrentActor | null; allowedRoles: UserRole[]; children: ReactNode }) {
  if (!actor) return <div className="mx-auto max-w-lg p-8" role="status">请登录后继续。</div>;
  if (!allowedRoles.includes(actor.role as UserRole)) return <div className="mx-auto max-w-lg p-8" role="alert"><h1 className="text-xl font-semibold">403</h1><p className="mt-2">当前账号没有访问此工作区的权限。</p></div>;
  return <>{children}</>;
}
