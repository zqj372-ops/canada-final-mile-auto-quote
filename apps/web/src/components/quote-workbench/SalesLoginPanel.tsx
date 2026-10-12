export default function SalesLoginPanel({
  error,
  isChecking,
  isLoggingIn,
  onLogin,
  onPasswordChange,
  onUsernameChange,
  password,
  username,
}: {
  error: string | null;
  isChecking: boolean;
  isLoggingIn: boolean;
  onLogin: () => void;
  onPasswordChange: (value: string) => void;
  onUsernameChange: (value: string) => void;
  password: string;
  username: string;
}) {
  return (
    <div className="sales-login-screen px-4 py-8">
      <section className="sales-login-card">
        <div>
          <div className="sales-brand">
            <span className="sales-brand-mark">CFM</span>
            <div>
              <p>Canada Final Mile</p>
              <small>销售前台</small>
            </div>
          </div>
          <h1 className="mt-10 text-3xl font-semibold tracking-normal text-slate-950">
            AI 报价与记录工作台
          </h1>
          <p className="mt-4 text-sm leading-6 text-slate-600">
            登录后直接进入新建报价和报价记录。后台配置、审计和人工复核由运营端处理。
          </p>
          <div className="mt-8 grid gap-3">
            <LoginCapability label="AI 智能报价" value="粘贴询价、核对字段，再确认报价" tone="teal" />
            <LoginCapability label="报价记录" value="回查自己的历史报价和客户回复" tone="indigo" />
            <LoginCapability label="人工复核" value="需确认的票自动进入后台队列" tone="amber" />
          </div>
        </div>

        <form
          className="panel grid content-center gap-5 p-6 sm:p-8"
          onSubmit={(event) => {
            event.preventDefault();
            onLogin();
          }}
        >
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">账号登录</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">销售账号登录</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              仅销售、运营或管理员账号可以提交报价；报价记录会按当前账号显示。
            </p>
          </div>

          {error && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm leading-6 text-rose-900">
              {error}
            </div>
          )}

          <label>
            <span className="text-xs font-semibold text-slate-700">账号</span>
            <input
              className="field-input mt-2"
              value={username}
              onChange={(event) => onUsernameChange(event.target.value)}
              placeholder="sales@example.com"
              autoComplete="username"
              autoFocus
            />
          </label>
          <label>
            <span className="text-xs font-semibold text-slate-700">密码</span>
            <input
              className="field-input mt-2"
              type="password"
              value={password}
              onChange={(event) => onPasswordChange(event.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </label>
          <button className="btn-primary" type="submit" disabled={isChecking || isLoggingIn}>
            {isChecking ? "恢复登录中..." : isLoggingIn ? "登录中..." : "登录并进入报价"}
          </button>
        </form>
      </section>
    </div>
  );
}

function LoginCapability({
  label,
  tone,
  value,
}: {
  label: string;
  tone: "amber" | "indigo" | "teal";
  value: string;
}) {
  const toneClass = {
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    indigo: "border-indigo-200 bg-indigo-50 text-indigo-900",
    teal: "border-teal-200 bg-teal-50 text-teal-900",
  }[tone];
  return (
    <div className={`rounded-lg border p-4 ${toneClass}`}>
      <p className="text-xs font-semibold uppercase tracking-wide">{label}</p>
      <p className="mt-2 text-sm font-semibold">{value}</p>
    </div>
  );
}

