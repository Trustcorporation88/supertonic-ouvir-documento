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

  let MAX_MB = 60;

  // ---------------------------------------------------------------- Health / capacidades
  const health = $("health"), healthText = $("health-text");
  async function checkHealth() {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      const j = await r.json();
      const ok = j.status === "ok";
      health.className = "pill " + (ok ? "ok" : "");
      healthText.textContent = ok ? "pronto" : "carregando modelo…";
      if (!ok) return setTimeout(checkHealth, 4000);
      if (j.mp3 === false) { formatEl.querySelector('[value="mp3"]').disabled = true; if (formatEl.value === "mp3") formatEl.value = "wav"; }
      loadVoices();
    } catch {
      health.className = "pill err";
      healthText.textContent = "offline";
      setTimeout(checkHealth, 6000);
    }
  }
  async function loadVoices() {
    try {
      const r = await fetch("/api/voices");
      if (!r.ok) return;
      const j = await r.json();
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
    if (f) say("");
  }
  drop.onclick = (e) => { if (!e.target.closest("#fclear")) fileEl.click(); };
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileEl.click(); } };
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
  function say(msg, cls) { status.className = "status " + (cls || ""); status.textContent = msg; }
  function setProgress(stage, pct, msg) {
    progress.hidden = false;
    const map = { queued: "read", download: "read", read: "read", transcribe: "read", tts: "tts", encode: "tts", done: "done" };
    const name = map[stage] || "read";
    let passed = true;
    steps.forEach((li) => { const on = li.dataset.step === name; li.classList.toggle("on", on); li.classList.toggle("done", passed && !on); if (on) passed = false; });
    fill.classList.toggle("indet", pct < 5);
    fill.style.width = Math.max(2, pct) + "%";
    progressMsg.textContent = msg || "";
  }
  function resetProgress() { progress.hidden = true; fill.classList.remove("indet"); fill.style.width = "0%"; progressMsg.textContent = ""; }

  // ---------------------------------------------------------------- Player progressivo
  const result = $("result"), player = $("player"), down = $("down"), preview = $("preview");
  const truncatedEl = $("truncated"), toggleText = $("toggle-text"), copyBtn = $("copy");
  let lastText = "";
  const play = { urls: [], index: -1, waiting: false, active: false, finalUrl: null, spans: [] };

  function renderChunks(chunks) {
    preview.innerHTML = "";
    play.spans = chunks.map((c, i) => {
      const s = document.createElement("span");
      s.className = "chunk";
      s.dataset.i = i;
      s.textContent = c;
      s.title = "Clique para ouvir daqui";
      s.onclick = () => { if (i < play.urls.length) playChunk(i); };
      preview.appendChild(s);
      return s;
    });
  }
  function highlight(i) {
    play.spans.forEach((s, k) => { s.classList.toggle("now", k === i); s.classList.toggle("ready", k < play.urls.length); });
    const el = play.spans[i];
    if (el && !preview.hidden) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
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
        lastText = h.text; player.src = urlFor(h); setDownload(urlFor(h), h.filename);
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
  let currentJob = null;

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.error?.message || `Erro HTTP ${r.status}.`); }
    return r;
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  go.onclick = async () => {
    // estado inicial
    result.hidden = true; truncatedEl.hidden = true; resetProgress(); say("");
    play.active = false; play.urls = []; play.index = -1; play.total = null; play.waiting = false;
    player.pause(); player.removeAttribute("src");
    setDownload(null);

    const body = new FormData();
    body.append("voice", voice); body.append("lang", langEl.value); body.append("speed", speedEl.value); body.append("response_format", formatEl.value);
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
    const t0 = performance.now();
    try {
      setProgress("queued", 2, "Enviando…");
      const job = await (await api("/api/jobs", { method: "POST", body })).json();
      currentJob = job.id;
      let started = false, textShown = false, delay = 700;

      for (;;) {
        const j = await (await api(`/api/jobs/${job.id}`)).json();
        if (currentJob !== job.id) return; // usuário começou outro
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
          const blob = await (await api(j.audio_url)).blob();
          const ext = j.format;
          const filename = `supertonic-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")}.${ext}`;
          const url = URL.createObjectURL(blob);
          play.finalUrl = url;
          setDownload(url, filename);
          if (!play.active) { player.src = url; play.spans.forEach((s) => s.classList.add("ready")); }
          const took = ((performance.now() - t0) / 1000).toFixed(1);
          say(`Pronto · ${fmtDur(j.duration)} de áudio · ${fmtBytes(blob.size)} · ${took}s`, "ok");
          await dbPut({ id: job.id, title, voice, duration: j.duration, text: j.text, chunks: j.chunks, filename, blob, when: Date.now() });
          renderHistory();
          break;
        }
        await sleep(delay);
        delay = Math.min(2000, delay + 100);
      }
    } catch (e) {
      resetProgress();
      say(e.message || String(e), "err");
    } finally {
      go.disabled = false;
    }
  };

  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !go.disabled) go.click(); });

  // ---------------------------------------------------------------- PWA
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
