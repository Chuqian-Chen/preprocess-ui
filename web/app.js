const TYPE_META = {
  "空列": { short: "空" },
  "数值型": { short: "数值" },
  "日期型": { short: "日期" },
  "分类/枚举型": { short: "分类" },
  "文本型": { short: "文本" },
  "ID型": { short: "ID" },
};

let state = {
  projectId: localStorage.getItem("preprocess_project_id") || null,
  project: null,
  fields: [],
  tables: [],
  currentTable: null,
  typeOverrides: {},
  fieldTypes: [],
  selectedField: null,
  fieldFilter: "",
  aiConfigured: false,
};

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2800);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.projectId && !headers["X-Project-Id"]) {
    headers["X-Project-Id"] = state.projectId;
  }
  if (!(opts.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.detail || JSON.stringify(j);
    } catch {
      msg = await res.text();
    }
    throw new Error(msg || res.statusText);
  }
  return res.json();
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function typeShort(dtype) {
  return (TYPE_META[dtype] || { short: dtype }).short;
}

function setProject(id, meta) {
  state.projectId = id;
  state.project = meta;
  if (id) localStorage.setItem("preprocess_project_id", id);
  else localStorage.removeItem("preprocess_project_id");
  const label = document.getElementById("project-label");
  if (meta) {
    label.textContent = `当前项目：${meta.name} · ${meta.file_count || meta.files?.length || 0} 个表 · ${id}`;
  } else {
    label.textContent = "未加载项目 — 请先选择或上传数据";
  }
}

function requireProject() {
  if (!state.projectId) {
    toast("请先在「数据源」创建或选择项目");
    document.querySelector('.step-tab[data-step="0"]').click();
    throw new Error("no project");
  }
}

// --- Tabs ---
document.querySelectorAll(".step-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".step-tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("panel-" + tab.dataset.step).classList.add("active");
    if (tab.dataset.step === "2") enterJoinStep();
    if (tab.dataset.step === "3") enterPreprocessStep();
    if (tab.dataset.step === "4") loadOutputFiles();
    if (tab.dataset.step === "5") enterAnalysisStep();
  });
});

// --- Step 0: Projects ---
async function loadProjects() {
  const { projects } = await api("/api/projects");
  const wrap = document.getElementById("project-list");
  if (!projects.length) {
    wrap.innerHTML = '<div class="empty">暂无项目</div>';
    return;
  }
  wrap.innerHTML = projects
    .map((p) => {
      const active = p.id === state.projectId ? " active" : "";
      return `<div class="table-list-item${active}" data-id="${p.id}">
        <strong>${escapeHtml(p.name)}</strong>
        <div class="meta">${p.file_count || 0} 表 · ${p.source_type} · ${(p.created_at || "").slice(0, 10)}</div>
      </div>`;
    })
    .join("");
  wrap.querySelectorAll(".table-list-item").forEach((el) => {
    el.addEventListener("click", async () => {
      const id = el.dataset.id;
      const meta = await api("/api/projects/" + id);
      setProject(id, meta);
      renderProjectList();
      toast("已切换项目");
      await loadProfile();
    });
  });
}

function renderProjectList() {
  document.querySelectorAll("#project-list .table-list-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === state.projectId);
  });
}

document.getElementById("btn-import-path").addEventListener("click", async () => {
  const path = document.getElementById("path-input").value.trim();
  const name = document.getElementById("path-project-name").value.trim();
  if (!path) return toast("请填写文件夹路径");
  try {
    const meta = await api("/api/projects/from-path", {
      method: "POST",
      body: JSON.stringify({ path, name }),
    });
    setProject(meta.id, { ...meta, file_count: meta.files?.length });
    await loadProjects();
    await loadProfile();
    toast(`已导入 ${meta.files.length} 个 CSV`);
    document.querySelector('.step-tab[data-step="1"]').click();
  } catch (e) {
    toast("导入失败: " + e.message);
  }
});

document.getElementById("btn-upload").addEventListener("click", async () => {
  const files = document.getElementById("file-input").files;
  const name = document.getElementById("upload-project-name").value.trim();
  if (!files.length) return toast("请选择文件");
  const fd = new FormData();
  if (name) fd.append("name", name);
  for (const f of files) fd.append("files", f);
  try {
    const meta = await api("/api/projects/upload", { method: "POST", body: fd, headers: {} });
    setProject(meta.id, { ...meta, file_count: meta.files?.length });
    await loadProjects();
    await loadProfile();
    toast(`已上传 ${meta.files.length} 个 CSV`);
    document.querySelector('.step-tab[data-step="1"]').click();
  } catch (e) {
    toast("上传失败: " + e.message);
  }
});

// --- Step 1: Raw QC (reuse from before) ---
function closeTypeMenu() {
  document.querySelectorAll(".type-menu").forEach((el) => el.remove());
}

document.addEventListener("click", (e) => {
  if (!e.target.closest(".type-pill") && !e.target.closest(".type-menu")) closeTypeMenu();
});

function renderTableList() {
  const wrap = document.getElementById("table-list");
  const byTable = {};
  state.fields.forEach((f) => {
    const key = f.table_key || f.table;
    if (!byTable[key]) byTable[key] = [];
    byTable[key].push(f);
  });
  state.tables = Object.keys(byTable).sort();
  if (!state.tables.length) {
    wrap.innerHTML = '<div class="empty">无数据，请先导入并扫描</div>';
    return;
  }
  wrap.innerHTML = state.tables
    .map((t) => {
      const n = byTable[t].length;
      const active = t === state.currentTable ? " active" : "";
      const samp = byTable[t].find((f) => f.sampled);
      const badge = samp
        ? ` · <span title="该表过大，画像基于前 ${Number(samp.sample_rows).toLocaleString()} 行采样估计">采样 ${Math.round(samp.sample_rows / 10000)}万行</span>`
        : "";
      return `<div class="table-list-item${active}" data-table="${escapeHtml(t)}">${escapeHtml(t)}<div class="meta">${n} 字段${badge}</div></div>`;
    })
    .join("");
  wrap.querySelectorAll(".table-list-item").forEach((el) => {
    el.addEventListener("click", () => {
      state.currentTable = el.dataset.table;
      state.selectedField = null;
      renderTableList();
      renderFieldTable();
      document.getElementById("domain-preview").innerHTML = '<div class="empty">点击字段行查看值域</div>';
    });
  });
  if (!state.currentTable) state.currentTable = state.tables[0];
}

function filteredFields() {
  const q = state.fieldFilter.trim().toLowerCase();
  return state.fields.filter((f) => {
    if ((f.table_key || f.table) !== state.currentTable) return false;
    if (!q) return true;
    return (f.field || "").toLowerCase().includes(q) || (f.field_key || "").toLowerCase().includes(q);
  });
}

function renderTypePill(fieldKey, dtype) {
  return `<button type="button" class="type-pill" data-type="${escapeHtml(dtype)}" data-key="${escapeHtml(fieldKey)}" title="${escapeHtml(dtype)}">${typeShort(dtype)}</button>`;
}

function openTypeMenu(pill, fieldKey, currentType) {
  closeTypeMenu();
  const menu = document.createElement("div");
  menu.className = "type-menu";
  menu.innerHTML = state.fieldTypes
    .map((t) => {
      const active = t === currentType ? " active" : "";
      return `<button type="button" class="${active.trim()}" data-dtype="${escapeHtml(t)}" data-key="${escapeHtml(fieldKey)}">${typeShort(t)} · ${escapeHtml(t)}</button>`;
    })
    .join("");
  document.body.appendChild(menu);
  const rect = pill.getBoundingClientRect();
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.left = `${Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      closeTypeMenu();
      await applyTypeChange(btn.dataset.key, btn.dataset.dtype);
    });
  });
}

async function applyTypeChange(key, dtype) {
  toast("正在重算值域…");
  try {
    const res = await api("/api/raw/type-override", {
      method: "POST",
      body: JSON.stringify({ field_key: key, dtype }),
    });
    state.typeOverrides = res.overrides;
    const idx = state.fields.findIndex((x) => x.field_key === key);
    if (idx >= 0) state.fields[idx] = { ...state.fields[idx], ...res.field };
    state.selectedField = key;
    renderFieldTable();
    renderDomain(state.fields[idx]);
    toast("类型已更新");
  } catch (err) {
    toast("错误: " + err.message);
  }
}

function renderFieldTable() {
  const wrap = document.getElementById("field-table-wrap");
  const rows = filteredFields();
  if (!rows.length) {
    wrap.innerHTML = '<div class="empty">无匹配字段</div>';
    return;
  }
  if (!state.selectedField || !rows.some((f) => f.field_key === state.selectedField)) {
    state.selectedField = rows[0].field_key;
    renderDomain(rows[0]);
  }
  wrap.innerHTML = `<table class="data"><thead><tr>
    <th>字段</th><th>类型</th><th>缺失%</th><th>去重</th><th>内容摘要</th>
  </tr></thead><tbody>${rows
    .map((f) => {
      const dtype = f.inferred_dtype || "文本型";
      const selected = f.field_key === state.selectedField ? " selected" : "";
      const nullPct = f.null_pct ?? 0;
      const missCls = nullPct > 20 ? "missing-high" : "missing-ok";
      return `<tr data-key="${escapeHtml(f.field_key)}" class="field-row${selected}">
        <td class="field-name">${escapeHtml(f.field)}</td>
        <td class="type-cell">${renderTypePill(f.field_key, dtype)}</td>
        <td class="num-cell ${missCls}">${nullPct}%</td>
        <td class="num-cell">${f.unique ?? "-"}</td>
        <td class="summary-cell" title="${escapeHtml(f.variable_content || "")}">${escapeHtml(f.variable_content || "-")}</td>
      </tr>`;
    })
    .join("")}</tbody></table>`;

  wrap.querySelectorAll(".type-pill").forEach((pill) => {
    pill.addEventListener("click", (e) => {
      e.stopPropagation();
      const f = state.fields.find((x) => x.field_key === pill.dataset.key);
      openTypeMenu(pill, pill.dataset.key, f?.inferred_dtype || "文本型");
    });
  });
  wrap.querySelectorAll(".field-row").forEach((tr) => {
    tr.addEventListener("click", () => {
      state.selectedField = tr.dataset.key;
      renderFieldTable();
      renderDomain(state.fields.find((x) => x.field_key === state.selectedField));
    });
  });
}

function renderDomainBars(domain, barClass = "") {
  if (!domain.length) return "";
  const maxFreq = Math.max(...domain.map((d) => d.频次 || 0), 1);
  return `<div class="domain-bars">${domain
    .slice(0, 25)
    .map((d) => {
      const pct = Math.round(((d.频次 || 0) / maxFreq) * 100);
      return `<div class="domain-bar-row">
        <div class="domain-bar-label" title="${escapeHtml(d.值)}">${escapeHtml(d.值)}</div>
        <div class="domain-bar-track"><div class="domain-bar-fill ${barClass}" style="width:${pct}%"></div></div>
        <div class="domain-bar-count">${d.频次} <span class="meta">(${d["占比%"]}%)</span></div>
      </div>`;
    })
    .join("")}${domain.length > 25 ? `<div class="domain-note">Top 25 / 共 ${domain.length} 项</div>` : ""}</div>`;
}

function renderDomain(f) {
  const wrap = document.getElementById("domain-preview");
  if (!f) {
    wrap.innerHTML = '<div class="empty">点击字段行查看值域</div>';
    return;
  }
  const dtype = f.inferred_dtype || "文本型";
  const domain = f.value_domain || [];
  let body = "";
  if (dtype === "数值型" && f.numeric_stats) {
    const s = f.numeric_stats;
    body = `<div class="numeric-cards">
      <div class="numeric-card"><div class="label">最小</div><div class="value">${s.min}</div></div>
      <div class="numeric-card"><div class="label">最大</div><div class="value">${s.max}</div></div>
      <div class="numeric-card"><div class="label">均值</div><div class="value">${Number(s.mean).toFixed(4)}</div></div>
      <div class="numeric-card"><div class="label">中位</div><div class="value">${Number(s.median).toFixed(4)}</div></div>
    </div>`;
  } else if (dtype === "日期型" && f.date_stats) {
    body = `<div class="numeric-cards">
      <div class="numeric-card"><div class="label">最早</div><div class="value">${f.date_stats.min}</div></div>
      <div class="numeric-card"><div class="label">最晚</div><div class="value">${f.date_stats.max}</div></div>
    </div>`;
  } else if (dtype === "空列") {
    body = '<div class="domain-note">全部为空</div>';
  } else if (domain.length) {
    const barCls = dtype === "ID型" ? "id" : dtype === "分类/枚举型" ? "cat" : "";
    body = renderDomainBars(domain, barCls);
  } else {
    body = `<div class="domain-note">${dtype === "文本型" ? "文本过散" : "可切换为分类/ID 查看频次"}</div>`;
  }
  wrap.innerHTML = `
    <div class="domain-header">
      <h3>${escapeHtml(f.field)}</h3>
      <div class="domain-meta">
        <span class="domain-badge type-pill" data-type="${escapeHtml(dtype)}">${typeShort(dtype)} · ${escapeHtml(dtype)}</span>
      </div>
    </div>
    <div class="domain-stats">
      <div class="stat-box"><div class="label">非空</div><div class="value">${f.non_null ?? "-"}</div></div>
      <div class="stat-box"><div class="label">缺失率</div><div class="value">${f.null_pct ?? 0}%</div></div>
      <div class="stat-box"><div class="label">去重</div><div class="value">${f.unique ?? "-"}</div></div>
    </div>${body}`;
}

document.getElementById("field-search")?.addEventListener("input", (e) => {
  state.fieldFilter = e.target.value;
  renderFieldTable();
});

document.getElementById("btn-scan").addEventListener("click", async () => {
  try {
    requireProject();
    toast("扫描中…");
    const res = await api("/api/raw/scan", { method: "POST" });
    state.fields = res.fields || [];
    renderTableList();
    renderFieldTable();
    toast(res.log || "扫描完成");
    document.querySelector('.step-tab[data-step="1"]').classList.add("done");
  } catch (e) {
    if (e.message !== "no project") toast("扫描失败: " + e.message);
  }
});

document.getElementById("btn-save-types").addEventListener("click", async () => {
  try {
    requireProject();
    const overrides = {};
    state.fields.forEach((f) => {
      if (f.inferred_dtype) overrides[f.field_key] = f.inferred_dtype;
    });
    await api("/api/raw/type-overrides/batch", {
      method: "POST",
      body: JSON.stringify({ overrides }),
    });
    toast(`已保存 ${Object.keys(overrides).length} 个类型`);
  } catch (e) {
    if (e.message !== "no project") toast("保存失败");
  }
});

document.getElementById("btn-exact-stats").addEventListener("click", async () => {
  try {
    requireProject();
    if (!state.currentTable) return toast("请先在左侧选择一张表");
    const btn = document.getElementById("btn-exact-stats");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "全量计算中…";
    try {
      const res = await api("/api/raw/exact-stats", {
        method: "POST",
        body: JSON.stringify({ table_key: state.currentTable }),
      });
      // 用精确结果替换该表字段
      const newKeys = new Set(res.fields.map((f) => f.field_key));
      state.fields = state.fields.filter((f) => !newKeys.has(f.field_key)).concat(res.fields);
      renderTableList();
      renderFieldTable();
      toast(`已精确重算「${res.table_key}」${res.count} 列`);
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  } catch (e) {
    if (e.message !== "no project") toast("精确计算失败: " + e.message);
  }
});

document.getElementById("btn-export-qc").addEventListener("click", async () => {
  try {
    requireProject();
    if (!state.fields.length) return toast("暂无画像，请先扫描");
    // 先保存当前类型，确保导出的 CSV 与界面一致
    const overrides = {};
    state.fields.forEach((f) => {
      if (f.inferred_dtype) overrides[f.field_key] = f.inferred_dtype;
    });
    await api("/api/raw/type-overrides/batch", {
      method: "POST",
      body: JSON.stringify({ overrides }),
    });
    // 触发浏览器下载（带 project_id，便于直接 GET 下载）
    const url = `/api/raw/profile/export?project_id=${encodeURIComponent(state.projectId)}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast("已开始下载质控 CSV");
  } catch (e) {
    if (e.message !== "no project") toast("导出失败: " + e.message);
  }
});

async function loadProfile() {
  if (!state.projectId) return;
  // 立即清空旧项目的画像，显示加载态，避免切项目后误以为还是旧表
  state.fields = [];
  state.tables = [];
  state.currentTable = null;
  state.selectedField = null;
  const tableWrap = document.getElementById("table-list");
  const fieldWrap = document.getElementById("field-table-wrap");
  const domainWrap = document.getElementById("domain-preview");
  if (tableWrap) tableWrap.innerHTML = '<div class="empty">画像计算中… 大表首次扫描可能需要几分钟</div>';
  if (fieldWrap) fieldWrap.innerHTML = '<div class="empty">画像计算中…</div>';
  if (domainWrap) domainWrap.innerHTML = '<div class="empty">点击字段行查看值域</div>';
  try {
    const prof = await api("/api/raw/profile");
    state.fields = prof.fields || [];
    renderTableList();
    renderFieldTable();
  } catch (e) {
    if (tableWrap) tableWrap.innerHTML = `<div class="empty">画像加载失败：${escapeHtml(e.message)}</div>`;
    if (fieldWrap) fieldWrap.innerHTML = '<div class="empty">—</div>';
    throw e;
  }
}

// --- Step 2: Join rules ---
let joinState = { mermaid: "", rules: [] };

// 确保画像已加载（关联页/值域速查依赖 state.fields 里的 value_domain）
async function ensureProfileLoaded() {
  if (state.fields.length || !state.projectId) return;
  try {
    const prof = await api("/api/raw/profile");
    state.fields = prof.fields || [];
  } catch (e) {
    /* ignore */
  }
}

async function enterJoinStep() {
  await ensureProfileLoaded();
  populateDomainLookup();
}

// 值域速查：表/字段下拉 + 渲染。字段下拉 value 统一编码为 "表|字段"
function populateDomainLookup(selectTable, selectField) {
  const tSel = document.getElementById("jd-table");
  const fSel = document.getElementById("jd-field");
  if (!tSel || !fSel) return;
  // 选定具体字段时，清空搜索框回到按表浏览模式
  const search = document.getElementById("jd-search");
  if (search && (selectTable || selectField)) search.value = "";
  const tables = [...new Set(state.fields.map((f) => f.table_key))].sort();
  if (!tables.length) {
    tSel.innerHTML = '<option>（请先在 ① 扫描生成画像）</option>';
    fSel.innerHTML = "";
    return;
  }
  const curT = selectTable || tSel.value || tables[0];
  tSel.disabled = false;
  tSel.innerHTML = tables.map((t) => `<option${t === curT ? " selected" : ""}>${escapeHtml(t)}</option>`).join("");
  const fields = state.fields.filter((f) => f.table_key === curT);
  const curF = selectField || fields[0]?.field;
  fSel.innerHTML = fields
    .map((f) => `<option value="${escapeHtml(f.table_key)}|${escapeHtml(f.field)}"${f.field === curF ? " selected" : ""}>${escapeHtml(f.field)} · ${typeShort(f.inferred_dtype || "")}</option>`)
    .join("");
  renderJoinDomain(curT, curF);
}

// 值域速查：跨表搜索字段名/表名
function searchDomainLookup(term) {
  const tSel = document.getElementById("jd-table");
  const fSel = document.getElementById("jd-field");
  if (!tSel || !fSel) return;
  const q = (term || "").trim().toLowerCase();
  if (!q) {
    populateDomainLookup();
    return;
  }
  const matches = state.fields.filter(
    (f) => (f.field || "").toLowerCase().includes(q) || (f.table_key || "").toLowerCase().includes(q)
  );
  tSel.disabled = true;
  tSel.innerHTML = `<option>搜索中（${matches.length} 个匹配）</option>`;
  if (!matches.length) {
    fSel.innerHTML = "";
    document.getElementById("jd-domain").innerHTML = '<div class="empty">无匹配字段</div>';
    return;
  }
  fSel.innerHTML = matches
    .slice(0, 300)
    .map((f, i) => `<option value="${escapeHtml(f.table_key)}|${escapeHtml(f.field)}"${i === 0 ? " selected" : ""}>${escapeHtml(f.table_key)} · ${escapeHtml(f.field)} · ${typeShort(f.inferred_dtype || "")}</option>`)
    .join("");
  renderJoinDomain(matches[0].table_key, matches[0].field);
}

// 返回一个字段值域的 HTML（统计卡 + 频次条形/数值卡），多处复用
function fieldDomainHtml(f, labelKey = "") {
  if (!f) return '<div class="empty">无此字段画像</div>';
  const dtype = f.inferred_dtype || "文本型";
  const domain = f.value_domain || [];
  let body = "";
  if (dtype === "数值型" && f.numeric_stats) {
    const s = f.numeric_stats;
    body = `<div class="numeric-cards">
      <div class="numeric-card"><div class="label">最小</div><div class="value">${s.min}</div></div>
      <div class="numeric-card"><div class="label">最大</div><div class="value">${s.max}</div></div>
      <div class="numeric-card"><div class="label">均值</div><div class="value">${Number(s.mean).toFixed(2)}</div></div>
      <div class="numeric-card"><div class="label">中位</div><div class="value">${s.median}</div></div>
    </div>`;
  } else if (dtype === "日期型" && f.date_stats) {
    body = `<div class="numeric-cards">
      <div class="numeric-card"><div class="label">最早</div><div class="value">${f.date_stats.min}</div></div>
      <div class="numeric-card"><div class="label">最晚</div><div class="value">${f.date_stats.max}</div></div>
    </div>`;
  } else if (domain.length) {
    const barCls = dtype === "ID型" ? "id" : dtype === "分类/枚举型" ? "cat" : "";
    body = renderDomainBars(domain, barCls);
  } else {
    body = `<div class="domain-note">${dtype === "文本型" ? "文本过散，未统计频次" : "无频次值域"}</div>`;
  }
  const sampNote = f.sampled ? ` · <span class="meta">采样 ${Math.round((f.sample_rows || 0) / 10000)}万行估计</span>` : "";
  const label = labelKey ? `<div class="meta" style="margin:4px 0 8px">${escapeHtml(labelKey)}${sampNote}</div>` : "";
  return `<div class="domain-stats">
      <div class="stat-box"><div class="label">类型</div><div class="value">${typeShort(dtype)}</div></div>
      <div class="stat-box"><div class="label">非空</div><div class="value">${f.non_null ?? "-"}</div></div>
      <div class="stat-box"><div class="label">缺失率</div><div class="value">${f.null_pct ?? 0}%</div></div>
      <div class="stat-box"><div class="label">去重</div><div class="value">${f.unique ?? "-"}</div></div>
    </div>${label}${body}`;
}

function renderJoinDomain(tableKey, field) {
  const wrap = document.getElementById("jd-domain");
  if (!wrap) return;
  const f = state.fields.find((x) => x.table_key === tableKey && x.field === field);
  wrap.innerHTML = fieldDomainHtml(f, `${tableKey}.${field}`);
}

document.getElementById("jd-table")?.addEventListener("change", (e) => populateDomainLookup(e.target.value));
document.getElementById("jd-field")?.addEventListener("change", (e) => {
  const [t, f] = (e.target.value || "").split("|");
  if (t && f) renderJoinDomain(t, f);
});
document.getElementById("jd-search")?.addEventListener("input", (e) => searchDomainLookup(e.target.value));

// 由规则重建一张「无边标签」的简化关联图：去重边、节点用表名。
// 边标签（join 字段）在大图里会触发 Mermaid/dagre 的几何报错，去掉后通常可正常渲染。
function buildFallbackMermaid(rules) {
  if (!rules || !rules.length) return "";
  const ids = new Map();
  let i = 0;
  const nid = (name) => {
    if (!ids.has(name)) ids.set(name, "N" + i++);
    return ids.get(name);
  };
  const edges = new Set();
  for (const r of rules) {
    const L = r["左表"], R = r["右表"];
    if (!L || !R) continue;
    edges.add(nid(L) + "-->" + nid(R));
  }
  const lines = ["flowchart LR"];
  for (const [name, id] of ids) lines.push(`  ${id}["${String(name).replace(/"/g, "")}"]`);
  for (const e of edges) lines.push("  " + e);
  return lines.join("\n");
}

async function renderMermaid(code) {
  const el = document.getElementById("join-mermaid");
  if (!code || !code.trim()) {
    el.innerHTML = '<div class="empty">暂无关联图</div>';
    return;
  }
  if (!window.mermaid) {
    el.innerHTML = `<pre class="mermaid-src">${escapeHtml(code)}</pre>`;
    return;
  }
  const tryRender = async (mmCode) => {
    el.innerHTML = "";
    const pre = document.createElement("pre");
    pre.className = "mermaid";
    pre.textContent = mmCode;
    el.appendChild(pre);
    mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });
    await mermaid.run({ nodes: [pre] });
  };
  try {
    await tryRender(code);
  } catch (e1) {
    // 降级：用规则重建无标签简化结构图再试
    const fb = buildFallbackMermaid(joinState.rules);
    if (fb) {
      try {
        await tryRender(fb);
        const note = document.createElement("div");
        note.className = "meta";
        note.style.marginTop = "6px";
        note.textContent = "（带字段标签的完整关联图渲染失败，已降级为简化结构图；字段级关联见下方规则表）";
        el.appendChild(note);
        return;
      } catch (e2) {
        /* 继续兜底 */
      }
    }
    el.innerHTML =
      '<div class="empty">关联图渲染失败（节点/边过多）。完整字段级关联请见下方「关联规则表」。</div>';
  }
}

function renderJoinRulesTable(rules) {
  const wrap = document.getElementById("join-rules-table");
  if (!rules?.length) {
    wrap.innerHTML = '<div class="empty">暂无规则</div>';
    return;
  }
  const cols = ["路径", "步骤", "左表", "左字段", "左值_示例", "右表", "右字段", "右值_示例", "匹配率", "备注"];
  wrap.innerHTML = `<table class="join-rules"><thead><tr>${cols
    .map((c) => `<th>${c}</th>`)
    .join("")}</tr></thead><tbody>${rules
    .map((r) => {
      const lkey = `${r["左表"] || ""}|${r["左字段"] || ""}`;
      const rkey = `${r["右表"] || ""}|${r["右字段"] || ""}`;
      return `<tr>${cols
        .map((c) => {
          // 左字段/右字段做成可点击，点了在「值域速查」里展示该字段值域
          if (c === "左字段" && r["左表"]) {
            return `<td><a href="#" class="jd-link" data-key="${escapeHtml(lkey)}" title="查看值域">${escapeHtml(r[c] ?? "")}</a></td>`;
          }
          if (c === "右字段" && r["右表"]) {
            return `<td><a href="#" class="jd-link" data-key="${escapeHtml(rkey)}" title="查看值域">${escapeHtml(r[c] ?? "")}</a></td>`;
          }
          return `<td>${escapeHtml(r[c] ?? "")}</td>`;
        })
        .join("")}</tr>`;
    })
    .join("")}</tbody></table>`;
  wrap.querySelectorAll(".jd-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const [tbl, fld] = a.dataset.key.split("|");
      populateDomainLookup(tbl, fld);
      document.getElementById("jd-domain")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

function renderJoinPaths(data) {
  const wrap = document.getElementById("join-paths");
  const parts = [];
  if (data.summary) {
    parts.push(`<p>${escapeHtml(data.summary)}</p>`);
  }
  (data.paths || []).forEach((p) => {
    parts.push(
      `<div class="path-item"><strong>${escapeHtml(p.id || p.name || "")}</strong>${escapeHtml(p.description || p.name || "")}</div>`
    );
  });
  if (data.key_ids?.length) {
    parts.push("<div class='meta' style='margin-top:10px'>关键 ID</div>");
    data.key_ids.slice(0, 8).forEach((k) => {
      parts.push(
        `<div class="path-item"><strong>${escapeHtml(k.字段 || k.field || "")}</strong>${escapeHtml(k.含义 || k.meaning || "")}<br/><span class="meta">${escapeHtml(k.注意 || k.note || "")}</span></div>`
      );
    });
  }
  if (data.pitfalls?.length) {
    parts.push("<ul class='pitfall-list'>" + data.pitfalls.map((p) => `<li>${escapeHtml(p)}</li>`).join("") + "</ul>");
  }
  wrap.innerHTML = parts.length ? parts.join("") : '<div class="empty">—</div>';
}

function applyJoinData(data) {
  joinState = data;
  const rules = data.rules || [];
  document.getElementById("join-rules-edit").value = JSON.stringify(rules, null, 2);
  document.getElementById("join-summary").textContent = data.summary || "表间 join 规则";
  renderJoinRulesTable(rules);
  renderJoinPaths(data);
  renderMermaid(data.mermaid || "");
}

async function loadJoinRules() {
  if (!state.projectId) return;
  const data = await api("/api/join-rules");
  applyJoinData(data);
}

document.getElementById("btn-join-probe").addEventListener("click", async () => {
  try {
    requireProject();
    document.getElementById("join-log").textContent = "统计探查中…";
    const probe = await api("/api/join-rules/probe", { method: "POST" });
    const res = await api("/api/join-rules/discover", {
      method: "POST",
      body: JSON.stringify({ use_ai: false }),
    });
    applyJoinData(res.discovery);
    document.getElementById("join-log").textContent = `统计探查完成：${probe.count} 个候选匹配 → ${(res.discovery.rules || []).length} 条规则`;
    toast("统计探查完成");
    document.querySelector('.step-tab[data-step="2"]').classList.add("done");
  } catch (e) {
    if (e.message !== "no project") {
      document.getElementById("join-log").textContent = "错误: " + e.message;
      toast("探查失败: " + e.message);
    }
  }
});

document.getElementById("btn-join-ai").addEventListener("click", async () => {
  try {
    requireProject();
    document.getElementById("join-log").textContent = "AI 分析表结构与匹配率…";
    const res = await api("/api/join-rules/discover", {
      method: "POST",
      body: JSON.stringify({ use_ai: true }),
    });
    applyJoinData(res.discovery);
    document.getElementById("join-log").textContent = `AI 识别完成：探查 ${res.probe_count} 候选 → ${(res.discovery.rules || []).length} 条规则${res.discovery.model ? " (" + res.discovery.model + ")" : ""}`;
    toast("AI 关联识别完成");
    document.querySelector('.step-tab[data-step="2"]').classList.add("done");
  } catch (e) {
    if (e.message !== "no project") {
      document.getElementById("join-log").textContent = "错误: " + e.message;
      toast("AI 识别失败: " + e.message);
    }
  }
});

document.getElementById("btn-save-joins").addEventListener("click", async () => {
  try {
    requireProject();
    let rules;
    try {
      rules = JSON.parse(document.getElementById("join-rules-edit").value);
    } catch {
      return toast("JSON 格式错误");
    }
    if (!Array.isArray(rules)) rules = rules.rules || [];
    const payload = { ...joinState, rules };
    payload.mermaid = buildMermaidFromRules(rules);
    await api("/api/join-rules", { method: "PUT", body: JSON.stringify(payload) });
    applyJoinData(payload);
    toast("关联规则已保存");
    document.querySelector('.step-tab[data-step="2"]').classList.add("done");
  } catch (e) {
    if (e.message !== "no project") toast("保存失败");
  }
});

function buildMermaidFromRules(rules) {
  const nodes = new Set();
  const edges = [];
  rules.forEach((r) => {
    if (!r.左表) return;
    nodes.add(r.左表);
    if (r.右表) {
      nodes.add(r.右表);
      edges.push(`  ${sanitizeId(r.左表)} -->|"${(r.左字段 || "")}→${r.右字段 || ""}"| ${sanitizeId(r.右表)}`);
    }
  });
  if (!nodes.size) return "";
  return (
    "flowchart TB\n" +
    [...nodes].map((n) => `  ${sanitizeId(n)}["${n}"]`).join("\n") +
    "\n" +
    edges.join("\n")
  );
}

function sanitizeId(name) {
  return "T_" + String(name).replace(/\W/g, "_").slice(0, 40);
}

// --- Step 3: Field-level preprocess ---
let preState = {
  tables: [],
  currentTable: null,
  fields: [],
  selectedField: null,
  tableNote: "",
  workingInfo: null,
  fieldFilter: "",
  aiGenerating: false,
  domainCollapsed: false,
};

async function enterPreprocessStep() {
  await loadPreprocessTables();
  if (!state.aiConfigured) {
    document.getElementById("pre-log").textContent = "请先配置 AI Key（点击右上角）";
    await openAiWizard();
    return;
  }
  const needAll = preState.tables.some((t) => !t.ai_generated_at);
  if (needAll && preState.tables.length) {
    document.getElementById("pre-log").textContent = "正在为全部表生成 AI 修改意见…";
    await aiFillAllTables(false);
  } else if (preState.currentTable) {
    await maybeAutoAiFillTable(preState.currentTable);
  }
}

async function maybeAutoAiFillTable(tableKey) {
  const t = preState.tables.find((x) => x.table_key === tableKey);
  if (!state.aiConfigured || !t || t.ai_generated_at) return;
  await aiFillCurrentTable(false);
}

async function aiFillCurrentTable(regenerate = false) {
  if (!preState.currentTable) return;
  if (!state.aiConfigured) return toast("未配置 AI Key");
  preState.aiGenerating = true;
  document.getElementById("pre-log").textContent = regenerate ? "AI 重新生成中…" : "AI 生成修改意见…";
  try {
    const table_note = document.getElementById("pre-table-note").value;
    const res = await api("/api/preprocess/ai-fill-table", {
      method: "POST",
      body: JSON.stringify({
        table_key: preState.currentTable,
        table_note,
        user_hint: table_note,
        regenerate,
      }),
    });
    await loadPreprocessFields();
    await loadPreprocessTables();
    const msg = res.cached ? "已加载 AI 草稿" : `AI 已生成 (${res.model || "-"})`;
    document.getElementById("pre-log").textContent = msg + " — 请审阅后保存或应用";
    if (!res.cached) toast("AI 修改意见已生成，请审阅");
  } catch (e) {
    document.getElementById("pre-log").textContent = "错误: " + e.message;
    toast("AI 失败: " + e.message);
  }
  preState.aiGenerating = false;
}

async function aiFillAllTables(regenerate = false) {
  if (!state.aiConfigured) return toast("未配置 AI Key");
  const hint = document.getElementById("pre-table-note")?.value || "";
  try {
    const res = await api("/api/preprocess/ai-fill-all", {
      method: "POST",
      body: JSON.stringify({ user_hint: hint, only_missing: !regenerate }),
    });
    document.getElementById("pre-log").textContent = res.log || `完成 ${res.count} 表`;
    await loadPreprocessTables();
    if (preState.currentTable) await loadPreprocessFields();
    toast(`AI 已生成 ${res.count} 个表的修改意见`);
  } catch (e) {
    document.getElementById("pre-log").textContent = "错误: " + e.message;
  }
}

async function loadPreprocessTables() {
  if (!state.projectId) return;
  const { tables } = await api("/api/preprocess/tables");
  preState.tables = tables || [];
  renderPreTableList();
  if (!preState.currentTable && preState.tables.length) {
    preState.currentTable = preState.tables[0].table_key;
    await loadPreprocessFields();
  }
}

function renderPreTableList() {
  const wrap = document.getElementById("pre-table-list");
  if (!preState.tables.length) {
    wrap.innerHTML = '<div class="empty">请先在 Raw 质控扫描</div>';
    return;
  }
  wrap.innerHTML = preState.tables
    .map((t) => {
      const active = t.table_key === preState.currentTable ? " active" : "";
      const aiBadge = t.ai_generated_at
        ? `<span class="badge badge-ai">AI草稿</span>`
        : `<span class="badge badge-raw">待AI</span>`;
      const rev = t.review_status === "reviewed" ? `<span class="badge badge-out">已审阅</span>` : "";
      return `<div class="table-list-item pre-table-item${active}" data-table="${escapeHtml(t.table_key)}">
        ${escapeHtml(t.table_key)}${aiBadge}${rev}
        <div class="meta">${t.edit_count || 0} 条意见 · ${t.working_source === "output" ? t.output_file : "raw"}</div>
      </div>`;
    })
    .join("");
  wrap.querySelectorAll(".pre-table-item").forEach((el) => {
    el.addEventListener("click", async () => {
      await savePreEditsSilent(true);
      preState.currentTable = el.dataset.table;
      renderPreTableList();
      await loadPreprocessFields();
      await maybeAutoAiFillTable(preState.currentTable);
    });
  });
}

async function loadPreprocessFields() {
  if (!preState.currentTable) return;
  const data = await api("/api/preprocess/fields?table_key=" + encodeURIComponent(preState.currentTable));
  preState.fields = data.fields || [];
  // 切表后默认选中首列，右侧直接展示其值域
  preState.selectedField = preState.fields[0]?.field || null;
  preState.tableNote = data.table_note || "";
  preState.workingInfo = data;
  document.getElementById("pre-table-note").value = preState.tableNote;
  renderPreFieldTable();
  renderPreStatus();
}

function filteredPreFields() {
  const q = preState.fieldFilter.trim().toLowerCase();
  return preState.fields.filter((f) => {
    if (!q) return true;
    return (f.field || "").toLowerCase().includes(q) || (f.instruction || "").toLowerCase().includes(q);
  });
}

function renderPreFieldTable() {
  const wrap = document.getElementById("pre-field-wrap");
  const rows = filteredPreFields();
  if (!rows.length) {
    wrap.innerHTML = '<div class="empty">无字段</div>';
    return;
  }
  wrap.innerHTML = `<table class="data"><thead><tr>
    <th>字段</th><th>类型</th><th>缺失%</th><th>AI 修改建议（审阅后可改）</th><th>来源</th>
  </tr></thead><tbody>${rows
    .map((f) => {
      const dtype = f.inferred_dtype || "文本型";
      const src = f.edit_source === "ai"
        ? '<span class="badge badge-ai">AI</span>'
        : f.instruction
        ? '<span class="meta">人工</span>'
        : '<span class="meta">—</span>';
      const cls = f.edit_source === "ai" ? " instr-ai" : "";
      const selected = f.field === preState.selectedField ? " selected" : "";
      return `<tr data-field="${escapeHtml(f.field)}" class="field-row${selected}">
        <td class="field-name">${escapeHtml(f.field)}</td>
        <td><span class="type-pill" data-type="${escapeHtml(dtype)}" style="cursor:default">${typeShort(dtype)}</span></td>
        <td class="num-cell">${f.null_pct ?? 0}%</td>
        <td class="instr-cell"><textarea class="instr-input${cls}" data-field="${escapeHtml(f.field)}" rows="2" placeholder="AI 生成或手动填写">${escapeHtml(f.instruction || "")}</textarea></td>
        <td>${src}</td>
      </tr>`;
    })
    .join("")}</tbody></table>`;

  wrap.querySelectorAll(".instr-input").forEach((el) => {
    el.addEventListener("input", () => el.classList.remove("instr-ai"));
    // 编辑/聚焦某列时，右侧同步显示该列值域
    el.addEventListener("focus", () => selectPreField(el.dataset.field));
  });
  // 点击行（非输入框区域）也可选中查看值域
  wrap.querySelectorAll("tr.field-row").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest(".instr-input")) return;
      selectPreField(tr.dataset.field);
    });
  });
}

function selectPreField(field) {
  if (preState.selectedField === field) return;
  preState.selectedField = field;
  document.querySelectorAll("#pre-field-wrap tr.field-row").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.field === field);
  });
  renderPreStatus();
}

function renderPreStatus() {
  const w = preState.workingInfo;
  const wrap = document.getElementById("pre-status-panel");
  if (!w) {
    wrap.innerHTML = '<div class="empty">选择表</div>';
    return;
  }
  const srcLabel = w.working_source === "output" ? "working copy（可继续更新）" : "raw（首次应用）";
  const review = w.review_status || "pending";
  const reviewLabel =
    review === "reviewed" ? "已审阅" : review === "ai_draft" ? "AI 草稿待审阅" : "待 AI 生成";

  // 选中字段时，顶部展示该字段值域（可折叠），方便对照修改建议
  let domainBlock = "";
  const sel = preState.selectedField && preState.fields.find((f) => f.field === preState.selectedField);
  if (sel) {
    const collapsed = preState.domainCollapsed;
    domainBlock = `<div class="pre-domain-block">
      <div class="domain-header pre-domain-toggle" id="pre-domain-toggle" title="点击折叠/展开值域">
        <span class="caret">${collapsed ? "▸" : "▾"}</span>
        <h3>${escapeHtml(sel.field)}</h3>
        <span class="meta">值域</span>
      </div>
      <div class="pre-domain-body" style="${collapsed ? "display:none" : ""}">${fieldDomainHtml(sel)}</div>
    </div><hr class="pre-divider"/>`;
  } else {
    domainBlock = '<div class="meta" style="margin-bottom:10px">点击左侧任一字段行，这里显示其值域</div>';
  }

  wrap.innerHTML = `${domainBlock}<div class="working-info">
    <p><strong>${escapeHtml(w.table_key)}</strong></p>
    <p>审阅：<span class="${review === "reviewed" ? "status-applied" : "status-pending"}">${reviewLabel}</span></p>
    <p>读取：<code>${escapeHtml(w.working_file)}</code><br/><span class="meta">${srcLabel}</span></p>
    <p>输出：<code>${escapeHtml(w.output_file)}</code></p>
    <p class="meta">${w.current_columns?.length || 0} 列 · AI 生成于 ${(w.ai_generated_at || "").slice(0, 19) || "—"}</p>
    <p class="meta" style="margin-top:10px">① AI 生成意见 → ② 您编辑审阅 → ③ 保存 → ④ 确认应用</p>
  </div>`;

  // 折叠/展开值域：只切换显示，不整面板重渲染，避免闪烁
  const toggle = document.getElementById("pre-domain-toggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      preState.domainCollapsed = !preState.domainCollapsed;
      const body = toggle.parentElement.querySelector(".pre-domain-body");
      const caret = toggle.querySelector(".caret");
      if (body) body.style.display = preState.domainCollapsed ? "none" : "";
      if (caret) caret.textContent = preState.domainCollapsed ? "▸" : "▾";
    });
  }
}

function collectPreEdits() {
  const fields = {};
  document.querySelectorAll("#pre-field-wrap .instr-input").forEach((el) => {
    fields[el.dataset.field] = el.value;
  });
  return {
    table_key: preState.currentTable,
    table_note: document.getElementById("pre-table-note").value,
    fields,
  };
}

async function savePreEditsSilent(markReviewed = false) {
  if (!preState.currentTable) return;
  const payload = collectPreEdits();
  payload.mark_reviewed = markReviewed;
  await api("/api/preprocess/edits", { method: "PUT", body: JSON.stringify(payload) });
}

document.getElementById("pre-field-search")?.addEventListener("input", (e) => {
  preState.fieldFilter = e.target.value;
  renderPreFieldTable();
});

document.getElementById("btn-pre-save").addEventListener("click", async () => {
  try {
    requireProject();
    await savePreEditsSilent(true);
    await loadPreprocessTables();
    await loadPreprocessFields();
    toast("审阅结果已保存");
  } catch (e) {
    if (e.message !== "no project") toast("保存失败");
  }
});

document.getElementById("btn-pre-ai-fill").addEventListener("click", async () => {
  try {
    requireProject();
    if (!preState.currentTable) return toast("请选择表");
    await aiFillCurrentTable(true);
  } catch (e) {
    if (e.message !== "no project") toast("AI 失败");
  }
});

document.getElementById("btn-pre-ai-fill-all").addEventListener("click", async () => {
  try {
    requireProject();
    await aiFillAllTables(true);
  } catch (e) {
    if (e.message !== "no project") toast("批量 AI 失败");
  }
});

async function applyCurrentTable() {
  requireProject();
  if (!preState.currentTable) return toast("请选择表");
  await savePreEditsSilent(true);
  document.getElementById("pre-log").textContent = "应用本表…";
  const res = await api("/api/preprocess/apply-table", {
    method: "POST",
    body: JSON.stringify({ table_key: preState.currentTable, use_ai: true }),
  });
  document.getElementById("pre-log").textContent = res.log || "完成";
  await loadPreprocessFields();
  await loadPreprocessTables();
  toast(`已更新 ${res.output_file}`);
  document.querySelector('.step-tab[data-step="3"]').classList.add("done");
  document.querySelector('.step-tab[data-step="4"]').classList.add("done");
}

document.getElementById("btn-pre-apply-table").addEventListener("click", async () => {
  try {
    await applyCurrentTable();
  } catch (e) {
    if (e.message !== "no project") {
      document.getElementById("pre-log").textContent = "错误: " + e.message;
      toast("应用失败: " + e.message);
    }
  }
});

// --- 变更预览（before/after） ---
function closePreviewModal() {
  document.getElementById("preview-modal").classList.add("hidden");
}

function renderPreviewTable(data, which) {
  const d = data[which];
  const otherCols = which === "after" ? data.before.columns : data.after.columns;
  const otherSet = new Set(otherCols);
  const head = d.columns
    .map((c) => {
      let cls = "";
      if (which === "after" && data.added_columns.includes(c)) cls = "col-added";
      return `<th class="${cls}">${escapeHtml(c)}</th>`;
    })
    .join("");
  const body = d.rows
    .map((r) => `<tr>${r.map((v) => `<td>${escapeHtml(String(v))}</td>`).join("")}</tr>`)
    .join("");
  return `<table class="data preview-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

document.getElementById("btn-pre-preview").addEventListener("click", async () => {
  try {
    requireProject();
    if (!preState.currentTable) return toast("请选择表");
    const modal = document.getElementById("preview-modal");
    const bodyEl = document.getElementById("preview-body");
    document.getElementById("preview-title").textContent = `变更预览 · ${preState.currentTable}（前 20 行）`;
    bodyEl.innerHTML = '<div class="empty">编译变换并预览中…</div>';
    modal.classList.remove("hidden");
    await savePreEditsSilent(true); // 用当前编辑预览
    const data = await api("/api/preprocess/preview-table", {
      method: "POST",
      body: JSON.stringify({ table_key: preState.currentTable, use_ai: true }),
    });
    const opsList = (data.operations || []).map((o) => o.action).join(" → ") || "（无操作）";
    const dropNote = data.dropped_columns.length
      ? `<span class="col-removed">删除列: ${data.dropped_columns.map(escapeHtml).join("、")}</span>`
      : "";
    const addNote = data.added_columns.length
      ? `<span class="col-added">新增列: ${data.added_columns.map(escapeHtml).join("、")}</span>`
      : "";
    bodyEl.innerHTML = `
      <div class="preview-meta">
        <p><strong>变换操作：</strong>${escapeHtml(opsList)}</p>
        <p>${dropNote} ${addNote}</p>
      </div>
      <div class="preview-grid">
        <div class="preview-col"><div class="preview-col-head">变更前（raw / 当前 working）</div>${renderPreviewTable(data, "before")}</div>
        <div class="preview-col"><div class="preview-col-head">变更后（应用建议后）</div>${renderPreviewTable(data, "after")}</div>
      </div>
      <pre class="preview-log">${escapeHtml(data.log || "")}</pre>`;
  } catch (e) {
    if (e.message !== "no project") {
      document.getElementById("preview-body").innerHTML = `<div class="empty">预览失败：${escapeHtml(e.message)}</div>`;
    }
  }
});

document.getElementById("preview-modal-close").addEventListener("click", closePreviewModal);
document.getElementById("preview-modal-backdrop").addEventListener("click", closePreviewModal);
document.getElementById("preview-cancel").addEventListener("click", closePreviewModal);
document.getElementById("preview-confirm-apply").addEventListener("click", async () => {
  closePreviewModal();
  try {
    await applyCurrentTable();
  } catch (e) {
    if (e.message !== "no project") {
      document.getElementById("pre-log").textContent = "错误: " + e.message;
      toast("应用失败: " + e.message);
    }
  }
});

document.getElementById("btn-pre-apply-all").addEventListener("click", async () => {
  try {
    requireProject();
    await savePreEditsSilent(true);
    document.getElementById("pre-log").textContent = "批量应用中…";
    const res = await api("/api/preprocess/apply-all", { method: "POST", body: "{}" });
    document.getElementById("pre-log").textContent = res.log || "完成";
    await loadPreprocessTables();
    if (preState.currentTable) await loadPreprocessFields();
    toast(`已应用 ${(res.results || []).length} 个表`);
    loadOutputFiles();
  } catch (e) {
    if (e.message !== "no project") toast("批量应用失败: " + e.message);
  }
});

// --- Step 5: 数据分析（可视化） ---
let anState = { scope: "raw", tableKey: null, field: null, charts: [] };

function destroyAnCharts() {
  anState.charts.forEach((c) => {
    try {
      c.destroy();
    } catch (e) {
      /* ignore */
    }
  });
  anState.charts = [];
}

function anBarOpts(indexAxis = "x", legend = false) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis,
    plugins: { legend: { display: legend, labels: { color: "#94a3b8" } } },
    scales: {
      x: { ticks: { color: "#94a3b8", font: { size: 10 } }, grid: { color: "rgba(148,163,184,0.1)" } },
      y: { ticks: { color: "#94a3b8", font: { size: 10 } }, grid: { color: "rgba(148,163,184,0.1)" } },
    },
  };
}

async function enterAnalysisStep() {
  await ensureProfileLoaded();
  renderAnTableList();
  const tables = [...new Set(state.fields.map((f) => f.table_key))].sort();
  if (!anState.tableKey || !tables.includes(anState.tableKey)) anState.tableKey = tables[0] || null;
  if (anState.tableKey) {
    renderAnTableList();
    await loadAnTable();
  }
}

function renderAnTableList() {
  const wrap = document.getElementById("an-table-list");
  const tables = [...new Set(state.fields.map((f) => f.table_key))].sort();
  if (!tables.length) {
    wrap.innerHTML = '<div class="empty">请先在 ① 扫描生成画像</div>';
    return;
  }
  wrap.innerHTML = tables
    .map(
      (t) =>
        `<div class="table-list-item${t === anState.tableKey ? " active" : ""}" data-table="${escapeHtml(t)}"><strong>${escapeHtml(t)}</strong></div>`
    )
    .join("");
  wrap.querySelectorAll(".table-list-item").forEach((el) =>
    el.addEventListener("click", async () => {
      anState.tableKey = el.dataset.table;
      anState.field = null;
      renderAnTableList();
      await loadAnTable();
    })
  );
}

document.querySelectorAll(".an-scope").forEach((b) =>
  b.addEventListener("click", async () => {
    document.querySelectorAll(".an-scope").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    anState.scope = b.dataset.scope;
    anState.field = null;
    if (anState.tableKey) await loadAnTable();
  })
);

async function fetchAnFields(scope) {
  return api(`/api/analysis/fields?scope=${scope}&table_key=${encodeURIComponent(anState.tableKey)}`);
}

const SCOPE_LABEL = { raw: "Raw 概览", output: "处理后概览", compare: "对比" };

async function loadAnTable() {
  destroyAnCharts();
  const body = document.getElementById("an-body");
  const fieldSel = document.getElementById("an-field");
  document.getElementById("an-title").textContent = `${anState.tableKey} · ${SCOPE_LABEL[anState.scope]}`;
  body.innerHTML = '<div class="empty">加载中…</div>';
  if (anState.scope === "compare") return loadAnCompare();

  const res = await fetchAnFields(anState.scope);
  if (!res.exists || !res.fields.length) {
    fieldSel.innerHTML = "";
    body.innerHTML =
      anState.scope === "output"
        ? '<div class="empty">处理后文件尚未生成，请先在 ③ 应用本表</div>'
        : '<div class="empty">无画像，请先在 ① 扫描</div>';
    return;
  }
  fieldSel.innerHTML =
    '<option value="">— 选择一列看取值分布 —</option>' +
    res.fields
      .map((f) => `<option value="${escapeHtml(f.field)}">${escapeHtml(f.field)} · ${typeShort(f.inferred_dtype || "")}</option>`)
      .join("");
  body.innerHTML = `
    <div class="an-overview">
      <div class="an-chart-box"><div class="an-chart-title">字段类型分布</div><div class="an-canvas-wrap" style="height:180px"><canvas id="an-type-chart"></canvas></div></div>
      <div class="an-chart-box"><div class="an-chart-title">各列缺失率 %（红:&gt;20%）</div><div class="an-canvas-wrap" style="height:${Math.max(180, res.fields.length * 18)}px"><canvas id="an-miss-chart"></canvas></div></div>
    </div>
    <div id="an-dist" class="an-dist"></div>`;
  renderTypeChart("an-type-chart", res.fields);
  renderMissChart("an-miss-chart", res.fields);
}

function renderTypeChart(id, fields) {
  const counts = {};
  fields.forEach((f) => {
    const t = f.inferred_dtype || "未知";
    counts[t] = (counts[t] || 0) + 1;
  });
  const labels = Object.keys(counts);
  anState.charts.push(
    new Chart(document.getElementById(id), {
      type: "bar",
      data: { labels, datasets: [{ data: labels.map((l) => counts[l]), backgroundColor: "#3b82f6" }] },
      options: anBarOpts("x"),
    })
  );
}

function renderMissChart(id, fields) {
  const sorted = [...fields].sort((a, b) => (b.null_pct || 0) - (a.null_pct || 0));
  anState.charts.push(
    new Chart(document.getElementById(id), {
      type: "bar",
      data: {
        labels: sorted.map((f) => f.field),
        datasets: [{ data: sorted.map((f) => f.null_pct || 0), backgroundColor: sorted.map((f) => ((f.null_pct || 0) > 20 ? "#f87171" : "#34d399")) }],
      },
      options: anBarOpts("y"),
    })
  );
}

function renderDistChart(id, d) {
  const canvas = document.getElementById(id);
  if (!d || !d.data || !d.data.length) {
    if (canvas) canvas.parentElement.innerHTML = '<div class="empty">无分布数据（可能为文本过散列）</div>';
    return;
  }
  const labels = d.data.map((x) => x.label ?? x.value);
  anState.charts.push(
    new Chart(canvas, {
      type: "bar",
      data: { labels, datasets: [{ data: d.data.map((x) => x.count), backgroundColor: d.kind === "numeric" ? "#60a5fa" : "#a78bfa" }] },
      options: anBarOpts("x"),
    })
  );
}

document.getElementById("an-field").addEventListener("change", async (e) => {
  anState.field = e.target.value || null;
  if (anState.scope === "compare") return renderCompareDistribution();
  const box = document.getElementById("an-dist");
  if (!anState.field) {
    if (box) box.innerHTML = "";
    return;
  }
  box.innerHTML = `<div class="an-chart-box"><div class="an-chart-title">「${escapeHtml(anState.field)}」取值分布</div><div class="an-canvas-wrap" style="height:240px"><canvas id="an-dist-chart"></canvas></div></div>`;
  try {
    const d = await api(
      `/api/analysis/distribution?scope=${anState.scope}&table_key=${encodeURIComponent(anState.tableKey)}&field=${encodeURIComponent(anState.field)}`
    );
    renderDistChart("an-dist-chart", d);
  } catch (err) {
    box.innerHTML = `<div class="empty">分布加载失败：${escapeHtml(err.message)}</div>`;
  }
});

async function loadAnCompare() {
  const body = document.getElementById("an-body");
  const fieldSel = document.getElementById("an-field");
  const [raw, out] = await Promise.all([fetchAnFields("raw"), fetchAnFields("output")]);
  if (!out.exists || !out.fields.length) {
    fieldSel.innerHTML = "";
    body.innerHTML = '<div class="empty">处理后文件尚未生成，无法对比。请先在 ③ 应用本表。</div>';
    return;
  }
  const rawMap = new Map(raw.fields.map((f) => [f.field, f]));
  const outMap = new Map(out.fields.map((f) => [f.field, f]));
  const rawCols = raw.fields.map((f) => f.field);
  const outCols = out.fields.map((f) => f.field);
  const dropped = rawCols.filter((c) => !outMap.has(c));
  const added = outCols.filter((c) => !rawMap.has(c));
  const common = rawCols.filter((c) => outMap.has(c));
  const rowsRaw = raw.fields[0] ? (raw.fields[0].non_null || 0) + (raw.fields[0].null || 0) : 0;
  const rowsOut = out.fields[0] ? (out.fields[0].non_null || 0) + (out.fields[0].null || 0) : 0;
  fieldSel.innerHTML =
    '<option value="">— 选共同列对比分布 —</option>' + common.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  body.innerHTML = `
    <div class="an-overview" style="grid-template-columns:repeat(4,1fr)">
      <div class="stat-box"><div class="label">列数</div><div class="value">${rawCols.length} → ${outCols.length}</div></div>
      <div class="stat-box"><div class="label">行数(样本)</div><div class="value">${rowsRaw} → ${rowsOut}</div></div>
      <div class="stat-box"><div class="label">删除列</div><div class="value col-removed">${dropped.length}</div></div>
      <div class="stat-box"><div class="label">新增列</div><div class="value col-added">${added.length}</div></div>
    </div>
    <div class="an-coldiff">
      ${dropped.length ? `<div><span class="col-removed">删除：</span>${dropped.map(escapeHtml).join("、")}</div>` : ""}
      ${added.length ? `<div><span class="col-added">新增：</span>${added.map(escapeHtml).join("、")}</div>` : ""}
    </div>
    <div class="an-chart-box"><div class="an-chart-title">共同列缺失率对比 %（raw vs 处理后）</div><div class="an-canvas-wrap" style="height:${Math.max(200, common.length * 20)}px"><canvas id="an-cmp-miss"></canvas></div></div>
    <div id="an-dist" class="an-dist"></div>`;
  anState.charts.push(
    new Chart(document.getElementById("an-cmp-miss"), {
      type: "bar",
      data: {
        labels: common,
        datasets: [
          { label: "raw", data: common.map((c) => rawMap.get(c).null_pct || 0), backgroundColor: "#64748b" },
          { label: "处理后", data: common.map((c) => outMap.get(c).null_pct || 0), backgroundColor: "#34d399" },
        ],
      },
      options: anBarOpts("y", true),
    })
  );
}

async function renderCompareDistribution() {
  const box = document.getElementById("an-dist");
  if (!box) return;
  if (!anState.field) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `<div class="an-dist-compare">
      <div class="an-chart-box"><div class="an-chart-title">raw：${escapeHtml(anState.field)}</div><div class="an-canvas-wrap" style="height:240px"><canvas id="an-cmp-raw"></canvas></div></div>
      <div class="an-chart-box"><div class="an-chart-title">处理后：${escapeHtml(anState.field)}</div><div class="an-canvas-wrap" style="height:240px"><canvas id="an-cmp-out"></canvas></div></div>
    </div>`;
  try {
    const [draw, dout] = await Promise.all([
      api(`/api/analysis/distribution?scope=raw&table_key=${encodeURIComponent(anState.tableKey)}&field=${encodeURIComponent(anState.field)}`),
      api(`/api/analysis/distribution?scope=output&table_key=${encodeURIComponent(anState.tableKey)}&field=${encodeURIComponent(anState.field)}`),
    ]);
    renderDistChart("an-cmp-raw", draw);
    renderDistChart("an-cmp-out", dout);
  } catch (err) {
    box.innerHTML = `<div class="empty">分布对比加载失败：${escapeHtml(err.message)}</div>`;
  }
}

// --- Step 4 ---
async function loadOutputFiles() {
  if (!state.projectId) return;
  const wrap = document.getElementById("output-list");
  try {
    const { files } = await api("/api/output/files");
    if (!files.length) {
      wrap.innerHTML = '<div class="empty">尚无输出文件</div>';
      return;
    }
    wrap.innerHTML = files
      .map(
        (f) => `<div class="pipeline-step">
          <span class="name">${escapeHtml(f.name)}</span>
          <span class="meta">${(f.size / 1024).toFixed(1)} KB</span>
          <a class="btn" href="/api/output/download/${encodeURIComponent(f.name)}?project_id=${encodeURIComponent(state.projectId)}" download>下载</a>
        </div>`
      )
      .join("");
  } catch {
    wrap.innerHTML = '<div class="empty">加载失败</div>';
  }
}

document.getElementById("btn-refresh-output").addEventListener("click", loadOutputFiles);

// --- AI Settings Wizard ---
const DEFAULT_AI_PROVIDERS = [
  {
    id: "openai",
    name: "OpenAI",
    signup_url: "https://platform.openai.com/signup",
    keys_url: "https://platform.openai.com/api-keys",
    docs_url: "https://platform.openai.com/docs/api-reference/authentication",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    steps: [
      "注册 / 登录 OpenAI 账号",
      "打开 API Keys 页面，点击「Create new secret key」",
      "复制以 sk- 开头的密钥（只显示一次）",
      "粘贴到第 3 步 API Key 输入框",
    ],
  },
  {
    id: "deepseek",
    name: "DeepSeek（国产 · OpenAI 兼容）",
    signup_url: "https://platform.deepseek.com/sign_in",
    keys_url: "https://platform.deepseek.com/api_keys",
    docs_url: "https://platform.deepseek.com/api-docs",
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    steps: [
      "注册 DeepSeek 开放平台账号",
      "进入 API Keys 页面创建密钥",
      "复制 API Key 粘贴到第 3 步",
    ],
  },
  {
    id: "moonshot",
    name: "Moonshot / Kimi",
    signup_url: "https://platform.moonshot.cn/console",
    keys_url: "https://platform.moonshot.cn/console/api-keys",
    docs_url: "https://platform.moonshot.cn/docs/api/chat",
    base_url: "https://api.moonshot.cn/v1",
    model: "moonshot-v1-8k",
    steps: ["登录 Kimi 开放平台", "创建 API Key 并复制", "粘贴到第 3 步"],
  },
  {
    id: "custom",
    name: "其他 OpenAI 兼容接口",
    signup_url: "",
    keys_url: "",
    docs_url: "",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    steps: ["向服务商获取 API Key 与 Base URL", "填入第 3 步并测试连接"],
  },
];

let aiWizard = { step: 1, providers: [...DEFAULT_AI_PROVIDERS], selected: null, settings: null };

async function refreshAiBadge() {
  try {
    const pub = await api("/api/ai/settings");
    state.aiConfigured = pub.configured;
    const badge = document.getElementById("ai-badge");
    if (pub.configured) {
      badge.textContent = `AI 已就绪 ${pub.key_hint || ""}`;
      badge.classList.add("ok");
    } else {
      badge.textContent = "点击配置 AI Key";
      badge.classList.remove("ok");
    }
    if (!pub.providers?.length) pub.providers = DEFAULT_AI_PROVIDERS;
    return pub;
  } catch {
    try {
      const health = await api("/api/health");
      state.aiConfigured = health.ai_configured;
    } catch {
      /* ignore */
    }
    return { configured: state.aiConfigured, providers: DEFAULT_AI_PROVIDERS };
  }
}

function showAiModal() {
  document.getElementById("ai-modal").classList.remove("hidden");
}

function hideAiModal() {
  document.getElementById("ai-modal").classList.add("hidden");
}

function setWizardStep(n) {
  aiWizard.step = n;
  document.querySelectorAll(".wizard-step").forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.wstep) === n);
  });
  document.querySelectorAll(".wizard-pane").forEach((el) => {
    el.classList.toggle("active", el.id === "wstep-" + n);
  });
  document.getElementById("btn-wizard-prev").style.visibility = n === 1 ? "hidden" : "visible";
  document.getElementById("btn-wizard-next").textContent = n === 3 ? "完成" : "下一步";
}

function renderProviders() {
  const grid = document.getElementById("provider-grid");
  grid.innerHTML = aiWizard.providers
    .map(
      (p) =>
        `<button type="button" class="provider-card${aiWizard.selected?.id === p.id ? " selected" : ""}" data-id="${p.id}">
          <strong>${escapeHtml(p.name)}</strong>
          <span class="meta">${escapeHtml(p.model)} · ${escapeHtml(p.base_url)}</span>
        </button>`
    )
    .join("");
  grid.querySelectorAll(".provider-card").forEach((el) => {
    el.addEventListener("click", () => {
      aiWizard.selected = aiWizard.providers.find((p) => p.id === el.dataset.id);
      renderProviders();
      renderProviderGuide();
      document.getElementById("ai-base-input").value = aiWizard.selected.base_url;
      document.getElementById("ai-model-input").value = aiWizard.selected.model;
    });
  });
}

function renderProviderGuide() {
  const p = aiWizard.selected;
  const wrap = document.getElementById("provider-guide");
  if (!p) {
    wrap.innerHTML = '<div class="empty">请先选择平台</div>';
    return;
  }
  const links = [];
  if (p.signup_url) links.push(`<a href="${p.signup_url}" target="_blank" rel="noopener">注册账号</a>`);
  if (p.keys_url) links.push(`<a href="${p.keys_url}" target="_blank" rel="noopener">打开 API Keys 页面 ↗</a>`);
  if (p.docs_url) links.push(`<a href="${p.docs_url}" target="_blank" rel="noopener">查看文档</a>`);
  wrap.innerHTML = `
    <p><strong>${escapeHtml(p.name)}</strong> — 按以下步骤获取 Key：</p>
    <ol>${(p.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>
    <div class="guide-links">${links.join("")}</div>
    <p class="meta" style="margin-top:14px">获取 Key 后点「下一步」粘贴并测试。</p>
  `;
}

async function openAiWizard() {
  const pub = await refreshAiBadge();
  aiWizard.settings = pub;
  aiWizard.providers = pub?.providers?.length ? pub.providers : DEFAULT_AI_PROVIDERS;
  const pid = pub?.provider || "openai";
  aiWizard.selected = aiWizard.providers.find((p) => p.id === pid) || aiWizard.providers[0];
  document.getElementById("ai-base-input").value = pub?.base_url || aiWizard.selected.base_url;
  document.getElementById("ai-model-input").value = pub?.model || aiWizard.selected.model;
  document.getElementById("ai-key-input").value = "";
  document.getElementById("ai-env-note").textContent = pub?.env_override
    ? "当前 Key 来自环境变量。界面保存写入 config/ai_settings.local.json"
    : pub?.key_hint
    ? `已保存 Key：${pub.key_hint}（留空则保持原 Key）`
    : "Key 保存在本机 preprocess_ui/config/ai_settings.local.json";
  document.getElementById("ai-test-log").textContent = "—";
  renderProviders();
  renderProviderGuide();
  setWizardStep(1);
  showAiModal();
}

document.getElementById("ai-badge").addEventListener("click", openAiWizard);
document.getElementById("ai-modal-close").addEventListener("click", hideAiModal);
document.getElementById("ai-modal-backdrop").addEventListener("click", hideAiModal);

document.getElementById("btn-wizard-prev").addEventListener("click", () => {
  if (aiWizard.step > 1) setWizardStep(aiWizard.step - 1);
});

document.getElementById("btn-wizard-next").addEventListener("click", () => {
  if (aiWizard.step === 1 && !aiWizard.selected) return toast("请选择 AI 平台");
  if (aiWizard.step < 3) {
    setWizardStep(aiWizard.step + 1);
    if (aiWizard.step === 2) renderProviderGuide();
  } else {
    hideAiModal();
  }
});

document.getElementById("btn-ai-test").addEventListener("click", async () => {
  const body = {
    api_key: document.getElementById("ai-key-input").value,
    base_url: document.getElementById("ai-base-input").value,
    model: document.getElementById("ai-model-input").value,
    provider: aiWizard.selected?.id || "",
  };
  document.getElementById("ai-test-log").textContent = "测试中…";
  try {
    const res = await api("/api/ai/settings/test", { method: "POST", body: JSON.stringify(body) });
    document.getElementById("ai-test-log").textContent = `连接成功 · 模型 ${res.model} · 回复: ${res.reply}`;
    toast("连接成功");
  } catch (e) {
    document.getElementById("ai-test-log").textContent = "失败: " + e.message;
    toast("连接失败");
  }
});

document.getElementById("btn-ai-save").addEventListener("click", async () => {
  const body = {
    api_key: document.getElementById("ai-key-input").value,
    base_url: document.getElementById("ai-base-input").value,
    model: document.getElementById("ai-model-input").value,
    provider: aiWizard.selected?.id || "",
  };
  try {
    await api("/api/ai/settings/test", { method: "POST", body: JSON.stringify(body) });
  } catch (e) {
    if (!confirm("连接测试未通过，仍要保存吗？\n" + e.message)) return;
  }
  try {
    await api("/api/ai/settings", { method: "PUT", body: JSON.stringify(body) });
    await refreshAiBadge();
    toast("AI 配置已保存");
    hideAiModal();
  } catch (e) {
    toast("保存失败: " + e.message);
  }
});

// --- Init ---
// 深链接：?project=ID&step=N&table=idx&field=idx
// 既支持无头截图渲染"已加载"状态，也是一个可分享的定位链接功能
async function applyDeepLink() {
  const p = new URLSearchParams(location.search);
  const step = p.get("step");
  if (step === null) return;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const tab = document.querySelector('.step-tab[data-step="' + step + '"]');
  if (!tab) return;
  tab.click();
  await wait(500);
  const tIdx = parseInt(p.get("table") || "", 10);
  if (step === "1" && !isNaN(tIdx)) {
    const items = document.querySelectorAll("#table-list .table-list-item");
    if (items[tIdx]) items[tIdx].click();
    await wait(400);
    const fIdx = parseInt(p.get("field") || "0", 10);
    const rows = document.querySelectorAll("#field-table-wrap .field-row");
    if (rows[fIdx]) rows[fIdx].click();
  } else if (step === "3" && !isNaN(tIdx)) {
    const items = document.querySelectorAll("#pre-table-list .table-list-item");
    if (items[tIdx]) items[tIdx].click();
  }
}

async function init() {
  try {
    const health = await api("/api/health");
    await refreshAiBadge();
    state.aiConfigured = health.ai_configured;

    const ft = await api("/api/raw/field-types");
    state.fieldTypes = ft.types || [];

    await loadProjects();

    // 深链接可覆盖 localStorage 里的项目
    const urlProject = new URLSearchParams(location.search).get("project");
    if (urlProject) state.projectId = urlProject;

    if (state.projectId) {
      try {
        const meta = await api("/api/projects/" + state.projectId);
        setProject(state.projectId, meta);
        await loadProfile();
        await loadJoinRules();
        await loadPreprocessTables();
      } catch {
        setProject(null, null);
      }
    }

    await applyDeepLink();
  } catch (e) {
    toast("后端未启动: " + e.message);
  }
}

init();
