const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");
const modelSel = $("#model");
const statusEl = $("#status");
const ragEl = $("#rag");
const stdEl = $("#standard-only");
const formEl = $("#form");
const inputEl = $("#input");
const citeListEl = $("#cite-list");
const citeBox = $("#citations");

const history = [];

const FORMAT_ABBR = {
  standard: "STD",
  pioneer: "PIO",
  modern: "MOD",
  legacy: "LEG",
  vintage: "VIN",
  commander: "CMD",
  pauper: "PAU",
};

async function refreshModels() {
  try {
    const r = await fetch("/api/models");
    const j = await r.json();
    modelSel.innerHTML = "";
    if (!j.models || !j.models.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "(no Ollama models found - run `ollama pull llama3.1:8b`)";
      modelSel.append(o);
      return;
    }
    for (const name of j.models) {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = name;
      if (name === j.default) o.selected = true;
      modelSel.append(o);
    }
  } catch (e) {
    statusEl.textContent = "Backend offline";
  }
}

async function refreshHealth() {
  try {
    const r = await fetch("/api/health");
    const j = await r.json();
    statusEl.textContent = j.ollama ? "Ollama: ready" : "Ollama: starting...";
    statusEl.className = "status " + (j.ollama ? "ok" : "warn");
  } catch {
    statusEl.textContent = "Backend offline";
    statusEl.className = "status err";
  }
}

function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text || "";
  messagesEl.append(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function formatPill(fmt, status) {
  const span = document.createElement("span");
  span.className = "fmt-pill fmt-" + status;
  span.textContent = FORMAT_ABBR[fmt] || fmt.slice(0, 3).toUpperCase();
  span.title = fmt + ": " + status;
  return span;
}

function renderCitations(items) {
  citeListEl.innerHTML = "";
  if (!items || !items.length) {
    citeBox.hidden = true;
    return;
  }
  citeBox.hidden = false;
  for (const c of items) {
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = "badge " + c.source.toLowerCase();
    badge.textContent = c.source;
    li.append(badge, " ", c.label || "");
    if (c.source === "CARD" && c.set) {
      const setSpan = document.createElement("span");
      setSpan.className = "set";
      setSpan.textContent = " (" + c.set + ")";
      li.append(setSpan);
    }
    if (c.source === "CARD" && c.formats) {
      const pills = document.createElement("div");
      pills.className = "pills";
      for (const [fmt, status] of Object.entries(c.formats)) {
        if (status === "not_legal") continue; // only show formats that designate something
        pills.append(formatPill(fmt, status));
      }
      if (pills.childElementCount) li.append(pills);
      // Always show an explicit Standard pill so users see legal/not-legal at a glance.
      const stdStatus = c.formats.standard || (c.standard_legal ? "legal" : "not_legal");
      const stdRow = document.createElement("div");
      stdRow.className = "std-row";
      stdRow.append(
        document.createTextNode("Standard: "),
        formatPill("standard", stdStatus),
      );
      li.append(stdRow);
    }
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = String(c.score);
    li.append(" ", score);
    citeListEl.append(li);
  }
}

async function send(text) {
  history.push({ role: "user", content: text });
  addBubble("user", text);
  const out = addBubble("assistant", "");
  const model = modelSel.value;
  if (!model) {
    out.textContent = "No model selected. Run `ollama pull llama3.1:8b` first.";
    return;
  }

  let res;
  try {
    res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: history,
        use_rag: ragEl.checked,
        standard_only: stdEl.checked,
      }),
    });
  } catch (e) {
    out.textContent = "Network error: " + e.message;
    return;
  }
  if (!res.ok || !res.body) {
    out.textContent = "Request failed: " + res.status;
    return;
  }

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let acc = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 2);
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let obj;
      try {
        obj = JSON.parse(payload);
      } catch {
        continue;
      }
      if (obj.type === "token") {
        acc += obj.data;
        out.textContent = acc;
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } else if (obj.type === "citations") {
        renderCitations(obj.data);
      } else if (obj.type === "error") {
        out.textContent = (acc ? acc + "\n\n" : "") + "[error] " + obj.data;
      } else if (obj.type === "done") {
        history.push({ role: "assistant", content: acc });
      }
    }
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const t = inputEl.value.trim();
  if (!t) return;
  inputEl.value = "";
  send(t).catch((err) => addBubble("assistant", "Error: " + err.message));
});
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

refreshHealth();
refreshModels();
setInterval(refreshHealth, 5000);
setInterval(refreshModels, 15000);
