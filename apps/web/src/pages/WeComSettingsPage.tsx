import { FormEvent, useEffect, useState } from "react";
import {
  createWeComBot,
  deleteWeComBot,
  listWeComBots,
  setDefaultWeComBot,
  testWeComBot,
  updateWeComBot,
  type WeComBotConfigPayload,
  type WeComBotConfigPublic,
} from "../api/client";

interface FormState {
  id: number | null;
  name: string;
  webhook_url: string;
  bot_id: string;
  secret: string;
  bot_type: string;
  purpose: string;
  enabled: boolean;
  is_default: boolean;
  mention_all_on_manual_required: boolean;
}

const emptyForm: FormState = {
  id: null,
  name: "",
  webhook_url: "",
  bot_id: "",
  secret: "",
  bot_type: "wecom_aibot_long_connection",
  purpose: "general",
  enabled: true,
  is_default: false,
  mention_all_on_manual_required: false,
};

const purposes = ["quote_success", "manual_required", "ai_quote", "manual_resolved", "general"];

const botTypes = [
  { value: "wecom_aibot_long_connection", label: "智能机器人长连接（Bot ID + Secret）" },
  { value: "group_webhook", label: "群机器人 Webhook" },
];

export default function WeComSettingsPage() {
  const [bots, setBots] = useState<WeComBotConfigPublic[]>([]);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);

  useEffect(() => {
    void loadBots();
  }, []);

  async function loadBots() {
    setError(null);
    try {
      setBots(await listWeComBots());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "企业微信机器人加载失败");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!form.enabled && form.is_default) {
      setError("禁用的企业微信机器人不能设为默认，请先启用或取消默认。");
      return;
    }
    setIsSaving(true);
    try {
      const payload = buildPayload(form);
      if (form.id) {
        await updateWeComBot(form.id, payload);
        setNotice("企业微信机器人配置已更新");
      } else {
        await createWeComBot({
          ...payload,
          name: payload.name || "",
        });
        setNotice("企业微信机器人配置已新增");
      }
      setForm(emptyForm);
      await loadBots();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "企业微信机器人保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(bot: WeComBotConfigPublic) {
    if (!window.confirm(`确认删除企业微信机器人「${bot.name}」吗？`)) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      await deleteWeComBot(bot.id);
      setNotice(`已删除 ${bot.name}`);
      await loadBots();
      if (form.id === bot.id) {
        setForm(emptyForm);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "企业微信机器人删除失败");
    }
  }

  async function handleSetDefault(bot: WeComBotConfigPublic) {
    setError(null);
    setNotice(null);
    if (!bot.enabled) {
      setError("禁用的企业微信机器人不能设为默认，请先启用后再设置。");
      return;
    }
    try {
      await setDefaultWeComBot(bot.id);
      setNotice(`${bot.name} 已设为默认`);
      await loadBots();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "设置默认失败");
    }
  }

  async function handleTest(bot: WeComBotConfigPublic) {
    setError(null);
    setNotice(null);
    setTestingId(bot.id);
    try {
      const response = await testWeComBot(bot.id);
      setNotice(
        response.success
          ? `测试发送成功，耗时 ${response.latency_ms}ms`
          : `测试发送失败：${response.error || "unknown error"} (${response.latency_ms}ms)`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "测试发送失败");
    } finally {
      setTestingId(null);
    }
  }

  function edit(bot: WeComBotConfigPublic) {
    setForm({
      id: bot.id,
      name: bot.name,
      webhook_url: "",
      bot_id: "",
      secret: "",
      bot_type: bot.bot_type,
      purpose: bot.purpose,
      enabled: bot.enabled,
      is_default: bot.is_default,
      mention_all_on_manual_required: bot.mention_all_on_manual_required,
    });
    setNotice("编辑模式：Webhook URL / Secret 留空表示不修改");
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
      return next;
    });
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-blue-800">企业微信 Settings</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          企业微信机器人配置
        </h1>
      </header>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900" role="status">
          {notice}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[0.75fr_1.25fr]">
        <section className="panel p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">{form.id ? "编辑机器人" : "新增机器人"}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                智能机器人按企业微信 API 配置填写 Bot ID + Secret；Secret 和 Webhook 都只加密保存，不回显明文。
              </p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => setForm(emptyForm)}>
              新建
            </button>
          </div>

          <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
            <TextField label="机器人名称 *" value={form.name} onChange={(value) => update("name", value)} required />
            <label>
              <span className="field-label">连接方式</span>
              <select className="field-input" value={form.bot_type} onChange={(event) => update("bot_type", event.target.value)}>
                {botTypes.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </label>
            {form.bot_type === "wecom_aibot_long_connection" ? (
              <div className="grid gap-4">
                <TextField label="Bot ID *" value={form.bot_id} onChange={(value) => update("bot_id", value)} required={!form.id} />
                <label>
                  <span className="field-label">Secret {form.id ? "" : "*"}</span>
                  <input
                    className="field-input"
                    type="password"
                    value={form.secret}
                    onChange={(event) => update("secret", event.target.value)}
                    autoComplete="new-password"
                    required={!form.id}
                  />
                  {form.id && <p className="field-hint">留空表示不修改当前 Secret</p>}
                </label>
                <p className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
                  适用于企业微信“智能机器人 / API 配置 / 使用长连接”。Bot ID 可显示掩码，Secret 不回显。
                </p>
              </div>
            ) : (
              <label>
                <span className="field-label">Webhook URL {form.id ? "" : "*"}</span>
                <input
                  className="field-input"
                  type="password"
                  value={form.webhook_url}
                  onChange={(event) => update("webhook_url", event.target.value)}
                  autoComplete="new-password"
                  required={!form.id}
                />
                {form.id && <p className="field-hint">留空表示不修改当前 Webhook</p>}
              </label>
            )}
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
              <CheckboxField label="enabled" checked={form.enabled} onChange={(value) => update("enabled", value)} />
              <CheckboxField label="is_default" checked={form.is_default} onChange={(value) => update("is_default", value)} disabled={!form.enabled} />
              <CheckboxField
                label="manual_required 时 @all"
                checked={form.mention_all_on_manual_required}
                onChange={(value) => update("mention_all_on_manual_required", value)}
              />
            </div>
            <button className="btn-primary" type="submit" disabled={isSaving}>
              {isSaving ? "保存中..." : form.id ? "保存配置" : "新增机器人"}
            </button>
          </form>
        </section>

        <section className="panel p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="section-title">机器人列表</h2>
              <p className="mt-1 text-sm text-slate-600">
                禁用的机器人不会发送通知，Webhook / Secret 明文不会返回前端。
              </p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => void loadBots()}>
              刷新
            </button>
          </div>

          <div className="mt-5 grid gap-4">
            {bots.length === 0 ? (
              <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600">
                还没有企业微信机器人配置。
              </p>
            ) : (
              bots.map((bot) => (
                <article key={bot.id} className="rounded-md border border-slate-200 p-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-slate-950">{bot.name}</h3>
                        {bot.is_default && <Badge text="默认" tone="blue" />}
                        {!bot.enabled && <Badge text="disabled" tone="slate" />}
                        {bot.mention_all_on_manual_required && <Badge text="manual @all" tone="amber" />}
                      </div>
                      <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                        <FieldValue label="purpose" value={bot.purpose} />
                        <FieldValue label="bot_type" value={bot.bot_type} />
                        {bot.bot_type === "wecom_aibot_long_connection" ? (
                          <>
                            <FieldValue label="masked_bot_id" value={bot.masked_bot_id || "未设置"} />
                            <FieldValue label="secret" value={bot.has_secret ? "已加密保存" : "未设置"} />
                          </>
                        ) : (
                          <FieldValue label="masked_webhook_url" value={bot.masked_webhook_url || "未设置"} />
                        )}
                      </dl>
                    </div>
                    <div className="grid min-w-40 gap-2 sm:grid-cols-2 lg:grid-cols-1">
                      <button className="btn-secondary" type="button" onClick={() => edit(bot)}>编辑</button>
                      <button className="btn-secondary" type="button" onClick={() => void handleSetDefault(bot)} disabled={bot.is_default || !bot.enabled}>
                        设为默认
                      </button>
                      <button className="btn-secondary" type="button" onClick={() => void handleTest(bot)} disabled={testingId === bot.id}>
                        {testingId === bot.id ? "测试中..." : "测试发送"}
                      </button>
                      <button className="btn-danger" type="button" onClick={() => void handleDelete(bot)}>删除</button>
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
    <div>
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value break-words font-mono tabular-nums">{value}</dd>
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

function buildPayload(form: FormState): WeComBotConfigPayload {
  const payload: WeComBotConfigPayload = {
    name: form.name.trim(),
    bot_type: form.bot_type,
    purpose: form.purpose,
    enabled: form.enabled,
    is_default: form.is_default,
    mention_all_on_manual_required: form.mention_all_on_manual_required,
  };
  if (form.bot_type === "wecom_aibot_long_connection" && form.bot_id.trim()) {
    payload.bot_id = form.bot_id.trim();
  }
  if (form.bot_type === "wecom_aibot_long_connection" && form.secret.trim()) {
    payload.secret = form.secret.trim();
  }
  if (form.bot_type === "group_webhook" && form.webhook_url.trim()) {
    payload.webhook_url = form.webhook_url.trim();
  }
  return payload;
}
