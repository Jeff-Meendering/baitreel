// The labeling page. Plain JavaScript, no build step.
//
// The page knows only the transcript, the recording and the Field Guide. It
// never receives Baitreel's own flags or redactions, so the labels made here
// are blind. Every change is saved to the server straight away.

"use strict";

const $ = (id) => document.getElementById(id);
const audio = $("audio");
const state = {
  call: null,
  words: [], // every word in the call, in order: {text, start, end, line, el}
  flags: [],
  details: [],
  selection: null, // {start, end, from, to} — from/to are word indexes, or null for a time range
  anchor: null, // the word a click or drag started from
  dragging: false,
  current: -1, // the word being heard
  finished: false,
};

// --- Helpers -----------------------------------------------------------------

function clock(seconds, tenths = false) {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  const whole = Math.floor(s).toString().padStart(2, "0");
  return tenths ? `${m}:${whole}.${Math.floor((s % 1) * 10)}` : `${m}:${whole}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

const overlaps = (a0, a1, b0, b1) => Math.min(a1, b1) - Math.max(a0, b0) > 0;
const middle = (w) => (w.start + w.end) / 2;
const tacticName = (id) => state.call.tactics.find((t) => t.id === id)?.name ?? id;

function lineAt(time) {
  const lines = state.call.lines;
  for (const line of lines) if (time <= line.end + 0.3) return line;
  return lines[lines.length - 1];
}

function wordAt(time) {
  // The last word that has started by this time (binary search).
  let lo = 0;
  let hi = state.words.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (state.words[mid].start <= time) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found >= 0 && time <= state.words[found].end + 0.25 ? found : -1;
}

// --- Saving ------------------------------------------------------------------

let saveTimer = null;

function scheduleSave(finished = false) {
  clearTimeout(saveTimer);
  $("saved").textContent = "Saving…";
  $("saved").classList.remove("error");
  return new Promise((resolve) => {
    saveTimer = setTimeout(() => save(finished).then(resolve), finished ? 0 : 250);
  });
}

async function save(finished = false) {
  try {
    const response = await fetch("api/labels", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ flags: state.flags, details: state.details, finished }),
    });
    const answer = await response.json();
    if (!response.ok) throw new Error(answer.error || response.statusText);
    state.finished = answer.finished;
    $("saved").textContent = "All changes saved";
    return true;
  } catch (error) {
    $("saved").textContent = "Not saved. Is `baitreel label` still running in the terminal?";
    $("saved").classList.add("error");
    return false;
  }
}

// --- Drawing ------------------------------------------------------------------

function drawTranscript() {
  const box = $("transcript");
  box.replaceChildren();
  state.words = [];
  for (const line of state.call.lines) {
    const words = el("div", { class: "words" });
    line.words.forEach((word, n) => {
      const index = state.words.length;
      const span = el("span", { class: "w", "data-i": index }, word.text);
      state.words.push({ ...word, line: line.id, el: span });
      words.append(span, n < line.words.length - 1 ? " " : "");
    });
    const row = el(
      "div",
      { class: "line", id: `line-${line.id}` },
      el("button", { class: "time", type: "button", onclick: () => seek(line.start) }, clock(line.start)),
      words,
      el("div", { class: "chips", id: `chips-${line.id}` }),
    );
    box.append(row);
  }
}

function drawMarks() {
  for (const word of state.words) {
    const mid = middle(word);
    const sel = state.selection;
    word.el.classList.toggle("tactic", state.flags.some((f) => mid >= f.start && mid <= f.end));
    word.el.classList.toggle(
      "detail",
      state.details.some((d) => overlaps(word.start, word.end, d.start, d.end)),
    );
    word.el.classList.toggle("sel", !!sel && mid >= sel.start && mid <= sel.end);
  }
  document.querySelectorAll(".chips").forEach((box) => box.replaceChildren());
  const chip = (label, cls, remove) =>
    el("span", { class: `chip ${cls}` }, label, el("button", { type: "button", "aria-label": `Remove ${label}`, onclick: remove }, "×"));
  state.flags.forEach((flag, i) => {
    $(`chips-${lineAt(flag.start).id}`).append(chip(tacticName(flag.tactic), "", () => removeLabel("flags", i)));
  });
  state.details.forEach((detail, i) => {
    $(`chips-${lineAt(detail.start).id}`).append(chip(`personal detail: ${detail.kind}`, "pii", () => removeLabel("details", i)));
  });
  drawSelection();
  drawList();
}

function drawSelection() {
  const sel = state.selection;
  $("clear").hidden = !sel;
  for (const button of document.querySelectorAll(".tactic-pick, .kinds button")) button.disabled = !sel;
  if (!sel) {
    $("selection").textContent = "Nothing selected. Click a word, or press [ and ] while listening.";
    return;
  }
  const words = state.words.filter((w) => middle(w) >= sel.start && middle(w) <= sel.end).map((w) => w.text);
  const text = words.length > 14 ? words.slice(0, 14).join(" ") + " …" : words.join(" ");
  $("selection").replaceChildren(
    `${clock(sel.start, true)} to ${clock(sel.end, true)} `,
    text ? el("q", {}, text) : el("span", { class: "labeler" }, "(no transcript words: a time range)"),
  );
}

function drawList() {
  const items = [
    ...state.flags.map((f, i) => ({ ...f, what: tacticName(f.tactic), group: "flags", i })),
    ...state.details.map((d, i) => ({ ...d, what: `Personal detail: ${d.kind}`, group: "details", i })),
  ].sort((a, b) => a.start - b.start);
  $("count").textContent = items.length ? `(${items.length})` : "";
  const list = $("list");
  list.replaceChildren();
  if (!items.length) {
    list.append(el("li", { class: "empty" }, "None yet."));
    return;
  }
  for (const item of items) {
    list.append(
      el(
        "li",
        {},
        el("button", { class: "at", type: "button", onclick: () => seek(item.start), title: "Jump here" }, clock(item.start)),
        el("span", {}, item.what),
        el("button", { class: "remove", type: "button", "aria-label": `Remove ${item.what}`, onclick: () => removeLabel(item.group, item.i) }, "×"),
      ),
    );
  }
}

function drawPanel() {
  const box = $("tactics");
  for (const tactic of state.call.tactics) {
    const about = el(
      "div",
      { class: "about", hidden: "" },
      tactic.description,
      el("ul", {}, ...tactic.sounds_like.map((s) => el("li", {}, `“${s}”`))),
    );
    box.append(
      el(
        "div",
        { class: "tactic-row" },
        el(
          "button",
          { class: "tactic-pick", type: "button", onclick: () => addFlag(tactic.id) },
          el("b", {}, tactic.name),
          el("span", {}, tactic.plain_label),
        ),
        el("button", { class: "more", type: "button", title: "What this sounds like", "aria-expanded": "false", onclick: (e) => {
          about.hidden = !about.hidden;
          e.currentTarget.setAttribute("aria-expanded", String(!about.hidden));
        } }, "?"),
        about,
      ),
    );
  }
  for (const kind of state.call.kinds) {
    $("kinds").append(el("button", { type: "button", onclick: () => addDetail(kind) }, kind));
  }
}

// --- Editing ------------------------------------------------------------------

function selectWords(from, to) {
  const [a, b] = from <= to ? [from, to] : [to, from];
  state.selection = { start: state.words[a].start, end: state.words[b].end, from: a, to: b };
  drawMarks();
}

function addFlag(tactic) {
  const sel = state.selection;
  if (!sel) return;
  state.flags.push({ tactic, start: sel.start, end: sel.end });
  state.selection = null;
  drawMarks();
  scheduleSave();
}

function addDetail(kind) {
  const sel = state.selection;
  if (!sel) return;
  state.details.push({ kind, start: sel.start, end: sel.end });
  state.selection = null;
  drawMarks();
  scheduleSave();
}

function removeLabel(group, index) {
  state[group].splice(index, 1);
  drawMarks();
  scheduleSave();
}

// --- Playing ------------------------------------------------------------------

function seek(time) {
  audio.currentTime = Math.max(0, Math.min(time, audio.duration || state.call.duration));
  tick();
}

function tick() {
  const t = audio.currentTime;
  const total = audio.duration || state.call.duration;
  $("clock").textContent = `${clock(t)} / ${clock(total)}`;
  if (document.activeElement !== $("scrub")) $("scrub").value = String((t / total) * 100 || 0);
  const now = wordAt(t);
  if (now !== state.current) {
    state.words[state.current]?.el.classList.remove("now");
    state.current = now;
    const word = state.words[now];
    if (word) {
      word.el.classList.add("now");
      if ($("follow").checked && !audio.paused) {
        const box = word.el.getBoundingClientRect();
        if (box.top < 120 || box.bottom > window.innerHeight - 40) {
          word.el.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      }
    }
  }
}

function loop() {
  tick();
  if (!audio.paused) requestAnimationFrame(loop);
}

function togglePlay() {
  if (audio.paused) audio.play();
  else audio.pause();
}

// --- Wiring --------------------------------------------------------------------

function wire() {
  const box = $("transcript");
  box.addEventListener("mousedown", (event) => {
    const target = event.target.closest(".w");
    if (!target) return;
    event.preventDefault();
    const i = Number(target.dataset.i);
    if (event.shiftKey && state.anchor !== null) {
      selectWords(state.anchor, i);
    } else {
      state.anchor = i;
      selectWords(i, i);
      seek(state.words[i].start);
    }
    state.dragging = true;
  });
  box.addEventListener("mouseover", (event) => {
    const target = event.target.closest(".w");
    if (state.dragging && target && state.anchor !== null) selectWords(state.anchor, Number(target.dataset.i));
  });
  document.addEventListener("mouseup", () => (state.dragging = false));

  $("play").addEventListener("click", togglePlay);
  $("back").addEventListener("click", () => seek(audio.currentTime - 5));
  $("ahead").addEventListener("click", () => seek(audio.currentTime + 5));
  $("speed").addEventListener("change", (e) => (audio.playbackRate = Number(e.target.value)));
  $("scrub").addEventListener("input", (e) => seek((Number(e.target.value) / 100) * (audio.duration || state.call.duration)));
  $("clear").addEventListener("click", () => {
    state.selection = null;
    drawMarks();
  });
  audio.addEventListener("play", () => {
    $("play").textContent = "❚❚";
    $("play").setAttribute("aria-label", "Pause");
    requestAnimationFrame(loop);
  });
  audio.addEventListener("pause", () => {
    $("play").textContent = "▶";
    $("play").setAttribute("aria-label", "Play");
    tick();
  });
  audio.addEventListener("loadedmetadata", tick);

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, select, textarea") || event.metaKey || event.ctrlKey) return;
    const t = audio.currentTime;
    if (event.key === " ") {
      event.preventDefault();
      togglePlay();
    } else if (event.key === "ArrowLeft") {
      seek(t - 5);
    } else if (event.key === "ArrowRight") {
      seek(t + 5);
    } else if (event.key === "[") {
      state.selection = { start: t, end: Math.min(t + 1, audio.duration || t + 1), from: null, to: null };
      drawMarks();
    } else if (event.key === "]") {
      const start = state.selection ? state.selection.start : Math.max(t - 1, 0);
      state.selection = { start: Math.min(start, t), end: Math.max(start, t), from: null, to: null };
      drawMarks();
    } else if (event.key === "Escape") {
      state.selection = null;
      drawMarks();
    }
  });

  $("finish").addEventListener("click", async () => {
    const ok = window.confirm(
      "Have you been through the whole call?\n\nOnly finished labels are scored. You can reopen them later with `baitreel label`.",
    );
    if (!ok) return;
    clearTimeout(saveTimer);
    if (!(await save(true))) return;
    await fetch("api/done", { method: "POST" }).catch(() => {});
    audio.pause();
    $("done").hidden = false;
  });

  window.addEventListener("beforeunload", (event) => {
    if ($("saved").classList.contains("error") || $("saved").textContent === "Saving…") {
      event.preventDefault();
    }
  });
}

async function start() {
  const response = await fetch("api/call");
  state.call = await response.json();
  state.flags = state.call.labels.flags;
  state.details = state.call.labels.details;
  state.finished = state.call.finished;
  document.title = `Labeling: ${state.call.title}`;
  $("title").textContent = state.call.title;
  $("labeler").textContent = `labeled by ${state.call.labeler}`;
  $("saved").textContent = state.finished ? "Finished earlier. Changes are still saved." : "";
  if (state.call.tool_ran_first) {
    $("warning").hidden = false;
    $("warning").textContent =
      "Baitreel has already looked at this call. To keep your labels blind, do not open its clips or flags until you finish.";
  }
  if (state.flags.length || state.details.length) $("howto").open = false;
  audio.src = "audio";
  drawTranscript();
  drawPanel();
  drawMarks();
  wire();
  tick();
}

start().catch(() => {
  $("title").textContent = "Could not load the call. Is `baitreel label` still running?";
});
