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
  const withImages = run.candidates.filter((candidate) => candidate.local_thumbnail_path).length;
  const searchOnly = run.candidates.filter((candidate) => candidate.status_labels.includes("search_page_only")).length;
  summary.textContent = `候选 ${run.candidates.length} 条，已处理图片 ${withImages} 张，搜索页线索 ${searchOnly} 条`;
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
    const image = candidate.local_thumbnail_path ? `<img src="/${candidate.local_thumbnail_path}" alt="">` : "";
    card.innerHTML = `
      ${image || '<div class="placeholder">搜索页线索</div>'}
      <div class="meta"><strong>${candidate.platform}</strong></div>
      <div class="meta"><a href="${candidate.source_page_url}" target="_blank" rel="noreferrer">来源链接</a></div>
      <div class="meta">${candidate.title || ""}</div>
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
    summary.textContent = "任务已进入后台，正在逐个平台抓取。";
    pollRun(data.run_id);
  } catch (error) {
    runTitle.textContent = "网络或服务异常";
    logs.textContent = String(error);
    submitButton.disabled = false;
    submitButton.textContent = "开始采集";
  }
});

loadPlatforms();
