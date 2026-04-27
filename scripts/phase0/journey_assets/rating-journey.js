/* Rating-journey visualization — runs in an IIFE against `window.RATING_DATA`.
 *
 * Mounts into a `.rating-journey-section` block whose internal IDs are all
 * prefixed with `journey-` so they don't collide with anything on the host
 * page. Reads its data from `window.RATING_DATA` (the per-page inline blob).
 *
 * Schema contract: see scripts/phase0/journey.py compute_journey_data().
 *
 * If `window.RATING_DATA` is missing (e.g. journey skipped for this player),
 * the script no-ops silently. Don't throw — the host page should keep working.
 */
(function () {
  const D = window.RATING_DATA;
  if (!D) return;

  const chartEl = document.getElementById('journey-chart');
  if (!chartEl) return; // Section markup not on this page → nothing to mount.

  const FOCAL = String(D.focal_id);
  const CHART_PIDS = D.chart_pids.map(String);

  const PALETTE = ['#46c281', '#4ea1ff', '#ffb74d', '#ba68c8', '#4dd0c4', '#ff8a65', '#f48fb1', '#e57373', '#ffc857', '#a5d8a5'];
  const COLOR = {};
  CHART_PIDS.forEach((pid, i) => {
    COLOR[pid] = (pid === FOCAL) ? '#46c281' : PALETTE[(i % (PALETTE.length - 1)) + 1];
  });

  const subEl = document.getElementById('journey-sub');
  if (subEl) {
    subEl.textContent =
      `OpenSkill PL · y-axis = conservative rating (μ−3σ) · ${D.events.length} matches over ${CHART_PIDS.length - 1} regular partners/opponents`;
  }

  const dateMs = s => new Date(s + 'T12:00:00Z').getTime();
  const T0 = dateMs(D.window_start);
  const T1 = dateMs(D.window_end);

  let yMin = Infinity, yMax = -Infinity;
  for (const pid of CHART_PIDS) {
    for (const pt of D.series[pid]) {
      yMin = Math.min(yMin, pt.score);
      yMax = Math.max(yMax, pt.score);
    }
  }
  const yPad = Math.max(0.5, (yMax - yMin) * 0.08);
  yMin = Math.floor(yMin - yPad);
  yMax = Math.ceil(yMax + yPad);

  const CHART = { x0: 80, x1: 870, y0: 30, y1: 410 };
  const xOf = ms => CHART.x0 + (ms - T0) / (T1 - T0) * (CHART.x1 - CHART.x0);
  const yOf = s => CHART.y1 - (s - yMin) / (yMax - yMin) * (CHART.y1 - CHART.y0);

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, text) => {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  };

  function pathFor(pts) {
    if (!pts.length) return '';
    let d = `M ${xOf(dateMs(pts[0].date)).toFixed(1)} ${yOf(pts[0].score).toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) {
      const x0 = xOf(dateMs(pts[i - 1].date)), y0 = yOf(pts[i - 1].score);
      const x1 = xOf(dateMs(pts[i].date)), y1 = yOf(pts[i].score);
      const midX = (x0 + x1) / 2;
      d += ` C ${midX.toFixed(1)} ${y0.toFixed(1)}, ${midX.toFixed(1)} ${y1.toFixed(1)}, ${x1.toFixed(1)} ${y1.toFixed(1)}`;
    }
    return d;
  }

  // ─── Static chrome ─────────────────────────────────────────────────────
  (function drawGridAndAxes() {
    const grid = document.getElementById('journey-grid');
    const yStep = (yMax - yMin) > 8 ? 2 : 1;
    for (let r = yMin; r <= yMax; r += yStep) {
      grid.appendChild(el('line', { x1: CHART.x0, x2: CHART.x1, y1: yOf(r), y2: yOf(r) }));
    }
    const yAxis = document.getElementById('journey-y-axis');
    for (let r = yMin; r <= yMax; r += yStep) {
      yAxis.appendChild(el('text', { x: CHART.x0 - 8, y: yOf(r) + 4, 'text-anchor': 'end' }, r.toFixed(0)));
    }
    const xAxis = document.getElementById('journey-x-axis');
    // Generate month ticks dynamically across the window. Cap at 24 ticks
    // for very long careers — beyond that we space ticks out by quarter.
    const start = new Date(T0); start.setUTCDate(1); start.setUTCMonth(start.getUTCMonth() + 1);
    const totalMonths = Math.ceil((T1 - T0) / (30 * 24 * 3600 * 1000));
    const monthStep = totalMonths > 24 ? 3 : (totalMonths > 12 ? 2 : 1);
    const ticks = [];
    for (let i = 0; i < 50; i++) {
      const d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + i * monthStep, 1));
      if (d.getTime() > T1) break;
      ticks.push(d);
    }
    for (const d of ticks) {
      const ms = d.getTime();
      const x = xOf(ms);
      const label = monthStep >= 3
        ? d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })
        : d.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' });
      xAxis.appendChild(el('line', { x1: x, x2: x, y1: CHART.y0, y2: CHART.y1, stroke: 'var(--rj-border)', 'stroke-width': 0.5, 'stroke-dasharray': '2 4' }));
      xAxis.appendChild(el('text', { x: x, y: CHART.y1 + 16, 'text-anchor': 'middle' }, label));
    }
  })();

  (function drawLines() {
    const ghostG = document.getElementById('journey-lines-ghost');
    const activeG = document.getElementById('journey-lines-active');
    for (const pid of CHART_PIDS) {
      const d = pathFor(D.series[pid]);
      const focal = pid === FOCAL ? ' focal' : '';
      ghostG.appendChild(el('path', { class: 'player-line ghost' + focal, d, stroke: COLOR[pid] }));
      activeG.appendChild(el('path', { class: 'player-line' + focal, d, stroke: COLOR[pid] }));
    }
  })();

  (function drawDotsAndLabels() {
    const dotsG = document.getElementById('journey-dots');
    const labelsG = document.getElementById('journey-labels');
    for (const pid of CHART_PIDS) {
      const focal = pid === FOCAL;
      const startY = yOf(D.series[pid][0].score);
      dotsG.appendChild(el('circle', {
        class: 'player-dot' + (focal ? ' focal' : ''),
        id: 'journey-dot-' + pid, r: focal ? 6 : 4,
        fill: COLOR[pid], cx: CHART.x0, cy: startY,
      }));
      labelsG.appendChild(el('text', {
        class: 'player-label', id: 'journey-label-' + pid,
        x: CHART.x0 + 10, y: startY + 3, fill: COLOR[pid],
      }, D.players[pid].short));
    }
  })();

  (function drawRatingsList() {
    const list = document.getElementById('journey-ratings-list');
    for (const pid of CHART_PIDS) {
      const li = document.createElement('li');
      li.id = 'journey-rating-li-' + pid;
      if (pid === FOCAL) li.className = 'focal';
      li.innerHTML = `
        <span class="rank" id="journey-rating-rank-${pid}">—</span>
        <span class="swatch" style="background:${COLOR[pid]}"></span>
        <span class="name" title="${D.players[pid].name}">${D.players[pid].name}</span>
        <span class="rating-prev" id="journey-rating-prev-${pid}">—</span>
        <span class="rating-arrow zero" id="journey-rating-arrow-${pid}">→</span>
        <span class="rating-new" id="journey-rating-new-${pid}">—</span>
        <span class="rating-delta" id="journey-rating-delta-${pid}"></span>`;
      list.appendChild(li);
    }
  })();

  // ─── Score interpolation ───────────────────────────────────────────────
  function scoreAt(pid, ms) {
    const series = D.series[pid];
    if (ms <= dateMs(series[0].date)) return series[0].score;
    if (ms >= dateMs(series[series.length - 1].date)) return series[series.length - 1].score;
    for (let i = 1; i < series.length; i++) {
      const ti = dateMs(series[i].date);
      if (ms <= ti) {
        const a = series[i - 1], b = series[i];
        const ta = dateMs(a.date);
        const t = (ms - ta) / (ti - ta);
        const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        return a.score + (b.score - a.score) * eased;
      }
    }
    return series[series.length - 1].score;
  }

  function previousEventIndex(ms) {
    let idx = -1;
    for (let i = 0; i < D.events.length; i++) {
      if (dateMs(D.events[i].date) <= ms) idx = i; else break;
    }
    return idx;
  }

  // ─── Match panel rendering ─────────────────────────────────────────────
  const playhead = document.getElementById('journey-playhead');
  const clipRect = document.getElementById('journey-past-clip-rect');
  const dateEl = document.getElementById('journey-current-date');
  const dateSubEl = document.getElementById('journey-current-date-sub');
  const timeDisplay = document.getElementById('journey-time-display');
  const matchPanelWrap = document.getElementById('journey-match-panel-wrap');
  const popupsG = document.getElementById('journey-popups');

  function fmtDate(ms) {
    return new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  }
  function fmtDelta(d) {
    if (d == null) return '·';
    if (Math.abs(d) < 0.01) return '0.00';
    return (d >= 0 ? '+' : '') + d.toFixed(2);
  }
  function deltaClass(d) {
    if (d == null || Math.abs(d) < 0.01) return 'zero';
    return d > 0 ? 'up' : 'down';
  }

  function teamLabel(ev, side) {
    return side === 1
      ? ev.team1.map(p => D.players[String(p)].name.split(' ')[0]).join(' & ')
      : ev.team2.map(p => D.players[String(p)].name.split(' ')[0]).join(' & ');
  }

  function buildNarrative(ev) {
    const t1 = teamLabel(ev, 1), t2 = teamLabel(ev, 2);
    const ex1 = ev.expected1, ex2 = 1 - ex1;
    const fav = ex1 > ex2 ? 1 : 2;
    const favName = fav === 1 ? t1 : t2;
    const dogName = fav === 1 ? t2 : t1;
    const favPct = Math.round(Math.max(ex1, ex2) * 100);

    if (ev.winner === 0) {
      return `<span class="highlight">Dead tie</span> — split sets and equal games. The model used the games-won fraction (${ev.a_games}/${ev.a_games + ev.b_games}) as the score, so ratings barely moved.`;
    }

    const winnerName = ev.winner === 1 ? t1 : t2;
    const loserName = ev.winner === 1 ? t2 : t1;

    if (ev.is_tied) {
      const winGames = ev.winner === 1 ? ev.a_games : ev.b_games;
      const loseGames = ev.winner === 1 ? ev.b_games : ev.a_games;
      return `Sets split 1–1; <strong>${winnerName}</strong> took it on games (${winGames}–${loseGames}). The model used the full games-won fraction as the score, not just the binary win/loss — that's why the rating shift is moderate even though it was technically a tied rubber.`;
    }

    if (ev.upset) {
      return `On paper <strong>${favName}</strong> were favoured <span class="highlight">${favPct}/${100 - favPct}</span>. <strong>${dogName}</strong> pulled the upset. Big rating swing: beating a stronger team is high-value information the model hadn't seen yet.`;
    }

    if (winnerName === favName) {
      return `<strong>${favName}</strong> were favoured ${favPct}/${100 - favPct} and won as expected. Modest rating moves — the model already priced this in, so it's just confirming what it knew.`;
    }

    return `${winnerName} won. The teams were nearly even on paper (${Math.round(ex1 * 100)}/${Math.round(ex2 * 100)}), so this only nudges the ratings.`;
  }

  function buildQuirkNote(ev) {
    const losers = ev.winner === 1 ? ev.team2 : ev.winner === 2 ? ev.team1 : [];
    const quirky = [];
    for (const pid of losers) {
      const s = String(pid);
      const wasNew = ev.new_player[s];
      const delta = ev.deltas[s];
      if (wasNew && delta > 0.5) {
        quirky.push({ pid: s, name: D.players[s].name, delta });
      }
    }
    if (quirky.length === 0) return '';
    const list = quirky.map(q => `<strong>${q.name}</strong> (${fmtDelta(q.delta)})`).join(', ');
    return `<div class="quirk-note">⚠ <strong>New-player effect:</strong> ${list} actually went UP after losing. Reason: this was their first match in the system, so the model had σ ≈ 8.3 (max uncertainty) for them. After any match — even a loss — σ shrinks dramatically, and the conservative score (μ − 3σ) jumps as the model gains confidence. This will normalise after 5–10 more matches.</div>`;
  }

  function renderTeam(ev, side) {
    const ids = side === 1 ? ev.team1 : ev.team2;
    const isWinner = ev.winner === side;
    const isLoser = ev.winner !== 0 && !isWinner;
    const isTie = ev.winner === 0;
    const cls = isTie ? 'tied' : isWinner ? 'winner' : 'loser';
    const resultLabel = isTie ? 'Tied' : isWinner ? (ev.is_tied ? 'Won (games)' : 'Won') : 'Lost';

    const players = ids.map(pid => {
      const s = String(pid);
      const p = D.players[s];
      const d = ev.deltas[s];
      const colour = COLOR[s] || 'var(--rj-muted)';
      const nameCls = s === FOCAL ? ' focal' : '';
      return `<div class="team-player">
        <span class="swatch" style="background:${colour}"></span>
        <span class="name${nameCls}" title="${p.name}">${p.short}</span>
        <span class="delta ${deltaClass(d)}">${fmtDelta(d)}</span>
      </div>`;
    }).join('');

    return `<div class="match-team ${cls}">
      <div class="team-result ${cls}">${resultLabel}</div>
      ${players}
    </div>`;
  }

  function renderMatchPanel(eventIdx) {
    if (eventIdx < 0) {
      matchPanelWrap.innerHTML = `<div class="match-panel empty">Window opens — initial ratings shown above</div>`;
      return;
    }
    const ev = D.events[eventIdx];
    const ex1Pct = Math.round(ev.expected1 * 100);
    const ex2Pct = 100 - ex1Pct;

    const isEvenStevens = Math.abs(ex1Pct - ex2Pct) <= 4;
    const team1Won = ev.winner === 1;
    const team2Won = ev.winner === 2;
    const isTrueDraw = ev.winner === 0;

    const team1Cls = isTrueDraw ? 'tied' : team1Won ? 'won' : 'lost';
    const team2Cls = isTrueDraw ? 'tied' : team2Won ? 'won' : 'lost';

    const team1Label = isTrueDraw ? `${ex1Pct}% · evenly matched` : `${ex1Pct}% chance · ${team1Won ? 'WON ✓' : 'LOST ✗'}`;
    const team2Label = isTrueDraw ? `${ex2Pct}% · evenly matched` : `${ex2Pct}% chance · ${team2Won ? 'WON ✓' : 'LOST ✗'}`;

    const centreLabel = isTrueDraw
      ? '<span class="as-predicted">tied</span>'
      : ev.upset
        ? '<span class="upset-flag">⚡ UPSET</span>'
        : isEvenStevens
          ? '<span class="set-all">set all — tossup</span>'
          : '<span class="as-predicted">as predicted</span>';

    const scoreLines = ev.score.split(' ').map(s => `<div>${s}</div>`).join('');
    const tieBadge = ev.is_tied ? `<div class="games-tiebreak">games tiebreak</div>` : '';

    matchPanelWrap.innerHTML = `
      <div class="match-panel">
        <div class="match-meta">
          ${ev.tournament}<br>
          <span class="division">${ev.division} · ${fmtDate(dateMs(ev.date))}</span>
        </div>
        <div class="match-result">
          ${renderTeam(ev, 1)}
          <div class="match-center">
            <div class="vs">vs</div>
            <div class="score">${scoreLines}</div>
            ${tieBadge}
          </div>
          ${renderTeam(ev, 2)}
        </div>
        <div class="expectation">
          <div class="expectation-bar">
            <div class="seg ${team1Cls}" style="width:${ex1Pct}%"></div>
            <div class="seg ${team2Cls}" style="width:${ex2Pct}%"></div>
          </div>
          <div class="expectation-label">
            <span class="ex-team-label ${team1Cls}">${team1Label}</span>
            ${centreLabel}
            <span class="ex-team-label ${team2Cls}">${team2Label}</span>
          </div>
        </div>
        <div class="narrative ${ev.upset ? '' : 'boring'} ${ev.winner === 0 || ev.is_tied ? 'tied' : ''}">${buildNarrative(ev)}</div>
        ${buildQuirkNote(ev)}
      </div>
    `;
  }

  function spawnDeltaPopup(pid, x, y, delta) {
    if (delta == null || Math.abs(delta) < 0.01) return;
    const txt = el('text', {
      class: 'delta-popup', x: x + 10, y: y - 6,
      fill: delta > 0 ? 'var(--rj-accent)' : 'var(--rj-loss)',
    }, fmtDelta(delta));
    popupsG.appendChild(txt);
    let frame = 0;
    const animate = () => {
      frame++;
      const t = frame / 40;
      if (t >= 1) { txt.remove(); return; }
      txt.setAttribute('y', y - 6 - t * 24);
      txt.setAttribute('opacity', 1 - t);
      requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  }

  // ─── Main render ───────────────────────────────────────────────────────
  let lastEventIdxRendered = -2;

  function render(ms) {
    const x = xOf(ms);
    playhead.setAttribute('x1', x);
    playhead.setAttribute('x2', x);
    clipRect.setAttribute('width', x);

    const current = {};
    for (const pid of CHART_PIDS) current[pid] = scoreAt(pid, ms);

    for (const pid of CHART_PIDS) {
      const y = yOf(current[pid]);
      document.getElementById('journey-dot-' + pid).setAttribute('cy', y);
      document.getElementById('journey-dot-' + pid).setAttribute('cx', x);
      const lbl = document.getElementById('journey-label-' + pid);
      lbl.setAttribute('x', x + 8);
      lbl.setAttribute('y', y + 3);
    }

    const eventIdx = previousEventIndex(ms);
    const ev = eventIdx >= 0 ? D.events[eventIdx] : null;

    const prev = {};
    for (const pid of CHART_PIDS) {
      if (ev && ev.deltas && ev.deltas[pid] != null) {
        prev[pid] = current[pid] - ev.deltas[pid];
      } else {
        prev[pid] = current[pid];
      }
    }

    const sortedIds = [...CHART_PIDS].sort((a, b) => current[b] - current[a]);
    const list = document.getElementById('journey-ratings-list');
    for (const pid of sortedIds) list.appendChild(document.getElementById('journey-rating-li-' + pid));
    for (let i = 0; i < sortedIds.length; i++) {
      const pid = sortedIds[i];
      const p = prev[pid], n = current[pid];
      const delta = n - p;
      const arrowEl = document.getElementById('journey-rating-arrow-' + pid);
      const deltaEl = document.getElementById('journey-rating-delta-' + pid);
      document.getElementById('journey-rating-rank-' + pid).textContent = '#' + (i + 1);
      document.getElementById('journey-rating-prev-' + pid).textContent = p.toFixed(2);
      document.getElementById('journey-rating-new-' + pid).textContent = n.toFixed(2);
      if (Math.abs(delta) < 0.005) {
        arrowEl.textContent = '→';
        arrowEl.className = 'rating-arrow zero';
        deltaEl.textContent = '';
        deltaEl.className = 'rating-delta';
      } else if (delta > 0) {
        arrowEl.textContent = '↑';
        arrowEl.className = 'rating-arrow up';
        deltaEl.textContent = '+' + delta.toFixed(2);
        deltaEl.className = 'rating-delta up';
      } else {
        arrowEl.textContent = '↓';
        arrowEl.className = 'rating-arrow down';
        deltaEl.textContent = delta.toFixed(2);
        deltaEl.className = 'rating-delta down';
      }
    }

    dateEl.textContent = fmtDate(ms);
    dateSubEl.textContent = eventIdx >= 0
      ? `${eventIdx + 1} of ${D.events.length} matches played`
      : 'No matches yet';
    timeDisplay.textContent = fmtDate(ms);

    if (eventIdx !== lastEventIdxRendered) {
      renderMatchPanel(eventIdx);
      if (eventIdx > lastEventIdxRendered && eventIdx >= 0 && ev) {
        const evMs = dateMs(ev.date);
        for (const pid of CHART_PIDS) {
          const d = ev.deltas[pid];
          if (d != null) {
            const sNew = scoreAt(pid, evMs);
            spawnDeltaPopup(pid, xOf(evMs), yOf(sNew), d);
          }
        }
      }
      lastEventIdxRendered = eventIdx;
    }
  }

  // ─── Controls ──────────────────────────────────────────────────────────
  const scrub = document.getElementById('journey-scrub');
  const playBtn = document.getElementById('journey-play-btn');
  const speedSel = document.getElementById('journey-speed');
  const prevBtn = document.getElementById('journey-prev-btn');
  const nextBtn = document.getElementById('journey-next-btn');

  let playing = false;
  let currentMs = T0;
  let lastFrameTs = null;

  function setMs(ms, suppressFlash = false) {
    currentMs = Math.max(T0, Math.min(T1, ms));
    const sliderVal = ((currentMs - T0) / (T1 - T0) * 1000).toFixed(0);
    scrub.value = sliderVal;
    scrub.setAttribute('value', sliderVal);
    if (suppressFlash) lastEventIdxRendered = previousEventIndex(currentMs);
    render(currentMs);
  }

  scrub.addEventListener('input', () => {
    const frac = scrub.value / 1000;
    setMs(T0 + frac * (T1 - T0), true);
  });

  playBtn.addEventListener('click', () => {
    if (currentMs >= T1) { currentMs = T0; lastEventIdxRendered = -2; }
    playing = !playing;
    playBtn.textContent = playing ? '⏸ Pause' : '▶ Play';
    lastFrameTs = null;
    if (playing) requestAnimationFrame(tick);
  });

  prevBtn.addEventListener('click', () => {
    const idx = previousEventIndex(currentMs - 86400000);
    if (idx >= 0) { lastEventIdxRendered = idx - 1; setMs(dateMs(D.events[idx].date)); }
    else { lastEventIdxRendered = -2; setMs(T0); }
  });
  nextBtn.addEventListener('click', () => {
    const idx = previousEventIndex(currentMs);
    const next = idx + 1;
    if (next < D.events.length) setMs(dateMs(D.events[next].date));
  });

  function tick(ts) {
    if (!playing) return;
    if (lastFrameTs == null) lastFrameTs = ts;
    const dt = ts - lastFrameTs;
    lastFrameTs = ts;
    const speed = parseFloat(speedSel.value);
    const msPerFrame = (T1 - T0) * (dt / 30000) * speed;
    setMs(currentMs + msPerFrame);
    if (currentMs >= T1) {
      playing = false;
      playBtn.textContent = '▶ Replay';
      return;
    }
    requestAnimationFrame(tick);
  }

  setMs(T0, true);
})();
