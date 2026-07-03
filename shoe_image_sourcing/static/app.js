const form = document.querySelector("#run-form");
const fastPlatformBox = document.querySelector("#fast-platforms");
const deepPlatformBox = document.querySelector("#deep-platforms");
const logs = document.querySelector("#logs");
const gallery = document.querySelector("#gallery");
const runTitle = document.querySelector("#run-title");
const summary = document.querySelector("#summary");
const submitButton = document.querySelector("#submit-button");

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

function renderSummary(run) {
  const withImages = run.candidates.filter((candidate) => candidate.local_thumbnail_path || candidate.image_url).length;
  const processed = run.candidates.filter((candidate) => candidate.local_processed_path).length;
  const searchOnly = run.candidates.filter((candidate) => candidate.status_labels.includes("search_page_only")).length;
  summary.textContent = `图片 ${withImages} 张，已转 3:4 ${processed} 张，搜索页线索 ${searchOnly} 条`;
}

function imageMarkup(candidate) {
  const imagePath = candidate.local_processed_path || candidate.local_thumbnail_path;
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
  run.candidates.forEach((candidate) => {
    const card = document.createElement("article");
    card.className = "card";
    const tags = candidate.status_labels.map((tag) => `<span class="tag">${tag}</span>`).join(" ");
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = new FormData(form);
  body.set("platforms", selectedPlatforms());
  runTitle.textContent = "正在上传并创建任务...";
  summary.textContent = "Render 免费版冷启动时，首次请求可能需要几十秒。";
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
    summary.textContent = "任务已进入后台，正在逐个平台抓图。";
    pollRun(data.run_id);
  } catch (error) {
    runTitle.textContent = "网络或服务异常";
    logs.textContent = String(error);
    submitButton.disabled = false;
    submitButton.textContent = "开始采集";
  }
});

loadPlatforms();
