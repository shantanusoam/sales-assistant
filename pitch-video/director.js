/**
 * Deterministic Minimalist SaaS / Bento UI Motion Director (`window.seek(t)` contract).
 * Every frame is a pure function of `t` in seconds, driven by `timeline.json`.
 */

const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
const prog = (t, t0, dur) => clamp((t - t0) / Math.max(0.0001, dur));
const easeOut = (x) => 1 - Math.pow(1 - clamp(x), 3);
const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

const $ = (id) => document.getElementById(id);

let TIMELINE = null;

async function loadTimeline() {
  if (TIMELINE) return TIMELINE;
  const res = await fetch('./timeline.json', { cache: 'no-store' });
  TIMELINE = await res.json();
  window.CUES = TIMELINE;
  return TIMELINE;
}

function setPointAlongPath(pathEl, circleEl, u) {
  if (!pathEl || !circleEl) return;
  const len = pathEl.getTotalLength();
  const pt = pathEl.getPointAtLength(clamp(u) * len);
  circleEl.setAttribute('cx', pt.x.toFixed(1));
  circleEl.setAttribute('cy', pt.y.toFixed(1));
}

function renderScene1(t) {
  // Hook & CTA are 100% legible at frame 0 (0.0s - 3.6s)
  const paths = [];
  for (let i = 0; i < 8; i++) {
    const p = $(`cpath-${i}`);
    const c = $(`cpulse-${i}`);
    const card = $(`cnode-${i}`);
    paths.push({ p, c, card });
    if (p) {
      const len = p.getTotalLength();
      const drawP = easeOut(prog(t, 0.2 + (i % 4) * 0.18, 1.8));
      p.style.strokeDasharray = `${len}`;
      p.style.strokeDashoffset = `${(1 - drawP) * len}`;
    }
    if (p && c) {
      // Travelling pulse along bezier curve into central hub
      const cycle = ((t * 0.42 + i * 0.11) % 1);
      setPointAlongPath(p, c, easeInOut(cycle));
    }
    if (card) {
      // Subtle convergence pull toward center hub after 4.0s
      const pull = easeInOut(prog(t, 3.8, 2.2));
      const dx = (i < 4 ? 1 : -1) * pull * 36;
      card.style.transform = `translateX(${dx.toFixed(1)}px)`;
      card.style.borderColor = pull > 0.6 ? '#45c2b8' : '#262e3b';
    }
  }
  const hub = $('brain-hub');
  if (hub) {
    const lock = easeOut(prog(t, 4.8, 0.9));
    const scale = 1 + 0.04 * Math.sin(lock * Math.PI);
    hub.style.transform = `scale(${scale.toFixed(3)})`;
  }
}

function renderScene2(t) {
  const localT = t - 7.9;
  // Term 'Playbook RAG' is held cleanly from 12.4s to 16.1s; keep it visible throughout Scene 2
  const ragEl = $('term-playbook-rag');
  if (ragEl) {
    ragEl.style.opacity = '1';
  }
  for (let i = 0; i < 4; i++) {
    const box = $(`abox-${i}`);
    if (!box) continue;
    const enter = easeOut(prog(t, 8.0 + i * 0.45, 0.65));
    const y = (1 - enter) * 22;
    box.style.opacity = enter.toFixed(3);
    box.style.transform = `translateY(${y.toFixed(1)}px)`;
  }
  // Animate data pulses between architecture stages
  const p1 = 360 + ((localT * 110) % 90);
  const p2 = 800 + (((localT + 0.3) * 110) % 90);
  const p3 = 1240 + (((localT + 0.6) * 80) % 80);
  $('apulse-1')?.setAttribute('cx', p1.toFixed(1));
  $('apulse-2')?.setAttribute('cx', p2.toFixed(1));
  $('apulse-3')?.setAttribute('cx', p3.toFixed(1));
}

function renderScene3(t) {
  // Automated cursor moves to Consent checkbox (17.0s), then Connect pill (17.9s)
  const cursor = $('sim-cursor');
  const checkbox = $('sim-checkbox');
  const connectPill = $('sim-connect-pill');
  if (cursor) {
    let cx = 620;
    let cy = 540;
    if (t < 17.0) {
      const u = easeInOut(prog(t, 16.3, 0.7));
      cx = 620 + (68 - 620) * u;
      cy = 540 + (128 - 540) * u;
    } else if (t < 17.9) {
      const u = easeInOut(prog(t, 17.1, 0.75));
      cx = 68 + (710 - 68) * u;
      cy = 128 + (128 - 128) * u;
    } else {
      const u = easeOut(prog(t, 18.0, 0.8));
      cx = 710 + (1120 - 710) * u;
      cy = 128 + (320 - 128) * u;
    }
    cursor.style.transform = `translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px)`;
  }
  const consentChecked = t >= 17.0;
  if (checkbox) {
    checkbox.classList.toggle('checked', consentChecked);
    checkbox.textContent = consentChecked ? '✓' : '';
  }
  if (connectPill) {
    const isConn = t >= 17.9;
    connectPill.textContent = isConn ? 'Connected · Live' : 'Connect';
    connectPill.style.background = isConn ? '#45c2b8' : '#244258';
    connectPill.style.color = isConn ? '#052821' : '#f5f7fa';
  }

  // Deterministic typewriter for Hinglish utterance (18.2s - 20.6s)
  const fullUtterance = '“आपका solution थोड़ा expensive लग रहा है, अभी हमारा budget tight है।”';
  const uChars = Math.floor(prog(t, 18.2, 2.3) * fullUtterance.length);
  if ($('sim-utterance')) {
    $('sim-utterance').textContent = fullUtterance.slice(0, uChars);
  }

  const pillsP = easeOut(prog(t, 20.4, 0.5));
  if ($('sim-pills')) {
    $('sim-pills').style.opacity = pillsP.toFixed(3);
  }

  // Talk-time bar shifts from 50% to 36% Rep / 64% Customer
  const talkP = easeInOut(prog(t, 20.5, 1.2));
  const repPct = Math.round(50 - 14 * talkP);
  const custPct = 100 - repPct;
  if ($('sim-talk-bar')) $('sim-talk-bar').style.width = `${repPct}%`;
  if ($('sim-rep-pct')) $('sim-rep-pct').textContent = `Rep ${repPct}%`;
  if ($('sim-cust-pct')) $('sim-cust-pct').textContent = `Customer ${custPct}%`;

  // Grounded hint illuminates at 21.2s
  const hintText = 'Ask what missed follow-ups cost today in Excel before discussing scope or pricing.';
  const hintChars = Math.floor(prog(t, 21.1, 1.4) * hintText.length);
  if ($('sim-hint-text')) {
    $('sim-hint-text').textContent = hintText.slice(0, hintChars);
  }
}

function renderScene4(t) {
  // High-contrast white stage (24.6s - 33.6s); complete visual stillness during silence 33.0s - 33.6s
  const dpdpEl = $('term-dpdp-consent');
  if (dpdpEl) {
    dpdpEl.style.opacity = '1';
  }
  const cards = ['wcard-1', 'wcard-2', 'wcard-3'];
  cards.forEach((id, idx) => {
    const el = $(id);
    if (!el) return;
    const p = easeOut(prog(t, 24.8 + idx * 0.9, 0.65));
    el.style.opacity = p.toFixed(3);
    el.style.transform = `translateX(${((1 - p) * 28).toFixed(1)}px)`;
  });
  const hud = $('mobile-hud');
  if (hud) {
    // Freeze motion completely during planned silence 33.0-33.6s
    const activeT = Math.min(t, 32.9);
    const shift = Math.sin((activeT - 24.6) * 2.2) * 3;
    hud.style.transform = `translateY(${shift.toFixed(1)}px)`;
  }
}

function renderScene5(t) {
  // Hero moment at 33.7s: Post-call card lands & counter climbs to 85 before label appears
  const scoreP = easeOut(prog(t, 33.7, 1.5));
  const scoreVal = Math.round(85 * scoreP);
  if ($('payoff-score')) {
    $('payoff-score').textContent = String(scoreVal);
  }
  // Honesty rule (craft.md §11): unit/claim label appears only once counter lands at 85 (t >= 35.2s)
  if ($('payoff-score-label')) {
    $('payoff-score-label').style.opacity = t >= 35.2 ? '1' : '0';
  }

  for (let i = 0; i < 3; i++) {
    const p = $(`ppath-${i}`);
    const c = $(`ppulse-${i}`);
    const node = $(`dnode-${i}`);
    if (p && c) {
      const u = ((Math.max(0, t - 34.2) * 0.65 + i * 0.22) % 1);
      setPointAlongPath(p, c, easeInOut(u));
    }
    if (node) {
      const np = easeOut(prog(t, 34.2 + i * 0.45, 0.6));
      node.style.opacity = np.toFixed(3);
      node.style.borderColor = t >= 36.5 + i * 0.3 ? '#45c2b8' : '#262e3b';
    }
  }
}

function renderScene6(t) {
  // Closing poster frame: enters at 0.45 opacity + subtle scale so 40.3s is never flat, settles by 41.2s
  const wrap = document.querySelector('#s6_close .close-wrap');
  if (wrap) {
    const p = easeOut(prog(t, 40.3, 0.8));
    const op = 0.48 + 0.52 * p;
    const sc = 0.96 + 0.04 * p;
    wrap.style.opacity = op.toFixed(3);
    wrap.style.transform = `scale(${sc.toFixed(3)})`;
  }
}

export async function seek(t) {
  const tl = await loadTimeline();
  const clampedT = clamp(t, 0, tl.meta.dur);
  const stage = $('stage');

  // Determine active scene
  let activeId = tl.scenes[0].id;
  for (const s of tl.scenes) {
    if (clampedT >= s.start && clampedT < s.end) {
      activeId = s.id;
      break;
    }
  }
  if (clampedT >= tl.scenes[tl.scenes.length - 1].start) {
    activeId = tl.scenes[tl.scenes.length - 1].id;
  }

  for (const s of tl.scenes) {
    const el = $(s.id);
    if (el) el.classList.toggle('active', s.id === activeId);
  }

  // High-contrast white flip in Scene 4
  const isLight = activeId === 's4_white_mobile';
  stage.classList.toggle('theme-light', isLight);
  const gridLines = $('grid-lines');
  if (gridLines) {
    gridLines.setAttribute('stroke', isLight ? '#dde3ea' : '#181f29');
  }

  if (activeId === 's1_converge') renderScene1(clampedT);
  else if (activeId === 's2_arch') renderScene2(clampedT);
  else if (activeId === 's3_bento') renderScene3(clampedT);
  else if (activeId === 's4_white_mobile') renderScene4(clampedT);
  else if (activeId === 's5_payoff') renderScene5(clampedT);
  else if (activeId === 's6_close') renderScene6(clampedT);

  // Subtitle caption bar synced to timeline captions
  const capEl = $('caption-bar');
  if (capEl) {
    const cap = (tl.captions || []).find((c) => clampedT >= c.from && clampedT <= c.to);
    if (cap) {
      capEl.style.display = 'block';
      capEl.textContent = cap.text;
    } else {
      capEl.style.display = 'none';
      capEl.textContent = '';
    }
  }
}

window.DUR = 47.5;
window.FPS = 30;
window.seek = seek;
window.TEXTS = (t) => {
  if (!TIMELINE) return [];
  return (TIMELINE.texts || [])
    .filter((x) => t >= x.from && t <= x.to && Array.isArray(x.box))
    .map((x) => ({
      text: x.text,
      x: x.box[0],
      y: x.box[1],
      w: x.box[2],
      h: x.box[3],
    }));
};
window.READY = (async () => {
  if (document.fonts?.ready) await document.fonts.ready;
  await loadTimeline();
  await seek(0);
})();

window.__playPitchVideo = async () => {
  await window.READY;
  const start = performance.now();
  return new Promise((resolve) => {
    async function frame(now) {
      const elapsed = (now - start) / 1000;
      await seek(Math.min(elapsed, window.DUR));
      if (elapsed < window.DUR) {
        requestAnimationFrame(frame);
      } else {
        document.body.dataset.done = 'true';
        resolve();
      }
    }
    requestAnimationFrame(frame);
  });
};
