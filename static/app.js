const state = {
  token: localStorage.getItem("token") || "",
  user: null,
  docs: [],
  selectedDocId: null,
  templates: [],
};

const byId = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Ошибка запроса");
  return data;
}

function setMessage(id, message, isError = false) {
  const el = byId(id);
  el.textContent = message;
  el.style.color = isError ? "#b00020" : "#1e2a38";
}

function showView(viewId) {
  document.querySelectorAll(".view").forEach((node) => node.classList.add("hidden"));
  byId(viewId).classList.remove("hidden");
  document.querySelectorAll(".menu-btn").forEach((btn) => btn.classList.remove("active"));
  const active = [...document.querySelectorAll(".menu-btn")].find((btn) => btn.dataset.view === viewId);
  if (active) active.classList.add("active");
}

async function loadUser() {
  const me = await api("/api/me");
  state.user = me;
  byId("whoami").textContent = `Пользователь: ${me.identifier} (${me.role})`;
  byId("profileInfo").textContent = `Идентификатор: ${me.identifier}, роль: ${me.role}, режим модели: ${me.model_mode}`;
  if (me.role === "admin") {
    byId("devSettingsCard").classList.remove("hidden");
    byId("modelModeSelect").value = me.model_mode || "server";
  } else {
    byId("devSettingsCard").classList.add("hidden");
  }
}

function renderDocs() {
  const list = byId("docList");
  list.innerHTML = "";
  for (const doc of state.docs) {
    const btn = document.createElement("button");
    btn.className = "btn btn-secondary";
    btn.textContent = `${doc.folder}: ${doc.title} [${doc.tool}]`;
    btn.onclick = () => {
      state.selectedDocId = doc.id;
      byId("docTitle").value = doc.title;
      byId("docFolder").value = doc.folder;
      byId("docTool").value = doc.tool;
      byId("docEditor").value = doc.content;
    };
    list.appendChild(btn);
  }
}

async function loadDocs() {
  const data = await api("/api/documents");
  state.docs = data.items;
  renderDocs();
}

async function loadTemplates() {
  const data = await api("/api/templates");
  state.templates = data.items;
  const sel = byId("templateSelect");
  sel.innerHTML = "";
  for (const t of data.items) {
    const option = document.createElement("option");
    option.value = t.name;
    option.textContent = t.name;
    sel.appendChild(option);
  }
}

async function loadMetrics() {
  const data = await api("/api/chat/metrics");
  byId("promptMetrics").textContent = data.items
    .map((x) => `${x.created_at}: ${x.response_ms} ms, ${x.tokens_out} токенов, ${x.tokens_per_sec} ток/с`)
    .join("\n");
}

async function initializeApp() {
  byId("authView").classList.add("hidden");
  byId("appView").classList.remove("hidden");
  await loadUser();
  await loadDocs();
  await loadTemplates();
  await loadMetrics();
}

byId("loginBtn").onclick = async () => {
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        identifier: byId("authIdentifier").value.trim(),
        password: byId("authPassword").value,
      }),
    });
    state.token = data.token;
    localStorage.setItem("token", state.token);
    await initializeApp();
  } catch (err) {
    setMessage("authMsg", err.message, true);
  }
};

byId("registerBtn").onclick = async () => {
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        identifier: byId("authIdentifier").value.trim(),
        password: byId("authPassword").value,
      }),
    });
    state.token = data.token;
    localStorage.setItem("token", state.token);
    await initializeApp();
  } catch (err) {
    setMessage("authMsg", err.message, true);
  }
};

byId("logoutBtn").onclick = () => {
  localStorage.removeItem("token");
  location.reload();
};

document.querySelectorAll(".menu-btn,.settings-icon").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

byId("transcribeBtn").onclick = async () => {
  try {
    const file = byId("audioFile").files[0];
    if (!file) throw new Error("Выберите аудиофайл");
    const form = new FormData();
    form.append("file", file);
    const data = await api("/api/analysis/transcribe", { method: "POST", body: form });
    byId("transcriptText").value = data.transcript;
  } catch (err) {
    setMessage("analysisResult", err.message, true);
  }
};

byId("uploadKbBtn").onclick = async () => {
  try {
    const file = byId("kbFile").files[0];
    if (!file) throw new Error("Выберите файл базы знаний");
    const form = new FormData();
    form.append("file", file);
    const tool = byId("kbTool").value;
    const data = await fetch(`/api/rag/upload?tool=${encodeURIComponent(tool)}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${state.token}` },
      body: form,
    }).then((res) => res.json());
    if (data.detail) throw new Error(data.detail);
    setMessage("analysisResult", `В базу знаний добавлено чанков: ${data.chunks_indexed}`);
  } catch (err) {
    setMessage("analysisResult", err.message, true);
  }
};

byId("importJiraBtn").onclick = async () => {
  try {
    const data = await api("/api/jira/import");
    byId("jiraList").textContent = data.items.map((x) => `${x.id}: ${x.title} (${x.tool})`).join("\n");
  } catch (err) {
    byId("jiraList").textContent = err.message;
  }
};

byId("findCasesBtn").onclick = async () => {
  try {
    const data = await api("/api/rag/search", {
      method: "POST",
      body: JSON.stringify({ query: byId("problemTitle").value }),
    });
    byId("similarCases").textContent = data.items
      .map((x) => `${x.source_name} [${x.tool}] score=${x.score}`)
      .join("\n");
  } catch (err) {
    byId("similarCases").textContent = err.message;
  }
};

byId("extractIdeasBtn").onclick = async () => {
  try {
    const payload = {
      problem: byId("problemTitle").value,
      transcript: byId("transcriptText").value,
      context: byId("analysisContext").value,
    };
    const data = await api("/api/analysis/extract-ideas", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    byId("analysisResult").textContent = `${data.analysis}\n\nМетрики: ${data.metrics.elapsed_ms} ms, ${data.metrics.tokens_out} токенов, ${data.metrics.tokens_per_sec} ток/с`;
    byId("similarCases").textContent = (data.similar_cases || []).join("\n") || "Похожих кейсов не найдено";
    await loadMetrics();
  } catch (err) {
    setMessage("analysisResult", err.message, true);
  }
};

byId("createDocBtn").onclick = async () => {
  try {
    await api("/api/documents", {
      method: "POST",
      body: JSON.stringify({
        title: byId("docTitle").value,
        folder: byId("docFolder").value,
        content: byId("docEditor").value,
        tool: byId("docTool").value,
      }),
    });
    await loadDocs();
    setMessage("analysisResult", "Документ создан");
  } catch (err) {
    setMessage("analysisResult", err.message, true);
  }
};

byId("saveDocBtn").onclick = async () => {
  try {
    if (!state.selectedDocId) throw new Error("Выберите документ в списке");
    await api(`/api/documents/${state.selectedDocId}`, {
      method: "PUT",
      body: JSON.stringify({
        title: byId("docTitle").value,
        folder: byId("docFolder").value,
        content: byId("docEditor").value,
        tool: byId("docTool").value,
      }),
    });
    await loadDocs();
  } catch (err) {
    setMessage("analysisResult", err.message, true);
  }
};

byId("applyTemplateBtn").onclick = async () => {
  try {
    if (!state.selectedDocId) throw new Error("Сначала откройте документ");
    await api(`/api/documents/${state.selectedDocId}/apply-template`, {
      method: "POST",
      body: JSON.stringify({ template_name: byId("templateSelect").value }),
    });
    await loadDocs();
    const updated = state.docs.find((d) => d.id === state.selectedDocId);
    if (updated) byId("docEditor").value = updated.content;
  } catch (err) {
    setMessage("analysisResult", err.message, true);
  }
};

byId("sendPromptBtn").onclick = async () => {
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ prompt: byId("chatPrompt").value }),
    });
    byId("chatAnswer").textContent = data.answer;
    await loadMetrics();
  } catch (err) {
    byId("chatAnswer").textContent = err.message;
  }
};

byId("saveSettingsBtn").onclick = async () => {
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ model_mode: byId("modelModeSelect").value }),
    });
    setMessage("serverStatusMsg", `Режим сохранен: ${data.model_mode}`);
    await loadUser();
  } catch (err) {
    setMessage("serverStatusMsg", err.message, true);
  }
};

byId("checkServerBtn").onclick = async () => {
  try {
    const data = await api("/api/server/status");
    setMessage("serverStatusMsg", data.running ? "Сервер уже запущен" : "Сервер остановлен");
  } catch (err) {
    setMessage("serverStatusMsg", err.message, true);
  }
};

byId("startServerBtn").onclick = async () => {
  try {
    const data = await api("/api/server/start", { method: "POST", body: JSON.stringify({}) });
    setMessage("serverStatusMsg", data.message, !data.started);
  } catch (err) {
    setMessage("serverStatusMsg", err.message, true);
  }
};

(async () => {
  if (!state.token) return;
  try {
    await initializeApp();
  } catch {
    localStorage.removeItem("token");
  }
})();
