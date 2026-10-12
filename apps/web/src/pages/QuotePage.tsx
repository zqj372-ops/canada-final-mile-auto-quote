import { useEffect, useRef, useState } from "react";
import {
  clearStoredAuthToken, getCurrentActor, getQuoteWorkbenchConfig, getStoredAuthToken,
  listSalesQuoteRecords, login, setStoredAuthToken,
  type CurrentActor, type QuoteWorkbenchConfig, type SalesQuoteRecord,
} from "../api/client";
import AccountMenu from "../components/AccountMenu";
import LogoutConfirmationDialog from "../components/LogoutConfirmationDialog";
import QuoteWorkbench from "../components/quote-workbench/QuoteWorkbench";
import SalesLoginPanel from "../components/quote-workbench/SalesLoginPanel";
import SalesQuoteRecords, { type SalesQuoteRecordFilter } from "../components/quote-workbench/SalesQuoteRecords";

export default function QuotePage({ adminHref }: { adminHref: string }) {
  const [actor, setActor] = useState<CurrentActor | null>(null);
  const [config, setConfig] = useState<QuoteWorkbenchConfig | null>(null);
  const [tab, setTab] = useState<"quote" | "records">("quote");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(Boolean(getStoredAuthToken()));
  const [loggingIn, setLoggingIn] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [records, setRecords] = useState<SalesQuoteRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  const [filter, setFilter] = useState<SalesQuoteRecordFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const sessionGeneration = useRef(0);

  useEffect(() => {
    let active = true;
    if (!getStoredAuthToken()) { setChecking(false); return; }
    void getCurrentActor("quote").then((value) => { if (active) setActor(value); })
      .catch((caught) => { if (active) { clearStoredAuthToken(); setAuthError(String(caught.message)); } })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => { if (actor) void loadConfig(); }, [actor]);
  useEffect(() => { if (actor && tab === "records") void refreshRecords(); }, [actor, tab]);

  async function loadConfig() {
    const generation = sessionGeneration.current;
    setError(null);
    try { const value = await getQuoteWorkbenchConfig("quote"); if (generation === sessionGeneration.current) setConfig(value); }
    catch (caught) { if (generation === sessionGeneration.current) setError(caught instanceof Error ? caught.message : "配置读取失败"); }
  }
  async function handleLogin() {
    if (loggingIn) return;
    if (!username.trim() || !password) { setAuthError("请输入账号和密码。"); return; }
    setLoggingIn(true); setAuthError(null);
    try { const response = await login({ username: username.trim(), password }); sessionGeneration.current += 1; setStoredAuthToken(response.access_token); setActor(response.actor); setPassword(""); }
    catch (caught) { setAuthError(caught instanceof Error ? caught.message : "登录失败"); }
    finally { setLoggingIn(false); }
  }
  async function refreshRecords() {
    const generation = sessionGeneration.current;
    setRecordsLoading(true); setRecordsError(null);
    try { const value = await listSalesQuoteRecords({ limit: 80 }); if (generation === sessionGeneration.current) setRecords(value); }
    catch (caught) { if (generation === sessionGeneration.current) setRecordsError(caught instanceof Error ? caught.message : "记录刷新失败"); }
    finally { if (generation === sessionGeneration.current) setRecordsLoading(false); }
  }
  function logout() {
    sessionGeneration.current += 1;
    setTab("quote"); setRecordsError(null); setRecordsLoading(false);
    clearStoredAuthToken(); setActor(null); setConfig(null); setRecords([]); setSelectedId(null); setLogoutOpen(false);
  }
  if (!actor || checking) return <div className="sales-frontdesk min-h-dvh"><SalesLoginPanel error={authError} isChecking={checking} isLoggingIn={loggingIn} onLogin={() => void handleLogin()} onPasswordChange={setPassword} onUsernameChange={setUsername} password={password} username={username} /></div>;

  return <div className="quote-app">
    <header className="qw-topbar">
      <div className="qw-brand"><strong>Canada Final Mile</strong><span>尾程报价工作台</span></div>
      <nav aria-label="销售前台功能"><button aria-current={tab === "quote" ? "page" : undefined} onClick={() => setTab("quote")}>报价工作台</button><button aria-current={tab === "records" ? "page" : undefined} onClick={() => setTab("records")}>报价记录</button></nav>
      <div className="qw-account">{["admin", "operator", "viewer"].includes(actor.role) && <a href={adminHref}>运营后台</a>}<AccountMenu actor={actor} roleLabel={{ admin: "管理员", operator: "运营", sales: "销售", viewer: "查看者" }[actor.role] || actor.role} variant="sales" onRequestLogout={() => setLogoutOpen(true)} /></div>
    </header>
    <div className="qw-page">
      <section className="qw-heading"><h1>{tab === "quote" ? "加拿大尾程报价" : "报价记录"}</h1><p>{tab === "quote" ? "粘贴客户询价，核对货物与地址，再生成报价。" : "查询报价、人工复核进度与客户回复。"}</p></section>
      <div hidden={tab !== "quote"}>
        {config ? <QuoteWorkbench config={config} onSaved={() => void refreshRecords()} /> : <section className="qw-panel"><p role="status">{error || "正在读取工作台配置…"}</p>{error && <button className="qw-secondary" onClick={() => void loadConfig()}>重新加载</button>}</section>}
      </div>
      {tab === "records" && <>{recordsError && <p className="qw-warning" role="alert">{recordsError}</p>}<SalesQuoteRecords records={records} filter={filter} query={query} isLoading={recordsLoading} selectedRecordId={selectedId} onFilterChange={setFilter} onQueryChange={setQuery} onSelectRecord={setSelectedId} onRefresh={() => void refreshRecords()} onNewQuote={() => setTab("quote")} /></>}
    </div>
    <LogoutConfirmationDialog isOpen={logoutOpen} onCancel={() => setLogoutOpen(false)} onConfirm={logout} />
  </div>;
}
