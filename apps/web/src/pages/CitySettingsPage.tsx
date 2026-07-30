import {
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  listZoneCityRules,
  listZonePriceMatrix,
  saveZoneCityRuleGroup,
  type ZoneCityRuleRecord,
  type ZonePriceMatrixListResponse,
} from "../api/client";

type CityRuleGroup = {
  key: string;
  city: string;
  canonicalCity: string;
  province: string;
  rules: ZoneCityRuleRecord[];
};

type CityRuleDraft = {
  key: string;
  id: number | null;
  postalPrefix: string;
  origin: string;
  zone: string;
  priority: string;
  note: string;
};

type CityGroupDraft = {
  originalKey: string | null;
  city: string;
  canonicalCity: string;
  province: string;
  rules: CityRuleDraft[];
  removedRules: CityRuleDraft[];
};

type CityIconName =
  | "alert"
  | "check"
  | "city"
  | "close"
  | "edit"
  | "layers"
  | "map"
  | "plus"
  | "postal"
  | "refresh"
  | "save"
  | "search"
  | "trash"
  | "warehouse";

const PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"];
const WESTERN_PROVINCES = new Set(["AB", "BC", "MB", "SK", "NT", "NU", "YT"]);
const FSA_PATTERN = /^[ABCEGHJKLMNPRSTVXY]\d[ABCEGHJKLMNPRSTVWXYZ]$/;

export default function CitySettingsPage() {
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const [records, setRecords] = useState<ZoneCityRuleRecord[]>([]);
  const [matrix, setMatrix] = useState<ZonePriceMatrixListResponse | null>(null);
  const [search, setSearch] = useState("");
  const [originFilter, setOriginFilter] = useState(() => initialParams.get("origin") || "");
  const [zoneFilter, setZoneFilter] = useState(() => initialParams.get("zone") || "");
  const [draft, setDraft] = useState<CityGroupDraft | null>(null);
  const [prefixInput, setPrefixInput] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [batchZone, setBatchZone] = useState("");
  const [batchPriority, setBatchPriority] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLFormElement>(null);
  const editorTriggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    void loadAll();
  }, []);

  useEffect(() => {
    if (!draft) {
      return;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isSaving) {
        closeEditor();
      }
      if (event.key === "Tab" && dialogRef.current) {
        const focusable = Array.from(
          dialogRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href]',
          ),
        ).filter((element) => !element.hasAttribute("hidden"));
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) {
          return;
        }
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [draft !== null, isSaving]);

  const groups = useMemo(() => groupCityRules(records), [records]);
  const origins = useMemo(
    () =>
      Array.from(
        new Set([
          ...(matrix?.origins ?? []),
          ...records.map((record) => record.origin),
        ]),
      ).sort(),
    [matrix?.origins, records],
  );
  const zones = useMemo(
    () =>
      Array.from(
        new Set([
          ...(matrix?.zones ?? []),
          ...records.map((record) => record.zone),
        ]),
      ).sort((left, right) => left - right),
    [matrix?.zones, records],
  );
  const visibleGroups = useMemo(() => {
    const query = search.trim().toLowerCase();
    return groups.filter((group) => {
      const groupMatches =
        !query ||
        [group.city, group.canonicalCity, group.province].some((value) =>
          value.toLowerCase().includes(query),
        ) ||
        group.rules.some((rule) =>
          [rule.postal_prefix, rule.note].some((value) =>
            value?.toLowerCase().includes(query),
          ),
        );
      const assignmentMatches = group.rules.some(
        (rule) =>
          (!originFilter || rule.origin === originFilter) &&
          (!zoneFilter || String(rule.zone) === zoneFilter),
      );
      return groupMatches && assignmentMatches;
    });
  }, [groups, originFilter, search, zoneFilter]);
  const assignmentCount = useMemo(
    () => new Set(records.map((record) => `${record.origin}|${record.zone}`)).size,
    [records],
  );

  async function loadAll() {
    setIsLoading(true);
    setError(null);
    try {
      const [ruleResponse, matrixResponse] = await Promise.all([
        listZoneCityRules({ limit: 1000 }),
        listZonePriceMatrix({ limit: 5000 }),
      ]);
      setRecords(ruleResponse.records);
      setMatrix(matrixResponse);
      if (ruleResponse.total > ruleResponse.records.length) {
        setNotice(`当前规则超过 ${ruleResponse.records.length} 条，页面仅显示前 ${ruleResponse.records.length} 条。`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "城市与邮编配置读取失败。");
    } finally {
      setIsLoading(false);
    }
  }

  function startCreate() {
    editorTriggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const province = "ON";
    const origin = originForProvince(province);
    setDraft({
      originalKey: null,
      city: "",
      canonicalCity: "",
      province,
      rules: [],
      removedRules: [],
    });
    setPrefixInput("");
    setSelectedKeys(new Set());
    setBatchZone(String(defaultZone(matrix, origin)));
    setBatchPriority("100");
    setError(null);
    setNotice(null);
  }

  function startEdit(group: CityRuleGroup) {
    editorTriggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const rules = group.rules.map((rule) => ({
      key: `rule-${rule.id}`,
      id: rule.id,
      postalPrefix: rule.postal_prefix,
      origin: rule.origin,
      zone: String(rule.zone),
      priority: String(rule.priority),
      note: rule.note ?? "",
    }));
    const commonZone = mostCommon(rules.map((rule) => rule.zone)) || rules[0]?.zone || "1";
    const commonPriority =
      mostCommon(rules.map((rule) => rule.priority)) || rules[0]?.priority || "100";
    setDraft({
      originalKey: group.key,
      city: group.city,
      canonicalCity: group.canonicalCity,
      province: group.province,
      rules,
      removedRules: [],
    });
    setPrefixInput("");
    setSelectedKeys(new Set(rules.map((rule) => rule.key)));
    setBatchZone(commonZone);
    setBatchPriority(commonPriority);
    setError(null);
    setNotice(null);
  }

  function closeEditor() {
    setDraft(null);
    setPrefixInput("");
    setSelectedKeys(new Set());
    window.requestAnimationFrame(() => editorTriggerRef.current?.focus());
  }

  function updateProvince(province: string) {
    const origin = originForProvince(province);
    setDraft((current) =>
      current
        ? {
            ...current,
            province,
            rules: current.rules.map((rule) => ({ ...rule, origin })),
          }
        : current,
    );
  }

  function addPostalPrefixes() {
    if (!draft) {
      return;
    }
    const tokens = splitPostalPrefixes(prefixInput);
    const invalid = tokens.filter((prefix) => !FSA_PATTERN.test(prefix));
    if (!tokens.length) {
      setError("请输入至少一个加拿大 FSA，例如 L6P、L6T、L6W。");
      return;
    }
    if (invalid.length) {
      setError(`这些 FSA 格式无效：${invalid.join("、")}。`);
      return;
    }
    const existingPrefixes = new Set(draft.rules.map((rule) => rule.postalPrefix));
    const removedByPrefix = new Map(
      draft.removedRules.map((rule) => [rule.postalPrefix, rule]),
    );
    const duplicatePrefixes = tokens.filter((prefix) => existingPrefixes.has(prefix));
    const uniqueTokens = Array.from(new Set(tokens));
    const restoredRules = uniqueTokens
      .map((prefix) => removedByPrefix.get(prefix))
      .filter((rule): rule is CityRuleDraft => Boolean(rule));
    const restoredPrefixes = new Set(restoredRules.map((rule) => rule.postalPrefix));
    const newPrefixes = uniqueTokens.filter(
      (prefix) => !existingPrefixes.has(prefix) && !restoredPrefixes.has(prefix),
    );
    if (!newPrefixes.length && !restoredRules.length) {
      setError(`输入的 FSA 已在当前城市中${duplicatePrefixes.length ? `：${duplicatePrefixes.join("、")}` : ""}。`);
      return;
    }

    const origin = originForProvince(draft.province);
    const zone = batchZone || String(defaultZone(matrix, origin));
    const priority = batchPriority || "100";
    const nextRules = newPrefixes.map((postalPrefix, index) => ({
      key: `new-${Date.now()}-${index}`,
      id: null,
      postalPrefix,
      origin,
      zone,
      priority,
      note: "",
    }));
    setDraft((current) =>
      current
        ? {
            ...current,
            rules: [...current.rules, ...restoredRules, ...nextRules],
            removedRules: current.removedRules.filter(
              (rule) => !restoredPrefixes.has(rule.postalPrefix),
            ),
          }
        : current,
    );
    setSelectedKeys(new Set([...restoredRules, ...nextRules].map((rule) => rule.key)));
    setPrefixInput("");
    setError(null);
    if (duplicatePrefixes.length) {
      setNotice(`${duplicatePrefixes.join("、")} 已存在，已自动跳过。`);
    } else if (restoredRules.length) {
      setNotice(`已恢复 ${restoredRules.map((rule) => rule.postalPrefix).join("、")}，将沿用原规则记录。`);
    }
  }

  function toggleRule(ruleKey: string) {
    setSelectedKeys((current) => {
      const next = new Set(current);
      if (next.has(ruleKey)) {
        next.delete(ruleKey);
      } else {
        next.add(ruleKey);
      }
      return next;
    });
  }

  function toggleAllRules() {
    if (!draft) {
      return;
    }
    setSelectedKeys((current) =>
      current.size === draft.rules.length
        ? new Set()
        : new Set(draft.rules.map((rule) => rule.key)),
    );
  }

  function applyBatchAssignment() {
    if (!draft || !selectedKeys.size) {
      setError("请先勾选要批量修改的邮编。");
      return;
    }
    const zone = Number(batchZone);
    const priority = Number(batchPriority);
    if (!Number.isInteger(zone) || zone < 1) {
      setError("批量 Zone 必须是正整数。");
      return;
    }
    if (!Number.isInteger(priority) || priority < 1 || priority > 1000) {
      setError("批量优先级必须是 1 至 1000 的整数。");
      return;
    }
    const origin = originForProvince(draft.province);
    setDraft((current) =>
      current
        ? {
            ...current,
            rules: current.rules.map((rule) =>
              selectedKeys.has(rule.key)
                ? { ...rule, origin, zone: String(zone), priority: String(priority) }
                : rule,
            ),
          }
        : current,
    );
    setError(null);
    setNotice(`已将 ${selectedKeys.size} 个邮编统一调整为 ${formatOrigin(origin)} · Zone ${zone}。`);
  }

  function removeSelectedRules() {
    if (!draft || !selectedKeys.size) {
      setError("请先勾选要移除的邮编。");
      return;
    }
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const removed = current.rules.filter((rule) => selectedKeys.has(rule.key));
      return {
        ...current,
        rules: current.rules.filter((rule) => !selectedKeys.has(rule.key)),
        removedRules: [...current.removedRules, ...removed],
      };
    });
    setSelectedKeys(new Set());
    setError(null);
  }

  function removeRule(ruleKey: string) {
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const removed = current.rules.find((rule) => rule.key === ruleKey);
      if (!removed) {
        return current;
      }
      return {
        ...current,
        rules: current.rules.filter((rule) => rule.key !== ruleKey),
        removedRules: [...current.removedRules, removed],
      };
    });
    setSelectedKeys((current) => {
      const next = new Set(current);
      next.delete(ruleKey);
      return next;
    });
    setError(null);
  }

  function restoreRemovedRules() {
    setDraft((current) =>
      current
        ? {
            ...current,
            rules: [...current.rules, ...current.removedRules],
            removedRules: [],
          }
        : current,
    );
    setError(null);
  }

  function updateRule(ruleKey: string, patch: Partial<CityRuleDraft>) {
    setDraft((current) =>
      current
        ? {
            ...current,
            rules: current.rules.map((rule) =>
              rule.key === ruleKey ? { ...rule, ...patch } : rule,
            ),
          }
        : current,
    );
  }

  async function saveCity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) {
      return;
    }
    const city = draft.city.trim();
    const canonicalCity = (draft.canonicalCity || draft.city).trim();
    if (!city || !canonicalCity || !draft.province) {
      setError("请填写城市、省份和标准城市名。");
      return;
    }
    if (!draft.rules.length && !draft.removedRules.some((rule) => rule.id !== null)) {
      setError("请至少为这个城市添加一个 FSA。");
      return;
    }
    const prefixes = draft.rules.map((rule) => rule.postalPrefix.trim().toUpperCase());
    const invalidPrefixes = prefixes.filter((prefix) => !FSA_PATTERN.test(prefix));
    if (invalidPrefixes.length) {
      setError(`这些 FSA 格式无效：${invalidPrefixes.join("、")}。`);
      return;
    }
    if (new Set(prefixes).size !== prefixes.length) {
      setError("同一个城市中不能出现重复 FSA。");
      return;
    }
    const invalidRule = draft.rules.find((rule) => {
      const zone = Number(rule.zone);
      const priority = Number(rule.priority);
      return (
        !Number.isInteger(zone) ||
        zone < 1 ||
        !Number.isInteger(priority) ||
        priority < 1 ||
        priority > 1000
      );
    });
    if (invalidRule) {
      setError(`${invalidRule.postalPrefix || "某个邮编"} 的 Zone 或优先级无效。`);
      return;
    }

    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const result = await saveZoneCityRuleGroup({
        city,
        province: draft.province,
        canonical_city: canonicalCity,
        rules: draft.rules.map((rule) => ({
          id: rule.id,
          postal_prefix: rule.postalPrefix.trim().toUpperCase(),
          origin: originForProvince(draft.province),
          zone: Number(rule.zone),
          priority: Number(rule.priority),
          note: rule.note.trim() || null,
        })),
        deactivate_ids: draft.removedRules
          .map((rule) => rule.id)
          .filter((recordId): recordId is number => recordId !== null),
      });
      await loadAll();
      closeEditor();
      setNotice(
        `${canonicalCity.toUpperCase()} 已保存：新增 ${result.created_count} 个、更新 ${result.updated_count} 个、停用 ${result.deactivated_count} 个邮编。`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "城市邮编批量保存失败。");
    } finally {
      setIsSaving(false);
    }
  }

  const allRulesSelected = Boolean(
    draft?.rules.length && selectedKeys.size === draft.rules.length,
  );

  return (
    <div className="pricing-page-v2 city-settings-page">
      <header className="pricing-page-header city-settings-header">
        <div className="pricing-heading">
          <div className="pricing-breadcrumb" aria-label="当前位置">
            <span>运价管理</span>
            <span aria-hidden="true">/</span>
            <strong>城市配置</strong>
          </div>
          <h1>城市与邮编配置</h1>
          <p>以城市为单位集中维护多个 FSA；选中多个邮编后，可一次调整 Zone 或批量停用。</p>
        </div>
        <div className="pricing-page-actions">
          <button className="btn-secondary" type="button" onClick={loadAll} disabled={isLoading}>
            <CityIcon name="refresh" />
            {isLoading ? "读取中…" : "重新读取"}
          </button>
          <button className="btn-primary" type="button" onClick={startCreate} disabled={isLoading}>
            <CityIcon name="plus" />
            新增城市
          </button>
        </div>
      </header>

      {(error || notice) && !draft && (
        <div className={`pricing-feedback ${error ? "is-error" : "is-success"}`} role={error ? "alert" : "status"}>
          <CityIcon name={error ? "alert" : "check"} />
          <span>{error || notice}</span>
        </div>
      )}

      <section className="city-settings-metrics" aria-label="城市配置概览">
        <CityMetric icon="city" label="城市" value={`${groups.length} 个`} hint="一城一组" />
        <CityMetric icon="postal" label="有效 FSA" value={`${records.length} 个`} hint="集中维护" />
        <CityMetric icon="layers" label="分区组合" value={`${assignmentCount} 组`} hint="始发仓 / Zone" />
        <CityMetric icon="check" label="生效时间" value="保存后立即" hint="原子批量提交" />
      </section>

      <section className="pricing-panel city-settings-workspace">
        <div className="city-settings-command">
          <div>
            <span className="pricing-eyebrow">城市列表</span>
            <h2>先找城市，再管理它的邮编</h2>
            <p>不需要先进入某个 Zone。搜索城市或 FSA，打开城市后一次处理多个邮编。</p>
          </div>
          <span className="city-settings-result-count">
            {originFilter || zoneFilter ? "包含筛选分区的城市" : "显示城市"} {visibleGroups.length} / {groups.length}
          </span>
        </div>

        <div className="city-settings-filters">
          <label className="city-settings-search">
            <CityIcon name="search" />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索城市、标准城市名或 FSA"
              aria-label="搜索城市、标准城市名或 FSA"
            />
          </label>
          <label className="city-settings-filter">
            <span>始发仓</span>
            <select value={originFilter} onChange={(event) => setOriginFilter(event.target.value)}>
              <option value="">全部始发仓</option>
              {origins.map((origin) => (
                <option value={origin} key={origin}>{formatOrigin(origin)}</option>
              ))}
            </select>
          </label>
          <label className="city-settings-filter">
            <span>Zone</span>
            <select value={zoneFilter} onChange={(event) => setZoneFilter(event.target.value)}>
              <option value="">全部 Zone</option>
              {zones.map((zone) => (
                <option value={zone} key={zone}>Zone {zone}</option>
              ))}
            </select>
          </label>
          {(search || originFilter || zoneFilter) && (
            <button
              className="city-settings-reset"
              type="button"
              onClick={() => {
                setSearch("");
                setOriginFilter("");
                setZoneFilter("");
              }}
            >
              清除筛选
            </button>
          )}
        </div>

        <div className="city-group-list">
          {isLoading && !records.length ? (
            <div className="city-settings-empty">正在读取城市与邮编配置…</div>
          ) : visibleGroups.length ? (
            visibleGroups.map((group) => {
              const assignments = summarizeAssignments(group.rules);
              const assignmentFilterActive = Boolean(originFilter || zoneFilter);
              const matchingAssignmentCount = group.rules.filter(
                (rule) =>
                  (!originFilter || rule.origin === originFilter) &&
                  (!zoneFilter || String(rule.zone) === zoneFilter),
              ).length;
              return (
                <article className="city-group-card" key={group.key}>
                  <div className="city-group-identity">
                    <span className="city-group-mark"><CityIcon name="map" /></span>
                    <div>
                      <div className="city-group-title">
                        <h3>{group.canonicalCity}</h3>
                        <span>{group.province}</span>
                      </div>
                      {group.city !== group.canonicalCity && (
                        <small>规则城市名：{group.city}</small>
                      )}
                    </div>
                  </div>

                  <div className="city-group-postals">
                    <span className="city-group-label">
                      FSA 邮编 · {assignmentFilterActive ? `${matchingAssignmentCount} / ` : ""}{group.rules.length}
                    </span>
                    <div>
                      {group.rules.map((rule) => {
                        const assignmentMatches =
                          (!originFilter || rule.origin === originFilter) &&
                          (!zoneFilter || String(rule.zone) === zoneFilter);
                        const searchMatches =
                          search.trim() &&
                          rule.postal_prefix.toLowerCase().includes(search.trim().toLowerCase());
                        const className = [
                          "city-postal-chip",
                          searchMatches || (assignmentFilterActive && assignmentMatches) ? "is-match" : "",
                          assignmentFilterActive && !assignmentMatches ? "is-muted" : "",
                        ].filter(Boolean).join(" ");
                        return <span className={className} key={rule.id}>{rule.postal_prefix}</span>;
                      })}
                    </div>
                  </div>

                  <div className="city-group-assignments">
                    <span className="city-group-label">分区归属</span>
                    <div>
                      {assignments.map((assignment) => {
                        const assignmentMatches =
                          (!originFilter || assignment.origin === originFilter) &&
                          (!zoneFilter || String(assignment.zone) === zoneFilter);
                        return <span
                          className={`city-assignment-chip${assignmentFilterActive && !assignmentMatches ? " is-muted" : ""}${assignmentFilterActive && assignmentMatches ? " is-match" : ""}`}
                          key={assignment.key}
                        >
                          <CityIcon name="warehouse" />
                          {formatOrigin(assignment.origin)} · Zone {assignment.zone}
                          <small>{assignment.count}</small>
                        </span>;
                      })}
                    </div>
                  </div>

                  <button
                    className="city-group-manage"
                    type="button"
                    onClick={() => startEdit(group)}
                    aria-label={`批量管理 ${group.canonicalCity} 的 ${group.rules.length} 个邮编`}
                  >
                    <CityIcon name="edit" />
                    批量管理
                    <span>{group.rules.length}</span>
                  </button>
                </article>
              );
            })
          ) : (
            <div className="city-settings-empty">
              <span><CityIcon name="city" /></span>
              <strong>{groups.length ? "没有匹配的城市" : "还没有城市配置"}</strong>
              <small>{groups.length ? "换一个城市名、FSA 或筛选条件试试。" : "点击“新增城市”，一次加入多个 FSA。"}</small>
            </div>
          )}
        </div>
      </section>

      {draft && (
        <div
          className="city-batch-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !isSaving) {
              closeEditor();
            }
          }}
        >
          <form
            ref={dialogRef}
            className="city-batch-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="city-batch-title"
            onSubmit={saveCity}
          >
            <header className="city-batch-header">
              <div>
                <span className="pricing-eyebrow">城市批量配置</span>
                <h2 id="city-batch-title">
                  {draft.originalKey ? `管理 ${draft.canonicalCity}` : "新增城市"}
                </h2>
                <p>城市信息维护一次；下方可一次添加、勾选和调整多个 FSA。</p>
              </div>
              <button
                ref={closeButtonRef}
                className="city-batch-close"
                type="button"
                onClick={closeEditor}
                disabled={isSaving}
                aria-label="关闭城市批量配置"
              >
                <CityIcon name="close" />
              </button>
            </header>

            <div className="city-batch-scroll">
              {(error || notice) && (
                <div className={`pricing-feedback ${error ? "is-error" : "is-success"} city-batch-feedback`} role={error ? "alert" : "status"}>
                  <CityIcon name={error ? "alert" : "check"} />
                  <span>{error || notice}</span>
                </div>
              )}

              <section className="city-batch-section">
                <div className="city-batch-section-heading">
                  <div>
                    <span>1</span>
                    <strong>城市信息</strong>
                  </div>
                  <small>省份会自动确定始发仓：{formatOrigin(originForProvince(draft.province))}</small>
                </div>
                <div className="city-group-fields">
                  <label>
                    <span className="field-label">城市</span>
                    <input
                      className="field-input"
                      value={draft.city}
                      onChange={(event) =>
                        setDraft((current) => current ? { ...current, city: event.target.value } : current)
                      }
                      placeholder="例如 BRAMPTON"
                      autoComplete="off"
                    />
                  </label>
                  <label>
                    <span className="field-label">标准城市名</span>
                    <input
                      className="field-input"
                      value={draft.canonicalCity}
                      onChange={(event) =>
                        setDraft((current) => current ? { ...current, canonicalCity: event.target.value } : current)
                      }
                      placeholder="留空则与城市一致"
                      autoComplete="off"
                    />
                  </label>
                  <label>
                    <span className="field-label">省份</span>
                    <select
                      className="field-input"
                      value={draft.province}
                      onChange={(event) => updateProvince(event.target.value)}
                    >
                      {PROVINCES.map((province) => (
                        <option value={province} key={province}>{province}</option>
                      ))}
                    </select>
                  </label>
                </div>
              </section>

              <section className="city-batch-section">
                <div className="city-batch-section-heading">
                  <div>
                    <span>2</span>
                    <strong>批量加入 FSA</strong>
                  </div>
                  <small>支持用空格、逗号或换行分隔</small>
                </div>
                <div className="city-prefix-adder">
                  <label>
                    <span className="field-label">粘贴多个 FSA</span>
                    <textarea
                      value={prefixInput}
                      onChange={(event) => setPrefixInput(event.target.value.toUpperCase())}
                      placeholder={"例如：L6P, L6T, L6W\n也可以从表格直接粘贴"}
                      rows={2}
                    />
                  </label>
                  <div className="city-prefix-defaults">
                    <label>
                      <span className="field-label">默认 Zone</span>
                      <input
                        className="field-input"
                        type="number"
                        min={1}
                        step={1}
                        value={batchZone}
                        onChange={(event) => setBatchZone(event.target.value)}
                      />
                    </label>
                    <label>
                      <span className="field-label">默认优先级</span>
                      <input
                        className="field-input"
                        type="number"
                        min={1}
                        max={1000}
                        step={1}
                        value={batchPriority}
                        onChange={(event) => setBatchPriority(event.target.value)}
                      />
                    </label>
                    <button className="btn-primary" type="button" onClick={addPostalPrefixes}>
                      <CityIcon name="plus" />
                      加入列表
                    </button>
                  </div>
                </div>
              </section>

              <section className="city-batch-section city-rule-section">
                <div className="city-batch-section-heading">
                  <div>
                    <span>3</span>
                    <strong>邮编与分区</strong>
                  </div>
                  <small>{draft.rules.length} 个有效 · {draft.removedRules.filter((rule) => rule.id !== null).length} 个待停用</small>
                </div>

                <div className="city-batch-toolbar">
                  <label className="city-select-all">
                    <input
                      type="checkbox"
                      checked={allRulesSelected}
                      onChange={toggleAllRules}
                      disabled={!draft.rules.length}
                    />
                    <span>{selectedKeys.size ? `已选 ${selectedKeys.size} 个` : "全选"}</span>
                  </label>
                  <label>
                    <span>统一 Zone</span>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={batchZone}
                      onChange={(event) => setBatchZone(event.target.value)}
                    />
                  </label>
                  <label>
                    <span>统一优先级</span>
                    <input
                      type="number"
                      min={1}
                      max={1000}
                      step={1}
                      value={batchPriority}
                      onChange={(event) => setBatchPriority(event.target.value)}
                    />
                  </label>
                  <button
                    className="city-batch-apply"
                    type="button"
                    onClick={applyBatchAssignment}
                    disabled={!selectedKeys.size}
                  >
                    应用到已选
                  </button>
                  <button
                    className="city-batch-remove"
                    type="button"
                    onClick={removeSelectedRules}
                    disabled={!selectedKeys.size}
                  >
                    <CityIcon name="trash" />
                    批量移除
                  </button>
                </div>

                <div className="city-rule-list" role="list">
                  {draft.rules.length ? (
                    draft.rules.map((rule) => (
                      <div className={selectedKeys.has(rule.key) ? "city-rule-row is-selected" : "city-rule-row"} role="listitem" key={rule.key}>
                        <label className="city-rule-check">
                          <input
                            type="checkbox"
                            checked={selectedKeys.has(rule.key)}
                            onChange={() => toggleRule(rule.key)}
                            aria-label={`选择 ${rule.postalPrefix || "新邮编"}`}
                          />
                        </label>
                        <label className="city-rule-prefix-field">
                          <span>FSA</span>
                          <input
                            value={rule.postalPrefix}
                            onChange={(event) =>
                              updateRule(rule.key, {
                                postalPrefix: event.target.value.toUpperCase().replace(/\s/g, "").slice(0, 3),
                              })
                            }
                            placeholder="L6P"
                            maxLength={3}
                          />
                        </label>
                        <div className="city-rule-origin">
                          <span>始发仓</span>
                          <strong>{formatOrigin(originForProvince(draft.province))}</strong>
                        </div>
                        <label className="city-rule-zone">
                          <span>Zone</span>
                          <input
                            type="number"
                            min={1}
                            step={1}
                            value={rule.zone}
                            onChange={(event) => updateRule(rule.key, { zone: event.target.value })}
                          />
                        </label>
                        <label className="city-rule-priority">
                          <span>优先级</span>
                          <input
                            type="number"
                            min={1}
                            max={1000}
                            step={1}
                            value={rule.priority}
                            onChange={(event) => updateRule(rule.key, { priority: event.target.value })}
                          />
                        </label>
                        <label className="city-rule-note">
                          <span>备注</span>
                          <input
                            value={rule.note}
                            onChange={(event) => updateRule(rule.key, { note: event.target.value })}
                            placeholder="可选"
                          />
                        </label>
                        <button
                          className="city-rule-remove-one"
                          type="button"
                          onClick={() => removeRule(rule.key)}
                          aria-label={`移除 ${rule.postalPrefix || "新邮编"}`}
                        >
                          <CityIcon name="trash" />
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="city-rule-empty">
                      <CityIcon name="postal" />
                      <strong>当前列表没有邮编</strong>
                      <small>在上方粘贴多个 FSA 后点击“加入列表”。</small>
                    </div>
                  )}
                </div>

                {draft.removedRules.length > 0 && (
                  <div className="city-removed-summary">
                    <span>
                      已移除 {draft.removedRules.length} 个：
                      {draft.removedRules.map((rule) => rule.postalPrefix).join("、")}
                    </span>
                    <button type="button" onClick={restoreRemovedRules}>全部撤销</button>
                  </div>
                )}
              </section>
            </div>

            <footer className="city-batch-footer">
              <div>
                <CityIcon name="check" />
                <span>保存会一次提交全部变更；任一邮编有误时整批回滚。</span>
              </div>
              <div>
                <button className="btn-secondary" type="button" onClick={closeEditor} disabled={isSaving}>
                  取消
                </button>
                <button className="btn-primary" type="submit" disabled={isSaving}>
                  <CityIcon name="save" />
                  {isSaving ? "批量保存中…" : `保存城市配置 · ${draft.rules.length}`}
                </button>
              </div>
            </footer>
          </form>
        </div>
      )}
    </div>
  );
}

function CityMetric({
  icon,
  label,
  value,
  hint,
}: {
  icon: CityIconName;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="city-settings-metric">
      <span><CityIcon name={icon} /></span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <em>{hint}</em>
      </div>
    </div>
  );
}

function groupCityRules(records: ZoneCityRuleRecord[]): CityRuleGroup[] {
  const groups = new Map<string, CityRuleGroup>();
  records.forEach((record) => {
    const canonicalCity = (record.canonical_city || record.city).toUpperCase();
    const key = `${record.province.toUpperCase()}|${canonicalCity}`;
    const current = groups.get(key);
    if (current) {
      current.rules.push(record);
      return;
    }
    groups.set(key, {
      key,
      city: record.city.toUpperCase(),
      canonicalCity,
      province: record.province.toUpperCase(),
      rules: [record],
    });
  });
  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      rules: [...group.rules].sort((left, right) =>
        left.postal_prefix.localeCompare(right.postal_prefix),
      ),
    }))
    .sort((left, right) =>
      left.canonicalCity.localeCompare(right.canonicalCity) ||
      left.province.localeCompare(right.province),
    );
}

function summarizeAssignments(rules: ZoneCityRuleRecord[]) {
  const assignments = new Map<
    string,
    { key: string; origin: string; zone: number; count: number }
  >();
  rules.forEach((rule) => {
    const key = `${rule.origin}|${rule.zone}`;
    const current = assignments.get(key);
    if (current) {
      current.count += 1;
    } else {
      assignments.set(key, {
        key,
        origin: rule.origin,
        zone: rule.zone,
        count: 1,
      });
    }
  });
  return Array.from(assignments.values()).sort(
    (left, right) =>
      left.origin.localeCompare(right.origin) || left.zone - right.zone,
  );
}

function splitPostalPrefixes(value: string): string[] {
  return value
    .toUpperCase()
    .split(/[\s,，;；]+/)
    .map((prefix) => prefix.trim())
    .filter(Boolean);
}

function originForProvince(province: string): string {
  return WESTERN_PROVINCES.has(province.toUpperCase()) ? "calgary" : "toronto";
}

function defaultZone(matrix: ZonePriceMatrixListResponse | null, origin: string): number {
  const zones = matrix?.records
    .filter((record) => record.origin === origin)
    .map((record) => record.zone)
    .sort((left, right) => left - right);
  return zones?.[0] ?? matrix?.zones[0] ?? 1;
}

function mostCommon(values: string[]): string {
  const counts = new Map<string, number>();
  values.forEach((value) => counts.set(value, (counts.get(value) ?? 0) + 1));
  return Array.from(counts.entries()).sort(
    (left, right) => right[1] - left[1] || left[0].localeCompare(right[0]),
  )[0]?.[0] ?? "";
}

function formatOrigin(origin: string): string {
  if (origin.toLowerCase() === "toronto") {
    return "Toronto";
  }
  if (origin.toLowerCase() === "calgary") {
    return "Calgary";
  }
  return origin
    .split(/[-_\s]+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function CityIcon({ name }: { name: CityIconName }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 1.8,
  };
  let content;
  switch (name) {
    case "alert":
      content = <><path d="M12 3 2.8 20h18.4L12 3Z" /><path d="M12 9v4.6M12 17h.01" /></>;
      break;
    case "check":
      content = <><circle cx="12" cy="12" r="9" /><path d="m8 12 2.6 2.6L16.5 9" /></>;
      break;
    case "city":
      content = <><path d="M4 21V8l6-3v16M10 10l6-3v14M16 11l4 2v8" /><path d="M2 21h20M7 10h.01M7 14h.01M13 11h.01M13 15h.01" /></>;
      break;
    case "close":
      content = <path d="m6 6 12 12M18 6 6 18" />;
      break;
    case "edit":
      content = <><path d="M13.5 6.5 17.5 10.5M4 20l4.2-1 10-10a2.8 2.8 0 0 0-4-4l-10 10L4 20Z" /></>;
      break;
    case "layers":
      content = <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></>;
      break;
    case "map":
      content = <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z" /><path d="M9 3v15M15 6v15" /></>;
      break;
    case "plus":
      content = <path d="M12 5v14M5 12h14" />;
      break;
    case "postal":
      content = <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m4 7 8 6 8-6" /></>;
      break;
    case "refresh":
      content = <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 8.5A7 7 0 0 1 18.8 10M17.9 15.5A7 7 0 0 1 5.2 14" /></>;
      break;
    case "save":
      content = <><path d="M5 3h12l3 3v15H4V3h1Z" /><path d="M8 3v6h8V3M8 21v-7h8v7" /></>;
      break;
    case "search":
      content = <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>;
      break;
    case "trash":
      content = <><path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6" /></>;
      break;
    case "warehouse":
      content = <><path d="m3 10 9-6 9 6v11H3V10Z" /><path d="M7 21v-7h10v7M8 10h8" /></>;
      break;
  }
  return (
    <svg className="pricing-icon" viewBox="0 0 24 24" aria-hidden="true" {...common}>
      {content}
    </svg>
  );
}
