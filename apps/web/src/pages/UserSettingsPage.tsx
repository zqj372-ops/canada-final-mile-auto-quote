import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createUser,
  listUsers,
  updateUser,
  type UserPublic,
  type UserRole,
} from "../api/client";

interface UserFormState {
  username: string;
  display_name: string;
  password: string;
  role: UserRole;
  enabled: boolean;
}

const emptyUserForm: UserFormState = {
  username: "",
  display_name: "",
  password: "",
  role: "sales",
  enabled: true,
};

const roleOptions: Array<{ value: UserRole; label: string; hint: string }> = [
  { value: "admin", label: "管理员", hint: "系统配置与账号管理" },
  { value: "operator", label: "运营", hint: "后台处理与配置" },
  { value: "sales", label: "销售", hint: "前台报价与记录" },
  { value: "viewer", label: "查看者", hint: "后台只读查看" },
];

export default function UserSettingsPage() {
  const [users, setUsers] = useState<UserPublic[]>([]);
  const [form, setForm] = useState<UserFormState>(emptyUserForm);
  const [passwordDrafts, setPasswordDrafts] = useState<Record<number, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [savingId, setSavingId] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void refreshUsers();
  }, []);

  const stats = useMemo(() => {
    const enabled = users.filter((user) => user.enabled).length;
    const backoffice = users.filter((user) =>
      ["admin", "operator", "viewer"].includes(user.role),
    ).length;
    const sales = users.filter((user) => user.role === "sales").length;
    return { backoffice, enabled, sales, total: users.length };
  }, [users]);

  async function refreshUsers() {
    setIsLoading(true);
    setError(null);
    try {
      setUsers(await listUsers());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "用户列表加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!form.username.trim() || !form.password.trim()) {
      setError("请输入账号和初始密码。");
      return;
    }
    if (form.password.trim().length < 8) {
      setError("初始密码至少 8 位。");
      return;
    }
    setSavingId("new");
    try {
      const created = await createUser({
        username: form.username.trim(),
        password: form.password,
        display_name: form.display_name.trim() || null,
        role: form.role,
        enabled: form.enabled,
      });
      setUsers((current) => [created, ...current]);
      setForm(emptyUserForm);
      setNotice(`账号 ${created.username} 已创建`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建账号失败");
    } finally {
      setSavingId(null);
    }
  }

  async function patchUser(user: UserPublic, payload: Parameters<typeof updateUser>[1]) {
    setSavingId(user.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateUser(user.id, payload);
      setUsers((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice(`账号 ${updated.username} 已更新`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "更新账号失败");
    } finally {
      setSavingId(null);
    }
  }

  async function resetPassword(user: UserPublic) {
    const nextPassword = passwordDrafts[user.id]?.trim() ?? "";
    if (nextPassword.length < 8) {
      setError("新密码至少 8 位。");
      return;
    }
    await patchUser(user, { password: nextPassword });
    setPasswordDrafts((current) => ({ ...current, [user.id]: "" }));
  }

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="admin-page-header">
        <div>
          <p className="admin-eyebrow">Access Control</p>
          <h1>用户账号</h1>
          <p>
            后台和销售前台都使用账号登录。管理员负责创建账号、分配角色、停用离职账号和重置密码。
          </p>
        </div>
        <button className="btn-secondary" type="button" onClick={() => void refreshUsers()}>
          刷新
        </button>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <UserStat label="全部账号" value={stats.total} tone="slate" />
        <UserStat label="已启用" value={stats.enabled} tone="emerald" />
        <UserStat label="后台角色" value={stats.backoffice} tone="indigo" />
        <UserStat label="销售账号" value={stats.sales} tone="teal" />
      </section>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-900" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-900" role="status">
          {notice}
        </div>
      )}

      <section className="grid gap-5 lg:grid-cols-[minmax(20rem,0.78fr)_minmax(0,1.22fr)]">
        <form className="panel p-5" onSubmit={handleCreateUser}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="admin-eyebrow">New Account</p>
              <h2 className="section-title">新增账号</h2>
            </div>
            <span className="rounded-md bg-teal-50 px-2.5 py-1 text-xs font-semibold text-teal-800">
              默认销售
            </span>
          </div>

          <div className="mt-4 grid gap-3">
            <label>
              <span className="field-label">登录账号</span>
              <input
                className="field-input"
                value={form.username}
                onChange={(event) =>
                  setForm((current) => ({ ...current, username: event.target.value }))
                }
                placeholder="name@example.com"
                autoComplete="username"
              />
            </label>
            <label>
              <span className="field-label">显示名称</span>
              <input
                className="field-input"
                value={form.display_name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, display_name: event.target.value }))
                }
                placeholder="销售 / 运营姓名"
              />
            </label>
            <label>
              <span className="field-label">初始密码</span>
              <input
                className="field-input"
                type="password"
                value={form.password}
                onChange={(event) =>
                  setForm((current) => ({ ...current, password: event.target.value }))
                }
                placeholder="至少 8 位"
                autoComplete="new-password"
              />
            </label>
            <label>
              <span className="field-label">角色</span>
              <select
                className="field-input"
                value={form.role}
                onChange={(event) =>
                  setForm((current) => ({ ...current, role: event.target.value as UserRole }))
                }
              >
                {roleOptions.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label} - {role.hint}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-h-11 items-center gap-3 rounded-md border border-slate-200 bg-slate-50 px-3">
              <input
                className="h-4 w-4 rounded border-slate-300 text-teal-700 focus:ring-teal-700"
                type="checkbox"
                checked={form.enabled}
                onChange={(event) =>
                  setForm((current) => ({ ...current, enabled: event.target.checked }))
                }
              />
              <span className="text-sm font-semibold text-slate-800">创建后立即启用</span>
            </label>
            <button className="btn-primary" type="submit" disabled={savingId === "new"}>
              {savingId === "new" ? "创建中..." : "创建账号"}
            </button>
          </div>
        </form>

        <section className="panel overflow-hidden">
          <div className="flex flex-col gap-2 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="admin-eyebrow">Accounts</p>
              <h2 className="section-title">账号列表</h2>
            </div>
            <span className="text-sm font-medium text-slate-500">
              {isLoading ? "读取中" : `${users.length} 个账号`}
            </span>
          </div>

          {isLoading ? (
            <div className="p-6 text-sm text-slate-600">正在加载用户账号...</div>
          ) : users.length === 0 ? (
            <div className="p-6 text-sm text-slate-600">暂无用户账号。</div>
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[960px]">
                <div className="grid grid-cols-[1fr_0.78fr_0.82fr_0.72fr_1fr_1.15fr] gap-3 bg-slate-50 px-5 py-3 text-xs font-semibold text-slate-500">
                  <span>账号</span>
                  <span>角色</span>
                  <span>状态</span>
                  <span>最后登录</span>
                  <span>重置密码</span>
                  <span>操作</span>
                </div>
                {users.map((user) => (
                  <div
                    key={user.id}
                    className="grid grid-cols-[1fr_0.78fr_0.82fr_0.72fr_1fr_1.15fr] items-center gap-3 border-t border-slate-100 px-5 py-3 text-sm"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-950">{user.display_name}</p>
                      <p className="truncate font-mono text-xs text-slate-500">{user.username}</p>
                    </div>
                    <select
                      className="field-input mt-0 min-h-10 py-1 text-sm"
                      value={user.role}
                      onChange={(event) =>
                        void patchUser(user, { role: event.target.value as UserRole })
                      }
                      disabled={savingId === user.id}
                    >
                      {roleOptions.map((role) => (
                        <option key={role.value} value={role.value}>
                          {role.label}
                        </option>
                      ))}
                    </select>
                    <span
                      className={`w-fit rounded-md px-2.5 py-1 text-xs font-semibold ${
                        user.enabled
                          ? "bg-emerald-50 text-emerald-800"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {user.enabled ? "已启用" : "已停用"}
                    </span>
                    <span className="text-xs text-slate-600">
                      {formatDateTime(user.last_login_at)}
                    </span>
                    <input
                      className="field-input mt-0 min-h-10 py-1 text-sm"
                      type="password"
                      value={passwordDrafts[user.id] ?? ""}
                      onChange={(event) =>
                        setPasswordDrafts((current) => ({
                          ...current,
                          [user.id]: event.target.value,
                        }))
                      }
                      placeholder="新密码"
                      autoComplete="new-password"
                    />
                    <div className="flex flex-wrap gap-2">
                      <button
                        className="btn-secondary min-h-10 px-3 py-1"
                        type="button"
                        onClick={() => void resetPassword(user)}
                        disabled={savingId === user.id || !(passwordDrafts[user.id] ?? "").trim()}
                      >
                        重置
                      </button>
                      <button
                        className={user.enabled ? "btn-danger min-h-10 px-3 py-1" : "btn-primary min-h-10 px-3 py-1"}
                        type="button"
                        onClick={() => void patchUser(user, { enabled: !user.enabled })}
                        disabled={savingId === user.id}
                      >
                        {user.enabled ? "停用" : "启用"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </section>
    </div>
  );
}

function UserStat({
  label,
  tone,
  value,
}: {
  label: string;
  tone: "emerald" | "indigo" | "slate" | "teal";
  value: number;
}) {
  const toneClass = {
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-900",
    indigo: "border-indigo-200 bg-indigo-50 text-indigo-900",
    slate: "border-slate-200 bg-white text-slate-900",
    teal: "border-teal-200 bg-teal-50 text-teal-900",
  }[tone];
  return (
    <div className={`rounded-lg border p-4 shadow-sm ${toneClass}`}>
      <p className="text-xs font-semibold uppercase tracking-wide">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "未登录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
