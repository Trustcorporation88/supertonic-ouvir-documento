/* SuperTonic — lógica da interface */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- Tema
  const THEME_KEY = "supertonic.theme";
  const root = document.documentElement;
  function applyTheme(t) {
    if (t === "light") root.setAttribute("data-theme", "light");
    else root.removeAttribute("data-theme");
  }
  const savedTheme = localStorage.getItem(THEME_KEY);
  applyTheme(savedTheme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
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
  const DEFAULT_VOICES = Object.keys(VOICE_LABELS);
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
      const label = VOICE_LABELS[id] || id;
      b.textContent = label; b.title = id;
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
  renderVoices(DEFAULT_VOICES);

  // ---------------------------------------------------------------- Health
  const health = $("health");
  const healthText = $("health-text");
  async function checkHealth() {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      const j = await r.json();
      const ok = j.status === "ok";
      health.className = "pill " + (ok ? "ok" : "");
      healthText.textContent = ok ? "pronto" : "carregando modelo…";
      if (!ok) setTimeout(checkHealth, 4000);
      else loadVoices();
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
      if (j.default_lang) {
        const sel = $("lang");
        if ([...sel.options].some((o) => o.value === j.default_lang) && !localStorage.getItem("supertonic.lang")) sel.value = j.default_lang;
      }
    } catch { /* mantém as vozes padrão */ }
  }
  checkHealth();

  // ---------------------------------------------------------------- Abas
  let mode = "file";
  const tabs = [...document.querySelectorAll(".tab")];
  const panes = { file: $("pane-file"), text: $("pane-text"), video: $("pane-video") };
  const goLabel = document.querySelector(".go-label");
  function showTab(next) {
    mode = next;
    tabs.forEach((t) => {
      const on = t.dataset.mode === next;
      t.classList.toggle("on", on);
      t.setAttribute("aria-selected", String(on));
    });
    Object.entries(panes).forEach(([k, el]) => { el.hidden = k !== next; });
    goLabel.textContent = next === "video" ? "Transcrever e gerar áudio" : "Gerar áudio";
  }
  tabs.forEach((t) => (t.onclick = () => showTab(t.dataset.mode)));

  // ---------------------------------------------------------------- Arquivo
  const drop = $("drop");
  const fileEl = $("file");
  const fname = $("fname");
  const fnameText = $("fname-text");
  let chosen = null;

  function fmtBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(0) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }
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
  drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) { showTab("file"); takeFile(f); } });
  // Soltar arquivo em qualquer lugar da página
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    const f = e.dataTransfer?.files?.[0];
    if (f) { showTab("file"); takeFile(f); }
  });
  // Colar texto/arquivo
  document.addEventListener("paste", (e) => {
    if (document.activeElement === $("text") || document.activeElement === $("video-url")) return;
    const f = [...(e.clipboardData?.files || [])][0];
    if (f) { showTab("file"); takeFile(f); return; }
    const t = e.clipboardData?.getData("text");
    if (t && t.trim()) {
      if (/^https?:\/\/\S+$/.test(t.trim()) && /youtu|\.mp4|\.webm|\.m4a|\.mp3/i.test(t)) { showTab("video"); $("video-url").value = t.trim(); }
      else { showTab("text"); $("text").value = t; updateCount(); }
    }
  });

  // ---------------------------------------------------------------- Texto
  const textEl = $("text");
  const count = $("count");
  const estimate = $("estimate");
  function updateCount() {
    const n = textEl.value.length;
    count.textContent = n.toLocaleString("pt-BR") + (n === 1 ? " caractere" : " caracteres");
    const words = textEl.value.trim() ? textEl.value.trim().split(/\s+/).length : 0;
    const sec = Math.round((words / 160) * 60 / parseFloat(speedEl.value || 1));
    estimate.textContent = words ? `≈ ${fmtDur(sec)} de áudio` : "";
  }
  textEl.addEventListener("input", updateCount);

  // ---------------------------------------------------------------- Opções
  const speedEl = $("speed");
  const speedOut = $("speed-out");
  speedEl.value = localStorage.getItem("supertonic.speed") || "1";
  speedOut.textContent = parseFloat(speedEl.value).toFixed(2).replace(/0$/, "") + "×";
  speedEl.oninput = () => {
    speedOut.textContent = parseFloat(speedEl.value).toFixed(2).replace(/0$/, "") + "×";
    localStorage.setItem("supertonic.speed", speedEl.value);
    updateCount();
  };
  const langEl = $("lang");
  if (localStorage.getItem("supertonic.lang")) langEl.value = localStorage.getItem("supertonic.lang");
  langEl.onchange = () => localStorage.setItem("supertonic.lang", langEl.value);

  const SAMPLES = {
    pt: "Olá! Esta é uma amostra da minha voz. Assim vou ler o seu documento.",
    en: "Hi! This is a sample of my voice. This is how I will read your document.",
    es: "¡Hola! Esta es una muestra de mi voz. Así leeré tu documento.",
    fr: "Bonjour ! Voici un échantillon de ma voix.",
    it: "Ciao! Questo è un esempio della mia voce.",
    de: "Hallo! Das ist eine Probe meiner Stimme.",
    na: "Olá! Esta é uma amostra da minha voz.",
  };
  const previewBtn = $("preview-voice");
  let previewAudio = null;
  previewBtn.onclick = async () => {
    if (previewAudio) { previewAudio.pause(); previewAudio = null; previewBtn.textContent = "Ouvir amostra"; return; }
    previewBtn.disabled = true;
    previewBtn.textContent = "…";
    try {
      const body = new FormData();
      body.append("text", SAMPLES[langEl.value] || SAMPLES.pt);
      body.append("voice", voice);
      body.append("lang", langEl.value);
      body.append("speed", speedEl.value);
      const r = await fetch("/usar", { method: "POST", body });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error?.message || "Falhou.");
      const url = URL.createObjectURL(await r.blob());
      previewAudio = new Audio(url);
      previewBtn.textContent = "Parar";
      previewAudio.onended = () => { previewBtn.textContent = "Ouvir amostra"; previewAudio = null; URL.revokeObjectURL(url); };
      await previewAudio.play();
    } catch (e) {
      say(e.message, "err");
      previewBtn.textContent = "Ouvir amostra";
    } finally {
      previewBtn.disabled = false;
    }
  };

  // ---------------------------------------------------------------- Progresso / status
  const status = $("status");
  const progress = $("progress");
  const fill = $("fill");
  const steps = [...document.querySelectorAll("#steps li")];
  function say(msg, cls) { status.className = "status " + (cls || ""); status.textContent = msg; }
  function setStep(name, pct, indet) {
    progress.hidden = false;
    let passed = true;
    steps.forEach((li) => {
      const on = li.dataset.step === name;
      li.classList.toggle("on", on);
      li.classList.toggle("done", passed && !on);
      if (on) passed = false;
    });
    fill.classList.toggle("indet", !!indet);
    fill.style.width = pct + "%";
  }
  function fmtDur(s) {
    s = Math.max(0, Math.round(s));
    const m = Math.floor(s / 60), r = s % 60;
    return m ? `${m}min ${String(r).padStart(2, "0")}s` : `${r}s`;
  }

  // ---------------------------------------------------------------- Resultado
  const result = $("result");
  const player = $("player");
  const down = $("down");
  const preview = $("preview");
  const truncatedEl = $("truncated");
  const toggleText = $("toggle-text");
  const copyBtn = $("copy");
  let lastUrl = null;
  let lastText = "";

  toggleText.onclick = () => {
    const open = preview.hidden;
    preview.hidden = !open;
    toggleText.textContent = open ? "Ocultar texto" : "Ver texto";
    toggleText.setAttribute("aria-expanded", String(open));
  };
  copyBtn.onclick = async () => {
    try { await navigator.clipboard.writeText(lastText); copyBtn.textContent = "Copiado ✓"; }
    catch { copyBtn.textContent = "Não deu para copiar"; }
    setTimeout(() => (copyBtn.textContent = "Copiar texto"), 1600);
  };

  // ---------------------------------------------------------------- Histórico (sessão)
  const historyWrap = $("history-wrap");
  const historyEl = $("history");
  const history = [];
  function addHistory(item) {
    history.unshift(item);
    if (history.length > 8) { const old = history.pop(); URL.revokeObjectURL(old.url); }
    renderHistory();
  }
  function renderHistory() {
    historyWrap.hidden = history.length === 0;
    historyEl.innerHTML = "";
    history.forEach((h) => {
      const li = document.createElement("li");
      li.innerHTML = `
        <button class="play" type="button" aria-label="Tocar">▶</button>
        <div class="info"><div class="title"></div><div class="sub"></div></div>
        <a class="dl" download="${h.filename}">Baixar</a>`;
      li.querySelector(".title").textContent = h.title;
      li.querySelector(".sub").textContent = `${VOICE_LABELS[h.voice] || h.voice} · ${h.duration ? fmtDur(h.duration) : ""} · ${h.when}`;
      li.querySelector(".dl").href = h.url;
      li.querySelector(".play").onclick = () => {
        player.src = h.url; down.href = h.url; down.download = h.filename;
        lastText = h.text; preview.textContent = h.text;
        result.hidden = false; player.play().catch(() => {});
        result.scrollIntoView({ behavior: "smooth", block: "nearest" });
      };
      historyEl.appendChild(li);
    });
  }
  $("clear-history").onclick = () => { history.forEach((h) => URL.revokeObjectURL(h.url)); history.length = 0; renderHistory(); };

  // ---------------------------------------------------------------- Gerar
  const go = $("go");
  const MAX_MB = parseInt($("max-mb").textContent, 10) || 60;

  async function requestAudio(form) {
    const res = await fetch("/usar", { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error?.message || `Não deu para concluir (HTTP ${res.status}).`);
    }
    return res;
  }

  go.onclick = async () => {
    result.hidden = true;
    preview.hidden = true;
    toggleText.textContent = "Ver texto";
    truncatedEl.hidden = true;
    progress.hidden = true;
    fill.classList.remove("indet");
    fill.style.width = "0%";
    if (lastUrl) { lastUrl = null; }
    go.disabled = true;
    say("");

    let title = "";
    try {
      const body = new FormData();
      body.append("voice", voice);
      body.append("lang", langEl.value);
      body.append("speed", speedEl.value);

      if (mode === "file") {
        if (!chosen) { say("Escolha um arquivo.", "err"); return; }
        if (chosen.size > MAX_MB * 1048576) { say(`Arquivo maior que ${MAX_MB} MB.`, "err"); return; }
        body.append("file", chosen);
        title = chosen.name;
        const isMedia = /\.(mp4|webm|mov|mkv|mp3|wav|m4a|ogg|flac)$/i.test(chosen.name);
        setStep("read", 15, true);
        say(isMedia ? "Transcrevendo o áudio… pode demorar alguns minutos." : "Lendo o documento…");
      } else if (mode === "video") {
        const link = $("video-url").value.trim();
        if (!link) { say("Cole o link do vídeo.", "err"); return; }
        body.append("url", link);
        title = link.replace(/^https?:\/\//, "").slice(0, 60);
        setStep("read", 15, true);
        say("Baixando e transcrevendo o vídeo… pode demorar.");
      } else {
        const text = textEl.value.trim();
        if (!text) { say("Cole um texto.", "err"); return; }
        body.append("text", text);
        title = text.slice(0, 60) + (text.length > 60 ? "…" : "");
        setStep("tts", 45, true);
        say("Gerando áudio…");
      }

      const t0 = performance.now();
      let res = await requestAudio(body);
      let text = "";
      let blob;
      const type = res.headers.get("content-type") || "";

      if (type.includes("application/json")) {
        // Transcrição pronta → mostrar texto e pedir o áudio
        const payload = await res.json();
        text = payload.text || "";
        if (payload.truncated) truncatedEl.hidden = false;
        if (text) { preview.textContent = text; preview.hidden = false; toggleText.textContent = "Ocultar texto"; result.hidden = false; }
        setStep("tts", 55, true);
        say("Transcrição pronta. Gerando áudio…");
        const speak = new FormData();
        speak.append("voice", voice);
        speak.append("lang", langEl.value);
        speak.append("speed", speedEl.value);
        speak.append("text", text);
        res = await requestAudio(speak);
      } else {
        setStep("tts", 70, true);
      }

      const raw = res.headers.get("X-Texto") || "";
      if (raw) { try { text = decodeURIComponent(raw); } catch { text = raw; } }
      if (res.headers.get("X-Truncated") === "1") truncatedEl.hidden = false;
      const duration = parseFloat(res.headers.get("X-Duration-Seconds") || "0");
      blob = await res.blob();

      if (lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = URL.createObjectURL(blob);
      lastText = text;
      const ext = (blob.type.split("/")[1] || "wav").replace("x-", "");
      const filename = `supertonic-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")}.${ext}`;

      preview.textContent = text;
      player.src = lastUrl;
      down.href = lastUrl;
      down.download = filename;
      result.hidden = false;
      setStep("done", 100, false);
      const took = ((performance.now() - t0) / 1000).toFixed(1);
      say(`Pronto${duration ? ` · ${fmtDur(duration)} de áudio` : ""} · gerado em ${took}s.`, "ok");
      await player.play().catch(() => {});
      result.scrollIntoView({ behavior: "smooth", block: "nearest" });

      addHistory({ url: lastUrl, filename, title, voice, duration, text, when: new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) });
      lastUrl = null; // agora pertence ao histórico
    } catch (e) {
      progress.hidden = true;
      say(e.message || String(e), "err");
    } finally {
      go.disabled = false;
    }
  };

  // Atalho: Ctrl/Cmd + Enter gera
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !go.disabled) go.click();
  });

  // ---------------------------------------------------------------- PWA
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
})();
