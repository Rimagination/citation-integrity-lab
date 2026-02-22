const SAMPLE_FULL = `城市绿地中增加本地开花植物通常会提高传粉昆虫多样性 [1]。湿地恢复后土壤有机碳储量通常会上升 [2]。因此城市绿地管理策略通常会优先配置本地物种 [3]。
[1] Baldock, K. C. R., Goddard, M. A., Hicks, D. M., et al. (2015). Where is the UK's pollinator biodiversity? The importance of urban areas for flower-visiting insects. Proceedings of the Royal Society B, 282(1803), 20142849. https://doi.org/10.1098/rspb.2014.2849
[2] Nahlik, A. M., & Fennessy, M. S. (2016). Carbon storage in US wetlands. Nature Communications, 7, 13835. https://doi.org/10.1038/ncomms13835
[3] Polack, F. P., Thomas, S. J., Kitchin, N., et al. (2020). Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine. New England Journal of Medicine, 383, 2603-2615. https://doi.org/10.1056/NEJMoa2034577`;

const SAMPLE_REFERENCES = `参考文献清单 (References)
[1] Yan, P., & Yang, J. (2017). Species diversity of urban forests in China. Urban Forestry & Urban Greening, 28, 137-144. https://doi.org/10.1016/j.ufug.2017.09.005
[2] Fan, S., & Li, X. (2024). Biodiversity dataset of vascular plants and birds in Chinese urban greenspace. Earth System Science Data, 16(4), 1635-1651. https://doi.org/10.5194/essd-16-1635-2024
[3] Xie, J., & Wang, H. (2022). Urbanization-induced biotic homogenization of gardens and greenspaces in the Yangtze River Delta. Urban Forestry & Urban Greening, 70, 127529. https://doi.org/10.1016/j.ufug.2022.127529`;

const PLACEHOLDER_FULL =
  "输入正文+参考文献，示例会按当前模式填充。";
const PLACEHOLDER_REFERENCES =
  "输入参考文献列表，示例会按当前模式填充。";

const state = {
  analysis: null,
  mode: "full",
  activeAnchorId: null,
};

const inputText = document.getElementById("inputText");
const modeBtn = document.getElementById("modeBtn");
const sampleBtn = document.getElementById("sampleBtn");
const analyzeBtn = document.getElementById("analyzeBtn");
const runState = document.getElementById("runState");
const resultSection = document.getElementById("resultSection");
const workspaceTitle = document.getElementById("workspaceTitle");
const workspaceHint = document.getElementById("workspaceHint");
const renderedText = document.getElementById("renderedText");
const detailPanel = document.getElementById("detailPanel");

function escapeHtml(value) {
  return (value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function withLineBreaks(value) {
  return escapeHtml(value).replaceAll("\n", "<br>");
}

function truncate(text, maxLen = 96) {
  const value = (text ?? "").trim();
  if (value.length <= maxLen) {
    return value;
  }
  return `${value.slice(0, maxLen - 3)}...`;
}

function modeLabel(mode) {
  return mode === "references" ? "仅参考文献" : "正文+参考文献";
}

function statusMeta(status) {
  if (status === "green") {
    return { text: "正常", code: "green", short: "正常" };
  }
  if (status === "yellow") {
    return { text: "需复核", code: "yellow", short: "复核" };
  }
  if (status === "red") {
    return { text: "高风险", code: "red", short: "风险" };
  }
  return { text: "证据不足", code: "white", short: "不足" };
}

function renderStatusLegend(mode) {
  const note =
    mode === "references"
      ? "本模式仅核查文献条目真实性。"
      : "每条结果分两部分：正文匹配判断 + 文献真实性核验。";
  return `<div class="status-legend">
    <div class="legend-row">
      <span class="legend-item"><span class="legend-dot green"></span>正常</span>
      <span class="legend-item"><span class="legend-dot yellow"></span>需复核</span>
      <span class="legend-item"><span class="legend-dot red"></span>高风险</span>
      <span class="legend-item"><span class="legend-dot white"></span>证据不足</span>
    </div>
    <div class="legend-note">${escapeHtml(note)}</div>
  </div>`;
}

function sourceLabel(source) {
  const key = String(source || "").toLowerCase();
  if (key === "crossref") {
    return "Crossref";
  }
  if (key === "openalex") {
    return "OpenAlex";
  }
  if (key === "datacite") {
    return "DataCite";
  }
  if (key === "semanticscholar") {
    return "Semantic Scholar";
  }
  return source || "Unknown";
}

function formatSourceNames(items) {
  return (items || []).map((item) => sourceLabel(item));
}

function normalizeDoi(doi) {
  if (!doi) {
    return "";
  }
  return String(doi)
    .trim()
    .replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")
    .replace(/^doi:\s*/i, "");
}

function buildDoiUrl(doi) {
  const normalized = normalizeDoi(doi);
  if (!normalized) {
    return "";
  }
  return `https://doi.org/${encodeURI(normalized)}`;
}

function buildRepositoryLinks(doi, sourceLinks) {
  const links = [];
  const linkMap = sourceLinks || {};
  const doiUrl = linkMap.doi || buildDoiUrl(doi);
  const normalized = normalizeDoi(doi);

  const crossrefUrl =
    linkMap.crossref ||
    (normalized ? `https://api.crossref.org/works/${encodeURI(normalized)}` : "");
  const openalexUrl =
    linkMap.openalex ||
    (normalized
      ? `https://api.openalex.org/works?filter=doi:https://doi.org/${encodeURIComponent(normalized)}`
      : "");
  const dataciteUrl =
    linkMap.datacite ||
    (normalized ? `https://api.datacite.org/dois/${encodeURIComponent(normalized)}` : "");
  const semanticUrl =
    linkMap.semanticscholar ||
    (normalized
      ? `https://www.semanticscholar.org/search?q=${encodeURIComponent(normalized)}`
      : "");

  if (doiUrl) {
    links.push({ key: "doi", label: "DOI", url: doiUrl });
  }
  if (crossrefUrl) {
    links.push({ key: "crossref", label: "Crossref", url: crossrefUrl });
  }
  if (openalexUrl) {
    links.push({ key: "openalex", label: "OpenAlex", url: openalexUrl });
  }
  if (dataciteUrl) {
    links.push({ key: "datacite", label: "DataCite", url: dataciteUrl });
  }
  if (semanticUrl) {
    links.push({ key: "semanticscholar", label: "Semantic", url: semanticUrl });
  }

  return links;
}

function updateModeButton() {
  modeBtn.textContent = `模式：${modeLabel(state.mode)}`;
}

function updateInputPlaceholder() {
  inputText.placeholder =
    state.mode === "references" ? PLACEHOLDER_REFERENCES : PLACEHOLDER_FULL;
}

function toggleMode() {
  state.mode = state.mode === "full" ? "references" : "full";
  state.activeAnchorId = null;
  updateModeButton();
  updateInputPlaceholder();
  runState.textContent = `已切换为 ${modeLabel(state.mode)}。`;
}

function sampleByMode() {
  return state.mode === "references" ? SAMPLE_REFERENCES : SAMPLE_FULL;
}

function buildRenderedBody(parseResult, anchorMap) {
  if (state.mode === "references") {
    return `<p class="empty-tip">仅核查参考文献。</p>`;
  }

  const body = parseResult.body_text || "";
  const anchors = [...(parseResult.anchors || [])].sort((a, b) => a.start - b.start);
  if (!anchors.length) {
    return body ? withLineBreaks(body) : `<p class="empty-tip">未检测到正文引用。</p>`;
  }

  let html = "";
  let cursor = 0;
  for (const anchor of anchors) {
    if (anchor.start < cursor) {
      continue;
    }
    html += withLineBreaks(body.slice(cursor, anchor.start));
    const markerText = body.slice(anchor.start, anchor.end) || anchor.marker;
    const anchorResult = anchorMap.get(anchor.anchor_id);
    const status = anchorResult?.overall_status || "white";
    html += `<button type="button" class="citation-tag status-${status}" data-anchor-id="${anchor.anchor_id}">
      ${escapeHtml(markerText)}<span class="dot"></span>
    </button>`;
    cursor = anchor.end;
  }
  html += withLineBreaks(body.slice(cursor));
  return html;
}

function renderLinkBlock(referenceResult, fallbackReference) {
  const official = referenceResult?.official || {};
  const doiRaw = official.doi || fallbackReference?.doi || "";
  const links = buildRepositoryLinks(doiRaw, referenceResult?.source_links);
  if (!links.length) {
    return "";
  }
  return `<div class="item-links">${links
    .map(
      (item) =>
        `<a class="item-link" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.label)}</a>`
    )
    .join("<span class=\"link-sep\">|</span>")}</div>`;
}

function renderConflictList(conflicts) {
  if (!conflicts || !conflicts.length) {
    return `<div class="item-sub">偏差字段：无</div>`;
  }
  const lines = conflicts
    .map((item) => {
      const field = item.field || "unknown";
      const from = truncate(item.user_value || "-", 48);
      const to = truncate(item.official_value || "-", 48);
      const sim =
        item.similarity === null || item.similarity === undefined
          ? ""
          : ` (${Math.round(item.similarity * 100)}%)`;
      return `<li><strong>${escapeHtml(field)}</strong>: ${escapeHtml(from)} → ${escapeHtml(to)}${sim}</li>`;
    })
    .join("");
  return `<ul class="conflict-list">${lines}</ul>`;
}

function summarizeReferenceResults(analysis) {
  const refs = Object.values(analysis.reference_results || {});
  const summary = {
    total: refs.length,
    green: 0,
    yellow: 0,
    red: 0,
    white: 0,
    topConflicts: [],
    sources: {},
  };

  const conflictCounter = new Map();
  for (const item of refs) {
    const status = item.status || "white";
    if (summary[status] !== undefined) {
      summary[status] += 1;
    }
    for (const source of item.sources_found || []) {
      summary.sources[source] = (summary.sources[source] || 0) + 1;
    }
    for (const conflict of item.conflicts || []) {
      const key = conflict.field || "unknown";
      conflictCounter.set(key, (conflictCounter.get(key) || 0) + 1);
    }
  }

  summary.topConflicts = [...conflictCounter.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  return summary;
}

function renderReferenceReport(analysis) {
  const summary = summarizeReferenceResults(analysis);
  if (!summary.total) {
    return `<p class="empty-tip">未生成总结报告。</p>`;
  }

  const sourceLines = Object.entries(summary.sources)
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => `<li>${escapeHtml(sourceLabel(name))}: ${count}</li>`)
    .join("");

  const conflictLines = summary.topConflicts.length
    ? summary.topConflicts
        .map(([field, count]) => `<li>${escapeHtml(field)}: ${count}</li>`)
        .join("")
    : "<li>无</li>";

  const riskRefs = Object.values(analysis.reference_results || {})
    .filter((item) => item.status === "red" || item.status === "yellow")
    .map((item) => item.ref_id)
    .slice(0, 8)
    .join(", ");

  return `<div class="report-block">
    <h3>总结报告</h3>
    <p>已核查 ${summary.total} 条参考文献。</p>
    <div class="report-grid">
      <div class="report-chip green">正常 ${summary.green}</div>
      <div class="report-chip yellow">复核 ${summary.yellow}</div>
      <div class="report-chip red">风险 ${summary.red}</div>
      <div class="report-chip white">不足 ${summary.white}</div>
    </div>
    <h4>高频偏差字段</h4>
    <ul class="report-list">${conflictLines}</ul>
    <h4>命中数据源</h4>
    <ul class="report-list">${sourceLines || "<li>无</li>"}</ul>
    <h4>建议优先复核</h4>
    <p>${escapeHtml(riskRefs || "无")}</p>
  </div>`;
}

function renderReferenceItems(analysis) {
  const references = [...(analysis.parse?.references || [])].sort(
    (a, b) => Number(a.index || a.ref_id || 0) - Number(b.index || b.ref_id || 0)
  );
  if (!references.length) {
    detailPanel.innerHTML = `<p class="empty-tip">未识别到参考文献。</p>`;
    return;
  }

  const resultMap = analysis.reference_results || {};
  const items = references
    .map((reference) => {
      const result = resultMap[String(reference.ref_id)];
      const status = result?.status || "white";
      const meta = statusMeta(status);
      const title = result?.official?.title || reference.title || reference.raw || "无标题";
      const reason = result?.reason || "无返回结果。";
      const sourceText =
        result?.sources_found && result.sources_found.length
          ? formatSourceNames(result.sources_found).join(" / ")
          : "无";
      return `<div class="result-item status-${status}">
        <div class="item-head">
          <span class="status-chip">[${escapeHtml(reference.ref_id)}] ${meta.text}</span>
          <span class="item-tag">${escapeHtml(result?.label || "未判定")}</span>
        </div>
        <div class="item-title">${escapeHtml(truncate(title, 108))}</div>
        <div class="item-sub">${escapeHtml(truncate(reason, 120))}</div>
        <div class="item-sub">命中源：${escapeHtml(sourceText)}</div>
        ${renderLinkBlock(result, reference)}
        ${renderConflictList(result?.conflicts || [])}
      </div>`;
    })
    .join("");

  detailPanel.innerHTML = `${renderStatusLegend("references")}<div class="result-list">${items}</div>`;
}

function anchorScoreSummary(anchorResult) {
  const dims = anchorResult.dimensions || {};
  const md = statusMeta(dims.metadata?.status || "white").short;
  const rv = statusMeta(dims.relevance?.status || "white").short;
  const sp = statusMeta(dims.support?.status || "white").short;
  return `元数据:${md} | 相关性:${rv} | 支持度:${sp}`;
}

function dimensionLabel(key) {
  if (key === "metadata") {
    return "元数据";
  }
  if (key === "relevance") {
    return "相关性";
  }
  if (key === "support") {
    return "支持度";
  }
  return key;
}

function renderAnchorReasonBlock(anchorResult) {
  const dimensions = anchorResult.dimensions || {};
  const all = [
    { key: "metadata", ...dimensions.metadata },
    { key: "relevance", ...dimensions.relevance },
    { key: "support", ...dimensions.support },
  ];
  const issues = all.filter(
    (item) => item.status === "red" || item.status === "yellow" || item.status === "white"
  );

  if (!issues.length) {
    return `<div class="risk-reason ok">正文匹配判断：未发现明显问题。</div>`;
  }

  const summary = issues
    .map((item) => `${dimensionLabel(item.key)}${statusMeta(item.status).text}`)
    .join("；");
  const details = issues
    .slice(0, 3)
    .map(
      (item) =>
        `<li><strong>${dimensionLabel(item.key)}</strong>：${escapeHtml(
          truncate(item.reason || "无说明。", 180)
        )}</li>`
    )
    .join("");

  return `<div class="risk-reason">正文匹配判断：${escapeHtml(summary)}</div>
    <ul class="reason-list">${details}</ul>`;
}

function renderAnchorEvidence(anchorResult) {
  const linked = anchorResult.linked_reference_results || [];
  if (!linked.length) {
    return `<div class="subsection-box"><div class="subsection-title">文献真实性核验</div><div class="item-sub">未映射参考文献。</div></div>`;
  }
  const rows = linked
    .map((referenceResult) => {
      const meta = statusMeta(referenceResult.status || "white");
      const sourceText =
        referenceResult.sources_found && referenceResult.sources_found.length
          ? formatSourceNames(referenceResult.sources_found).join(" / ")
          : "无";
      return `<div class="linked-ref">
        <div class="item-sub"><strong>[${escapeHtml(referenceResult.ref_id)}]</strong> 元数据：${meta.text}</div>
        <div class="item-sub">${escapeHtml(truncate(referenceResult.reason || "无说明。", 120))}</div>
        <div class="item-sub">命中源：${escapeHtml(sourceText)}</div>
        ${renderLinkBlock(referenceResult, null)}
        ${renderConflictList(referenceResult.conflicts || [])}
      </div>`;
    })
    .join("");
  return `<div class="subsection-box">
    <div class="subsection-title">文献真实性核验</div>
    <div class="subsection-note">只核对文献条目信息是否真实，不代表正文支持度。</div>
    ${rows}
  </div>`;
}

function renderAnchorItems(analysis) {
  const anchorResults = analysis.anchor_results || [];
  if (!anchorResults.length) {
    renderReferenceItems(analysis);
    return;
  }

  const items = anchorResults
    .map((anchorResult) => {
      const status = anchorResult.overall_status || "white";
      const meta = statusMeta(status);
      const refs = (anchorResult.linked_ref_ids || []).join(", ") || "-";
      const claim = anchorResult.claim || "";
      return `<div class="result-item status-${status}" data-anchor-id="${anchorResult.anchor_id}">
        <div class="item-head">
          <span class="status-chip">${escapeHtml(anchorResult.marker)} ${meta.text}</span>
          <span class="item-tag">${escapeHtml(anchorScoreSummary(anchorResult))}</span>
        </div>
        <div class="item-title">关联文献：${escapeHtml(refs)}</div>
        <div class="item-sub">${escapeHtml(truncate(claim, 108))}</div>
        ${renderAnchorReasonBlock(anchorResult)}
        ${renderAnchorEvidence(anchorResult)}
      </div>`;
    })
    .join("");

  detailPanel.innerHTML = `${renderStatusLegend("full")}<div class="result-list">${items}</div>`;
}

function setActiveAnchor(anchorId) {
  state.activeAnchorId = anchorId;
  const tags = renderedText.querySelectorAll(".citation-tag");
  for (const tag of tags) {
    tag.classList.toggle("active", tag.dataset.anchorId === anchorId);
  }
  const rows = detailPanel.querySelectorAll(".result-item[data-anchor-id]");
  for (const row of rows) {
    row.classList.toggle("active", row.dataset.anchorId === anchorId);
  }
}

function renderAnalysis(analysis) {
  state.analysis = analysis;
  const anchorMap = new Map();
  for (const result of analysis.anchor_results || []) {
    anchorMap.set(result.anchor_id, result);
  }
  resultSection.classList.remove("hidden");

  const refCount = (analysis.parse?.references || []).length;
  const anchorCount = (analysis.parse?.anchors || []).length;

  if (state.mode === "references") {
    workspaceTitle.textContent = "参考文献总结报告";
    workspaceHint.textContent = "左侧看总结，右侧看逐条结果。";
    renderedText.innerHTML = renderReferenceReport(analysis);
    renderReferenceItems(analysis);
    runState.textContent = `完成：文献 ${refCount} 条。`;
    return;
  }

  workspaceTitle.textContent = "核查工作区";
  workspaceHint.textContent = "左侧高亮引用，右侧查看证据。";
  renderedText.innerHTML = buildRenderedBody(analysis.parse, anchorMap);
  renderAnchorItems(analysis);
  const firstIssue =
    (analysis.anchor_results || []).find((item) => item.overall_status !== "green") ||
    (analysis.anchor_results || [])[0];
  if (firstIssue) {
    setActiveAnchor(firstIssue.anchor_id);
  } else {
    state.activeAnchorId = null;
  }
  runState.textContent = `完成：引用 ${anchorCount}，文献 ${refCount}。`;
}

async function runAnalysis() {
  const text = inputText.value.trim();
  if (!text) {
    runState.textContent = "请先输入文本。";
    return;
  }

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "核查中";
  runState.textContent = "正在核查...";

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, mode: state.mode }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    const data = await response.json();
    renderAnalysis(data);
  } catch (error) {
    runState.textContent = `失败：${error.message}`;
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "开始";
  }
}

modeBtn.addEventListener("click", toggleMode);

sampleBtn.addEventListener("click", () => {
  inputText.value = sampleByMode();
  runState.textContent = `已填充 ${modeLabel(state.mode)} 示例。`;
});

analyzeBtn.addEventListener("click", runAnalysis);

detailPanel.addEventListener("click", (event) => {
  if (event.target.closest("a")) {
    return;
  }
  const row = event.target.closest(".result-item[data-anchor-id]");
  if (!row) {
    return;
  }
  const anchorId = row.dataset.anchorId;
  if (anchorId) {
    setActiveAnchor(anchorId);
  }
});

renderedText.addEventListener("click", (event) => {
  const tag = event.target.closest(".citation-tag");
  if (!tag) {
    return;
  }
  const anchorId = tag.dataset.anchorId;
  if (anchorId) {
    setActiveAnchor(anchorId);
  }
});

updateModeButton();
updateInputPlaceholder();
