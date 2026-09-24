const $ = (id) => document.getElementById(id);
const wsUrl = (p) => (location.protocol === "https:" ? "wss://" : "ws://") + location.host + p;
const sessions = new Map();
let config = { engines: [] };

$("token").value = localStorage.getItem("transcriba.token") || "";
$("token").onchange = () => localStorage.setItem("transcriba.token", $("token").value);
const headers = () => ({ "Content-Type": "application/json", "X-Admin-Token": $("token").value });

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: headers(), body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; } throw new Error(typeof d === "string" ? d : JSON.stringify(d)); }
  return r.json();
}

fetch("/api/config").then((r) => r.json()).then((c) => {
  config = c;
  $("engine").innerHTML = c.engines.map((e) => `<option ${e === c.defaults.engine ? "selected" : ""}>${e}</option>`).join("");
  if (!c.auth_required) { $("warn").style.display = ""; $("warn").textContent = "server.admin_token está vacío: cualquiera en la red puede crear/parar sesiones e inyectar audio. Configurarlo antes del evento."; }
  const f = $("form").elements;
  f.namedItem("source_language").value = c.defaults.source_language || "auto";
  f.namedItem("target_languages").value = (c.defaults.target_languages || ["es"]).join(",");
});

$("form").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    id: f.get("id"), name: f.get("name"), source: f.get("source"), engine: f.get("engine"),
    source_language: ["", "auto"].includes(f.get("source_language").trim()) ? null : f.get("source_language").trim(),
    target_languages: f.get("target_languages").split(",").map((s) => s.trim()).filter(Boolean),
    glossary: (f.get("glossary") || "").split(",").map((s) => s.trim()).filter(Boolean),
    loop: f.get("loop") === "on", start: true,
  };
  $("form-msg").textContent = "creando…";
  try { await api("POST", "/api/sessions", body); $("form-msg").textContent = "sesión creada"; e.target.elements.namedItem("id").value = ""; }
  catch (err) { $("form-msg").textContent = "error: " + err.message; }
};

function level(db) { return Math.max(0, Math.min(100, ((db + 60) / 60) * 100)); }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function fmt(s) { s = Math.max(0, s || 0); const m = Math.floor(s / 60), x = Math.floor(s % 60); return `${m}:${String(x).padStart(2, "0")}`; }

function render() {
  const root = $("sessions");
  const list = [...sessions.values()].sort((a, b) => a.id.localeCompare(b.id));
  for (const s of list) {
    let card = document.getElementById("s-" + s.id);
    if (!card) { card = document.createElement("div"); card.className = "card"; card.id = "s-" + s.id; root.appendChild(card); }
    const id = encodeURIComponent(s.id);
    const ago = s.last_caption_ts ? Math.round(Date.now() / 1000 - s.last_caption_ts) + "s" : "—";
    card.innerHTML = `
      <h2><span class="dot ${s.state}"></span> ${esc(s.name)} <span class="chip">${esc(s.id)}</span></h2>
      <div class="meter"><i style="width:${level(s.level_dbfs)}%"></i></div>
      <div class="kv">
        <span>estado</span><b>${s.state}${s.error ? " · " + esc(s.error) : ""}</b>
        <span>motor</span><b>${esc(s.engine)} · ${esc(s.source_language || "auto")} → ${esc((s.target_languages || []).join(","))}</b>
        <span>fuente</span><b>${esc(s.source)}${s.source === "browser" ? (s.ingest_connected ? " · 🎙 conectado" : " · sin ingesta") : ""}</b>
        <span>audio</span><b>${fmt(s.stream_time)} (${s.audio_minutes} min) · ${s.level_dbfs.toFixed(0)} dBFS</b>
        <span>subtítulos</span><b>${s.captions} · último hace ${ago} · ${s.viewers} viendo</b>
      </div>
      <div class="preview">${esc(s.last_original)}<br><span class="tr">${esc(s.last_translation)}</span></div>
      <div class="actions">
        ${s.state === "running" || s.state === "starting" ? `<button class="btn small" data-act="stop">■ Detener</button>` : `<button class="btn small primary" data-act="start">▶ Iniciar</button>`}
        <button class="btn small danger" data-act="delete">✕ Eliminar</button>
        <a class="btn small" href="/view/${id}?lang=both" target="_blank">Ver</a>
        <a class="btn small" href="/view/${id}?lang=${encodeURIComponent((s.target_languages || ["es"])[0])}&overlay=1&lines=2" target="_blank">Overlay OBS</a>
        ${s.source === "browser" ? `<a class="btn small" href="/ingest/${id}?token=${encodeURIComponent($("token").value)}" target="_blank">🎙 Ingesta</a>` : ""}
        <a class="btn small" href="/api/sessions/${id}/qr.svg?lang=${encodeURIComponent((s.target_languages || ["es"])[0])}" target="_blank">QR</a>
        <a class="btn small" href="/api/sessions/${id}/transcript.srt?lang=both&download=1">SRT</a>
        <a class="btn small" href="/api/sessions/${id}/transcript.txt?lang=orig&download=1">TXT</a>
      </div>
      <details><summary>detalles del motor</summary><pre class="info">${esc(JSON.stringify(s.engine_info, null, 1))}</pre></details>`;
    card.querySelectorAll("button[data-act]").forEach((b) => (b.onclick = () => act(s.id, b.dataset.act)));
  }
  for (const card of [...root.children]) if (!sessions.has(card.id.slice(2))) card.remove();
}

async function act(id, action) {
  try {
    if (action === "delete") { if (!confirm(`¿Eliminar la sesión ${id}?`)) return; await api("DELETE", `/api/sessions/${encodeURIComponent(id)}`); sessions.delete(id); render(); }
    else await api("POST", `/api/sessions/${encodeURIComponent(id)}/${action}`);
  } catch (err) { alert(err.message); }
}

let backoff = 1000;
function connect() {
  const ws = new WebSocket(wsUrl("/ws/status"));
  ws.onopen = () => { backoff = 1000; $("conn").className = "dot running"; };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "sessions") { sessions.clear(); for (const s of m.data) sessions.set(s.id, s); }
    else if (m.type === "status") sessions.set(m.data.id, m.data);
    else if (m.type === "removed") sessions.delete(m.data.id);
    render();
  };
  ws.onclose = () => { $("conn").className = "dot error"; setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 10000); };
  ws.onerror = () => ws.close();
}
connect();
