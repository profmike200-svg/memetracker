/* Memetracker – interfaz */
const TZ = 'Europe/Madrid';
const $app = document.getElementById('app');
let refreshTimer = null, charts = [], sortKey = null, sortDir = -1, lastEventId = null;

// ------------------------------------------------------------ formato
const fmtDate = new Intl.DateTimeFormat('es-ES', { timeZone: TZ, weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
const fmtShort = new Intl.DateTimeFormat('es-ES', { timeZone: TZ, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const fmtDay = new Intl.DateTimeFormat('es-ES', { timeZone: TZ, day: '2-digit', month: 'short' });
const when = ts => ts ? fmtDate.format(new Date(ts * 1000)) : '—';
const whenS = ts => ts ? fmtShort.format(new Date(ts * 1000)) : '—';
function ago(ts) {
  if (!ts) return '—';
  const s = Date.now() / 1000 - ts;
  if (s < 90) return 'hace un momento';
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}
function usd(v, compact = true) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  if (compact && Math.abs(v) >= 1000) return '$' + Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 }).format(v);
  return '$' + Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(v);
}
function price(v) {
  if (v === null || v === undefined) return '—';
  if (v < 0) return '';
  if (v >= 1) return '$' + v.toLocaleString('en', { maximumFractionDigits: 4 });
  if (v === 0) return '$0';
  const s = v.toPrecision(4);
  const m = /^0\.(0{3,})(\d+)$/.exec(Number(s).toFixed(20).replace(/0+$/, ''));
  if (m) { const sub = '₀₁₂₃₄₅₆₇₈₉'; const z = String(m[1].length).split('').map(d => sub[d]).join(''); return `$0.0${z}${m[2].slice(0, 4)}`; }
  return '$' + Number(s);
}
const num = v => v === null || v === undefined ? '—' : Math.round(v).toLocaleString('es-ES');
function pct(v, digits = 1) {
  if (v === null || v === undefined || isNaN(v)) return '<span class="muted">—</span>';
  return `<span class="${v >= 0 ? 'up' : 'down'}">${v >= 0 ? '+' : ''}${v.toFixed(digits)}%</span>`;
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const trendCls = t => !t ? '' : t.startsWith('Alcista') ? 'up' : t.startsWith('Bajista') ? 'down' : 'warn';
const sentCls = l => ({ Euforia: 'up', Positivo: 'up', Negativo: 'down', 'Pánico': 'down' }[l] || 'warn');
const CHAIN = { solana: 'Solana', ethereum: 'Ethereum', bsc: 'BNB Chain', base: 'Base', arbitrum: 'Arbitrum', polygon: 'Polygon', avalanche: 'Avalanche', sui: 'Sui', ton: 'TON', tron: 'Tron' };
const chainName = c => CHAIN[c] || c;
const EV_ICON = { move: null, pump: '🚀', dump: '🩸', liquidity: '💧', holders: '👥', ath: '🏔️', security: '⚠️' };
const evIcon = e => EV_ICON[e.kind] || (e.direction === 'up' ? '📈' : '📉');

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function destroyCharts() { charts.forEach(c => { try { if (c.disconnect) c.disconnect(); else if (c.remove) c.remove(); else c.destroy(); } catch (e) { } }); charts = []; }
function logo(t, cls = '') {
  const ph = `<div class="logo ph ${cls}">${esc((t.symbol || '?').slice(0, 1))}</div>`;
  return t.image_url ? `<img class="logo ${cls}" src="${esc(t.image_url)}" onerror="this.outerHTML=this.dataset.ph" data-ph='${ph.replace(/'/g, '&#39;')}'>` : ph;
}

// ------------------------------------------------------------ estado
async function pollStatus() {
  try {
    const s = await api('/api/status');
    document.getElementById('status').textContent =
      `${s.tokens} coins · última actualización ${ago(s.last_cycle)}` + (s.last_error ? ` · ⚠ ${s.last_error}` : '');
  } catch (e) { document.getElementById('status').textContent = '⚠ servidor no disponible'; }
}

// ------------------------------------------------------------ notificaciones de eventos
async function checkNewEvents() {
  try {
    const ev = await api('/api/events?limit=10');
    if (!ev.length) return;
    if (lastEventId !== null && 'Notification' in window && Notification.permission === 'granted') {
      ev.filter(e => e.id > lastEventId && e.kind !== 'move').reverse().forEach(e =>
        new Notification(`${e.symbol}: ${e.message}`, { body: when(e.ts) }));
    }
    lastEventId = Math.max(...ev.map(e => e.id));
  } catch (e) { }
}

// ------------------------------------------------------------ router
function route() {
  clearInterval(refreshTimer); destroyCharts();
  const m = location.hash.match(/^#\/token\/(\d+)/);
  if (m) { renderDetail(+m[1]); refreshTimer = setInterval(() => renderDetail(+m[1], true), 60000); }
  else { renderList(); refreshTimer = setInterval(() => renderList(true), 30000); }
}
window.addEventListener('hashchange', route);

// ------------------------------------------------------------ watchlist
function sparkline(canvas, data) {
  if (!data || data.length < 2) return;
  const ctx = canvas.getContext('2d'), w = canvas.width = 220, h = canvas.height = 60;
  const mn = Math.min(...data), mx = Math.max(...data), up = data[data.length - 1] >= data[0];
  ctx.strokeStyle = up ? '#22c55e' : '#ef4444'; ctx.lineWidth = 3; ctx.beginPath();
  data.forEach((v, i) => { const x = i / (data.length - 1) * w, y = h - 4 - (v - mn) / ((mx - mn) || 1) * (h - 8); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();
}

function legText(l) {
  if (!l) return '<span class="muted">—</span>';
  const up = l.direction === 'up';
  return `<span class="${up ? 'up' : 'down'}">${up ? '▲ Subiendo' : '▼ Bajando'} ${l.pct >= 0 ? '+' : ''}${l.pct.toFixed(0)}%</span> <small class="muted">desde ${whenS(l.start_ts)}</small>`;
}

const COLS = [
  ['Coin', null], ['Precio', t => t.snap.price_usd], ['1h', t => t.snap.change_h1], ['24h', t => t.snap.change_h24],
  ['Desde que la añadí', t => t.since_added_pct], ['Market cap', t => t.snap.market_cap], ['Liquidez', t => t.snap.liquidity_usd],
  ['Vol 24h', t => t.snap.volume_h24], ['Holders', t => t.holders], ['Tendencia (1h)', t => t.rsi], ['Sentimiento', t => t.sentiment?.score],
  ['Movimiento actual', t => t.current_leg?.pct], ['Último evento', t => t.last_event?.ts], ['48h', null], ['', null],
];

async function renderList(silent) {
  let tokens, events;
  try { [tokens, events] = await Promise.all([api('/api/tokens'), api('/api/events?limit=150')]); }
  catch (e) { if (!silent) $app.innerHTML = `<div class="panel msg err">No puedo hablar con el servidor: ${esc(e.message)}</div>`; return; }
  if (silent && document.activeElement && document.activeElement.name === 'address') return; // no pisar lo que escribe
  if (sortKey !== null && COLS[sortKey][1]) {
    const f = COLS[sortKey][1];
    tokens.sort((a, b) => ((f(a) ?? -Infinity) - (f(b) ?? -Infinity)) * sortDir);
  }
  const rows = tokens.map(t => {
    const s = t.snap || {};
    const le = t.last_event;
    return `<tr class="click" data-id="${t.id}">
      <td><div class="tok">${logo(t)}<div><b>${esc(t.symbol)}</b><small>${esc(t.name)} · ${chainName(t.chain)}</small></div></div></td>
      <td>${price(s.price_usd)}</td><td>${pct(s.change_h1)}</td><td>${pct(s.change_h24)}</td>
      <td>${pct(t.since_added_pct)}<br><small class="muted">desde ${price(t.price_at_add)}</small></td>
      <td>${usd(s.market_cap)}</td><td>${usd(s.liquidity_usd)}</td><td>${usd(s.volume_h24)}</td><td>${num(t.holders)}</td>
      <td><span class="chip ${trendCls(t.trend)}">${t.trend || '—'}</span>${t.rsi != null ? `<br><small class="muted">RSI ${t.rsi.toFixed(0)}</small>` : ''}</td>
      <td>${t.sentiment ? `<span class="chip ${sentCls(t.sentiment.label)}">${t.sentiment.label}</span>` : '—'}</td>
      <td class="l">${legText(t.current_leg)}</td>
      <td class="l wrap">${le ? `${evIcon(le)} ${esc(le.message)}<br><small class="muted">${when(le.ts)}</small>` : '<span class="muted">—</span>'}</td>
      <td><canvas class="spark" data-spark="${t.id}"></canvas></td>
      <td><button class="danger" data-del="${t.id}" title="Dejar de seguir">✕</button></td></tr>`;
  }).join('');
  const prevAddr = document.querySelector('input[name=address]')?.value || '';
  $app.innerHTML = `
    <div class="panel">
      <h2>Añadir coin <small>pega la token address (Solana, Ethereum, Base, BSC…). La cadena se detecta sola.</small></h2>
      <form class="add" id="addForm">
        <input name="address" placeholder="Token address, p. ej. DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pcB263" autocomplete="off" value="${esc(prevAddr)}">
        <select name="chain"><option value="">Cadena: automática</option>${Object.entries(CHAIN).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
        <input name="note" placeholder="Nota (opcional)" style="min-width:180px">
        <button type="submit">Seguir coin</button>
      </form>
      <div class="msg" id="addMsg"></div>
    </div>
    <div class="panel">
      <h2>Mis coins <small>${tokens.length} en seguimiento · se actualiza sola · haz clic en una fila para ver el análisis</small></h2>
      <div class="scroll">${tokens.length ? `<table><thead><tr>${COLS.map(([n, f], i) => `<th class="${i === 11 || i === 12 ? 'l' : ''}" data-sort="${f ? i : ''}">${n}${sortKey === i ? (sortDir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`
      : '<div class="empty">Todavía no sigues ninguna coin. Pega una token address arriba.</div>'}</div>
    </div>
    <div class="panel">
      <h2>Historial de eventos de todas las coins <small>subidas, bajadas y alertas · hora de Madrid</small>
        ${'Notification' in window && Notification.permission === 'default' ? '<button class="ghost" id="notif" style="float:right;padding:4px 10px">🔔 Activar avisos</button>' : ''}</h2>
      <div class="ev-feed">${events.length ? events.map(e => evRow(e, true)).join('') : '<div class="empty">Aún no hay eventos. Aparecen cuando una coin sube o baja con fuerza.</div>'}</div>
    </div>
    <p class="disclaimer">Datos: DexScreener, GeckoTerminal, RugCheck, GoPlus. Las puntuaciones son heurísticas, no consejo de inversión.</p>`;
  tokens.forEach(t => { const c = document.querySelector(`[data-spark="${t.id}"]`); if (c) sparkline(c, t.spark); });
  document.querySelectorAll('tr.click').forEach(tr => tr.addEventListener('click', e => {
    if (e.target.closest('button')) return; location.hash = `#/token/${tr.dataset.id}`;
  }));
  document.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('¿Dejar de seguir esta coin? Se borrará su histórico.')) return;
    await api(`/api/tokens/${b.dataset.del}`, { method: 'DELETE' }); renderList();
  }));
  document.querySelectorAll('th[data-sort]').forEach(th => th.addEventListener('click', () => {
    if (th.dataset.sort === '') return;
    const i = +th.dataset.sort; sortDir = sortKey === i ? -sortDir : -1; sortKey = i; renderList();
  }));
  document.getElementById('notif')?.addEventListener('click', () => Notification.requestPermission().then(() => renderList()));
  document.getElementById('addForm').addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target, btn = f.querySelector('button'), msg = document.getElementById('addMsg');
    const body = { address: f.address.value.trim(), chain: f.chain.value, note: f.note.value };
    if (!body.address) return;
    btn.disabled = true; msg.className = 'msg'; msg.textContent = 'Buscando el token y descargando su histórico (puede tardar ~15 s)…';
    try {
      const r = await api('/api/tokens', { method: 'POST', body: JSON.stringify(body) });
      f.address.value = '';
      location.hash = `#/token/${r.id}`;
    } catch (err) { msg.className = 'msg err'; msg.textContent = err.message; }
    finally { btn.disabled = false; }
  });
}

function evRow(e, showToken) {
  let detail = '';
  if (e.kind === 'move') {
    detail = `${price(e.price_from)} → ${price(e.price_to)} · de ${whenS(e.start_ts)} a ${whenS(e.ts)}`;
  } else if (e.price_to) detail = price(e.price_to);
  const tok = showToken ? `<a href="#/token/${e.token_id}"><b>${esc(e.symbol)}</b></a> ` : '';
  const cls = e.direction === 'up' ? 'up' : e.direction === 'down' ? 'down' : 'warn';
  return `<div class="ev"><span class="when">${when(e.ts)}</span><span class="icon">${evIcon(e)}</span>
    <span>${tok}<span class="${cls}">${esc(e.message)}</span> <small class="muted">${detail}</small></span></div>`;
}

// ------------------------------------------------------------ ficha de una coin
let detailTf = 'h1';

function kpi(k, v, s = '') { return `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`; }

async function renderDetail(id, silent) {
  let d, snaps, events;
  try {
    [d, snaps, events] = await Promise.all([api(`/api/tokens/${id}?tf=${detailTf}`), api(`/api/tokens/${id}/snapshots`), api(`/api/tokens/${id}/events`)]);
  } catch (e) { $app.innerHTML = `<div class="panel msg err">${esc(e.message)} <a href="#/">volver</a></div>`; return; }
  if (silent && document.activeElement && document.activeElement.tagName === 'TEXTAREA') return;
  destroyCharts();
  const t = d.token, s = d.snap || {}, ta = d.ta || {}, sec = d.security, nar = d.narrative, se = d.sentiment, h = d.health;
  const links = [
    t.pair_url && `<a href="${esc(t.pair_url)}" target="_blank">DexScreener</a>`,
    `<a href="https://www.geckoterminal.com/${t.chain === 'ethereum' ? 'eth' : t.chain}/pools/${esc(t.pair_address)}" target="_blank">GeckoTerminal</a>`,
    t.chain === 'solana' && `<a href="https://rugcheck.xyz/tokens/${esc(t.address)}" target="_blank">RugCheck</a>`,
    t.chain === 'solana' && `<a href="https://solscan.io/token/${esc(t.address)}" target="_blank">Solscan</a>`,
    ...Object.entries(nar.socials || {}).map(([k, u]) => `<a href="${esc(u)}" target="_blank">${esc(k)}</a>`),
    ...(nar.websites || []).slice(0, 2).map(u => `<a href="${esc(u)}" target="_blank">web</a>`),
  ].filter(Boolean).join(' · ');
  const buyR = se ? `${Math.round(se.buy_ratio_h1 * 100)}% compras (1h) · ${Math.round(se.buy_ratio_h24 * 100)}% (24h)` : '';
  const legs = [...(d.legs || [])].reverse();
  const cur = d.current_leg;
  const ageDays = t.pair_created_at ? (Date.now() / 1000 - t.pair_created_at) / 86400 : null;

  $app.innerHTML = `
  <div class="head">
    <a href="#/">← Mis coins</a>
    ${logo(t, 'lg')}
    <div><h2>${esc(t.symbol)} <span class="muted" style="font-size:15px;font-weight:400">${esc(t.name)} · ${chainName(t.chain)} · ${esc(t.dex || '')}</span></h2>
      <div class="addr" title="Copiar" onclick="navigator.clipboard.writeText('${esc(t.address)}')">${esc(t.address)} ⧉</div>
      <div style="font-size:13px;margin-top:2px">${links}</div></div>
    <div class="actions">
      <button class="ghost" id="refresh">↻ Actualizar ahora</button>
      <a href="/api/tokens/${t.id}/export.csv"><button class="ghost">⬇ Exportar CSV</button></a>
    </div>
  </div>

  <div class="panel"><div class="kpis">
    ${kpi('Precio', price(s.price_usd), `5m ${pct(s.change_m5)} · 1h ${pct(s.change_h1)}`)}
    ${kpi('Cambio 6h / 24h', `${pct(s.change_h6)}`, `24h ${pct(s.change_h24)}`)}
    ${kpi('Market cap', usd(s.market_cap), `FDV ${usd(s.fdv)}`)}
    ${kpi('Liquidez', usd(s.liquidity_usd), `${s.pair_count || 0} pares · liq/mcap ${s.market_cap ? (s.liquidity_usd / s.market_cap * 100).toFixed(1) + '%' : '—'}`)}
    ${kpi('Volumen 24h', usd(s.volume_h24), `1h ${usd(s.volume_h1)}`)}
    ${kpi('Holders', num(d.holders), d.holders_trend_24h != null ? `24h ${pct(d.holders_trend_24h)}` : '<span class="muted">tendencia: falta histórico</span>')}
    ${kpi('Transacciones 24h', num((s.buys_h24 || 0) + (s.sells_h24 || 0)), `<span class="up">${num(s.buys_h24)} compras</span> · <span class="down">${num(s.sells_h24)} ventas</span>`)}
    ${kpi('Desde el máximo', ta.drawdown_from_ath != null ? pct(ta.drawdown_from_ath) : '—', ta.ath ? `máx ${price(ta.ath)} · ${whenS(ta.ath_ts)}` : '')}
    ${kpi('Edad del par', ageDays != null ? (ageDays < 1 ? `${Math.round(ageDays * 24)} h` : `${Math.round(ageDays)} días`) : '—', t.pair_created_at ? when(t.pair_created_at) : '')}
    ${kpi('Seguimiento desde', fmtDay.format(new Date(t.added_at * 1000)), `${snaps.length} registros guardados`)}
  </div></div>

  <div class="grid g3">
    <div class="panel"><h2>Tendencia <small>análisis técnico (${({ m15: '15 min', h1: '1 hora', d1: '1 día' })[detailTf]})</small></h2>
      ${ta.ok ? `<div class="big ${trendCls(ta.trend)}">${ta.trend}</div>
      <div class="muted" style="margin-bottom:8px">RSI ${ta.rsi?.toFixed(0) ?? '—'} · soporte ${price(ta.support)} · resistencia ${price(ta.resistance)} · volatilidad ${ta.atr_pct?.toFixed(1) ?? '—'}%/vela</div>
      <ul class="signals">${ta.signals.map(x => `<li class="${x.kind}">${esc(x.text)}</li>`).join('')}</ul>` : `<div class="muted">${esc(ta.reason || 'Sin datos de velas')}</div>`}
    </div>
    <div class="panel"><h2>Sentimiento y narrativa</h2>
      ${se ? `<div class="big ${sentCls(se.label)}">${se.label}</div><div class="muted">${buyR}${se.volume_accel ? ` · volumen 1h al ${(se.volume_accel * 100).toFixed(0)}% del ritmo diario` : ''}</div>` : ''}
      <div style="margin:10px 0">${nar.tags.map(x => `<span class="chip">${esc(x)}</span>`).join('')}${nar.boosts ? `<span class="chip warn">⚡ ${nar.boosts} boosts en DexScreener</span>` : ''}</div>
      ${nar.description ? `<div style="font-size:13px;max-height:120px;overflow:auto" class="muted">${esc(nar.description)}</div>` : '<div class="muted">Sin descripción pública.</div>'}
      <div class="muted" style="margin-top:8px;font-size:12px">Presencia social: ${nar.presence_score}/4 (X, Telegram, web, descripción)</div>
    </div>
    <div class="panel"><h2>Salud del token <small>heurística 0–100</small></h2>
      ${h ? `<div class="big ${h.score >= 65 ? 'up' : h.score >= 40 ? 'warn' : 'down'}">${h.score}/100</div>
      ${h.parts.map(p => `<div style="margin-top:8px;font-size:13px">${esc(p.name)} <span class="muted" style="float:right">${esc(p.detail)}</span><div class="bar"><i style="width:${p.pts / p.max * 100}%"></i></div></div>`).join('')}` : '<div class="muted">Sin datos</div>'}
    </div>
  </div>

  <div class="panel">
    <div class="tabs">${[['m15', '15m'], ['h1', '1h'], ['d1', '1D']].map(([k, n]) => `<button class="${k === detailTf ? 'on' : ''}" data-tf="${k}">${n}</button>`).join('')}
      <span class="muted" style="margin-left:auto;font-size:12px">Velas en USD · EMA9 <span style="color:#f59e0b">━</span> EMA21 <span style="color:#22d3ee">━</span> EMA50 <span style="color:#a78bfa">━</span> · flechas = subidas/bajadas ≥${d.config.move_threshold_pct}% · hora de Madrid</span></div>
    <div id="chart"></div><div id="rsi"></div>
  </div>

  <div class="grid g2">
    <div class="panel"><h2>Subidas y bajadas <small>tramos ≥${d.config.move_threshold_pct}% en velas de 1h · hora de Madrid</small></h2>
      ${cur ? `<div style="margin-bottom:10px">Ahora: ${legText(cur)} <small class="muted">(${price(cur.price_from)} → ${price(cur.last_price)}${cur.pullback_pct ? `, ${cur.pullback_pct.toFixed(1)}% desde el extremo` : ''})</small></div>` : ''}
      <div class="scroll" style="max-height:380px;overflow-y:auto">${legs.length ? `<table><thead><tr><th class="l">Movimiento</th><th class="l">Empieza</th><th class="l">Termina</th><th>Duración</th><th>Precio</th></tr></thead><tbody>
        ${legs.map(l => `<tr><td class="l ${l.direction === 'up' ? 'up' : 'down'}">${l.direction === 'up' ? '▲ Subida' : '▼ Bajada'} ${l.pct >= 0 ? '+' : ''}${l.pct.toFixed(1)}%</td>
          <td class="l">${when(l.start_ts)}</td><td class="l">${when(l.end_ts)}</td><td>${l.hours < 48 ? l.hours + ' h' : (l.hours / 24).toFixed(1) + ' d'}</td>
          <td>${price(l.price_from)} → ${price(l.price_to)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">Aún no hay tramos confirmados.</div>'}</div>
    </div>
    <div class="panel"><h2>Eventos y alertas <small>hora de Madrid</small></h2>
      <div class="ev-feed">${events.length ? events.map(e => evRow(e, false)).join('') : '<div class="empty">Sin eventos todavía.</div>'}</div>
    </div>
  </div>

  <div class="grid g2">
    <div class="panel"><h2>Holders <small>histórico guardado</small></h2><div class="small-chart"><canvas id="cHolders"></canvas></div></div>
    <div class="panel"><h2>Liquidez y market cap</h2><div class="small-chart"><canvas id="cLiq"></canvas></div></div>
    <div class="panel"><h2>Volumen 24h</h2><div class="small-chart"><canvas id="cVol"></canvas></div></div>
    <div class="panel"><h2>Presión compradora <small>% de compras sobre el total de transacciones</small></h2><div class="small-chart"><canvas id="cBuy"></canvas></div></div>
  </div>

  <div class="grid g2">
    <div class="panel"><h2>Seguridad <small>${sec ? esc(sec.source) : ''}</small></h2>${securityHtml(sec, d)}</div>
    <div class="panel"><h2>Mis notas</h2>
      <textarea id="note" rows="6" style="width:100%" placeholder="Por qué la sigo, objetivos, stop…">${esc(t.note || '')}</textarea>
      <div style="margin-top:8px"><button class="ghost" id="saveNote">Guardar nota</button> <span class="muted" id="noteMsg"></span></div>
    </div>
  </div>
  <p class="disclaimer">Las métricas son automáticas y heurísticas. No es consejo de inversión. DYOR.</p>`;

  document.querySelectorAll('[data-tf]').forEach(b => b.addEventListener('click', () => { detailTf = b.dataset.tf; renderDetail(id); }));
  document.getElementById('refresh').addEventListener('click', async e => {
    e.target.disabled = true; e.target.textContent = 'Actualizando…';
    try { await api(`/api/tokens/${id}/refresh`, { method: 'POST' }); } catch (err) { alert(err.message); }
    renderDetail(id);
  });
  document.getElementById('saveNote').addEventListener('click', async () => {
    await api(`/api/tokens/${id}/note`, { method: 'POST', body: JSON.stringify({ note: document.getElementById('note').value }) });
    document.getElementById('noteMsg').textContent = 'Guardada ✓';
  });
  drawPriceChart(d);
  drawHistory(snaps);
}

function securityHtml(sec, d) {
  if (!sec) return '<div class="muted">Sin datos de seguridad para esta cadena todavía.</div>';
  const risk = sec.score_norm;
  const lvl = risk == null ? '' : risk >= 60 ? 'down' : risk >= 25 ? 'warn' : 'up';
  const rows = [];
  if (sec.rugged) rows.push('<span class="chip down">MARCADO COMO RUG</span>');
  if ('mint_authority' in sec) rows.push(`Mint authority: ${sec.mint_authority ? '<span class="down">activa</span>' : '<span class="up">renunciada</span>'}`);
  if ('freeze_authority' in sec) rows.push(`Freeze authority: ${sec.freeze_authority ? '<span class="down">activa</span>' : '<span class="up">renunciada</span>'}`);
  if (sec.lp_locked_pct != null) rows.push(`LP bloqueada/quemada: ${sec.lp_locked_pct.toFixed(0)}%`);
  if (sec.top10_pct != null) rows.push(`Top 10 holders: <span class="${sec.top10_pct > 40 ? 'down' : sec.top10_pct > 25 ? 'warn' : 'up'}">${sec.top10_pct.toFixed(1)}%</span>`);
  if (sec.buy_tax != null) rows.push(`Impuestos: compra ${(sec.buy_tax * 100).toFixed(1)}% · venta ${((sec.sell_tax || 0) * 100).toFixed(1)}%`);
  if (sec.creator_pct) rows.push(`Creador tiene ${sec.creator_pct.toFixed(1)}%`);
  if (sec.insiders_detected) rows.push(`<span class="warn">Insiders detectados: ${sec.insiders_detected}</span>`);
  return `<div class="big ${lvl}">${risk == null ? '—' : `Riesgo ${Math.round(risk)}/100`}</div>
    <div style="margin:8px 0">${rows.join('<br>')}</div>
    ${sec.risks?.length ? `<ul class="signals">${sec.risks.map(r => `<li class="${r.level === 'danger' ? 'bear' : 'warn'}">${esc(r.name)}${r.description ? ` <small class="muted">${esc(r.description)}</small>` : ''}</li>`).join('')}</ul>` : '<div class="up">Sin riesgos detectados</div>'}`;
}

// ------------------------------------------------------------ gráficos
const madridTime = t => fmtShort.format(new Date(t * 1000));
function lwOpts(height) {
  return {
    height, layout: { background: { color: 'transparent' }, textColor: '#8a93a8' },
    grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
    timeScale: { timeVisible: true, borderColor: '#232b3d', tickMarkFormatter: t => madridTime(t).replace(',', '') },
    rightPriceScale: { borderColor: '#232b3d' },
    localization: { timeFormatter: madridTime, priceFormatter: p => price(p).slice(1) },
    crosshair: { mode: 0 },
  };
}

function drawPriceChart(d) {
  const el = document.getElementById('chart');
  if (!window.LightweightCharts || !d.candles.length) { el.innerHTML = '<div class="empty">Sin velas todavía (se descargan de GeckoTerminal en el siguiente ciclo).</div>'; return; }
  const chart = LightweightCharts.createChart(el, { ...lwOpts(420), width: el.clientWidth });
  charts.push(chart);
  const cs = chart.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', wickUpColor: '#22c55e', wickDownColor: '#ef4444', borderVisible: false,
    priceFormat: { type: 'custom', formatter: p => price(p).slice(1), minMove: 1e-12 } });
  cs.setData(d.candles.map(c => ({ time: c.ts, open: c.o, high: c.h, low: c.l, close: c.c })));
  const vol = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  vol.setData(d.candles.map(c => ({ time: c.ts, value: c.v, color: c.c >= c.o ? 'rgba(34,197,94,.35)' : 'rgba(239,68,68,.35)' })));
  const S = d.ta.series || {};
  [['ema9', '#f59e0b'], ['ema21', '#22d3ee'], ['ema50', '#a78bfa']].forEach(([k, col]) => {
    if (!S[k]) return;
    const l = chart.addLineSeries({ color: col, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    l.setData(d.candles.map((c, i) => ({ time: c.ts, value: S[k][i] })).filter((p, i) => p.value != null && (k !== 'ema50' || i >= 49)));
  });
  // marcas de subidas/bajadas
  const first = d.candles[0].ts, last = d.candles[d.candles.length - 1].ts;
  const snap = ts => { let best = d.candles[0].ts; for (const c of d.candles) { if (c.ts <= ts) best = c.ts; else break; } return best; };
  const marks = [];
  (d.legs || []).forEach(l => {
    if (l.end_ts < first || l.end_ts > last) return;
    marks.push({ time: snap(l.end_ts), position: l.direction === 'up' ? 'aboveBar' : 'belowBar', color: l.direction === 'up' ? '#22c55e' : '#ef4444',
      shape: l.direction === 'up' ? 'arrowDown' : 'arrowUp', text: `${l.pct >= 0 ? '+' : ''}${l.pct.toFixed(0)}%` });
  });
  marks.sort((a, b) => a.time - b.time);
  const dedup = marks.filter((m, i) => !i || m.time !== marks[i - 1].time);
  cs.setMarkers(dedup);
  chart.timeScale().fitContent();

  const rel = document.getElementById('rsi');
  if (S.rsi) {
    const rc = LightweightCharts.createChart(rel, { ...lwOpts(130), width: rel.clientWidth });
    charts.push(rc);
    const rs = rc.addLineSeries({ color: '#7c5cff', lineWidth: 1, priceFormat: { type: 'price', precision: 0, minMove: 1 } });
    rs.setData(d.candles.map((c, i) => ({ time: c.ts, value: S.rsi[i] })).filter(p => p.value != null));
    rs.createPriceLine({ price: 70, color: '#ef4444', lineStyle: 2, lineWidth: 1, title: '70' });
    rs.createPriceLine({ price: 30, color: '#22c55e', lineStyle: 2, lineWidth: 1, title: '30' });
    rc.timeScale().fitContent();
    chart.timeScale().subscribeVisibleLogicalRangeChange(r => r && rc.timeScale().setVisibleLogicalRange(r));
  }
  const ro = new ResizeObserver(() => charts.forEach(c => c.applyOptions && c.timeScale && c.applyOptions({ width: el.clientWidth })));
  ro.observe(el);
  charts.unshift(ro);
}

function lineChart(id, datasets, opts = {}) {
  const el = document.getElementById(id);
  if (!window.Chart || !el) return;
  const c = new Chart(el, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { labels: { color: '#8a93a8', boxWidth: 10 } }, tooltip: { callbacks: { title: it => it.length ? when(it[0].parsed.x / 1000) : '' } } },
      scales: {
        x: { type: 'linear', ticks: { color: '#8a93a8', maxTicksLimit: 6, callback: v => whenS(v / 1000) }, grid: { color: '#1a2130' } },
        y: { ticks: { color: '#8a93a8', callback: opts.yFmt || (v => v) }, grid: { color: '#1a2130' } },
        ...(opts.y2 ? { y2: { position: 'right', ticks: { color: '#8a93a8', callback: opts.yFmt }, grid: { display: false } } } : {}),
      },
    },
  });
  charts.push(c);
}

function drawHistory(snaps) {
  const pts = (k, f = v => v) => snaps.filter(s => s[k] != null).map(s => ({ x: s.ts * 1000, y: f(s[k]) }));
  const ds = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color + '22', pointRadius: data.length < 30 ? 2 : 0, borderWidth: 1.5, tension: .2, ...extra });
  const compact = v => Intl.NumberFormat('en', { notation: 'compact' }).format(v);
  if (snaps.length < 2) {
    ['cHolders', 'cLiq', 'cVol', 'cBuy'].forEach(id => { const c = document.getElementById(id); if (c) c.parentElement.innerHTML = '<div class="empty">Se irá llenando con cada actualización (cada 5 min).</div>'; });
    return;
  }
  lineChart('cHolders', [ds('Holders', pts('holders'), '#22d3ee', { fill: true })], { yFmt: v => Math.round(v).toLocaleString('es-ES') });
  lineChart('cLiq', [ds('Liquidez $', pts('liquidity_usd'), '#22c55e'), ds('Market cap $', pts('market_cap'), '#7c5cff', { yAxisID: 'y2' })], { yFmt: v => '$' + compact(v), y2: true });
  lineChart('cVol', [ds('Volumen 24h $', pts('volume_h24'), '#f59e0b', { fill: true })], { yFmt: v => '$' + compact(v) });
  const ratio = (b, s) => snaps.filter(x => x[b] != null && (x[b] + x[s]) > 0).map(x => ({ x: x.ts * 1000, y: x[b] / (x[b] + x[s]) * 100 }));
  lineChart('cBuy', [ds('Compras 1h %', ratio('buys_h1', 'sells_h1'), '#22c55e'), ds('Compras 24h %', ratio('buys_h24', 'sells_h24'), '#22d3ee')], { yFmt: v => v + '%' });
}

// ------------------------------------------------------------ arranque
pollStatus(); setInterval(pollStatus, 15000);
checkNewEvents(); setInterval(checkNewEvents, 60000);
route();
