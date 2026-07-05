const form = document.querySelector("#run-form");
const productText = document.querySelector("#product-text");
const detectedFacts = document.querySelector("#detected-facts");
const clearProductText = document.querySelector("#clear-product-text");
const fastPlatformBox = document.querySelector("#fast-platforms");
const deepPlatformBox = document.querySelector("#deep-platforms");
const logs = document.querySelector("#logs");
const gallery = document.querySelector("#gallery");
const runTitle = document.querySelector("#run-title");
const summary = document.querySelector("#summary");
const submitButton = document.querySelector("#submit-button");
const notice = document.querySelector("#notice");

const hiddenStatusLabels = new Set(["visual_mismatch", "download_failed", "search_page_only", "fetch_skipped_or_blocked"]);
const internalStatusPattern = /^(text_score|visual_score|profile_score)_/;

const knownBrands = [
  "Nike",
  "Adidas",
  "Puma",
  "Reebok",
  "Asics",
  "New Balance",
  "Mizuno",
  "Fila",
  "Skechers",
  "Under Armour",
  "Converse",
  "Vans",
  "Jordan",
];

function cleanValue(value) {
  return (value || "").replace(/[【】]/g, " ").replace(/\s+/g, " ").replace(/^[-|｜,，;；\s]+|[-|｜,，;；\s]+$/g, "");
}

function findLabeled(text, labels) {
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    for (const label of labels) {
      const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const match = line.match(new RegExp(`${escaped}\\s*[:：]\\s*(.+)`, "i"));
      if (match) return cleanValue(match[1]);
    }
  }
  return "";
}

function extractProductFacts(text) {
  const brand = knownBrands.find((item) => new RegExp(`(^|[^a-z0-9])${item.replace(/\s+/g, "\\s+")}([^a-z0-9]|$)`, "i").test(text)) || "";
  const sku =
    findLabeled(text, ["官方货号", "货号", "款号", "SKU", "Article", "Артикул"]) ||
    (text.match(/\b([A-Z0-9]{3,}-[A-Z0-9]{2,})\b/i)?.[1] || "").toUpperCase();
  const color = findLabeled(text, ["Цвет модели", "颜色", "色号", "Color", "Цвет"]);
  const labeledName = findLabeled(text, ["俄语名称", "品类", "标题", "商品标题", "名称", "产品名称", "Title", "Name"]);
  let model = "";
  const source = labeledName || text.split(/\r?\n/).slice(0, 6).join(" ");
  if (brand) {
    const match = source.match(new RegExp(`${brand}\\s+([A-Za-z0-9][A-Za-z0-9 '\\-]+)`, "i"));
    if (match) model = cleanValue(match[1]).split(/[|｜,，;；]/)[0].slice(0, 80);
  }
  if (!model && labeledName) model = cleanValue(labeledName).slice(0, 100);
  const keywordLines = text
    .split(/\r?\n/)
    .map(cleanValue)
    .filter((line) => /目标用户|使用场景|核心卖点|dad shoes|кроссовки/i.test(line));
  return { brand, model, sku, color, keywords: keywordLines.join(" ").slice(0, 220) };
}

function inputByName(name) {
  return form.querySelector(`[name="${name}"]`);
}

function applyDetectedFacts({ fillOnlyEmpty = true } = {}) {
  const text = productText.value.trim();
  if (!text) {
    detectedFacts.textContent = "等待粘贴产品资料";
    return;
  }
  const facts = extractProductFacts(text);
  ["brand", "model", "sku", "color", "keywords"].forEach((name) => {
    const input = inputByName(name);
    if (facts[name] && (!fillOnlyEmpty || !input.value.trim())) input.value = facts[name];
  });
  const chips = Object.entries(facts)
    .filter(([, value]) => value)
    .map(([key, value]) => `${key}: ${value}`);
  detectedFacts.textContent = chips.length ? `已识别 ${chips.join(" | ")}` : "未识别到货号/型号，可手动补充字段";
}

async function loadPlatforms() {
  const res = await fetch("/api/platforms");
  const data = await res.json();
  [...data.default, ...data.optional].forEach((platform) => {
    const label = document.createElement("label");
    const tag = platform.speed_tier === "deep" ? "<span>深度</span>" : "<span>快速</span>";
    label.innerHTML = `<input type="checkbox" value="${platform.name}" ${platform.enabled_by_default ? "checked" : ""}> ${platform.label} ${tag}`;
    if (platform.speed_tier === "deep") {
      deepPlatformBox.appendChild(label);
    } else {
      fastPlatformBox.appendChild(label);
    }
  });
}

function selectedPlatforms() {
  return [...document.querySelectorAll(".platforms input:checked")]
    .map((input) => input.value)
    .join(",");
}

function isVisibleCandidate(candidate) {
  const labels = candidate.status_labels || [];
  const hidden = labels.some((label) => hiddenStatusLabels.has(label));
  const hasImage = candidate.local_processed_path || candidate.local_thumbnail_path || candidate.local_original_path || candidate.image_url;
  return !hidden && Boolean(hasImage);
}

function visibleCandidates(run) {
  return (run.candidates || []).filter(isVisibleCandidate);
}

function displayTags(candidate) {
  return (candidate.status_labels || [])
    .filter((tag) => !hiddenStatusLabels.has(tag))
    .filter((tag) => !internalStatusPattern.test(tag));
}

function reverseSearchMarkup(run) {
  const links = run.reverse_search_links || [];
  if (!links.length) return "";
  const anchors = links
    .map((link) => `<a class="reverse-link" href="${link.url}" target="_blank" rel="noreferrer">${link.label}</a>`)
    .join("");
  return `<div class="reverse-links"><span>以图搜图</span>${anchors}</div>`;
}

function renderSummary(run) {
  const candidates = visibleCandidates(run);
  const withImages = candidates.filter((candidate) => candidate.local_processed_path || candidate.local_thumbnail_path || candidate.local_original_path || candidate.image_url).length;
  const processed = candidates.filter((candidate) => candidate.local_processed_path).length;
  const searchOnly = run.candidates.filter((candidate) => candidate.status_labels.includes("search_page_only")).length;
  summary.textContent = `图片 ${withImages} 张，已转 3:4 ${processed} 张，搜索页线索 ${searchOnly} 条`;
}

renderSummary = function (run) {
  const candidates = visibleCandidates(run);
  const withImages = candidates.filter((candidate) => candidate.local_processed_path || candidate.local_thumbnail_path || candidate.local_original_path || candidate.image_url).length;
  const processed = candidates.filter((candidate) => candidate.local_processed_path).length;
  const searchOnly = (run.candidates || []).filter((candidate) => (candidate.status_labels || []).includes("search_page_only")).length;
  const profile = run.visual_profile || {};
  const profileText = profile.foreground_aspect
    ? ` | visual: aspect ${profile.foreground_aspect}, coverage ${profile.foreground_coverage}, edge ${profile.edge_density}`
    : "";
  summary.innerHTML = `图片 ${withImages} 张，已转 3:4 ${processed} 张，搜索页线索 ${searchOnly} 条${profileText}${reverseSearchMarkup(run)}`;
  if (run.status === "complete" && processed === 0) {
    notice.hidden = false;
    notice.innerHTML = `
      <strong>未找到同款图片</strong>
      <span>当前平台没有命中与货号/实物图一致的产品，已过滤相似款和错款。</span>
    `;
  } else {
    notice.hidden = true;
    notice.textContent = "";
  }
};

function imageMarkup(candidate) {
  const imagePath = candidate.local_processed_path || candidate.local_thumbnail_path || candidate.local_original_path;
  if (imagePath) {
    return `<a class="image-link" href="/${imagePath}" target="_blank" rel="noreferrer"><img src="/${imagePath}" alt=""></a>`;
  }
  if (candidate.image_url) {
    return `<a class="image-link" href="${candidate.image_url}" target="_blank" rel="noreferrer"><img src="${candidate.image_url}" alt="" loading="lazy" referrerpolicy="no-referrer"></a>`;
  }
  return '<div class="placeholder">暂未拿到图片</div>';
}

function actionMarkup(candidate) {
  const processedPath = candidate.local_processed_path ? `/${candidate.local_processed_path}` : "";
  const originalPath = candidate.local_original_path ? `/${candidate.local_original_path}` : candidate.image_url;
  const processedButton = processedPath
    ? `<a class="action" href="${processedPath}" target="_blank" rel="noreferrer">打开 3:4 图</a>`
    : "";
  const originalButton = originalPath
    ? `<a class="action" href="${originalPath}" target="_blank" rel="noreferrer">打开原图</a>`
    : "";
  return `<div class="actions">${processedButton}${originalButton}</div>`;
}

async function pollRun(runId) {
  const res = await fetch(`/api/runs/${runId}`);
  const run = await res.json();
  runTitle.textContent = `任务 ${run.run_id} · ${run.status}`;
  renderSummary(run);
  logs.textContent = run.logs.join("\n");
  gallery.innerHTML = "";
  visibleCandidates(run).forEach((candidate) => {
    const card = document.createElement("article");
    card.className = "card";
    const tags = displayTags(candidate).map((tag) => `<span class="tag">${tag}</span>`).join(" ");
    card.innerHTML = `
      ${imageMarkup(candidate)}
      <div class="meta"><strong>${candidate.platform}</strong></div>
      <div class="meta">${candidate.title || ""}</div>
      ${actionMarkup(candidate)}
      <details class="source"><summary>来源</summary><a href="${candidate.source_page_url}" target="_blank" rel="noreferrer">${candidate.source_page_url}</a></details>
      ${tags}
    `;
    gallery.appendChild(card);
  });
  if (run.status === "running" || run.status === "created") {
    setTimeout(() => pollRun(runId), 1500);
  } else {
    submitButton.disabled = false;
    submitButton.textContent = "开始采集";
  }
}

productText.addEventListener("input", () => applyDetectedFacts());
clearProductText.addEventListener("click", () => {
  productText.value = "";
  detectedFacts.textContent = "等待粘贴产品资料";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  applyDetectedFacts({ fillOnlyEmpty: true });
  const body = new FormData(form);
  if (!body.get("product_text")?.trim() && !body.get("model")?.trim() && !body.get("sku")?.trim() && !body.get("keywords")?.trim()) {
    runTitle.textContent = "信息不够";
    summary.textContent = "请至少粘贴产品信息，或填写型号、货号、补充关键词之一；只填 Nike 会搜到很多无关图片。";
    notice.hidden = true;
    notice.textContent = "";
    logs.textContent = "";
    gallery.innerHTML = "";
    return;
  }
  body.set("platforms", selectedPlatforms());
  runTitle.textContent = "正在上传并创建任务...";
  summary.textContent = "Render 免费版冷启动时，首次请求可能需要几十秒。";
  notice.hidden = true;
  notice.textContent = "";
  logs.textContent = "";
  gallery.innerHTML = "";
  submitButton.disabled = true;
  submitButton.textContent = "创建中...";
  try {
    const res = await fetch("/api/runs", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) {
      runTitle.textContent = "创建失败";
      logs.textContent = data.detail || "请求失败";
      submitButton.disabled = false;
      submitButton.textContent = "开始采集";
      return;
    }
    runTitle.textContent = `任务 ${data.run_id} · 已创建`;
    summary.textContent = data.facts ? `已用识别信息搜索：${[data.facts.sku, data.facts.brand, data.facts.model, data.facts.color].filter(Boolean).join(" ")}` : "任务已进入后台，正在逐个平台抓图。";
    pollRun(data.run_id);
  } catch (error) {
    runTitle.textContent = "网络或服务异常";
    logs.textContent = String(error);
    submitButton.disabled = false;
    submitButton.textContent = "开始采集";
  }
});

loadPlatforms();
