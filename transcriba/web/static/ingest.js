const $ = (id) => document.getElementById(id);
const wsUrl = (p) => (location.protocol === "https:" ? "wss://" : "ws://") + location.host + p;
const sid = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop());
$("sid").textContent = sid;
$("view").href = `/view/${encodeURIComponent(sid)}?lang=both`;
const urlToken = new URLSearchParams(location.search).get("token");
$("token").value = urlToken || localStorage.getItem("transcriba.token") || "";
if (urlToken) localStorage.setItem("transcriba.token", urlToken);
$("token").onchange = () => localStorage.setItem("transcriba.token", $("token").value);
if (!window.isSecureContext) $("https-warn").style.display = "";

let ws = null, ctx = null, node = null, stream = null, running = false, sentBytes = 0, pingTimer = null, lastError = "";
const log = (m) => { $("log").textContent = `${new Date().toLocaleTimeString()} ${m}\n` + $("log").textContent.slice(0, 4000); };
const setConn = (cls, text) => { $("conn").className = "dot " + cls; $("conn-text").textContent = text; };
const FATAL_CODES = [4400, 4401, 4404, 4409];

async function listDevices() {
  try { const tmp = await navigator.mediaDevices.getUserMedia({ audio: true }); tmp.getTracks().forEach((t) => t.stop()); } catch (e) { log("sin permiso de micrófono: " + e.message); }
  const devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  $("devices").innerHTML = devs.map((d) => `<option value="${d.deviceId}">${d.label || d.deviceId.slice(0, 8)}</option>`).join("");
}
navigator.mediaDevices && listDevices();

function connectWs() {
  if (!$("token").value) log("atención: el campo 'Admin token' está vacío; si el servidor tiene token configurado va a rechazar la conexión");
  setConn("starting", "conectando…");
  lastError = "";
  ws = new WebSocket(wsUrl(`/ws/ingest/${encodeURIComponent(sid)}?token=${encodeURIComponent($("token").value)}`));
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { ws.send(JSON.stringify({ type: "hello", sampleRate: 16000 })); setConn("running", "conectado · enviando audio"); log("websocket conectado"); pingTimer = setInterval(() => ws && ws.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })), 5000); };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "pong") $("srv").textContent = `recibió ${(m.received / 32000).toFixed(0)} s · stream ${m.stream_time.toFixed(0)} s`;
    else if (m.type === "ready") log(`servidor listo (sesión ${m.session})`);
    else if (m.type === "error") { lastError = m.message; log("error del servidor: " + m.message); }
  };
  ws.onclose = (e) => {
    clearInterval(pingTimer);
    const reason = lastError || e.reason || (e.code === 1006 ? "el servidor cerró sin aceptar la conexión (¿token? ¿servidor caído?)" : `código ${e.code}`);
    setConn("error", "desconectado: " + reason);
    if (running && !FATAL_CODES.includes(e.code)) { log(`desconectado (${e.code}); reintento en 1 s`); setTimeout(connectWs, 1000); }
    else if (running) { log("no se reintenta: " + reason); stop(); }
  };
  ws.onerror = () => { log("error de websocket"); };
}

async function start() {
  try {
    if ($("system").checked) {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
      stream.getVideoTracks().forEach((t) => t.stop());
      if (!stream.getAudioTracks().length) throw new Error("la pestaña/pantalla compartida no incluye audio; marcá 'compartir audio'");
    } else {
      const deviceId = $("devices").value;
      stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: deviceId ? { exact: deviceId } : undefined, channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    }
    log(`micrófono OK: ${stream.getAudioTracks()[0].label || "(sin nombre)"}`);
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") await ctx.resume();
    await ctx.audioWorklet.addModule("/static/pcm-worklet.js");
    const src = ctx.createMediaStreamSource(stream);
    node = new AudioWorkletNode(ctx, "pcm16-downsampler", { processorOptions: { targetRate: 16000 } });
    node.port.onmessage = (e) => {
      if (e.data.type === "pcm") { if (ws && ws.readyState === 1) { ws.send(e.data.buffer); sentBytes += e.data.buffer.byteLength; $("sent").textContent = `${(sentBytes / 32000).toFixed(0)} s`; } }
      else if (e.data.type === "level") $("meter").style.width = Math.max(0, Math.min(100, ((e.data.dbfs + 60) / 60) * 100)) + "%";
    };
    const sink = ctx.createGain(); sink.gain.value = 0;
    src.connect(node); node.connect(sink); sink.connect(ctx.destination);
    running = true; sentBytes = 0;
    $("start").disabled = true; $("stop").disabled = false;
    log(`capturando a ${ctx.sampleRate} Hz → 16000 Hz`);
    connectWs();
  } catch (e) { log("no se pudo iniciar: " + e.name + " · " + e.message + (e.name === "NotAllowedError" ? " (permitir el micrófono en el candado de la barra de direcciones)" : "")); setConn("error", "sin micrófono"); stop(); }
}

function stop() {
  running = false;
  if ($("conn").className.includes("running")) setConn("", "desconectado");
  if (ws) { try { ws.close(); } catch (_) {} ws = null; }
  if (node) { node.disconnect(); node = null; }
  if (ctx) { ctx.close(); ctx = null; }
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  $("start").disabled = false; $("stop").disabled = true; $("meter").style.width = "0%";
}
$("start").onclick = start;
$("stop").onclick = stop;
window.addEventListener("beforeunload", (e) => { if (running) { e.preventDefault(); e.returnValue = ""; } });
