import { FormEvent, useEffect, useState } from "react";
import {
  createEmailConfig,
  deleteEmailConfig,
  listEmailConfigs,
  setDefaultEmailConfig,
  testEmailConfig,
  updateEmailConfig,
  type EmailConfigPayload,
  type EmailConfigPublic,
} from "../api/client";

interface FormState {
  id: number | null;
  name: string;
  smtp_host: string;
  smtp_port: string;
  username: string;
  password: string;
  from_email: string;
  from_name: string;
  recipient_emails: string;
  use_tls: boolean;
  use_ssl: boolean;
  purpose: string;
  enabled: boolean;
  is_default: boolean;
}

const emptyForm: FormState = {
  id: null,
  name: "",
  smtp_host: "",
  smtp_port: "587",
  username: "",
  password: "",
  from_email: "",
  from_name: "Canada Quote",
  recipient_emails: "",
  use_tls: true,
  use_ssl: false,
  purpose: "general",
  enabled: true,
  is_default: false,
};

const purposes = ["quote_success", "manual_required", "ai_quote", "manual_resolved", "general"];

export default function EmailSettingsPage() {
  const [configs, setConfigs] = useState<EmailConfigPublic[]>([]);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);

  useEffect(() => {
    void loadConfigs();
  }, []);

  async function loadConfigs() {
    setError(null);
    try {
      setConfigs(await listEmailConfigs());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "邮件配置加载失败");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!form.enabled && form.is_default) {
      setError("禁用的邮件配置不能设为默认，请先启用或取消默认。");
      return;
    }
    setIsSaving(true);
    try {
      const payload = buildPayload(form);
      if (form.id) {
        await updateEmailConfig(form.id, payload);
        setNotice("邮件配置已更新");
      } else {
        await createEmailConfig({
          ...payload,
          name: payload.name || "",
          smtp_host: payload.smtp_host || "",
          from_email: payload.from_email || "",
          recipient_emails: payload.recipient_emails || [],
        });
        setNotice("邮件配置已新增");
      }
      setForm(emptyForm);
      await loadConfigs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "邮件配置保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(config: EmailConfigPublic) {
    if (!window.confirm(`确认删除邮件配置「${config.name}」吗？`)) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      await deleteEmailConfig(config.id);
      setNotice(`已删除 ${config.name}`);
      await loadConfigs();
      if (form.id === config.id) {
        setForm(emptyForm);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "邮件配置删除失败");
    }
  }

  async function handleSetDefault(config: EmailConfigPublic) {
    setError(null);
    setNotice(null);
    if (!config.enabled) {
      setError("禁用的邮件配置不能设为默认，请先启用后再设置。");
      return;
    }
    try {
      await setDefaultEmailConfig(config.id);
      setNotice(`${config.name} 已设为默认`);
      await loadConfigs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "设置默认失败");
    }
  }

  async function handleTest(config: EmailConfigPublic) {
    setError(null);
    setNotice(null);
    setTestingId(config.id);
    try {
      const response = await testEmailConfig(config.id);
      setNotice(
        response.success
          ? `测试邮件发送成功，耗时 ${response.latency_ms}ms`
          : `测试邮件发送失败：${response.error || "unknown error"} (${response.latency_ms}ms)`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "测试邮件发送失败");
    } finally {
      setTestingId(null);
    }
  }

  function edit(config: EmailConfigPublic) {
    setForm({
      id: config.id,
      name: config.name,
      smtp_host: config.smtp_host,
      smtp_port: String(config.smtp_port),
      username: "",
      password: "",
      from_email: config.from_email,
      from_name: config.from_name || "",
      recipient_emails: config.recipient_emails.join("\n"),
      use_tls: config.use_tls,
      use_ssl: config.use_ssl,
      purpose: config.purpose,
      enabled: config.enabled,
      is_default: config.is_default,
    });
    setNotice("编辑模式：用户名/密码留空表示不修改当前保存值");
  }

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => {
      const next = { ...current, [key]: value };
      if (key === "enabled" && value === false) {
        next.is_default = false;
      }
      if (key === "is_default" && value === true && !next.enabled) {
        return current;
      }
      if (key === "use_ssl" && value === true) {
        next.use_tls = false;
        if (next.smtp_port === "587") {
          next.smtp_port = "465";
        }
      }
      return next;
    });
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-blue-800">Email Settings</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">邮件通知配置</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          用 SMTP 邮件接收报价成功、需要人工确认、AI 报价和人工任务处理结果。密码只加密保存，不会回显。
        </p>
      </header>

      {error && <Alert tone="red">{error}</Alert>}
      {notice && <Alert tone="green">{notice}</Alert>}

      <div className="grid gap-6 xl:grid-cols-[0.78fr_1.22fr]">
        <section className="panel p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">{form.id ? "编辑邮箱" : "新增邮箱"}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                建议为 manual_required 单独配置收件组，避免人工复核邮件漏看。
              </p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => setForm(emptyForm)}>
              新建
            </button>
          </div>

          <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
            <TextField label="配置名称 *" value={form.name} onChange={(value) => update("name", value)} required />
            <div className="grid gap-3 sm:grid-cols-[1fr_110px]">
              <TextField label="SMTP Host *" value={form.smtp_host} onChange={(value) => update("smtp_host", value)} required />
              <TextField label="端口 *" value={form.smtp_port} onChange={(value) => update("smtp_port", value)} required />
            </div>
            <TextField label="用户名" value={form.username} onChange={(value) => update("username", value)} />
            <label>
              <span className="field-label">密码 / 授权码 {form.id ? "" : "（如 SMTP 需要）"}</span>
              <input
                className="field-input"
                type="password"
                value={form.password}
                onChange={(event) => update("password", event.target.value)}
                autoComplete="new-password"
              />
              {form.id && <p className="field-hint">留空表示不修改当前密码</p>}
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField label="发件邮箱 *" value={form.from_email} onChange={(value) => update("from_email", value)} required />
              <TextField label="发件名称" value={form.from_name} onChange={(value) => update("from_name", value)} />
            </div>
            <label>
              <span className="field-label">收件邮箱 *</span>
              <textarea
                className="field-input min-h-24"
                value={form.recipient_emails}
                onChange={(event) => update("recipient_emails", event.target.value)}
                placeholder={"ops@example.com\nsales@example.com"}
                required
              />
              <p className="field-hint">一行一个，或用英文逗号分隔。</p>
            </label>
            <label>
              <span className="field-label">用途</span>
              <select className="field-input" value={form.purpose} onChange={(event) => update("purpose", event.target.value)}>
                {purposes.map((purpose) => (
                  <option key={purpose} value={purpose}>
                    {purpose}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <CheckboxField label="启用" checked={form.enabled} onChange={(value) => update("enabled", value)} />
              <CheckboxField label="设为默认" checked={form.is_default} onChange={(value) => update("is_default", value)} disabled={!form.enabled} />
              <CheckboxField label="STARTTLS" checked={form.use_tls} onChange={(value) => update("use_tls", value)} disabled={form.use_ssl} />
              <CheckboxField label="SSL 直连" checked={form.use_ssl} onChange={(value) => update("use_ssl", value)} />
            </div>
            <button className="btn-primary" type="submit" disabled={isSaving}>
              {isSaving ? "保存中..." : form.id ? "保存配置" : "新增邮箱"}
            </button>
          </form>
        </section>

        <section className="panel p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="section-title">邮箱列表</h2>
              <p className="mt-1 text-sm text-slate-600">禁用的邮箱不会发送通知，密码明文不会返回前端。</p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => void loadConfigs()}>
              刷新
            </button>
          </div>

          <div className="mt-5 grid gap-4">
            {configs.length === 0 ? (
              <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600">还没有邮件通知配置。</p>
            ) : (
              configs.map((config) => (
                <article key={config.id} className="rounded-md border border-slate-200 p-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-slate-950">{config.name}</h3>
                        {config.is_default && <Badge text="默认" tone="blue" />}
                        {!config.enabled && <Badge text="disabled" tone="slate" />}
                        <Badge text={config.purpose} tone="amber" />
                      </div>
                      <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                        <FieldValue label="SMTP" value={`${config.smtp_host}:${config.smtp_port}`} />
                        <FieldValue label="发件邮箱" value={config.from_email} />
                        <FieldValue label="用户名" value={config.masked_username || "未设置"} />
                        <FieldValue label="密码" value={config.has_password ? "已加密保存" : "未设置"} />
                        <FieldValue label="安全" value={config.use_ssl ? "SSL" : config.use_tls ? "STARTTLS" : "无加密"} />
                        <FieldValue label="收件人" value={config.recipient_emails.join(", ")} />
                      </dl>
                    </div>
                    <div className="grid min-w-40 gap-2 sm:grid-cols-2 lg:grid-cols-1">
                      <button className="btn-secondary" type="button" onClick={() => edit(config)}>编辑</button>
                      <button className="btn-secondary" type="button" onClick={() => void handleSetDefault(config)} disabled={config.is_default || !config.enabled}>
                        设为默认
                      </button>
                      <button className="btn-secondary" type="button" onClick={() => void handleTest(config)} disabled={testingId === config.id}>
                        {testingId === config.id ? "测试中..." : "测试发送"}
                      </button>
                      <button className="btn-danger" type="button" onClick={() => void handleDelete(config)}>删除</button>
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <input className="field-input" value={value} onChange={(event) => onChange(event.target.value)} required={required} />
    </label>
  );
}

function CheckboxField({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-h-11 items-center gap-3 rounded-md border border-slate-200 px-3 py-2">
      <input
        className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-700"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="text-sm font-medium text-slate-800">{label}</span>
    </label>
  );
}

function FieldValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value break-words font-mono tabular-nums">{value || "-"}</dd>
    </div>
  );
}

function Badge({ text, tone }: { text: string; tone: "blue" | "slate" | "amber" }) {
  const className =
    tone === "blue"
      ? "bg-blue-50 text-blue-800"
      : tone === "amber"
        ? "bg-amber-50 text-amber-900"
        : "bg-slate-100 text-slate-600";
  return <span className={`rounded-md px-2 py-1 text-xs font-semibold ${className}`}>{text}</span>;
}

function Alert({ children, tone }: { children: string; tone: "red" | "green" }) {
  const className =
    tone === "red"
      ? "border-red-300 bg-red-50 text-red-900"
      : "border-emerald-300 bg-emerald-50 text-emerald-900";
  return (
    <div className={`rounded-md border px-3 py-2 text-sm ${className}`} role={tone === "red" ? "alert" : "status"}>
      {children}
    </div>
  );
}

function buildPayload(form: FormState): EmailConfigPayload {
  const payload: EmailConfigPayload = {
    name: form.name.trim(),
    smtp_host: form.smtp_host.trim(),
    smtp_port: Number(form.smtp_port || 587),
    from_email: form.from_email.trim(),
    from_name: optionalText(form.from_name),
    recipient_emails: parseRecipients(form.recipient_emails),
    use_tls: form.use_tls,
    use_ssl: form.use_ssl,
    purpose: form.purpose,
    enabled: form.enabled,
    is_default: form.is_default,
  };
  if (form.username.trim()) {
    payload.username = form.username.trim();
  }
  if (form.password.trim()) {
    payload.password = form.password.trim();
  }
  return payload;
}

function parseRecipients(value: string): string[] {
  return value
    .split(/[\n,;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
