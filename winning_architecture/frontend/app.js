// NorthStar Chat - frontend
const $ = sel => document.querySelector(sel);
const messagesEl = $("#messages");
const form = $("#composer");
const qEl = $("#q");
const sendBtn = $("#send");
const samplesEl = $("#samples");
const schemaListEl = $("#schema-list");
const schemaSearch = $("#schema-search");
const statusText = $("#status-text");
const statusDot = document.querySelector(".status .dot");
const fileInput = $("#file-input");
const dropzone = $("#dropzone");
const clearBtn = $("#clear-chat");

// ---------- session memory ----------
const SESSION_KEY = "northstar.session_id";
let SESSION_ID = sessionStorage.getItem(SESSION_KEY);
if (!SESSION_ID) {
  SESSION_ID = (crypto && crypto.randomUUID) ? crypto.randomUUID()
    : ("s_" + Math.random().toString(36).slice(2) + Date.now().toString(36));
  sessionStorage.setItem(SESSION_KEY, SESSION_ID);
}

clearBtn?.addEventListener("click", async () => {
  await fetch(`/api/session/${encodeURIComponent(SESSION_ID)}/clear`, { method: "POST" });
  sessionStorage.removeItem(SESSION_KEY);
  SESSION_ID = (crypto && crypto.randomUUID) ? crypto.randomUUID()
    : ("s_" + Math.random().toString(36).slice(2) + Date.now().toString(36));
  sessionStorage.setItem(SESSION_KEY, SESSION_ID);
  messagesEl.innerHTML = `<div class="welcome"><h2>Memory cleared.</h2>
    <p>New session started. Upload a file or ask a question.</p></div>`;
  showToast("Chat memory cleared", "ok");
});

// ---------- bootstrap ----------
init();

async function init() {
  try {
    const h = await (await fetch("/healthz")).json();
    if (h.provider === "openai") {
      statusText.textContent = "OpenAI " + (h.model || "");
    } else if (h.provider === "anthropic") {
      statusText.textContent = "Claude " + (h.model || "");
    } else {
      statusText.textContent = "offline mode (no API key)";
      statusDot.classList.add("warn");
    }
  } catch (e) {
    statusText.textContent = "server unreachable";
    statusDot.classList.add("warn");
  }

  try {
    const samples = (await (await fetch("/api/sample-questions")).json()).questions;
    samples.forEach(q => {
      const li = document.createElement("li");
      li.textContent = q;
      li.onclick = () => { qEl.value = q; qEl.focus(); };
      samplesEl.appendChild(li);
    });
  } catch {}

  try {
    const tables = (await (await fetch("/api/schema")).json()).tables;
    window._tables = tables;
    renderSchemaList(tables);
    schemaSearch.addEventListener("input", () => {
      const q = schemaSearch.value.toLowerCase();
      renderSchemaList(tables.filter(t =>
        t.name.includes(q) || t.desc.toLowerCase().includes(q)));
    });
  } catch {}
}

function renderSchemaList(tables) {
  schemaListEl.innerHTML = "";
  tables.forEach(t => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${t.name}</strong><small>${escapeHtml(t.desc)}</small>`;
    schemaListEl.appendChild(li);
  });
}

// ---------- form ----------
form.addEventListener("submit", e => {
  e.preventDefault();
  const text = qEl.value.trim();
  if (!text) return;
  qEl.value = "";
  sendQuestion(text);
});

// ---------- file upload ----------
fileInput.addEventListener("change", e => {
  const f = e.target.files && e.target.files[0];
  if (f) uploadFile(f);
  fileInput.value = "";  // allow re-uploading same file
});

// drag-and-drop anywhere on the page
let dragDepth = 0;
window.addEventListener("dragenter", e => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth++;
  dropzone.classList.remove("hidden");
  dropzone.classList.add("active");
});
window.addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("dragleave", e => {
  if (!hasFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) {
    dropzone.classList.add("hidden");
    dropzone.classList.remove("active");
  }
});
window.addEventListener("drop", e => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  dropzone.classList.add("hidden");
  dropzone.classList.remove("active");
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) uploadFile(f);
});

function hasFiles(ev) {
  const t = ev.dataTransfer && ev.dataTransfer.types;
  return t && Array.from(t).indexOf("Files") !== -1;
}

async function uploadFile(file) {
  const allowed = [".txt", ".md", ".log", ".csv"];
  const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
  if (!allowed.includes(ext)) {
    showToast(`Unsupported file type: ${ext}. Use ${allowed.join(", ")}.`, "error");
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showToast("File too large (max 5 MB).", "error");
    return;
  }
  const w = document.querySelector(".welcome");
  if (w) w.remove();

  const toast = showToast(`Uploading ${file.name}...`, "loading");
  try {
    const fd = new FormData();
    fd.append("file", file);
    const url = "/api/upload?session_id=" + encodeURIComponent(SESSION_ID);
    const res = await fetch(url, { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const info = await res.json();
    toast.remove();
    renderUploadCard(info);
    showToast(
      info.duplicate
        ? `Already indexed: ${info.file_name} (${info.chunk_count} chunks)`
        : `Indexed ${info.file_name}: ${info.chunk_count} chunks, ${info.word_count} words`,
      "ok"
    );
    // Pre-fill the prompt to ask about the file
    qEl.value = `What does ${info.file_name} say about `;
    qEl.focus();
  } catch (e) {
    toast.remove();
    showToast(`Upload failed: ${e.message}`, "error");
    renderUploadCard({ file_name: file.name, error: e.message });
  }
}

function renderUploadCard(info) {
  const card = document.createElement("div");
  card.className = "upload-card msg" + (info.error ? " error" : "");
  if (info.error) {
    card.innerHTML = `
      <h4>Upload failed</h4>
      <div class="meta"><span><strong>${escapeHtml(info.file_name)}</strong></span></div>
      <div class="summary">${escapeHtml(info.error)}</div>`;
  } else {
    const kwHtml = (info.keywords || "")
      .split(",").filter(Boolean).slice(0, 8)
      .map(k => `<code>${escapeHtml(k)}</code>`).join(" ");
    card.innerHTML = `
      <h4>${info.duplicate ? "Already indexed" : "Document indexed"}</h4>
      <div class="meta">
        <span><strong>${escapeHtml(info.file_name)}</strong></span>
        <span>category <strong>${escapeHtml(info.document_category || "Other")}</strong></span>
        <span>chunks <strong>${info.chunk_count}</strong></span>
        <span>words <strong>${info.word_count}</strong></span>
        <span>chars <strong>${info.char_count}</strong></span>
        <span>extract_id <strong>${info.extract_id}</strong></span>
      </div>
      <div class="summary">${escapeHtml(info.summary || "")}</div>
      <div class="keywords">keywords: ${kwHtml || "(none)"}</div>`;
  }
  messagesEl.appendChild(card);
  scrollBottom();
}

function showToast(text, kind) {
  const t = document.createElement("div");
  t.className = "toast " + (kind === "loading" ? "" : kind);
  t.innerHTML = (kind === "loading" ? `<span class="spin"></span>` : "") +
                `<span>${escapeHtml(text)}</span>`;
  document.body.appendChild(t);
  if (kind !== "loading") setTimeout(() => t.remove(), 4000);
  return t;
}

function sendQuestion(text) {
  // remove welcome
  const w = document.querySelector(".welcome");
  if (w) w.remove();
  appendUserMsg(text);
  const botEl = appendBotShell();
  streamAnswer(text, botEl);
}

function appendUserMsg(text) {
  const m = document.createElement("div");
  m.className = "msg user";
  m.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  messagesEl.appendChild(m);
  scrollBottom();
}

function appendBotShell() {
  const m = document.createElement("div");
  m.className = "msg bot";
  m.innerHTML = `
    <div class="bubble">
      <div class="answer"><span class="thinking">routing your question</span></div>
      <div class="trace"></div>
      <div class="block sql-block" hidden><h4>SQL executed</h4><pre class="code sql-code"></pre></div>
      <div class="block rows-block" hidden><h4>Result rows</h4><div class="table-wrap"></div></div>
      <div class="block cites-block" hidden><h4>Cited documents</h4><div class="cites"></div></div>
    </div>`;
  messagesEl.appendChild(m);
  scrollBottom();
  return m;
}

// ---------- streaming via SSE ----------
function streamAnswer(question, botEl) {
  sendBtn.disabled = true;
  const url = "/api/chat/stream?question=" + encodeURIComponent(question)
            + "&session_id=" + encodeURIComponent(SESSION_ID);
  const es = new EventSource(url);
  const traceEl = botEl.querySelector(".trace");
  const answerEl = botEl.querySelector(".answer");

  es.addEventListener("trace", e => {
    const ev = JSON.parse(e.data);
    upsertTraceStep(traceEl, ev);
    if (ev.stage === "summarizer" && ev.status === "start") {
      answerEl.innerHTML = '<span class="thinking">composing the answer</span>';
    } else if (["sql_generate","schema_rag","executor","validator"].includes(ev.stage)
               && ev.status === "start") {
      answerEl.innerHTML = '<span class="thinking">' + ev.stage.replace(/_/g, " ") + '</span>';
    }
  });

  es.addEventListener("final", e => {
    const data = JSON.parse(e.data);
    answerEl.innerHTML = formatAnswer(data.answer);
    if (data.sql) {
      botEl.querySelector(".sql-block").hidden = false;
      botEl.querySelector(".sql-code").textContent = data.sql;
    }
    if (data.rows && data.rows.length) {
      botEl.querySelector(".rows-block").hidden = false;
      renderTable(botEl.querySelector(".table-wrap"), data.columns, data.rows);
    }
    if (data.citations && data.citations.length) {
      botEl.querySelector(".cites-block").hidden = false;
      renderCites(botEl.querySelector(".cites"), data.citations);
    }
  });

  es.addEventListener("done", () => {
    es.close();
    sendBtn.disabled = false;
    qEl.focus();
    scrollBottom();
  });

  es.onerror = () => {
    es.close();
    answerEl.textContent = "(connection error - is the server running?)";
    sendBtn.disabled = false;
  };
}

function upsertTraceStep(traceEl, ev) {
  const id = "step-" + ev.stage;
  let chip = traceEl.querySelector("[data-stage='" + ev.stage + "']");
  if (!chip) {
    chip = document.createElement("span");
    chip.className = "trace-step";
    chip.setAttribute("data-stage", ev.stage);
    traceEl.appendChild(chip);
  }
  chip.classList.remove("start", "ok", "warn", "error");
  chip.classList.add(ev.status);
  const icon = { start: "...", ok: "OK", warn: "!", error: "X" }[ev.status] || "";
  chip.innerHTML = `<span class="icon">${icon}</span> ${ev.stage.replace(/_/g, " ")}` +
                   (ev.message ? `: ${escapeHtml(ev.message).slice(0, 120)}` : "");
}

function formatAnswer(text) {
  if (!text) return "(no answer)";
  // mild markdown: paragraphs + bold
  const safe = escapeHtml(text);
  return safe
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n\n+/g, "</p><p>")
    .replace(/^/, "<p>") + "</p>";
}

function renderTable(host, cols, rows) {
  const t = document.createElement("table");
  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  cols.forEach(c => {
    const th = document.createElement("th"); th.textContent = c; trh.appendChild(th);
  });
  thead.appendChild(trh); t.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.slice(0, 100).forEach(r => {
    const tr = document.createElement("tr");
    cols.forEach(c => {
      const td = document.createElement("td");
      const v = r[c];
      td.textContent = v === null || v === undefined ? "" : String(v);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  t.appendChild(tbody);
  host.innerHTML = "";
  host.appendChild(t);
  if (rows.length > 100) {
    const more = document.createElement("div");
    more.style.padding = "6px 10px";
    more.style.color = "var(--text-dim)";
    more.style.fontSize = "11.5px";
    more.textContent = `... showing first 100 of ${rows.length} rows`;
    host.appendChild(more);
  }
}

function renderCites(host, cites) {
  host.innerHTML = "";
  cites.slice(0, 4).forEach(c => {
    const div = document.createElement("div");
    div.className = "cite";
    div.innerHTML = `<div class="file">${escapeHtml(c.file_name)} ` +
                    `<span style="color: var(--text-dim); font-weight: normal;">` +
                    `(${escapeHtml(c.document_category || "")})</span></div>` +
                    `<div class="snippet">${escapeHtml((c.chunk_text || "").slice(0, 280))}...</div>`;
    host.appendChild(div);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;"
  }[m]));
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
