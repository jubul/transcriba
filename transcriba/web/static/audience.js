const LANG_NAMES = { es: "Español", en: "English", pt: "Português", fr: "Français", de: "Deutsch", it: "Italiano", ja: "日本語", zh: "中文", ko: "한국어", ru: "Русский", ca: "Català", eu: "Euskara", gl: "Galego" };
const langName = (c) => (c ? LANG_NAMES[c.split("-")[0]] || c.toUpperCase() : "Original");
const wsUrl = (p) => (location.protocol === "https:" ? "wss://" : "ws://") + location.host + p;

const sessions = new Map();
const $ = (id) => document.getElementById(id);

fetch("/api/config").then((r) => r.json()).then((c) => { $("title").textContent = c.title || "Subtítulos en vivo"; document.title = c.title || document.title; }).catch(() => {});

function render() {
  const list = [...sessions.values()].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  $("empty").style.display = list.length ? "none" : "block";
  const root = $("sessions");
  root.innerHTML = "";
  for (const s of list) {
    const card = document.createElement("div");
    card.className = "card";
    const live = s.state === "running";
    const src = s.source_language;
    const targets = (s.target_languages || []).filter((t) => t !== src);
    const langs = [];
    langs.push({ code: "orig", label: src ? `${langName(src)} (original)` : "Original" });
    for (const t of targets) langs.push({ code: t, label: langName(t) });
    if (targets.length) langs.push({ code: "both", label: "Ambos idiomas" });
    card.innerHTML = `
      <h2><span class="dot ${s.state}"></span> ${escapeHtml(s.name || s.id)}</h2>
      <div class="muted">${live ? "En vivo" : s.state === "error" ? "Con problemas" : "Sin señal por ahora"} · ${s.captions} subtítulos</div>
      <div class="preview">${escapeHtml(s.last_original || "")}${s.last_translation ? `<br><span class="tr">${escapeHtml(s.last_translation)}</span>` : ""}</div>
      <div class="langs">${langs.map((l) => `<a class="btn ${l.code !== "orig" && l.code !== "both" ? "primary" : ""}" href="/view/${encodeURIComponent(s.id)}?lang=${encodeURIComponent(l.code)}">${escapeHtml(l.label)}</a>`).join("")}</div>`;
    root.appendChild(card);
  }
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

let backoff = 1000;
function connect() {
  const ws = new WebSocket(wsUrl("/ws/status"));
  ws.onopen = () => { backoff = 1000; $("conn").className = "dot running"; $("conn-text").textContent = "en vivo"; };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "sessions") { sessions.clear(); for (const s of m.data) sessions.set(s.id, s); }
    else if (m.type === "status") sessions.set(m.data.id, m.data);
    else if (m.type === "removed") sessions.delete(m.data.id);
    render();
  };
  ws.onclose = () => { $("conn").className = "dot error"; $("conn-text").textContent = "reconectando…"; setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 10000); };
  ws.onerror = () => ws.close();
}
fetch("/api/sessions").then((r) => r.json()).then((l) => { for (const s of l) sessions.set(s.id, s); render(); }).catch(() => {});
connect();
