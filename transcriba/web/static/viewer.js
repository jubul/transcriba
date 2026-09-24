const LANG_NAMES = { es: "Español", en: "English", pt: "Português", fr: "Français", de: "Deutsch", it: "Italiano", ja: "日本語", zh: "中文", ko: "한국어", ru: "Русский", ca: "Català", eu: "Euskara", gl: "Galego" };
const langName = (c) => (c ? LANG_NAMES[c.split("-")[0]] || c.toUpperCase() : "Original");
const wsUrl = (p) => (location.protocol === "https:" ? "wss://" : "ws://") + location.host + p;
const $ = (id) => document.getElementById(id);

const sid = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop());
const params = new URLSearchParams(location.search);
const stored = JSON.parse(localStorage.getItem("transcriba.viewer." + sid) || "{}");
const state = {
  lang: params.get("lang") || stored.lang || "both",
  size: parseFloat(params.get("size") || stored.size || "1"),
  lines: parseInt(params.get("lines") || stored.lines || "2", 10),
  overlay: params.get("overlay") === "1",
  history: params.get("history") === "1",
  light: (params.get("theme") || stored.theme) === "light",
  captions: new Map(),
  status: null,
  maxCaptions: 400,
};

function persist() {
  localStorage.setItem("transcriba.viewer." + sid, JSON.stringify({ lang: state.lang, size: state.size, lines: state.lines, theme: state.light ? "light" : "dark" }));
  const p = new URLSearchParams();
  p.set("lang", state.lang);
  if (state.size !== 1) p.set("size", state.size);
  if (state.lines !== 2) p.set("lines", state.lines);
  if (state.overlay) p.set("overlay", "1");
  if (state.history) p.set("history", "1");
  if (state.light) p.set("theme", "light");
  history.replaceState(null, "", location.pathname + "?" + p.toString());
  $("lnk-srt").href = `/api/sessions/${encodeURIComponent(sid)}/transcript.srt?lang=${encodeURIComponent(state.lang === "orig" ? "orig" : state.lang)}&download=1`;
  $("qr").src = `/api/sessions/${encodeURIComponent(sid)}/qr.svg?lang=${encodeURIComponent(state.lang)}`;
}

function applyChrome() {
  document.body.classList.toggle("overlay", state.overlay);
  document.body.classList.toggle("history", state.history);
  document.body.classList.toggle("light", state.light);
  document.body.classList.toggle("mode-orig", state.lang === "orig");
  document.documentElement.style.setProperty("--size", state.size);
  $("sel-size").value = state.size; $("size-val").textContent = state.size.toFixed(1) + "×";
  $("sel-lines").value = state.lines;
  $("sel-light").checked = state.light; $("sel-history").checked = state.history; $("sel-overlay").checked = state.overlay;
}

function sourceLang() { return state.status && state.status.source_language; }
function targetLangs() { return (state.status && state.status.target_languages) || []; }

function fillLangOptions() {
  const sel = $("sel-lang");
  const src = sourceLang();
  const opts = [{ v: "orig", t: src ? `${langName(src)} (original)` : "Original" }];
  for (const t of targetLangs()) if (t !== src) opts.push({ v: t, t: langName(t) });
  if (opts.length > 1) opts.push({ v: "both", t: "Ambos idiomas" });
  if (!opts.some((o) => o.v === state.lang)) opts.push({ v: state.lang, t: langName(state.lang) });
  sel.innerHTML = opts.map((o) => `<option value="${o.v}">${o.t}</option>`).join("");
  sel.value = state.lang;
}

function sorted() { return [...state.captions.values()].sort((a, b) => a.seq - b.seq); }

function transOf(c, lang) {
  if (lang === "orig") return c.original;
  if (c.language && lang && c.language.split("-")[0] === lang.split("-")[0]) return c.original;
  return c.translations ? c.translations[lang] : undefined;
}

function render() {
  const stage = $("stage");
  const caps = sorted();
  if (state.history) return renderHistory(stage, caps);
  const finals = caps.filter((c) => c.status !== "partial");
  const partial = caps.filter((c) => c.status === "partial").pop();
  const lanes = [];
  const showOrig = state.lang === "orig" || state.lang === "both";
  const trLang = state.lang === "both" ? targetLangs().find((t) => t !== sourceLang()) : state.lang !== "orig" ? state.lang : null;
  if (showOrig) {
    const items = finals.slice(-state.lines).map((c, i, a) => ({ text: c.original, cls: i < a.length - 1 ? "old" : "" }));
    if (partial && partial.original) items.push({ text: partial.original, cls: "partial" });
    lanes.push({ cls: "orig", items: items.slice(-(state.lines + (partial ? 1 : 0))) });
  }
  if (trLang) {
    const items = [];
    for (const c of finals) {
      const t = transOf(c, trLang);
      if (t) items.push({ text: t, cls: "" });
      else if (c.status === "final") items.push({ text: "…", cls: "pending" });
    }
    const shown = items.slice(-state.lines).map((it, i, a) => ({ ...it, cls: it.cls || (i < a.length - 1 ? "old" : "") }));
    lanes.push({ cls: "trans", items: shown });
  }
  stage.innerHTML = lanes.map((l) => `<div class="lane ${l.cls}">${l.items.map((i) => `<div class="cap ${i.cls}">${escapeHtml(i.text)}</div>`).join("")}</div>`).join("");
}

function renderHistory(stage, caps) {
  const trLang = state.lang === "orig" ? null : state.lang === "both" ? targetLangs().find((t) => t !== sourceLang()) : state.lang;
  const rows = caps.filter((c) => c.status !== "partial").map((c) => {
    const t = trLang ? transOf(c, trLang) : null;
    const showOrig = state.lang !== trLang || !t;
    return `<div class="t">${fmt(c.t_start)}</div><div>${showOrig ? `<div class="o">${escapeHtml(c.original)}</div>` : ""}${t && trLang ? `<div class="tr">${escapeHtml(t)}</div>` : ""}</div>`;
  });
  const atBottom = stage.scrollTop + stage.clientHeight >= stage.scrollHeight - 40;
  stage.innerHTML = `<div class="hist">${rows.join("")}</div>`;
  if (atBottom) stage.scrollTop = stage.scrollHeight;
}

function fmt(s) { s = Math.max(0, s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60); return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + String(x).padStart(2, "0"); }
function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function upsert(c) {
  state.captions.set(c.id, c);
  if (state.captions.size > state.maxCaptions) {
    const oldest = sorted()[0];
    if (oldest) state.captions.delete(oldest.id);
  }
}

function setStatus(s) {
  state.status = s;
  $("name").textContent = s.name || sid;
  document.title = (s.name || sid) + " · subtítulos";
  fillLangOptions();
  $("btn-audio").style.display = s.engine === "gemini-live-translate" ? "" : "none";
  $("status").textContent = `${s.state} · ${s.engine} · ${s.captions} subtítulos`;
}

let backoff = 1000;
function connect() {
  const ws = new WebSocket(wsUrl(`/ws/captions/${encodeURIComponent(sid)}`));
  ws.onopen = () => { backoff = 1000; };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "history") { state.captions.clear(); for (const c of m.data) upsert(c); if (m.status) setStatus(m.status); }
    else if (m.type === "caption") upsert(m.data);
    else if (m.type === "status") setStatus(m.data);
    render();
  };
  ws.onclose = () => { $("status").textContent = "reconectando…"; setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 10000); };
  ws.onerror = () => ws.close();
}

let audioCtx = null, audioWs = null, nextTime = 0;
function toggleAudio() {
  if (audioWs) { audioWs.close(); audioWs = null; audioCtx && audioCtx.close(); audioCtx = null; $("btn-audio").textContent = "🔊 Escuchar traducción"; return; }
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
  nextTime = 0;
  audioWs = new WebSocket(wsUrl(`/ws/audio/${encodeURIComponent(sid)}`));
  audioWs.binaryType = "arraybuffer";
  audioWs.onmessage = (e) => {
    const bytes = e.data.byteLength - (e.data.byteLength % 2);
    const i16 = new Int16Array(e.data.slice(0, bytes));
    if (!i16.length) return;
    const buf = audioCtx.createBuffer(1, i16.length, 24000);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < i16.length; i++) ch[i] = i16[i] / 32768;
    const src = audioCtx.createBufferSource();
    src.buffer = buf; src.connect(audioCtx.destination);
    const t = Math.max(audioCtx.currentTime + 0.05, nextTime);
    src.start(t); nextTime = t + buf.duration;
  };
  audioWs.onclose = () => { if (audioWs) { audioWs = null; $("btn-audio").textContent = "🔊 Escuchar traducción"; } };
  $("btn-audio").textContent = "🔇 Detener audio";
}

$("gear").onclick = () => $("panel").classList.toggle("open");
document.body.addEventListener("click", (e) => { if (!$("panel").contains(e.target) && e.target !== $("gear")) { if (window.matchMedia("(hover: none)").matches) document.body.classList.toggle("show-bar"); } });
$("sel-lang").onchange = (e) => { state.lang = e.target.value; persist(); applyChrome(); render(); };
$("sel-size").oninput = (e) => { state.size = parseFloat(e.target.value); persist(); applyChrome(); };
$("sel-lines").onchange = (e) => { state.lines = Math.max(1, parseInt(e.target.value || "2", 10)); persist(); render(); };
$("sel-light").onchange = (e) => { state.light = e.target.checked; persist(); applyChrome(); };
$("sel-history").onchange = (e) => { state.history = e.target.checked; persist(); applyChrome(); render(); };
$("sel-overlay").onchange = (e) => { state.overlay = e.target.checked; persist(); applyChrome(); };
$("btn-copy").onclick = () => navigator.clipboard.writeText(location.href).then(() => { $("btn-copy").textContent = "¡Copiado!"; setTimeout(() => ($("btn-copy").textContent = "Copiar enlace"), 1500); });
$("btn-audio").onclick = toggleAudio;
if (navigator.wakeLock) navigator.wakeLock.request("screen").catch(() => {});

persist(); applyChrome(); fillLangOptions(); connect();
