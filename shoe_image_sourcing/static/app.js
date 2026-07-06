const form = document.querySelector("#run-form");
const logs = document.querySelector("#logs");
const gallery = document.querySelector("#gallery");
const runTitle = document.querySelector("#run-title");
const summary = document.querySelector("#summary");
const submitButton = document.querySelector("#submit-button");
const notice = document.querySelector("#notice");

const hiddenStatusLabels = new Set(["visual_mismatch", "download_failed"]);
const internalStatusPattern = /^(text_score|visual_score|profile_score|feature_score)_/;

function isVisibleCandidate(candidate) {
  const labels = candidate.status_labels || [];
  const hidden = labels.some((label) => hiddenStatusLabels.has(label));
  const hasImage = candidate.local_processed_path || candidate.local_thumbnail_path || candidate.local_original_path || candidate.image_url;
  const hasSearchPage = candidate.source_page_url && labels.includes("search_page_only");
  return !hidden && Boolean(hasImage || hasSearchPage);
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
  return `
    <div class="reverse-links">
      <span>以图搜图</span>
      ${links.map((link) => `<a class="reverse-link" href="${link.url}" target="_blank" rel="noreferrer">${link.label}</a>`).join("")}
    </div>
  `;
}

function renderSummary(run) {
  const candidates = visibleCandidates(run);
  const withImages = candidates.filter((candidate) => candidate.local_processed_path || candidate.local_thumbnail_path || candidate.local_original_path || candidate.image_url).length;
  const processed = candidates.filter((candidate) => candidate.local_processed_path).length;
  const searchOnly = (run.candidates || []).filter((candidate) => (candidate.status_labels || []).includes("search_page_only")).length;
  const profile = run.visual_profile || {};
  const profileText = profile.foreground_aspect
    ? ` | visual: aspect ${profile.foreground_aspect}, coverage ${profile.foreground_coverage}, edge ${profile.edge_density}`
    : "";
  summary.innerHTML = `图片 ${withImages} 张，已转 3:4 ${processed} 张，搜索页线索 ${searchOnly} 条${profileText}${reverseSearchMarkup(run)}`;

  if (run.status === "failed") {
    notice.hidden = false;
    const lastLog = (run.logs || []).slice().reverse().find((log) => log.includes("failed") || log.includes("失败")) || "请查看下方日志";
    notice.innerHTML = `<strong>任务失败</strong><span>${lastLog}</span>`;
  } else if (run.status === "complete" && processed === 0) {
    notice.hidden = false;
    notice.innerHTML = `
      <strong>未找到同款图片</strong>
      <span>当前没有从上传图片识别到可用的 Poizon 同款图，已过滤相似款和错款。</span>
    `;
  } else {
    notice.hidden = true;
    notice.textContent = "";
  }
}

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
  if (!res.ok) {
    runTitle.textContent = `任务 ${runId} · failed`;
    summary.textContent = "任务状态读取失败";
    notice.hidden = false;
    const transient = [502, 503, 504].includes(res.status);
    const title = transient ? "服务临时不可用" : "任务状态丢失";
    const message = transient
      ? "Render 正在冷启动、重启或部署中。请等十几秒后重新提交一次。"
      : "Render 免费实例重启或重新部署后，本次临时任务文件可能已被清空。请重新提交一次。";
    notice.innerHTML = `<strong>${title}</strong><span>${message}</span>`;
    logs.textContent = `GET /api/runs/${runId} returned ${res.status}`;
    gallery.innerHTML = "";
    submitButton.disabled = false;
    submitButton.textContent = "开始搜图";
    return;
  }

  const run = await res.json();
  runTitle.textContent = `任务 ${run.run_id} · ${run.status}`;
  renderSummary(run);
  logs.textContent = (run.logs || []).join("\n");
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
    submitButton.textContent = "开始搜图";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = new FormData(form);
  const selectedPlatforms = Array.from(form.querySelectorAll('input[name="platforms"]:checked'))
    .map((input) => input.value)
    .filter(Boolean);
  body.delete("platforms");
  body.set("platforms", selectedPlatforms.join(",") || "poizon_visual,kr_poizon,wildberries,ozon");

  runTitle.textContent = "正在上传图片并创建任务...";
  summary.textContent = "系统会只根据上传图片做 Poizon Visual 搜图。";
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
      submitButton.textContent = "开始搜图";
      return;
    }
    runTitle.textContent = `任务 ${data.run_id} · 已创建`;
    summary.textContent = "任务已进入后台，正在以图搜图。";
    pollRun(data.run_id);
  } catch (error) {
    runTitle.textContent = "网络或服务异常";
    logs.textContent = String(error);
    submitButton.disabled = false;
    submitButton.textContent = "开始搜图";
  }
});
