/* Transcript Study — paste a YouTube link, study what is said in it. */

const $ = (id) => document.getElementById(id);

const state = {
  video: null,       // {id, title, channel, duration}
  lang: "en",
  segments: [],
  source: "",
  active: -1,
  loop: false,
  follow: true,
  player: null,
  ready: false,
  words: [],         // saved vocabulary for the current video
};

const DICTIONARY = {
  en: (word) => `https://en.wiktionary.org/wiki/${encodeURIComponent(word)}`,
  de: (word) => `https://www.dwds.de/wb/${encodeURIComponent(word)}`,
  ja: (word) => `https://jisho.org/search/${encodeURIComponent(word)}`,
};

/* ------------------------------------------------------------------ setup */

document.addEventListener("DOMContentLoaded", () => {
  const saved = localStorage.getItem("ts-theme");
  if (saved) document.documentElement.dataset.theme = saved;

  $("load-form").addEventListener("submit", onSubmit);
  $("error-retry").addEventListener("click", () => show("welcome"));
  $("theme-toggle").addEventListener("click", toggleTheme);
  $("search").addEventListener("input", onSearch);

  $("btn-play").addEventListener("click", togglePlay);
  $("btn-prev").addEventListener("click", () => step(-1));
  $("btn-next").addEventListener("click", () => step(1));
  $("btn-loop").addEventListener("click", toggleLoop);
  $("speed").addEventListener("change", (event) => {
    if (state.player) state.player.setPlaybackRate(parseFloat(event.target.value));
  });

  $("opt-follow").addEventListener("change", (event) => (state.follow = event.target.checked));
  $("opt-blur").addEventListener("change", (event) =>
    $("study").classList.toggle("blurred", event.target.checked)
  );
  $("opt-furigana").addEventListener("change", (event) =>
    $("transcript").classList.toggle("no-furigana", !event.target.checked)
  );

  $("clear-words").addEventListener("click", clearWords);
  $("export-csv").addEventListener("click", exportCsv);
  document.querySelectorAll("[data-export]").forEach((button) =>
    button.addEventListener("click", () => exportTranscript(button.dataset.export))
  );

  document.addEventListener("keydown", onKey);

  loadCapabilities();
  renderRecents();

  const fromUrl = new URLSearchParams(location.search).get("v");
  if (fromUrl) {
    $("url").value = fromUrl;
    $("load-form").requestSubmit();
  }
});

async function loadCapabilities() {
  try {
    const caps = await (await fetch("/api/capabilities")).json();
    const notes = [];
    notes.push(
      caps.whisper
        ? `Videos without captions are transcribed offline with Whisper (${caps.whisper_model}).`
        : "Offline transcription is off — videos without captions will fail. Run ./setup.sh --with-whisper."
    );
    if (!caps.furigana) notes.push("Furigana is off — run ./setup.sh to install the Japanese tokenizer.");
    $("capability-note").textContent = notes.join(" ");
  } catch {
    /* the note is cosmetic */
  }
}

/* --------------------------------------------------------------- fetching */

async function onSubmit(event) {
  event.preventDefault();
  const url = $("url").value.trim();
  if (!url) return;

  $("go").disabled = true;
  show("progress");
  setProgress("Looking up the video…", 0);
  $("progress-hint").textContent = "";

  try {
    const start = await post("/api/transcribe", { url, lang: $("lang").value });
    if (start.error) throw new Error(start.error);
    await poll(start.job);
  } catch (error) {
    fail(error.message);
  } finally {
    $("go").disabled = false;
  }
}

async function poll(jobId) {
  let hintShown = false;
  for (;;) {
    await sleep(600);
    const job = await (await fetch(`/api/job/${jobId}`)).json();

    if (job.status === "error") throw new Error(job.error);
    setProgress(job.stage, job.percent);

    if (!hintShown && /Transcrib|Downloading audio|speech model/.test(job.stage || "")) {
      hintShown = true;
      $("progress-hint").textContent =
        "No captions on this one, so the audio is being transcribed here on your machine. " +
        "This takes a few minutes for a long video — the result is cached afterwards.";
    }

    if (job.status === "done") {
      openStudy(job.meta, job.result);
      return;
    }
  }
}

function openStudy(meta, result) {
  state.video = meta;
  state.lang = result.language;
  state.segments = result.segments;
  state.source = result.source;
  state.active = -1;
  state.words = loadWords(meta.id);

  $("video-title").textContent = meta.title;
  $("video-sub").textContent = [meta.channel, formatTime(meta.duration)].filter(Boolean).join(" · ");
  $("source-badge").textContent =
    (result.source.startsWith("whisper") ? "whisper · " : "youtube · ") + state.lang;

  $("study").classList.toggle("ja", state.lang === "ja");
  $("furigana-field").style.display =
    state.lang === "ja" && state.segments.some((seg) => seg.tokens) ? "" : "none";

  renderTranscript();
  renderWords();
  show("study");
  mountPlayer(meta.id);
  rememberRecent(meta);
  history.replaceState(null, "", `?v=${meta.id}`);
}

/* -------------------------------------------------------------- rendering */

function renderTranscript() {
  const container = $("transcript");
  container.innerHTML = "";
  container.classList.toggle("no-furigana", !$("opt-furigana").checked);

  const fragment = document.createDocumentFragment();
  state.segments.forEach((segment, index) => {
    const row = document.createElement("div");
    row.className = "seg";
    row.dataset.index = index;

    const time = document.createElement("button");
    time.className = "time";
    time.textContent = formatTime(segment.start);
    time.title = "Jump here";
    time.addEventListener("click", (event) => {
      event.stopPropagation();
      seekToSegment(index);
    });

    const text = document.createElement("div");
    text.className = "text";
    buildTokens(segment).forEach((token) => text.appendChild(tokenNode(token, segment)));

    row.append(time, text);
    row.addEventListener("click", () => seekToSegment(index));
    fragment.appendChild(row);
  });
  container.appendChild(fragment);
}

/** One segment -> display tokens: {text, time, word, ruby}. */
function buildTokens(segment) {
  if (segment.tokens) {
    // Japanese: the backend already split words and worked out the furigana.
    return segment.tokens.map((token) => ({
      text: token.s,
      ruby: token.ruby,
      word: token.v ? token.b || token.s : null,
      reading: token.r,
      time: null,
    }));
  }

  const timed = (segment.words || []).filter((entry) => entry.w.trim());
  const out = [];
  const source = timed.length ? timed : [{ t: segment.start, w: segment.text }];

  source.forEach((entry) => {
    // A caption chunk can hold several words; give each the chunk's timestamp.
    entry.w.split(/(\s+)/).forEach((piece) => {
      if (!piece) return;
      if (!piece.trim()) {
        out.push({ text: piece, word: null, time: null });
        return;
      }
      out.push({ text: piece, word: cleanWord(piece), time: entry.t });
    });
  });

  // Collapse the double spaces that chunk boundaries leave behind.
  const kept = [];
  out.forEach((token) => {
    const blank = !token.text.trim();
    const previousBlank = kept.length ? !kept[kept.length - 1].text.trim() : true;
    if (blank && previousBlank) return;
    kept.push(token);
  });
  while (kept.length && !kept[kept.length - 1].text.trim()) kept.pop();
  return kept;
}

function tokenNode(token, segment) {
  if (!token.word) {
    const span = document.createElement("span");
    span.className = "punct";
    span.appendChild(rubyOrText(token));
    return span;
  }

  const span = document.createElement("span");
  span.className = "w";
  if (token.time != null) span.dataset.time = token.time;
  span.dataset.word = token.word;
  if (token.reading) span.title = token.reading;
  if (state.words.some((saved) => saved.word === token.word)) span.classList.add("saved");
  span.appendChild(rubyOrText(token));

  span.addEventListener("click", (event) => {
    event.stopPropagation();
    saveWord(token, segment, span);
  });
  return span;
}

function rubyOrText(token) {
  if (!token.ruby || token.ruby.length === 0) return document.createTextNode(token.text);
  if (token.ruby.length === 1 && !token.ruby[0][1]) return document.createTextNode(token.text);

  const fragment = document.createDocumentFragment();
  token.ruby.forEach(([base, reading]) => {
    if (!reading) {
      fragment.appendChild(document.createTextNode(base));
      return;
    }
    const ruby = document.createElement("ruby");
    ruby.appendChild(document.createTextNode(base));
    const rt = document.createElement("rt");
    rt.textContent = reading;
    ruby.appendChild(rt);
    fragment.appendChild(ruby);
  });
  return fragment;
}

function cleanWord(piece) {
  const stripped = piece.replace(/^[^\p{L}\p{N}'’-]+|[^\p{L}\p{N}'’-]+$/gu, "");
  return stripped.length ? stripped : null;
}

/* ----------------------------------------------------------- the player */

function mountPlayer(videoId) {
  if (state.player && state.ready) {
    state.player.loadVideoById(videoId);
    return;
  }
  loadYouTubeApi().then(() => {
    state.player = new YT.Player("player", {
      videoId,
      playerVars: { rel: 0, modestbranding: 1, playsinline: 1 },
      events: {
        onReady: () => {
          state.ready = true;
          state.player.setPlaybackRate(parseFloat($("speed").value));
          startTicker();
        },
        onStateChange: (event) => {
          const playing = event.data === YT.PlayerState.PLAYING;
          $("btn-play").textContent = playing ? "❚❚ Pause" : "▶ Play";
        },
      },
    });
  });
}

function loadYouTubeApi() {
  if (window.YT && window.YT.Player) return Promise.resolve();
  return new Promise((resolve) => {
    window.onYouTubeIframeAPIReady = resolve;
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(script);
  });
}

function startTicker() {
  setInterval(tick, 120);
}

function tick() {
  if (!state.ready || !state.segments.length) return;
  let now;
  try {
    now = state.player.getCurrentTime();
  } catch {
    return;
  }

  const index = findSegment(now);

  if (state.loop && state.active >= 0) {
    const current = state.segments[state.active];
    if (now >= current.end - 0.05 || now < current.start - 0.4) {
      state.player.seekTo(current.start, true);
      return;
    }
  }

  if (index !== state.active) {
    setActive(index);
  }
  paintSpokenWords(now);
}

function findSegment(now) {
  const segments = state.segments;
  let low = 0;
  let high = segments.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (segments[mid].start <= now) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  if (found >= 0 && now > segments[found].end + 2) return -1; // long silence
  return found;
}

function setActive(index) {
  document.querySelector(".seg.active")?.classList.remove("active");
  state.active = index;
  if (index < 0) return;

  const row = document.querySelector(`.seg[data-index="${index}"]`);
  if (!row) return;
  row.classList.add("active");
  if (state.follow) row.scrollIntoView({ behavior: "smooth", block: "center" });
}

function paintSpokenWords(now) {
  if (state.active < 0) return;
  const row = document.querySelector(".seg.active");
  if (!row) return;
  row.querySelectorAll(".w[data-time]").forEach((span) => {
    const spoken = parseFloat(span.dataset.time) <= now + 0.15;
    span.classList.toggle("spoken", spoken);
    span.classList.toggle("pending", !spoken);
  });
}

function seekToSegment(index) {
  if (!state.ready) return;
  const segment = state.segments[index];
  state.player.seekTo(segment.start, true);
  state.player.playVideo();
  setActive(index);
}

function togglePlay() {
  if (!state.ready) return;
  const playing = state.player.getPlayerState() === YT.PlayerState.PLAYING;
  playing ? state.player.pauseVideo() : state.player.playVideo();
}

function step(direction) {
  const next = Math.min(Math.max((state.active < 0 ? 0 : state.active) + direction, 0), state.segments.length - 1);
  seekToSegment(next);
}

function toggleLoop() {
  state.loop = !state.loop;
  $("btn-loop").classList.toggle("on", state.loop);
  if (state.loop && state.active < 0) setActive(0);
  toast(state.loop ? "Looping this line" : "Loop off");
}

function onKey(event) {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName)) return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if ($("study").hidden) return;

  const actions = {
    " ": togglePlay,
    ArrowLeft: () => step(-1),
    ArrowRight: () => step(1),
    r: toggleLoop,
    R: toggleLoop,
    f: () => $("opt-follow").click(),
    h: () => $("opt-blur").click(),
    "/": () => $("search").focus(),
  };
  const action = actions[event.key];
  if (!action) return;
  event.preventDefault();
  action();
}

/* -------------------------------------------------------------- word list */

function saveWord(token, segment, span) {
  const word = token.word;
  const existing = state.words.findIndex((saved) => saved.word === word);
  if (existing >= 0) {
    state.words.splice(existing, 1);
    toast(`Removed “${word}”`);
  } else {
    state.words.push({
      word,
      reading: token.reading || "",
      sentence: segment.text,
      at: segment.start,
    });
    toast(`Saved “${word}”`);
  }
  persistWords();
  document
    .querySelectorAll(`.w[data-word="${cssEscape(word)}"]`)
    .forEach((node) => node.classList.toggle("saved", existing < 0));
  renderWords();
  if (span) span.blur();
}

function renderWords() {
  const container = $("words");
  container.innerHTML = "";
  $("word-count").textContent = state.words.length;
  document.querySelector(".wordlist").classList.toggle("has-words", state.words.length > 0);

  state.words
    .slice()
    .sort((a, b) => a.at - b.at)
    .forEach((entry) => {
      const row = document.createElement("div");
      row.className = "word-row";

      const at = document.createElement("button");
      at.className = "at";
      at.textContent = formatTime(entry.at);
      at.addEventListener("click", () => {
        const index = state.segments.findIndex((segment) => segment.start === entry.at);
        if (index >= 0) seekToSegment(index);
      });

      const word = document.createElement("b");
      word.textContent = entry.word + (entry.reading ? `（${entry.reading}）` : "");

      const link = document.createElement("a");
      link.href = DICTIONARY[state.lang](entry.word);
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "ctx";
      link.textContent = entry.sentence;
      link.title = "Look this word up";

      const remove = document.createElement("button");
      remove.className = "rm";
      remove.textContent = "✕";
      remove.title = "Remove";
      remove.addEventListener("click", () => {
        state.words = state.words.filter((saved) => saved.word !== entry.word);
        persistWords();
        document
          .querySelectorAll(`.w[data-word="${cssEscape(entry.word)}"]`)
          .forEach((node) => node.classList.remove("saved"));
        renderWords();
      });

      row.append(at, word, link, remove);
      container.appendChild(row);
    });
}

function clearWords() {
  if (!state.words.length) return;
  if (!confirm("Clear the whole word list for this video?")) return;
  state.words = [];
  persistWords();
  document.querySelectorAll(".w.saved").forEach((node) => node.classList.remove("saved"));
  renderWords();
}

const wordsKey = (videoId) => `ts-words-${videoId}`;

function loadWords(videoId) {
  try {
    return JSON.parse(localStorage.getItem(wordsKey(videoId))) || [];
  } catch {
    return [];
  }
}

function persistWords() {
  try {
    localStorage.setItem(wordsKey(state.video.id), JSON.stringify(state.words));
  } catch {
    toast("Could not save the word list in this browser");
  }
}

/* ---------------------------------------------------------------- exports */

function exportTranscript(kind) {
  const title = state.video.title.replace(/[^\w\u00c0-\u024f\u3040-\u30ff\u4e00-\u9fff -]/g, "").trim();
  const link = `https://youtu.be/${state.video.id}`;

  if (kind === "txt") {
    const body = state.segments.map((segment) => `[${formatTime(segment.start)}] ${segment.text}`).join("\n");
    download(`${title}.txt`, `${state.video.title}\n${link}\n\n${body}\n`);
  } else if (kind === "srt") {
    const body = state.segments
      .map(
        (segment, index) =>
          `${index + 1}\n${srtTime(segment.start)} --> ${srtTime(segment.end)}\n${segment.text}\n`
      )
      .join("\n");
    download(`${title}.srt`, body);
  } else {
    const body = state.segments
      .map(
        (segment) =>
          `- [\`${formatTime(segment.start)}\`](${link}?t=${Math.floor(segment.start)}) ${segment.text}`
      )
      .join("\n");
    download(`${title}.md`, `# ${state.video.title}\n\n[${link}](${link})\n\n${body}\n`);
  }
}

function exportCsv() {
  if (!state.words.length) {
    toast("No saved words yet");
    return;
  }
  const rows = state.words
    .slice()
    .sort((a, b) => a.at - b.at)
    .map((entry) =>
      [
        entry.word,
        entry.reading,
        entry.sentence,
        `https://youtu.be/${state.video.id}?t=${Math.floor(entry.at)}`,
      ]
        .map((field) => `"${String(field).replace(/"/g, '""')}"`)
        .join(",")
    );
  download(`${state.video.id}-words.csv`, "Word,Reading,Sentence,Source\n" + rows.join("\n") + "\n");
}

function download(filename, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
  toast(`Saved ${filename}`);
}

/* -------------------------------------------------------------- recents */

function rememberRecent(meta) {
  let recents = [];
  try {
    recents = JSON.parse(localStorage.getItem("ts-recents")) || [];
  } catch {
    recents = [];
  }
  recents = recents.filter((item) => item.id !== meta.id);
  recents.unshift({ id: meta.id, title: meta.title, duration: meta.duration });
  localStorage.setItem("ts-recents", JSON.stringify(recents.slice(0, 8)));
}

function renderRecents() {
  let recents = [];
  try {
    recents = JSON.parse(localStorage.getItem("ts-recents")) || [];
  } catch {
    return;
  }
  if (!recents.length) return;

  $("recents").hidden = false;
  const list = $("recents-list");
  list.innerHTML = "";
  recents.forEach((item) => {
    const button = document.createElement("button");
    button.className = "recent";
    const title = document.createElement("span");
    title.textContent = item.title;
    const time = document.createElement("span");
    time.textContent = formatTime(item.duration);
    button.append(title, time);
    button.addEventListener("click", () => {
      $("url").value = `https://youtu.be/${item.id}`;
      $("load-form").requestSubmit();
    });
    list.appendChild(button);
  });
}

/* ---------------------------------------------------------------- search */

function onSearch(event) {
  const query = event.target.value.trim().toLowerCase();
  document.querySelectorAll(".seg").forEach((row) => {
    const segment = state.segments[+row.dataset.index];
    const hit = !query || segment.text.toLowerCase().includes(query);
    row.classList.toggle("hidden", !hit);
  });
}

/* ----------------------------------------------------------------- utils */

function show(section) {
  ["welcome", "progress", "error", "study"].forEach((id) => ($(id).hidden = id !== section));
  if (section === "welcome") renderRecents();
}

function setProgress(stage, percent) {
  $("progress-stage").textContent = stage || "Working…";
  $("progress-bar").style.width = `${percent || 0}%`;
}

function fail(message) {
  $("error-text").textContent = message;
  show("error");
}

function toggleTheme() {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const current = document.documentElement.dataset.theme || (dark ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("ts-theme", next);
}

let toastTimer;
function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (element.hidden = true), 1800);
}

function formatTime(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  const pad = (value) => String(value).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

function srtTime(seconds) {
  const ms = Math.floor((seconds % 1) * 1000);
  const total = Math.floor(seconds);
  const pad = (value, width = 2) => String(value).padStart(width, "0");
  return `${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)},${pad(ms, 3)}`;
}

function cssEscape(value) {
  return window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
