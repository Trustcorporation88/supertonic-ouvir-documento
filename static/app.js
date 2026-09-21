/* SuperTonic — lógica da interface (jobs progressivos, texto sincronizado, histórico) */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- Tema
  const THEME_KEY = "supertonic.theme";
  const root = document.documentElement;
  const applyTheme = (t) => (t === "light" ? root.setAttribute("data-theme", "light") : root.removeAttribute("data-theme"));
  applyTheme(localStorage.getItem(THEME_KEY) || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  $("theme").onclick = () => {
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next);
  };

  // ---------------------------------------------------------------- Vozes
  const VOICE_LABELS = {
    F1: "Mulher 1", F2: "Mulher 2", F3: "Mulher 3", F4: "Mulher 4", F5: "Mulher 5",
    M1: "Homem 1", M2: "Homem 2", M3: "Homem 3", M4: "Homem 4", M5: "Homem 5",
  };
  const VOICE_KEY = "supertonic.voice";
  let voice = localStorage.getItem(VOICE_KEY) || "F1";
  const voicesEl = $("voices");

  function renderVoices(names) {
    voicesEl.innerHTML = "";
    if (!names.includes(voice)) voice = names[0] || "F1";
    names.forEach((id) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(id === voice));
      b.dataset.voice = id;
      b.textContent = VOICE_LABELS[id] || id;
      b.title = id;
      b.classList.add(/^F/i.test(id) ? "f" : /^M/i.test(id) ? "m" : "x");
      if (id === voice) b.classList.add("on");
      b.onclick = () => {
        voice = id;
        localStorage.setItem(VOICE_KEY, id);
        [...voicesEl.children].forEach((x) => {
          x.classList.toggle("on", x.dataset.voice === id);
          x.setAttribute("aria-checked", String(x.dataset.voice === id));
        });
      };
      voicesEl.appendChild(b);
    });
  }
  renderVoices(Object.keys(VOICE_LABELS));

  // ---------------------------------------------------------------- Opções
  const speedEl = $("speed"), speedOut = $("speed-out"), langEl = $("lang"), formatEl = $("format");
  const fmtSpeed = (v) => parseFloat(v).toFixed(2).replace(/0$/, "") + "×";
  speedEl.value = localStorage.getItem("supertonic.speed") || "1";
  speedOut.textContent = fmtSpeed(speedEl.value);
  speedEl.oninput = () => { speedOut.textContent = fmtSpeed(speedEl.value); localStorage.setItem("supertonic.speed", speedEl.value); updateCount(); };
  if (localStorage.getItem("supertonic.lang")) langEl.value = localStorage.getItem("supertonic.lang");
  langEl.onchange = () => localStorage.setItem("supertonic.lang", langEl.value);
  if (localStorage.getItem("supertonic.format")) formatEl.value = localStorage.getItem("supertonic.format");
  formatEl.onchange = () => localStorage.setItem("supertonic.format", formatEl.value);
  const pauseEl = $("pause"), pauseOut = $("pause-out"), pagesField = $("pages-field"), pagesEl = $("pages");
  pauseEl.value = localStorage.getItem("supertonic.pause") || "0.6";
  pauseOut.textContent = parseFloat(pauseEl.value).toFixed(1) + "s";
  pauseEl.oninput = () => { pauseOut.textContent = parseFloat(pauseEl.value).toFixed(1) + "s"; localStorage.setItem("supertonic.pause", pauseEl.value); };

  let MAX_MB = 60;

  // ---------------------------------------------------------------- Health / capacidades
  const health = $("health"), healthText = $("health-text");
  let healthFailures = 0;
  async function checkHealth() {
    try {
      await waitToPoll(0);
      const j = await readResponse("/health", "json");
      healthFailures = 0;
      const ok = j.status === "ok";
      health.className = "pill " + (ok ? "ok" : "");
      healthText.textContent = ok ? "pronto" : "carregando modelo…";
      if (!ok) return setTimeout(checkHealth, 4000);
      if (j.mp3 === false) { formatEl.querySelector('[value="mp3"]').disabled = true; if (formatEl.value === "mp3") formatEl.value = "wav"; }
      loadVoices();
    } catch (e) {
      if (e.name !== "AbortError") {
        health.className = "pill err";
        healthText.textContent = "offline";
        healthFailures += 1;
      }
      await waitToPoll(e.name === "AbortError" ? 0 : retryDelay(healthFailures));
      checkHealth();
    }
  }
  async function loadVoices() {
    try {
      await waitToPoll(0);
      const j = await readResponse("/api/voices", "json");
      const names = [...(j.voices || []), ...(j.custom || [])];
      if (names.length) renderVoices(names);
      if (j.max_upload_mb) { MAX_MB = j.max_upload_mb; $("max-mb").textContent = MAX_MB; }
      if (j.default_lang && !localStorage.getItem("supertonic.lang") && [...langEl.options].some((o) => o.value === j.default_lang)) langEl.value = j.default_lang;
    } catch { /* mantém padrões */ }
  }
  checkHealth();

  // ---------------------------------------------------------------- Abas
  let mode = "file";
  const tabs = [...document.querySelectorAll(".tab")];
  const panes = { file: $("pane-file"), text: $("pane-text"), video: $("pane-video") };
  const goLabel = document.querySelector(".go-label");
  function showTab(next) {
    mode = next;
    tabs.forEach((t) => { const on = t.dataset.mode === next; t.classList.toggle("on", on); t.setAttribute("aria-selected", String(on)); });
    Object.entries(panes).forEach(([k, el]) => { el.hidden = k !== next; });
    goLabel.textContent = next === "video" ? "Transcrever e gerar áudio" : "Gerar áudio";
  }
  tabs.forEach((t) => (t.onclick = () => showTab(t.dataset.mode)));

  // ---------------------------------------------------------------- Arquivo
  const drop = $("drop"), fileEl = $("file"), fname = $("fname"), fnameText = $("fname-text");
  let chosen = null;
  const fmtBytes = (n) => (n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1) + " MB");
  function takeFile(f) {
    chosen = f || null;
    fname.hidden = !f;
    fnameText.textContent = f ? `${f.name} · ${fmtBytes(f.size)}` : "";
    drop.classList.toggle("has", !!f);
    pagesField.hidden = !(f && /\.pdf$/i.test(f.name));
    if (!f || !/\.pdf$/i.test(f.name)) pagesEl.value = "";
    if (f) say("");
  }
  drop.onclick = (e) => { if (!e.target.closest("#fclear")) fileEl.click(); };
  drop.onkeydown = (e) => { if (e.target === drop && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); fileEl.click(); } };
  fileEl.onchange = () => takeFile(fileEl.files[0]);
  $("fclear").onclick = (e) => { e.stopPropagation(); fileEl.value = ""; takeFile(null); };
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer?.files?.[0]; if (f) { showTab("file"); takeFile(f); } });
  document.addEventListener("paste", (e) => {
    if (document.activeElement === textEl || document.activeElement === $("video-url")) return;
    const f = [...(e.clipboardData?.files || [])][0];
    if (f) { showTab("file"); takeFile(f); return; }
    const t = e.clipboardData?.getData("text");
    if (t && t.trim()) {
      if (/^https?:\/\/\S+$/.test(t.trim()) && /youtu|vimeo|\.mp4|\.webm|\.m4a|\.mp3/i.test(t)) { showTab("video"); $("video-url").value = t.trim(); }
      else { showTab("text"); textEl.value = t; updateCount(); }
    }
  });

  // ---------------------------------------------------------------- Texto
  const textEl = $("text"), count = $("count"), estimate = $("estimate");
  function fmtDur(s) { s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60), r = s % 60; return m ? `${m}min ${String(r).padStart(2, "0")}s` : `${r}s`; }
  function updateCount() {
    const n = textEl.value.length;
    count.textContent = n.toLocaleString("pt-BR") + (n === 1 ? " caractere" : " caracteres");
    const words = textEl.value.trim() ? textEl.value.trim().split(/\s+/).length : 0;
    estimate.textContent = words ? `≈ ${fmtDur((words / 160) * 60 / parseFloat(speedEl.value || 1))} de áudio` : "";
  }
  textEl.addEventListener("input", updateCount);

  // ---------------------------------------------------------------- Amostra de voz
  const SAMPLES = {
    pt: "Olá! Esta é uma amostra da minha voz. Assim vou ler o seu documento.",
    en: "Hi! This is a sample of my voice. This is how I will read your document.",
    es: "¡Hola! Esta es una muestra de mi voz. Así leeré tu documento.",
    fr: "Bonjour ! Voici un échantillon de ma voix.", it: "Ciao! Questo è un esempio della mia voce.",
    de: "Hallo! Das ist eine Probe meiner Stimme.", na: "Olá! Esta é uma amostra da minha voz.",
  };
  const previewBtn = $("preview-voice");
  let previewAudio = null;
  previewBtn.onclick = async () => {
    if (previewAudio) { previewAudio.pause(); previewAudio = null; previewBtn.textContent = "Ouvir amostra"; return; }
    previewBtn.disabled = true; previewBtn.textContent = "…";
    try {
      const body = new FormData();
      body.append("text", SAMPLES[langEl.value] || SAMPLES.pt);
      body.append("voice", voice); body.append("lang", langEl.value); body.append("speed", speedEl.value);
      const r = await fetch("/usar", { method: "POST", body });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error?.message || "Falhou.");
      const url = URL.createObjectURL(await r.blob());
      previewAudio = new Audio(url);
      previewBtn.textContent = "Parar";
      previewAudio.onended = () => { previewBtn.textContent = "Ouvir amostra"; previewAudio = null; URL.revokeObjectURL(url); };
      await previewAudio.play();
    } catch (e) { say(e.message, "err"); previewBtn.textContent = "Ouvir amostra"; }
    finally { previewBtn.disabled = false; }
  };

  // ---------------------------------------------------------------- Progresso / status
  const status = $("status"), progress = $("progress"), fill = $("fill"), progressMsg = $("progress-msg");
  const steps = [...document.querySelectorAll("#steps li")];
  const errorStatus = $("error-status"), progressBar = $("progress-bar");
  function say(msg, cls) {
    const isError = cls === "err";
    const normal = isError ? "" : msg || "";
    const error = isError ? msg || "" : "";
    status.className = "status " + (isError ? "" : cls || "");
    status.hidden = isError;
    errorStatus.hidden = !isError;
    // Do not re-announce identical messages on every polling tick.
    if (status.textContent !== normal) status.textContent = normal;
    if (errorStatus.textContent !== error) errorStatus.textContent = error;
  }
  function setProgress(stage, pct, msg) {
    progress.hidden = false;
    const map = { queued: "read", download: "read", read: "read", transcribe: "read", tts: "tts", encode: "tts", done: "done" };
    const name = map[stage] || "read";
    let passed = true;
    steps.forEach((li) => {
      const on = li.dataset.step === name;
      li.classList.toggle("on", on); li.classList.toggle("done", passed && !on);
      if (on) { passed = false; li.setAttribute("aria-current", "step"); }
      else li.removeAttribute("aria-current");
    });
    const value = Math.max(0, Math.min(100, Number(pct) || 0));
    const indeterminate = value < 5 && stage !== "done";
    fill.classList.toggle("indet", indeterminate);
    fill.style.width = Math.max(2, value) + "%";
    if (indeterminate) progressBar.removeAttribute("aria-valuenow");
    else progressBar.setAttribute("aria-valuenow", String(value));
    progressBar.setAttribute("aria-valuetext", msg || (indeterminate ? "Aguardando…" : `${Math.round(value)}%`));
    if (progressMsg.textContent !== (msg || "")) progressMsg.textContent = msg || "";
  }
  function resetProgress() {
    progress.hidden = true; fill.classList.remove("indet"); fill.style.width = "0%"; progressMsg.textContent = "";
    progressBar.removeAttribute("aria-valuenow"); progressBar.removeAttribute("aria-valuetext");
    steps.forEach((li) => li.removeAttribute("aria-current"));
  }

  // ---------------------------------------------------------------- Player progressivo & Karaokê
  const result = $("result"), player = $("player"), down = $("down"), preview = $("preview");
  const truncatedEl = $("truncated"), toggleText = $("toggle-text"), copyBtn = $("copy");
  const toggleKaraoke = $("toggle-karaoke");
  let lastText = "";
  let karaokeEnabled = true;
  const play = { urls: [], index: -1, waiting: false, active: false, finalUrl: null, spans: [], chunkRatios: [] };

  if (toggleKaraoke) {
    toggleKaraoke.classList.add("active-karaoke");
    toggleKaraoke.onclick = () => {
      karaokeEnabled = !karaokeEnabled;
      toggleKaraoke.classList.toggle("active-karaoke", karaokeEnabled);
      toggleKaraoke.setAttribute("aria-pressed", String(karaokeEnabled));
      if (!karaokeEnabled) highlight(-1);
    };
  }

  function renderChunks(chunks) {
    preview.innerHTML = "";
    const totalChars = chunks.reduce((acc, c) => acc + c.length, 0) || 1;
    let accumulated = 0;
    play.chunkRatios = chunks.map((c) => {
      const start = accumulated / totalChars;
      accumulated += c.length;
      const end = accumulated / totalChars;
      return { start, end };
    });

    play.spans = chunks.map((c, i) => {
      const s = document.createElement("span");
      s.className = "chunk";
      s.dataset.i = i;
      s.textContent = c;
      s.title = "Clique para ouvir este trecho";
      s.onclick = () => {
        if (player.src && player.duration && isFinite(player.duration)) {
          const ratio = play.chunkRatios[i]?.start || 0;
          player.currentTime = ratio * player.duration;
          highlight(i);
          player.play().catch(() => {});
        } else if (i < play.urls.length) {
          playChunk(i);
        }
      };
      preview.appendChild(s);
      return s;
    });
  }

  function highlight(i) {
    play.spans.forEach((s, k) => {
      s.classList.toggle("now", k === i);
      s.classList.toggle("ready", k < play.urls.length || Boolean(player.src));
    });
    const el = play.spans[i];
    if (el && !preview.hidden && karaokeEnabled) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  player.addEventListener("timeupdate", () => {
    if (!karaokeEnabled || !player.duration || !isFinite(player.duration) || !play.chunkRatios.length) return;
    const progressRatio = player.currentTime / player.duration;
    const idx = play.chunkRatios.findIndex((r) => progressRatio >= r.start && progressRatio <= r.end);
    if (idx !== -1 && idx !== play.index) {
      play.index = idx;
      highlight(idx);
    }
  });

  function playChunk(i) {
    if (i >= play.urls.length) { play.waiting = true; return; }
    play.index = i; play.waiting = false; play.active = true;
    player.src = play.urls[i];
    highlight(i);
    player.play().catch(() => {});
  }
  player.addEventListener("ended", () => {
    if (!play.active) return;
    const next = play.index + 1;
    if (next < play.urls.length) playChunk(next);
    else if (play.total != null && next >= play.total) { play.active = false; highlight(-1); }
    else { play.waiting = true; say("Aguardando o próximo trecho…"); }
  });

  toggleText.onclick = () => {
    const open = preview.hidden;
    preview.hidden = !open;
    toggleText.textContent = open ? "Ocultar texto" : "Ver texto";
    toggleText.setAttribute("aria-expanded", String(open));
  };
  copyBtn.onclick = async () => {
    try { await navigator.clipboard.writeText(lastText); copyBtn.textContent = "Copiado ✓"; } catch { copyBtn.textContent = "Não deu para copiar"; }
    setTimeout(() => (copyBtn.textContent = "Copiar texto"), 1600);
  };
  const shareBtn = $("share");
  let shareJobId = null;
  shareBtn.onclick = async () => {
    if (!shareJobId) return;
    shareBtn.disabled = true; shareBtn.textContent = "Gerando link…";
    try {
      const fd = new FormData(); fd.append("title", (lastText || "").slice(0, 80));
      const j = await (await api(`/api/jobs/${shareJobId}/share`, { method: "POST", body: fd })).json();
      let copied = false;
      try { await navigator.clipboard.writeText(j.url); copied = true; } catch {}
      if (navigator.share && !copied) { try { await navigator.share({ title: "Áudio do TrustVoice", url: j.url }); } catch {} }
      shareBtn.textContent = copied ? "Link copiado ✓" : "Link criado";
      say(`Link válido por 24 h: ${j.url}`, "ok");
    } catch (e) { shareBtn.textContent = "Compartilhar"; say(e.message, "err"); }
    finally { shareBtn.disabled = false; setTimeout(() => (shareBtn.textContent = "Compartilhar"), 2500); }
  };
  function setShare(jobId) { shareJobId = jobId; shareBtn.disabled = !jobId; shareBtn.textContent = "Compartilhar"; }

  function setDownload(url, filename) {
    if (url) { down.href = url; down.download = filename; down.textContent = "Baixar " + filename.split(".").pop().toUpperCase(); down.removeAttribute("aria-disabled"); }
    else { down.removeAttribute("href"); down.textContent = "Preparando arquivo…"; down.setAttribute("aria-disabled", "true"); }
  }

  // ---------------------------------------------------------------- Histórico (IndexedDB)
  const DB_NAME = "supertonic", STORE = "history", MAX_HISTORY = 20;
  const dbp = new Promise((resolve) => {
    if (!("indexedDB" in window)) return resolve(null);
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(null);
  });
  async function dbAll() {
    const db = await dbp; if (!db) return [];
    return new Promise((res) => { const r = db.transaction(STORE).objectStore(STORE).getAll(); r.onsuccess = () => res(r.result || []); r.onerror = () => res([]); });
  }
  async function dbPut(item) {
    const db = await dbp; if (!db) return;
    const all = (await dbAll()).sort((a, b) => b.when - a.when);
    const tx = db.transaction(STORE, "readwrite"); const st = tx.objectStore(STORE);
    st.put(item);
    all.slice(MAX_HISTORY - 1).forEach((old) => st.delete(old.id));
  }
  async function dbClear() { const db = await dbp; if (db) db.transaction(STORE, "readwrite").objectStore(STORE).clear(); }

  const historyWrap = $("history-wrap"), historyEl = $("history");
  const objectUrls = new Map();
  function urlFor(item) {
    if (!objectUrls.has(item.id)) objectUrls.set(item.id, URL.createObjectURL(item.blob));
    return objectUrls.get(item.id);
  }
  async function renderHistory() {
    const items = (await dbAll()).sort((a, b) => b.when - a.when);
    historyWrap.hidden = items.length === 0;
    historyEl.innerHTML = "";
    items.forEach((h) => {
      const li = document.createElement("li");
      li.innerHTML = `<button class="play" type="button" aria-label="Tocar">▶</button>
        <div class="info"><div class="title"></div><div class="sub"></div></div>
        <a class="dl" download="${h.filename}">Baixar</a>`;
      li.querySelector(".title").textContent = h.title;
      const d = new Date(h.when);
      li.querySelector(".sub").textContent = `${VOICE_LABELS[h.voice] || h.voice} · ${fmtDur(h.duration)} · ${fmtBytes(h.blob.size)} · ${d.toLocaleDateString("pt-BR")} ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
      li.querySelector(".dl").href = urlFor(h);
      li.querySelector(".play").onclick = () => {
        play.active = false; play.urls = []; play.total = null;
        renderChunks(h.chunks || [h.text]); play.spans.forEach((s) => s.classList.add("ready"));
        lastText = h.text; player.src = urlFor(h); setDownload(urlFor(h), h.filename); setShare(h.id && h.when > Date.now() - 3 * 3600e3 ? h.id : null);
        result.hidden = false; preview.hidden = false; toggleText.textContent = "Ocultar texto";
        player.play().catch(() => {});
        result.scrollIntoView({ behavior: "smooth", block: "nearest" });
      };
      historyEl.appendChild(li);
    });
  }
  $("clear-history").onclick = async () => { await dbClear(); objectUrls.forEach((u) => URL.revokeObjectURL(u)); objectUrls.clear(); renderHistory(); };
  renderHistory();

  // ---------------------------------------------------------------- Gerar (job)
  const go = $("go");
  let currentJob = null, currentRun = null;
  const cancelBtn = $("cancel-job");

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      const error = new Error(body.error?.message || `Erro HTTP ${r.status}.`);
      error.status = r.status;
      const retryAfter = r.headers.get("Retry-After");
      const seconds = retryAfter == null ? NaN : Number(retryAfter);
      error.retryAfter = Number.isFinite(seconds) ? Math.max(0, seconds * 1000) : Math.max(0, Date.parse(retryAfter) - Date.now()) || 0;
      throw error;
    }
    return r;
  }

  // Polling helpers: one in-flight GET, no timers/network while hidden/offline.
  function abortError() { return new DOMException("Acompanhamento interrompido.", "AbortError"); }
  function canPoll() { return !document.hidden && navigator.onLine !== false; }
  function retryable(e) {
    return e.name === "TypeError" || e.name === "TimeoutError" || e.name === "SyntaxError" ||
      e.status === 408 || e.status === 429 || e.status >= 500;
  }
  function retryDelay(failures, retryAfter = 0) {
    return Math.max(retryAfter, Math.min(30000, 1000 * (2 ** Math.min(Math.max(0, failures - 1), 5))));
  }
  function nextPollDelay(previous, changed, state) {
    if (changed) return state.status === "queued" ? 2000 : 700;
    return Math.min(state.status === "queued" ? 10000 : 5000, Math.round(previous * 1.5));
  }
  function waitToPoll(delay, signal) {
    return new Promise((resolve, reject) => {
      let timer;
      const until = Date.now() + delay;
      function cleanup() {
        clearTimeout(timer);
        document.removeEventListener("visibilitychange", ready);
        window.removeEventListener("online", ready);
        window.removeEventListener("offline", ready);
        signal?.removeEventListener("abort", aborted);
      }
      function aborted() { cleanup(); reject(abortError()); }
      function ready() {
        clearTimeout(timer);
        if (signal?.aborted) return aborted();
        if (!canPoll()) return;
        const remaining = Math.max(0, until - Date.now());
        if (remaining) timer = setTimeout(ready, Math.min(remaining, 2147483647));
        else { cleanup(); resolve(); }
      }
      document.addEventListener("visibilitychange", ready);
      window.addEventListener("online", ready);
      window.addEventListener("offline", ready);
      signal?.addEventListener("abort", aborted, { once: true });
      ready();
    });
  }
  async function readResponse(path, kind, signal) {
    const controller = new AbortController();
    let timedOut = false;
    const abort = () => controller.abort();
    const suspend = () => { if (!canPoll()) abort(); };
    signal?.addEventListener("abort", abort, { once: true });
    document.addEventListener("visibilitychange", suspend);
    window.addEventListener("offline", suspend);
    const timer = setTimeout(() => { timedOut = true; abort(); }, kind === "blob" ? 120000 : 15000);
    try {
      if (signal?.aborted || !canPoll()) throw abortError();
      const r = await api(path, { cache: "no-store", signal: controller.signal });
      return await r[kind](); // Timeout also covers reading/parsing the body.
    } catch (e) {
      if (signal?.aborted) throw abortError();
      if (timedOut) throw new DOMException("O servidor demorou para responder.", "TimeoutError");
      throw e;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      document.removeEventListener("visibilitychange", suspend);
      window.removeEventListener("offline", suspend);
    }
  }
  async function readWithRetry(path, kind, signal) {
    let failures = 0, delay = 0;
    for (;;) {
      await waitToPoll(delay, signal);
      try { return await readResponse(path, kind, signal); }
      catch (e) {
        if (signal?.aborted) throw abortError();
        if (e.name === "AbortError") { delay = 0; continue; }
        if (!retryable(e)) throw e;
        delay = retryDelay(++failures, e.retryAfter);
        say(`Conexão instável. Nova tentativa em ${Math.ceil(delay / 1000)}s; seu pedido não será reenviado.`, "err");
      }
    }
  }

  cancelBtn.onclick = () => {
    const run = currentRun;
    if (!run || !currentJob || run.cancelled) return;
    const jobId = currentJob;
    run.cancelled = true;
    run.restoreFocus = document.activeElement === cancelBtn;
    currentJob = null;
    run.controller.abort();
    cancelBtn.disabled = true;
    play.active = false; play.waiting = false;
    player.pause(); player.removeAttribute("src"); player.load();
    result.hidden = true; resetProgress(); setShare(null); setDownload(null);
    if (play.finalUrl) { URL.revokeObjectURL(play.finalUrl); play.finalUrl = null; }
    say("Acompanhamento interrompido. Solicitando cancelamento ao servidor…");
    // DELETE exists, but the current backend cannot interrupt every running stage.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    run.cancelPromise = api(`/api/jobs/${jobId}`, { method: "DELETE", signal: controller.signal })
      .then(() => say("Cancelamento solicitado. Uma etapa já em execução pode continuar no servidor."))
      .catch(() => say("Acompanhamento interrompido, mas não foi possível confirmar o cancelamento no servidor.", "err"))
      .finally(() => clearTimeout(timer));
  };

  go.onclick = async () => {
    if (go.disabled) return;
    // estado inicial
    result.hidden = true; truncatedEl.hidden = true; resetProgress(); say("");
    play.active = false; play.urls = []; play.index = -1; play.total = null; play.waiting = false;
    player.pause(); player.removeAttribute("src"); player.load();
    if (play.finalUrl) { URL.revokeObjectURL(play.finalUrl); play.finalUrl = null; }
    setDownload(null); setShare(null);

    const body = new FormData();
    body.append("voice", voice); body.append("lang", langEl.value); body.append("speed", speedEl.value); body.append("response_format", formatEl.value);
    body.append("pause", pauseEl.value);
    const audioModeEl = $("mode"), translateEl = $("translate"), smartSkipEl = $("smart-skip");
    if (audioModeEl) body.append("mode", audioModeEl.value);
    if (translateEl) body.append("translate", translateEl.value === "true");
    if (smartSkipEl) body.append("smart_skip", smartSkipEl.checked);
    if (mode === "file" && chosen && /\.pdf$/i.test(chosen.name) && pagesEl.value.trim()) body.append("pages", pagesEl.value.trim());
    let title = "";
    if (mode === "file") {
      if (!chosen) return say("Escolha um arquivo.", "err");
      if (chosen.size > MAX_MB * 1048576) return say(`Arquivo maior que ${MAX_MB} MB.`, "err");
      body.append("file", chosen); title = chosen.name;
    } else if (mode === "video") {
      const link = $("video-url").value.trim();
      if (!link) return say("Cole o link do vídeo.", "err");
      body.append("url", link); title = link.replace(/^https?:\/\//, "").slice(0, 60);
    } else {
      const text = textEl.value.trim();
      if (!text) return say("Cole um texto.", "err");
      body.append("text", text); title = text.slice(0, 60) + (text.length > 60 ? "…" : "");
    }

    go.disabled = true;
    go.setAttribute("aria-busy", "true");
    const submittedVoice = voice;
    const run = { controller: new AbortController(), cancelled: false, cancelPromise: null };
    currentRun = run;
    const signal = run.controller.signal;
    const t0 = performance.now();
    try {
      setProgress("queued", 2, "Enviando…");
      const job = await (await api("/api/jobs", { method: "POST", body })).json();
      currentJob = job.id;
      cancelBtn.hidden = false; cancelBtn.disabled = false; $("cancel-help").hidden = false;
      let started = false, textShown = false, delay = 700, fingerprint = "";

      for (;;) {
        const j = await readWithRetry(`/api/jobs/${job.id}`, "json", signal);
        if (signal.aborted || currentJob !== job.id) return;
        const nextFingerprint = JSON.stringify([j.status, j.stage, j.percent, j.queue_position, j.chunk_urls?.length, j.message]);
        delay = nextPollDelay(delay, nextFingerprint !== fingerprint, j);
        fingerprint = nextFingerprint;
        if (j.status === "cancelled") {
          play.active = false; play.waiting = false;
          player.pause(); player.removeAttribute("src"); player.load();
          result.hidden = true; resetProgress();
          say("Pedido cancelado no servidor."); break;
        }
        const msg = j.status === "queued" && j.queue_position > 1 ? `Na fila (posição ${j.queue_position})…` : j.message;
        setProgress(j.stage, j.percent, msg);
        say(j.status === "error" ? "" : msg);

        if (j.text && !textShown) {
          textShown = true; lastText = j.text; renderChunks(j.chunks);
          result.hidden = false; preview.hidden = false; toggleText.textContent = "Ocultar texto"; toggleText.setAttribute("aria-expanded", "true");
          if (j.truncated) truncatedEl.hidden = false;
        }
        if (j.chunk_urls.length > play.urls.length) {
          play.urls = j.chunk_urls; play.total = j.chunks.length;
          highlight(play.index);
          if (!started) { started = true; playChunk(0); say(`Tocando o primeiro trecho · ${((performance.now() - t0) / 1000).toFixed(1)}s`, "ok"); }
          else if (play.waiting) playChunk(play.index + 1);
        }
        if (j.status === "error") throw new Error(j.error?.message || "Falhou.");
        if (j.status === "done") {
          play.total = j.chunks.length;
          setProgress("done", 100, "");
          const blob = await readWithRetry(j.audio_url, "blob", signal);
          if (signal.aborted || currentJob !== job.id) return;
          const ext = j.format;
          const filename = `trustvoice-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")}.${ext}`;
          const url = URL.createObjectURL(blob);
          play.finalUrl = url;
          setDownload(url, filename);
          if (!play.active) { player.src = url; play.spans.forEach((s) => s.classList.add("ready")); }
          const took = ((performance.now() - t0) / 1000).toFixed(1);
          setShare(job.id);
          say(`Pronto · ${fmtDur(j.duration)} de áudio · ${fmtBytes(blob.size)} · ${took}s${j.cached ? " · do cache ⚡" : ""}`, "ok");
          await dbPut({ id: job.id, title, voice: submittedVoice, duration: j.duration, text: j.text, chunks: j.chunks, filename, blob, when: Date.now() });
          renderHistory();
          break;
        }
        await waitToPoll(delay, signal);
      }
    } catch (e) {
      resetProgress();
      if (!run.cancelled) {
        play.active = false; play.waiting = false;
        player.pause();
        say(e.message || String(e), "err");
      }
    } finally {
      await run.cancelPromise;
      currentJob = null; currentRun = null;
      const restoreFocus = run.restoreFocus || document.activeElement === cancelBtn;
      cancelBtn.hidden = true; cancelBtn.disabled = true; $("cancel-help").hidden = true;
      go.disabled = false; go.removeAttribute("aria-busy");
      if (restoreFocus) go.focus();
    }
  };

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !go.disabled) {
      go.click();
      return;
    }
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
    if (e.code === "Space" && player.src) {
      e.preventDefault();
      if (player.paused) player.play().catch(() => {});
      else player.pause();
    } else if (e.code === "ArrowLeft" && player.src) {
      e.preventDefault();
      player.currentTime = Math.max(0, player.currentTime - 5);
    } else if (e.code === "ArrowRight" && player.src) {
      e.preventDefault();
      player.currentTime = Math.min(player.duration || 0, player.currentTime + 5);
    }
  });

  // ---------------------------------------------------------------- Guia Como Usar
  const guideBtn = $("guide-btn"), heroGuideBtn = $("hero-guide-btn"), guideModal = $("guide-modal");
  const closeGuide = $("close-guide"), gotItBtn = $("got-it-btn");

  function openGuide() {
    if (guideModal) guideModal.hidden = false;
  }
  function hideGuide() {
    if (guideModal) guideModal.hidden = true;
  }

  if (guideBtn) guideBtn.onclick = openGuide;
  if (heroGuideBtn) heroGuideBtn.onclick = openGuide;
  if (closeGuide) closeGuide.onclick = hideGuide;
  if (gotItBtn) gotItBtn.onclick = hideGuide;
  if (guideModal) {
    guideModal.onclick = (e) => {
      if (e.target === guideModal) hideGuide();
    };
  }

  // ---------------------------------------------------------------- Biblioteca Supabase
  const libraryBtn = $("library-btn"), libraryModal = $("library-modal");
  const closeLibrary = $("close-library"), libraryList = $("library-items"), libraryCount = $("library-count");
  const copyRssBtn = $("copy-rss");

  if (copyRssBtn) {
    copyRssBtn.onclick = async () => {
      const rssUrl = new URL("/api/feed.xml", location.href).href;
      try {
        await navigator.clipboard.writeText(rssUrl);
        copyRssBtn.textContent = "Feed Copiado! ✓";
      } catch {
        copyRssBtn.textContent = "Copie: /api/feed.xml";
      }
      setTimeout(() => (copyRssBtn.textContent = "📡 Feed RSS"), 2500);
    };
  }

  function escapeHtml(str) {
    return String(str || "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  async function loadLibrary() {
    if (!libraryList) return;
    libraryList.innerHTML = '<p class="hint">Carregando documentos da nuvem…</p>';
    try {
      const r = await fetch("/api/documents");
      const data = await r.json();
      if (!data.enabled) {
        libraryList.innerHTML = '<div class="library-empty">Supabase não configurado. Adicione as variáveis SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no Railway para ativar a nuvem.</div>';
        return;
      }
      const docs = data.documents || [];
      if (libraryCount) {
        libraryCount.textContent = docs.length;
        libraryCount.hidden = docs.length === 0;
      }
      if (docs.length === 0) {
        libraryList.innerHTML = '<div class="library-empty">Nenhum documento salvo ainda. Converta um documento para vê-lo aqui!</div>';
        return;
      }
      libraryList.innerHTML = "";
      docs.forEach((doc) => {
        const card = document.createElement("div");
        card.className = "doc-card";
        const dateStr = new Date(doc.created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
        card.innerHTML = `
          <div class="doc-card-top">
            <span class="doc-card-title" title="${escapeHtml(doc.title)}">${escapeHtml(doc.title)}</span>
            <span class="doc-card-tag">${escapeHtml((doc.format || "mp3").toUpperCase())} · ${escapeHtml(doc.voice || "F1")}</span>
          </div>
          <div class="doc-card-preview">${escapeHtml(doc.preview || "")}</div>
          <div class="doc-card-bottom">
            <span class="doc-card-meta">${dateStr}</span>
            <div class="doc-card-actions">
              <button type="button" class="btn-sm play-doc" data-url="${doc.audio_url}">▶ Ouvir</button>
              <a class="btn-sm" href="${doc.audio_url}" target="_blank" download="trustvoice-${doc.job_uuid}.${doc.format}">⬇ Baixar</a>
              <button type="button" class="btn-sm del del-doc" data-uuid="${doc.job_uuid}">Excluir</button>
            </div>
          </div>
        `;
        libraryList.appendChild(card);
      });

      libraryList.querySelectorAll(".play-doc").forEach((btn) => {
        btn.onclick = () => {
          libraryModal.hidden = true;
          player.src = btn.dataset.url;
          result.hidden = false;
          player.play().catch(() => {});
        };
      });

      libraryList.querySelectorAll(".del-doc").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm("Deseja realmente excluir este áudio da nuvem?")) return;
          btn.disabled = true;
          btn.textContent = "…";
          try {
            await fetch(`/api/documents/${btn.dataset.uuid}`, { method: "DELETE" });
            loadLibrary();
          } catch (e) {
            alert("Erro ao excluir: " + e.message);
          }
        };
      });
    } catch (e) {
      libraryList.innerHTML = `<div class="library-empty">Erro ao carregar documentos: ${escapeHtml(e.message)}</div>`;
    }
  }

  if (libraryBtn && libraryModal) {
    libraryBtn.onclick = () => {
      libraryModal.hidden = false;
      loadLibrary();
    };
    if (closeLibrary) {
      closeLibrary.onclick = () => { libraryModal.hidden = true; };
    }
    libraryModal.onclick = (e) => {
      if (e.target === libraryModal) libraryModal.hidden = true;
    };
  }

  async function refreshLibraryCount() {
    try {
      const r = await fetch("/api/documents");
      const data = await r.json();
      if (data.enabled && libraryCount) {
        const count = data.documents?.length || 0;
        libraryCount.textContent = count;
        libraryCount.hidden = count === 0;
      }
    } catch {}
  }
  refreshLibraryCount();

  // ---------------------------------------------------------------- PWA
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
