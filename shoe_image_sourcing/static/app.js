const form = document.querySelector("#run-form");
const platformBox = document.querySelector("#platforms");
const logs = document.querySelector("#logs");
const gallery = document.querySelector("#gallery");
const runTitle = document.querySelector("#run-title");

async function loadPlatforms() {
  const res = await fetch("/api/platforms");
  const data = await res.json();
  [...data.default, ...data.optional].forEach((platform) => {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" value="${platform.name}" ${platform.enabled_by_default ? "checked" : ""}> ${platform.label}`;
    platformBox.appendChild(label);
  });
}

function selectedPlatforms() {
  return [...platformBox.querySelectorAll("input:checked")].map((input) => input.value).join(",");
}

async function pollRun(runId) {
  const res = await fetch(`/api/runs/${runId}`);
  const run = await res.json();
  runTitle.textContent = `任务 ${run.run_id} · ${run.status}`;
  logs.textContent = run.logs.join("\n");
  gallery.innerHTML = "";
  run.candidates.forEach((candidate) => {
    const card = document.createElement("article");
    card.className = "card";
    const tags = candidate.status_labels.map((tag) => `<span class="tag">${tag}</span>`).join(" ");
    const image = candidate.local_thumbnail_path
      ? `<img src="/${candidate.local_thumbnail_path}" alt="">`
      : "";
    card.innerHTML = `
      ${image}
      <div class="meta"><strong>${candidate.platform}</strong></div>
      <div class="meta"><a href="${candidate.source_page_url}" target="_blank">来源链接</a></div>
      <div class="meta">${candidate.title || ""}</div>
      ${tags}
    `;
    gallery.appendChild(card);
  });
  if (run.status === "running" || run.status === "created") {
    setTimeout(() => pollRun(runId), 1500);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = new FormData(form);
  body.set("platforms", selectedPlatforms());
  runTitle.textContent = "正在创建任务...";
  logs.textContent = "";
  gallery.innerHTML = "";
  const res = await fetch("/api/runs", { method: "POST", body });
  const data = await res.json();
  if (!res.ok) {
    runTitle.textContent = "创建失败";
    logs.textContent = data.detail || "请求失败";
    return;
  }
  pollRun(data.run_id);
});

loadPlatforms();
