/*
  Draws a Baitreel clip. See index.html for how this is used.

  stage.load(spec)  build the page for a clip spec (see models.ClipSpec)
  stage.seek(t)     draw the frame at t seconds; returns a short "state key"

  The state key changes only when the picture changes. The renderer skips the
  screenshot when the key repeats, which makes still moments cheap to render.
*/
(() => {
  const $ = (id) => document.getElementById(id);
  const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
  const easeOut = (p) => 1 - Math.pow(1 - clamp(p), 3);
  const mix = (a, b, p) => a + (b - a) * p;
  const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  const SPEAKERS = { scammer: "Scammer", target: "Scambaiter" };
  const KICKERS = { real: "Real scam call", "scripted-demo": "Scripted demo call" };

  let spec = null;
  let beats = {};
  let cards = [];
  let replayCards = [];

  /** Build one hidden element per caption card. */
  function buildCards(list, container) {
    container.replaceChildren();
    return list.map((card) => {
      const el = document.createElement("div");
      el.className = "card";
      if (SPEAKERS[card.speaker]) {
        const who = document.createElement("span");
        who.className = `speaker ${card.speaker}`;
        who.textContent = SPEAKERS[card.speaker];
        el.append(who);
      }
      const words = card.words.map((word) => {
        const span = document.createElement("span");
        span.className = "word" + (word.redacted ? " redacted" : "");
        span.textContent = word.text;
        el.append(span, " ");
        return { el: span, start: word.start, end: word.end, cue: word.cue };
      });
      container.append(el);
      return { el, words, start: card.words[0].start };
    });
  }

  /** Shrink the tactic name until it fits the stamp on at most two lines. */
  function fitStamp() {
    const name = $("stamp-name");
    let size = 170;
    name.style.fontSize = `${size}px`;
    while (size > 70 && (name.scrollWidth > name.clientWidth || name.offsetHeight > size * 2.2)) {
      size -= 6;
      name.style.fontSize = `${size}px`;
    }
  }

  async function load(clip) {
    spec = clip;
    beats = Object.fromEntries(spec.beats.map((beat) => [beat.name, beat]));
    cards = buildCards(spec.cards, $("captions"));
    replayCards = buildCards(spec.replay_cards, $("replay"));

    $("kicker").textContent = KICKERS[spec.kind] || KICKERS.real;
    const minutes = Math.max(1, Math.round(spec.call_duration / 60));
    const where = `${clock(spec.call_time)} into a ${minutes}-minute call`;
    $("calltime").textContent = spec.kind === "real" ? where : `Not a real recording. ${where}`;
    $("stamp-name").textContent = spec.tactic.name;
    $("stamp-label").textContent = spec.tactic.plain_label;
    $("counter-body").textContent = spec.tactic.counter_move;
    $("counter-source").textContent = `Advice from ${spec.tactic.source_title}`;
    $("credit-name").textContent = spec.credit;
    $("byline").textContent = `Recording: ${spec.credit}`;

    await document.fonts.ready;
    fitStamp();
    return true;
  }

  /** The scrolling waveform: what was just said on the left, what is coming on the right. */
  function drawTape(frame) {
    const canvas = $("tape");
    const ctx = canvas.getContext("2d");
    const bars = 46;
    const step = canvas.width / bars;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let k = 0; k < bars; k++) {
      const level = spec.envelope[frame + (k - bars / 2) * 2] || 0;
      const height = Math.max(8, level * canvas.height);
      ctx.fillStyle = k < bars / 2 ? "#1a1917" : "rgba(26, 25, 23, 0.22)";
      ctx.beginPath();
      ctx.roundRect(k * step + 4, (canvas.height - height) / 2, step - 8, height, 6);
      ctx.fill();
    }
    ctx.fillStyle = "#d42a20";
    ctx.fillRect(canvas.width / 2 - 3, 0, 6, canvas.height);
  }

  /** Show the card being spoken at time t. Returns [card index, words said]. */
  function showCards(list, t, sweep) {
    let active = -1;
    list.forEach((card, i) => {
      if (t >= card.start - 0.2) active = i;
    });
    if (active < 0 && list.length) active = 0;
    let said = 0;
    list.forEach((card, i) => {
      card.el.classList.toggle("on", i === active);
      if (i !== active) return;
      for (const word of card.words) {
        const on = t >= word.start - 0.04;
        word.el.classList.toggle("said", on);
        if (on) said++;
        if (sweep && word.cue) {
          // The highlighter crosses the word while it is being spoken.
          const p = clamp((t - word.start) / Math.max(word.end - word.start, 0.12));
          word.el.style.backgroundSize = `${Math.round(p * 20) * 5}% 62%`;
          if (p > 0 && p < 1) said += p;
        }
      }
    });
    return [active, Math.round(said * 20)];
  }

  function seek(t) {
    const beat = spec.beats.find((b) => t < b.end) || spec.beats[spec.beats.length - 1];
    const { play, flag, replay, counter, credit } = beats;
    $("stage").dataset.beat = beat.name;
    const key = [beat.name];

    // Header and prompt.
    const afterFlag = t >= replay.start;
    $("kicker").textContent =
      beat.name === "flag" ? "Flag on the play" :
      beat.name === "replay" ? "Instant replay" :
      KICKERS[spec.kind] || KICKERS.real;
    $("prompt").style.opacity = beat.name === "play" ? 1 : 0;

    // Waveform, redrawn 15 times a second.
    const showTape = t < counter.start;
    $("tape").style.opacity = showTape ? 1 : 0;
    if (showTape) {
      const frame = Math.floor((t * spec.fps) / 2) * 2;
      drawTape(frame);
      key.push(frame);
    }

    // Captions: live during the play, frozen and dimmed under the stamp.
    const captions = $("captions");
    if (t < replay.start) {
      captions.style.opacity = beat.name === "flag" ? 0.3 : 1;
      key.push(...showCards(cards, Math.min(t, play.end - 0.001), false));
    } else {
      captions.style.opacity = 0;
    }

    // The replay: the quote again, highlighter on the cue words.
    const again = $("replay");
    if (beat.name === "replay") {
      again.style.opacity = easeOut((t - replay.start) / 0.3);
      key.push(...showCards(replayCards, t, true), again.style.opacity);
    } else {
      again.style.opacity = 0;
    }

    // The stamp: slams in, settles, then shrinks into the header area.
    const stamp = $("stamp");
    if (t < flag.start) {
      stamp.style.opacity = 0;
      $("flash").style.opacity = 0;
    } else {
      const slam = clamp((t - flag.start) / 0.2);
      const settle = clamp((t - flag.start - 0.2) / 0.25);
      const tuck = afterFlag ? easeOut((t - replay.start) / 0.4) : 0;
      const scale = mix(mix(2.6, 1, easeOut(slam)) * (1 - 0.04 * Math.sin(settle * Math.PI)), 0.42, tuck);
      const lift = mix(0, -780, tuck); // from the middle of the page up under the header
      const tilt = mix(-6, -3, tuck);
      stamp.style.opacity = clamp(slam * 1.5);
      stamp.style.transform = `translateY(calc(-50% + ${lift.toFixed(1)}px)) rotate(${tilt.toFixed(2)}deg) scale(${scale.toFixed(3)})`;
      $("flash").style.opacity = (0.22 * (1 - clamp((t - flag.start) / 0.45))).toFixed(3);
      key.push(scale.toFixed(3), lift.toFixed(0), $("flash").style.opacity);
    }

    // What to do instead, then the credit.
    const card = $("counter");
    const creditPanel = $("credit");
    if (t >= counter.start) {
      const rise = easeOut((t - counter.start) / 0.45);
      const leave = t >= credit.start ? easeOut((t - credit.start) / 0.35) : 0;
      card.style.opacity = (rise * (1 - leave)).toFixed(3);
      card.style.transform = `translateY(${mix(90, 0, rise).toFixed(1)}px)`;
      creditPanel.style.opacity = leave.toFixed(3);
      creditPanel.style.transform = `translateY(${mix(60, 0, leave).toFixed(1)}px)`;
      key.push(card.style.opacity, creditPanel.style.opacity);
    } else {
      card.style.opacity = 0;
      creditPanel.style.opacity = 0;
    }
    // The byline shows the credit all the way through, until the credit beat says it large.
    $("byline").style.opacity = t >= credit.start ? 0 : 1;

    return key.join("|");
  }

  window.stage = { load, seek };
})();
