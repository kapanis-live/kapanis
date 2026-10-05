/* eslint-disable */
/* @ds-bundle: {"format":4,"namespace":"Kapanis","components":[{"name":"PageHeader"},{"name":"Card"},{"name":"StatCard"},{"name":"SignalCard"},{"name":"ChangeBadge"},{"name":"Trend"},{"name":"RsiMeter"},{"name":"RangeBar"},{"name":"Ticker"},{"name":"Button"},{"name":"Chip"},{"name":"Segmented"},{"name":"SearchField"},{"name":"FontScale"},{"name":"ThemeToggle"},{"name":"WatchlistTable"},{"name":"PositionCard"},{"name":"CandleChart"},{"name":"ChartPanel"},{"name":"Disclaimer"},{"name":"AppShell"},{"name":"LiveStatus"},{"name":"BrandMark"},{"name":"Icon"},{"name":"Tabs"},{"name":"DecisionBadge"},{"name":"GateList"},{"name":"SignalList"},{"name":"AiNote"},{"name":"OutcomeBox"},{"name":"RegimeGauge"},{"name":"FreshnessList"},{"name":"FeedList"},{"name":"MoverList"},{"name":"PulseList"},{"name":"MiniChart"},{"name":"MarketCard"},{"name":"DataTable"},{"name":"Donut"},{"name":"Callout"},{"name":"CompareCard"},{"name":"AlarmCard"},{"name":"AlarmForm"},{"name":"Field"},{"name":"TextInput"},{"name":"Select"},{"name":"ShieldStatus"},{"name":"LimitMeter"},{"name":"StreakStrip"},{"name":"FearGreedGauge"},{"name":"LineChart"},{"name":"LevelBar"},{"name":"SiteHeader"},{"name":"SiteFooter"},{"name":"StepList"},{"name":"FeatureCard"},{"name":"RuleStrip"},{"name":"FaqList"},{"name":"CloseRuleDiagram"},{"name":"MessagePreview"},{"name":"AuthFrame"},{"name":"AuthBox"},{"name":"SetupChecklist"},{"name":"EmptyState"},{"name":"Skeleton"},{"name":"QuotaMeter"},{"name":"BuyForm"},{"name":"TelegramLink"},{"name":"ApiKeyList"},{"name":"DangerZone"}]} */
(function () {
  var R = window.React, h = R.createElement;
  var useState = R.useState, useMemo = R.useMemo, useRef = R.useRef, useEffect = R.useEffect;

  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(' '); }

  /* ---------- formatting (tr-TR, Istanbul time) ---------- */
  var NF = {};
  function nf(d) { if (!NF[d]) NF[d] = new Intl.NumberFormat('tr-TR', { minimumFractionDigits: d, maximumFractionDigits: d }); return NF[d]; }
  function autoDigits(v) { var a = Math.abs(v); return a >= 1 ? 2 : a >= 0.01 ? 4 : 6; }
  function fmtNum(v, d) { return nf(d == null ? autoDigits(v) : d).format(v); }
  var SYM = { TRY: '₺', USD: '$' };
  function fmtPrice(v, cur, d) { return (SYM[cur] || '') + fmtNum(v, d); }
  function fmtSignedMoney(v, cur) { return (v >= 0 ? '+' : '−') + (SYM[cur] || '') + fmtNum(Math.abs(v), 2); }
  function fmtPct(v) { return '%' + fmtNum(Math.abs(v), 2); }
  var TZ = 'Europe/Istanbul';
  var DF = {};
  function df(key, opts) { if (!DF[key]) DF[key] = new Intl.DateTimeFormat('tr-TR', Object.assign({ timeZone: TZ }, opts)); return DF[key]; }
  function fmtTime(t) { return df('hm', { hour: '2-digit', minute: '2-digit' }).format(t); }
  function fmtDay(t) { return df('dm', { day: 'numeric', month: 'short' }).format(t); }
  function fmtMonth(t) { return df('my', { month: 'short', year: 'numeric' }).format(t); }
  function fmtFull(t, intraday) { return intraday ? fmtDay(t) + ' ' + fmtTime(t) : df('dmy', { day: 'numeric', month: 'short', year: 'numeric' }).format(t); }
  function istDay(t) { return Math.floor((t + 3 * 3600e3) / 86400e3); } /* Turkey is UTC+3 all year */

  /* ---------- indicators ---------- */
  function sma(vals, n) {
    var out = new Array(vals.length), s = 0;
    for (var i = 0; i < vals.length; i++) {
      s += vals[i]; if (i >= n) s -= vals[i - n];
      out[i] = i >= n - 1 ? s / n : null;
    }
    return out;
  }
  function rsi(closes, n) {
    n = n || 14;
    var out = new Array(closes.length).fill(null), g = 0, l = 0;
    for (var i = 1; i < closes.length; i++) {
      var d = closes[i] - closes[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
      if (i <= n) { g += up; l += dn; if (i === n) { g /= n; l /= n; out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); } }
      else { g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n; out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); }
    }
    return out;
  }
  function vwap(c, intraday) {
    var out = [], pv = 0, vv = 0, day = null;
    for (var i = 0; i < c.length; i++) {
      var k = istDay(c[i].t);
      if (intraday && k !== day) { pv = 0; vv = 0; day = k; }
      var tp = (c[i].h + c[i].l + c[i].c) / 3;
      pv += tp * c[i].v; vv += c[i].v;
      out.push(vv ? pv / vv : null);
    }
    return out;
  }

  /* ---------- demo data (deterministic) ---------- */
  var TF = {
    '15m': { label: '15 dk', ms: 9e5, intraday: true, vol: 0.004 },
    '1h': { label: '1 saat', ms: 3.6e6, intraday: true, vol: 0.007 },
    '4h': { label: '4 saat', ms: 1.44e7, intraday: true, vol: 0.012 },
    '1d': { label: 'Günlük', ms: 8.64e7, intraday: false, vol: 0.02 },
    '1w': { label: 'Haftalık', ms: 6.048e8, intraday: false, vol: 0.045 }
  };
  function hashStr(s) { var x = 2166136261; for (var i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 16777619); } return x >>> 0; }
  function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; var t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function demoCandles(symbol, tf, base, n) {
    var cfg = TF[tf] || TF['1d']; n = n || 180;
    var r = rng(hashStr(symbol + tf)), end = Math.floor(Date.now() / cfg.ms) * cfg.ms;
    var p = base || 100, drift = (r() - 0.45) * cfg.vol * 0.25, out = [];
    for (var i = 0; i < n; i++) {
      var o = p, ch = (r() - 0.5) * 2 * cfg.vol + drift + Math.sin(i / 17) * cfg.vol * 0.3;
      var c = o * (1 + ch), hi = Math.max(o, c) * (1 + r() * cfg.vol * 0.6), lo = Math.min(o, c) * (1 - r() * cfg.vol * 0.6);
      var v = (0.6 + r() * 0.8 + Math.abs(ch) / cfg.vol * 0.6) * 1e6 * (r() < 0.05 ? 2.4 : 1);
      out.push({ t: end - (n - 1 - i) * cfg.ms, o: o, h: hi, l: lo, c: c, v: v });
      p = c;
    }
    var k = (base || 100) / out[n - 1].c; /* end at the given base price */
    out.forEach(function (x) { x.o *= k; x.h *= k; x.l *= k; x.c *= k; });
    return out;
  }
  var UNIVERSE = {
    kripto: { label: 'Kripto', cur: 'USD', items: [['BTC', 'Bitcoin', 64250], ['ETH', 'Ethereum', 3420], ['SOL', 'Solana', 151.4]] },
    bist: { label: 'BIST', cur: 'TRY', items: [['THYAO', 'Türk Hava Yolları', 312.5], ['ASELS', 'Aselsan', 64.3], ['BIMAS', 'BİM Mağazalar', 541]] },
    abd: { label: 'ABD', cur: 'USD', items: [['AAPL', 'Apple', 228.4], ['NVDA', 'NVIDIA', 118.2], ['MSFT', 'Microsoft', 432.1]] }
  };

  /* ---------- small parts ---------- */
  function ChangeBadge(p) {
    var v = +p.value || 0, tone = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    var arrow = tone === 'up' ? '▲' : tone === 'down' ? '▼' : '–';
    return h('span', { className: cx('kp-badge', 'kp-badge--' + tone, p.size === 'lg' && 'kp-badge--lg', p.className), title: p.title },
      p.label ? h('span', { className: 'kp-badge__label' }, p.label) : null,
      h('span', { 'aria-hidden': true }, arrow),
      h('span', null, fmtPct(v)));
  }

  var TREND = { up: ['↗', 'Güçlü'], flat: ['→', 'Karışık'], down: ['↘', 'Zayıf'] };
  function Trend(p) {
    var d = TREND[p.dir] ? p.dir : 'flat';
    return h('span', { className: cx('kp-trend', 'kp-trend--' + d) },
      h('span', { className: 'kp-trend__arrow', 'aria-hidden': true }, TREND[d][0]), p.label || TREND[d][1]);
  }

  function RsiMeter(p) {
    var v = Math.max(0, Math.min(100, +p.value || 0));
    var tone = v >= 70 ? 'hot' : v <= 30 ? 'cold' : 'mid';
    return h('span', { className: cx('kp-rsi', 'kp-rsi--' + tone), title: 'RSI 14: ' + fmtNum(v, 1) },
      h('span', { className: 'kp-rsi__num' }, fmtNum(v, 0)),
      h('span', { className: 'kp-rsi__bar', 'aria-hidden': true },
        h('span', { className: 'kp-rsi__fill', style: { width: v + '%' } }),
        h('span', { className: 'kp-rsi__tick', style: { left: '30%' } }),
        h('span', { className: 'kp-rsi__tick', style: { left: '70%' } })));
  }

  function RangeBar(p) {
    var s = +p.support, r = +p.resistance, x = +p.price;
    var pct = r > s ? (x - s) / (r - s) * 100 : 50, pos = pct > 100 ? 'above' : pct < 0 ? 'below' : 'in';
    var c = Math.max(0, Math.min(100, pct));
    return h('span', { className: cx('kp-range', 'kp-range--' + pos) },
      h('span', { className: 'kp-range__labels' },
        h('span', null, fmtPrice(s, p.cur)), h('span', { className: 'kp-range__sep', 'aria-hidden': true }, '→'), h('span', null, fmtPrice(r, p.cur))),
      h('span', { className: 'kp-range__track', role: 'img', 'aria-label': 'Fiyat destek ile direnç arasında %' + fmtNum(c, 0) + ' konumunda' },
        h('span', { className: 'kp-range__dot', style: { left: c + '%' } })));
  }

  function TickerLogo(p) {
    /* Kapanış paneli: logo her yerde aynı bileşenle (AssetLogo, window.KapanisLogo) çizilir:
       40px yuvarlak, dolu logolar daireyi doldurur, yazılı logolar beyaz rozette. p.src = { code, market }. */
    var size = p.size || 'md';
    if (p.src && p.src.code && window.KapanisLogo) {
      return h(window.KapanisLogo, { code: p.src.code, market: p.src.market, size: size === 'lg' ? 48 : 40 });
    }
    /* logo verilmediyse de koddan bul (HYPE, HYPE/USDT, THYAO.IS, AAPL.US): her listede logo görünsün */
    if (!p.src && p.symbol && window.KapanisLogo) {
      return h(window.KapanisLogo, { code: p.symbol, market: p.market, size: size === 'lg' ? 48 : 40 });
    }
    return h('span', { className: cx('kp-logo', 'kp-logo--' + size), 'aria-hidden': true },
      p.src && typeof p.src === 'string' ? h('img', { src: p.src, alt: '' }) : String(p.symbol || '?').slice(0, size === 'lg' ? 3 : 2));
  }
  function Ticker(p) {
    return h('span', { className: cx('kp-ticker', p.size === 'lg' && 'kp-ticker--lg') },
      h(TickerLogo, { symbol: p.symbol, src: p.logo, market: p.market, size: p.size }),
      h('span', { className: 'kp-ticker__text' },
        h('span', { className: 'kp-ticker__code' }, p.symbol),
        p.name ? h('span', { className: 'kp-ticker__name' }, p.name) : null));
  }

  function Button(p) {
    var rest = Object.assign({}, p); delete rest.variant; delete rest.className; delete rest.icon; delete rest.iconEnd;
    var cls = cx('kp-btn', 'kp-btn--' + (p.variant || 'secondary'), p.className);
    var kids = [p.icon ? h('span', { key: 'i', className: 'kp-btn__icon', 'aria-hidden': true }, p.icon) : null, p.children,
      p.iconEnd ? h('span', { key: 'e', className: 'kp-btn__icon', 'aria-hidden': true }, p.iconEnd) : null];
    if (p.href) return h.apply(null, ['a', Object.assign({}, rest, { className: cls })].concat(kids));
    return h.apply(null, ['button', Object.assign({ type: 'button' }, rest, { className: cls })].concat(kids));
  }

  function Chip(p) {
    return h('button', { type: 'button', className: cx('kp-chip', p.active && 'is-active'), 'aria-pressed': !!p.active, onClick: p.onClick },
      h('span', { className: 'kp-chip__swatch', style: { background: p.color }, 'aria-hidden': true }), p.children);
  }

  function Segmented(p) {
    var opts = (p.options || []).map(function (o) { return typeof o === 'string' ? { value: o, label: o } : o; });
    return h('div', { className: 'kp-seg', role: 'radiogroup', 'aria-label': p.ariaLabel },
      opts.map(function (o) {
        var on = o.value === p.value;
        return h('button', { key: o.value, type: 'button', role: 'radio', 'aria-checked': on, className: cx('kp-seg__opt', on && 'is-active'),
          onClick: function () { p.onChange && p.onChange(o.value); } }, o.label);
      }));
  }

  var SEARCH_ICON = h('svg', { viewBox: '0 0 20 20', width: 18, height: 18, 'aria-hidden': true },
    h('circle', { cx: 8.5, cy: 8.5, r: 5.5, fill: 'none', stroke: 'currentColor', strokeWidth: 1.8 }),
    h('path', { d: 'M13 13l4 4', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' }));
  function SearchField(p) {
    var st = useState(p.defaultValue || ''), val = p.value != null ? p.value : st[0];
    return h('label', { className: 'kp-search' }, SEARCH_ICON,
      h('input', { type: 'search', value: val, placeholder: p.placeholder || 'Kod ara (ör. THYAO)', 'aria-label': p.ariaLabel || 'Kod ara',
        onChange: function (e) { st[1](e.target.value); p.onChange && p.onChange(e.target.value); },
        onKeyDown: function (e) { if (e.key === 'Enter' && p.onSubmit) p.onSubmit(e.target.value.trim().toUpperCase()); } }));
  }

  /* font scale: every size in the system is rem, so the root size scales all of it */
  var SCALES = [15, 16, 17, 18, 20];
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function FontScale() {
    var init = +store('kp-font') || 16, st = useState(SCALES.indexOf(init) >= 0 ? init : 16), px = st[0];
    useEffect(function () { document.documentElement.style.fontSize = px + 'px'; store('kp-font', String(px)); }, [px]);
    var i = SCALES.indexOf(px);
    return h('div', { className: 'kp-fontscale', role: 'group', 'aria-label': 'Yazı boyutu' },
      h('button', { type: 'button', className: 'kp-fontscale__btn', disabled: i <= 0, 'aria-label': 'Yazıyı küçült', onClick: function () { st[1](SCALES[i - 1]); } }, 'A−'),
      h('span', { className: 'kp-fontscale__val' }, '%' + Math.round(px / 16 * 100)),
      h('button', { type: 'button', className: 'kp-fontscale__btn kp-fontscale__btn--lg', disabled: i >= SCALES.length - 1, 'aria-label': 'Yazıyı büyüt', onClick: function () { st[1](SCALES[i + 1]); } }, 'A+'));
  }

  function ThemeToggle() {
    var st = useState(document.documentElement.getAttribute('data-theme') || store('kp-theme') || 'dark');
    useEffect(function () { document.documentElement.setAttribute('data-theme', st[0]); store('kp-theme', st[0]); }, [st[0]]);
    return h(Segmented, { ariaLabel: 'Tema', value: st[0], onChange: st[1], options: [{ value: 'dark', label: 'Koyu' }, { value: 'light', label: 'Açık' }] });
  }

  function PageHeader(p) {
    return h('header', { className: 'kp-pagehead' },
      h('div', null,
        h('h1', { className: 'kp-pagehead__title' }, p.title),
        p.subtitle ? h('p', { className: 'kp-pagehead__sub' }, p.subtitle) : null),
      h('div', { className: 'kp-pagehead__actions' }, p.actions, p.controls === false ? null : [h(ThemeToggle, { key: 't' })]));
  }

  function Card(p) {
    return h('section', { className: cx('kp-card', p.className) },
      p.title || p.actions ? h('div', { className: 'kp-card__head' },
        p.title ? h('h2', { className: 'kp-card__title' }, p.title) : null,
        p.actions ? h('div', { className: 'kp-card__actions' }, p.actions) : null) : null,
      p.children);
  }

  function StatCard(p) {
    return h('div', { className: 'kp-card kp-stat' },
      h('div', { className: 'kp-stat__label' }, p.label),
      h('div', { className: cx('kp-stat__value', p.tone && 'is-' + p.tone) }, p.value),
      p.change != null || p.sub ? h('div', { className: 'kp-stat__foot' },
        p.change != null ? h(ChangeBadge, { value: p.change, label: p.changeLabel }) : null,
        p.sub ? h('span', { className: 'kp-stat__sub' }, p.sub) : null) : null);
  }

  function SignalCard(p) {
    return h('div', { className: cx('kp-card kp-signal', 'is-' + (p.tone || 'flat')) },
      h('div', { className: 'kp-signal__title' }, p.title),
      h('div', { className: 'kp-signal__verdict' }, h('span', { className: 'kp-signal__dot', 'aria-hidden': true }), p.verdict),
      p.detail ? h('p', { className: 'kp-signal__detail' }, p.detail) : null);
  }

  function Disclaimer(p) {
    return h('footer', { className: 'kp-disclaimer' }, p.children || 'Yatırım tavsiyesi değildir. Bot işlem yapmaz.');
  }

  /* ---------- watchlist ---------- */
  function WatchlistTable(p) {
    var rows = p.rows || [];
    function open(r) { p.onOpen && p.onOpen(r); }
    return h('div', { className: 'kp-tablewrap' },
      h('table', { className: 'kp-table' },
        h('thead', null, h('tr', null,
          h('th', null, 'Kod'), h('th', { className: 'is-num' }, 'Fiyat'), h('th', { className: 'is-num' }, 'Gün'), h('th', { className: 'is-num' }, 'Hafta'),
          h('th', null, 'Trend'), h('th', null, 'RSI'), h('th', null, 'Destek → Direnç'))),
        h('tbody', null, rows.map(function (r) {
          return h('tr', { key: r.symbol, tabIndex: 0, className: 'kp-row', 'aria-label': r.symbol + ' grafiğini aç',
            onClick: function () { open(r); }, onKeyDown: function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(r); } } },
            h('td', null, h(Ticker, { symbol: r.symbol, name: r.name, logo: r.logo })),
            h('td', { className: 'is-num kp-price' }, fmtPrice(r.price, r.cur)),
            h('td', { className: 'is-num' }, h(ChangeBadge, { value: r.d1 })),
            h('td', { className: 'is-num' }, h(ChangeBadge, { value: r.w1 })),
            h('td', null, h(Trend, { dir: r.trend })),
            h('td', null, h(RsiMeter, { value: r.rsi })),
            h('td', null, h(RangeBar, { support: r.support, resistance: r.resistance, price: r.price, cur: r.cur })));
        }))));
  }

  /* ---------- position ---------- */
  function PositionCard(p) {
    var cur = p.cur, invested = p.qty * p.cost, now = p.qty * p.price, pl = now - invested, plPct = invested ? pl / invested * 100 : 0;
    var tone = pl > 0 ? 'up' : pl < 0 ? 'down' : 'flat', hasStop = p.stop != null;
    var mode = useState(null), val = useState(''), err = useState(null);
    var nowLabel = p.priceLabel || (hasStop ? 'Son kapanış' : 'Şimdi');
    function open(m) { var base = m === 'stop' ? p.stop : p.price; err[1](null); val[1](fmtNum(base, autoDigits(base)).replace(/\./g, '')); mode[1](m); }
    function submit(e) {
      e.preventDefault();
      var v = parseTr(val[0]);
      if (!(v > 0)) { err[1]('Geçerli bir fiyat yaz.'); return; }
      if (mode[0] === 'stop') {
        if (v <= p.stop) { err[1]('Stop yalnız yukarı taşınır. ' + fmtPrice(p.stop, cur) + ' üstünde bir değer yaz.'); return; }
        if (v >= p.price) { err[1]('Stop son kapanışın (' + fmtPrice(p.price, cur) + ') altında olmalı.'); return; }
        p.onRaiseStop && p.onRaiseStop({ symbol: p.symbol, stop: v });
      } else if (p.onSold) p.onSold({ symbol: p.symbol, price: v, qty: p.qty });
      mode[1](null);
    }
    function tile(k, v) { return h('div', { key: k, className: 'kp-tile' }, h('span', { className: 'kp-tile__label' }, k), h('span', { className: 'kp-tile__val' }, v)); }
    var tiles = hasStop
      ? [tile('Alış', fmtPrice(p.cost, cur)), tile(nowLabel, fmtPrice(p.price, cur)), tile('Değer', fmtPrice(now, cur, 2))]
      : [tile('Yatırdığın', fmtPrice(invested, cur, 2)), tile('Şimdiki değeri', fmtPrice(now, cur, 2)),
         h('div', { key: 'a', className: 'kp-tile' }, h('span', { className: 'kp-tile__label' }, 'Alış → şimdi'),
           h('span', { className: 'kp-tile__val' }, fmtPrice(p.cost, cur), h('span', { className: 'kp-tile__arrow' }, ' → '), fmtPrice(p.price, cur)))];
    var form = mode[0] ? h('form', { className: 'kp-pos__sell', onSubmit: submit, noValidate: true },
        h(Field, { label: mode[0] === 'stop' ? 'Yeni stop' : 'Sattığın fiyat', error: err[0],
          hint: mode[0] === 'stop' ? 'Şu an ' + fmtPrice(p.stop, cur) + ' · stop yalnız yukarı taşınır' : 'Son kapanışla dolu geldi; gerçekleşen fiyatı yaz' },
          h(TextInput, { prefix: SYM[cur] || '', inputMode: 'decimal', value: val[0], autoFocus: true, onChange: function (e) { val[1](e.target.value); } })),
        h('div', { className: 'kp-pos__actions' },
          h(Button, { variant: 'ghost', onClick: function () { mode[1](null); } }, 'Vazgeç'),
          h(Button, { variant: 'primary', type: 'submit' }, 'Kaydet'))) : null;
    return h('article', { className: 'kp-card kp-pos' },
      h('div', { className: 'kp-pos__head' },
        /* Kapanış paneli düzeltmesi: başlığa tıklamak grafiği açar; ayrı "Grafiği aç" butonu yok */
        h('button', { type: 'button', title: 'Grafiği aç', onClick: function () { p.onOpenChart && p.onOpenChart(p.symbol); },
          style: { background: 'none', border: 0, padding: 0, cursor: 'pointer', textAlign: 'left', color: 'inherit', font: 'inherit', minWidth: 0 } },
          h(Ticker, { symbol: p.symbol, name: p.name, logo: p.logo, size: 'lg' })),
        h('span', { className: 'kp-pos__qty' }, new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 8 }).format(p.qty) + ' adet')),
      h('div', { className: 'kp-pos__pl' },
        h('span', { className: cx('kp-pos__plval', 'is-' + tone) }, fmtSignedMoney(pl, cur)),
        h(ChangeBadge, { value: plPct, size: 'lg' }), hasStop ? h('span', { className: 'kp-pos__pllabel' }, 'açık K/Z') : null),
      h('div', { className: 'kp-pos__tiles' }, tiles),
      hasStop ? h(LevelBar, { stop: p.stop, target: p.target, cost: p.cost, price: p.price, cur: cur }) : null,
      form || h('div', { className: 'kp-pos__actions' },
        hasStop && p.onRaiseStop !== false ? h(Button, { variant: 'secondary', onClick: function () { open('stop'); } }, 'Stopu yükselt') : null,
        p.onSold !== false ? h(Button, { variant: 'secondary', onClick: function () { open('sell'); } }, 'Sattım') : null,
        /* Kapanış paneli düzeltmesi: satış fiyatı sormadan kaydı kaldıran tek tıklık buton */
        p.onDelete ? h(Button, { variant: 'secondary', onClick: function () { p.onDelete(p.symbol); } }, 'Sil') : null));
  }

  function signedPct(v) { return (v >= 0 ? '+' : '−') + '%' + fmtNum(Math.abs(v), 1); }
  function LevelBar(p) {
    var s = p.stop, t = p.target, x = p.price, c = p.cost, cur = p.cur, has = t != null && t > s;
    function pos(v) { return has ? Math.max(0, Math.min(100, (v - s) / (t - s) * 100)) : 50; }
    return h('div', { className: 'kp-levelbar' },
      h('div', { className: 'kp-levelbar__track', role: 'img', 'aria-label': 'Stop ' + fmtPrice(s, cur) + (has ? ', hedef ' + fmtPrice(t, cur) : '') + ', son kapanış ' + fmtPrice(x, cur) },
        has && c != null ? h('span', { className: 'kp-levelbar__cost', style: { left: pos(c) + '%' }, title: 'Alış ' + fmtPrice(c, cur) }) : null,
        h('span', { className: 'kp-levelbar__dot', style: { left: pos(x) + '%' } })),
      h('div', { className: 'kp-levelbar__labels' },
        h('span', { className: 'kp-levelbar__stop' }, h('b', null, 'Stop '), fmtPrice(s, cur), h('span', { className: 'kp-levelbar__pct' }, signedPct((s / x - 1) * 100))),
        has ? h('span', { className: 'kp-levelbar__target' }, h('b', null, 'Hedef '), fmtPrice(t, cur), h('span', { className: 'kp-levelbar__pct' }, signedPct((t / x - 1) * 100)))
          : h('span', { className: 'kp-levelbar__pct' }, 'Hedef yok')));
  }

  /* ---------- candlestick chart ---------- */
  var IND = [
    { key: 'sma20', label: 'SMA 20', color: 'var(--sma-20)' },
    { key: 'sma50', label: 'SMA 50', color: 'var(--sma-50)' },
    { key: 'sma200', label: 'SMA 200', color: 'var(--sma-200)' },
    { key: 'vwap', label: 'VWAP', color: 'var(--vwap)' }
  ];
  function niceStep(range, count) {
    var raw = range / count, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
    return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
  }
  function pathOf(arr, x, y) {
    var d = '', pen = false;
    for (var i = 0; i < arr.length; i++) {
      if (arr[i] == null) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(arr[i]).toFixed(1); pen = true;
    }
    return d;
  }
  function useWidth(ref) {
    var st = useState(900);
    useEffect(function () {
      var el = ref.current; if (!el || !window.ResizeObserver) return;
      var ro = new ResizeObserver(function (e) { st[1](Math.max(320, Math.floor(e[0].contentRect.width))); });
      ro.observe(el); return function () { ro.disconnect(); };
    }, []);
    return st[0];
  }
  function analyse(c, tf) {
    var closes = c.map(function (x) { return x.c; }), vols = c.map(function (x) { return x.v; });
    return { sma20: sma(closes, 20), sma50: sma(closes, 50), sma200: sma(closes, 200), vwap: vwap(c, (TF[tf] || TF['1d']).intraday), rsi: rsi(closes, 14), volAvg: sma(vols, 20) };
  }

  function CandleChart(p) {
    var c = p.candles || [], tf = p.tf || '1d', cfg = TF[tf] || TF['1d'], on = p.indicators || { sma20: true, sma50: true };
    var ref = useRef(null), w = useWidth(ref), hv = useState(null), hover = hv[0];
    var a = useMemo(function () { return p.analysis || analyse(c, tf); }, [c, tf, p.analysis]);
    var rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    var H = p.height || Math.round(rem * 34), axisW = Math.round(rem * 5.75), timeH = Math.round(rem * 2), g = Math.round(rem * 0.75);
    var plotW = w - axisW, plotH = H - timeH - 2 * g;
    var priceH = plotH * 0.65, volH = plotH * 0.17, rsiH = plotH * 0.18, vTop = priceH + g, rTop = vTop + volH + g;
    var n = c.length; if (!n) return h('div', { ref: ref, className: 'kp-chart' });
    var step = plotW / n, bw = Math.max(1, step * 0.66);
    function x(i) { return step * i + step / 2; }
    var lo = Infinity, hi = -Infinity;
    c.forEach(function (k, i) {
      lo = Math.min(lo, k.l); hi = Math.max(hi, k.h);
      IND.forEach(function (d) { var v = a[d.key][i]; if (on[d.key] && v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    });
    var pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
    var pTop = Math.round(rem * 3.5); /* room for the OHLC legend */
    function yP(v) { return pTop + (hi - v) / (hi - lo) * (priceH - pTop); }
    var vmax = Math.max.apply(null, c.map(function (k) { return k.v; }));
    function yV(v) { return vTop + volH - v / vmax * volH * 0.9; }
    function yR(v) { return rTop + (100 - v) / 100 * rsiH; }
    var st = niceStep(hi - lo, 5), ticks = [];
    for (var t = Math.ceil(lo / st) * st; t <= hi; t += st) ticks.push(t);
    var tdig = st >= 1 ? (st % 1 ? 1 : 0) : Math.min(6, Math.ceil(-Math.log10(st)));
    /* time labels at least ~7rem apart */
    var every = Math.max(1, Math.ceil(rem * 7 / step)), tlabels = [];
    for (var i = n - 1; i >= 0; i -= every) tlabels.unshift(i);
    function tlabel(idx) {
      var t0 = c[idx].t;
      if (cfg.intraday) { var prev = idx - every >= 0 ? c[idx - every].t : null; return prev != null && istDay(prev) === istDay(t0) ? fmtTime(t0) : fmtDay(t0); }
      return tf === '1w' ? fmtMonth(t0) : fmtDay(t0);
    }
    var last = c[n - 1], lastUp = last.c >= last.o, lastY = yP(last.c);
    var hi2 = hover != null ? hover : n - 1, k = c[hi2], rsiNow = a.rsi[hi2];

    function onMove(e) {
      var b = e.currentTarget.getBoundingClientRect(), mx = e.clientX - b.left;
      if (mx > plotW) { hv[1](null); return; }
      hv[1](Math.max(0, Math.min(n - 1, Math.floor(mx / step))));
    }

    var svg = h('svg', { width: w, height: H, className: 'kp-chart__svg', onMouseMove: onMove, onMouseLeave: function () { hv[1](null); }, role: 'img',
        'aria-label': (p.symbol || '') + ' mum grafiği, ' + cfg.label },
      /* grid */
      ticks.map(function (t) { return h('line', { key: 'g' + t, className: 'kp-ch-grid', x1: 0, x2: plotW, y1: yP(t), y2: yP(t) }); }),
      tlabels.map(function (i) { return h('line', { key: 'v' + i, className: 'kp-ch-grid', x1: x(i), x2: x(i), y1: 0, y2: rTop + rsiH }); }),
      h('line', { className: 'kp-ch-sep', x1: 0, x2: w, y1: vTop - g / 2, y2: vTop - g / 2 }),
      h('line', { className: 'kp-ch-sep', x1: 0, x2: w, y1: rTop - g / 2, y2: rTop - g / 2 }),
      h('line', { className: 'kp-ch-sep', x1: plotW, x2: plotW, y1: 0, y2: rTop + rsiH }),
      /* volume */
      c.map(function (k, i) { var y = yV(k.v); return h('rect', { key: 'vb' + i, className: k.c >= k.o ? 'kp-ch-vol-up' : 'kp-ch-vol-down', x: x(i) - bw / 2, y: y, width: bw, height: vTop + volH - y }); }),
      h('path', { className: 'kp-ch-volavg', d: pathOf(a.volAvg, x, yV) }),
      /* candles */
      c.map(function (k, i) {
        var up = k.c >= k.o, top = yP(Math.max(k.o, k.c)), bh = Math.max(1, Math.abs(yP(k.o) - yP(k.c)));
        return h('g', { key: 'c' + i, className: up ? 'kp-ch-up' : 'kp-ch-down' },
          h('line', { x1: x(i), x2: x(i), y1: yP(k.h), y2: yP(k.l) }),
          h('rect', { x: x(i) - bw / 2, y: top, width: bw, height: bh }));
      }),
      /* overlays */
      IND.map(function (d) { return on[d.key] ? h('path', { key: d.key, className: 'kp-ch-line', style: { stroke: d.color }, d: pathOf(a[d.key], x, yP) }) : null; }),
      /* rsi */
      h('line', { className: 'kp-ch-lvl kp-ch-lvl--hot', x1: 0, x2: plotW, y1: yR(70), y2: yR(70) }),
      h('line', { className: 'kp-ch-lvl kp-ch-lvl--cold', x1: 0, x2: plotW, y1: yR(30), y2: yR(30) }),
      h('path', { className: 'kp-ch-line kp-ch-rsi', d: pathOf(a.rsi, x, yR) }),
      /* crosshair */
      hover != null ? h('line', { className: 'kp-ch-cross', x1: x(hover), x2: x(hover), y1: 0, y2: rTop + rsiH }) : null,
      /* axes */
      ticks.map(function (t) { return h('text', { key: 'a' + t, className: 'kp-ch-axis', x: plotW + 8, y: yP(t), dy: '0.35em' }, fmtNum(t, tdig)); }),
      h('text', { className: 'kp-ch-axis', x: plotW + 8, y: yR(70), dy: '0.35em' }, '70'),
      h('text', { className: 'kp-ch-axis', x: plotW + 8, y: yR(30), dy: '0.35em' }, '30'),
      tlabels.map(function (i) { return h('text', { key: 't' + i, className: 'kp-ch-axis', x: x(i), y: H - timeH / 2 + 2, textAnchor: x(i) < rem * 2.5 ? 'start' : 'middle', dy: '0.35em' }, tlabel(i)); }),
      h('g', { className: lastUp ? 'kp-ch-tag--up' : 'kp-ch-tag--down' },
        h('line', { className: 'kp-ch-lastline', x1: 0, x2: plotW, y1: lastY, y2: lastY }),
        h('rect', { x: plotW + 2, y: lastY - rem * 0.8, width: axisW - 4, height: rem * 1.6, rx: 4 }),
        h('text', { x: plotW + 8, y: lastY, dy: '0.35em' }, fmtNum(last.c, tdig + 1 > 6 ? 6 : Math.max(2, tdig)))));

    var legend = h('div', { className: 'kp-chart__legend' },
      h('div', { className: 'kp-chart__ohlc' },
        h('span', { className: 'kp-chart__when' }, fmtFull(k.t, cfg.intraday)),
        ['A', k.o, 'Y', k.h, 'D', k.l, 'K', k.c].reduce(function (acc, v, j, arr) {
          if (j % 2) return acc;
          acc.push(h('span', { key: j }, h('b', null, v), ' ', h('span', { className: k.c >= k.o ? 'is-up' : 'is-down' }, fmtNum(arr[j + 1])))); return acc;
        }, [])),
      h('div', { className: 'kp-chart__inds' }, IND.map(function (d) {
        var v = a[d.key][hi2];
        return on[d.key] ? h('span', { key: d.key }, h('i', { style: { background: d.color } }), d.label + ' ', h('b', null, v == null ? '—' : fmtNum(v))) : null;
      })));

    return h('div', { ref: ref, className: 'kp-chart' }, legend,
      h('div', { className: 'kp-chart__pane-label', style: { top: vTop + 4 + 'px' } }, 'Hacim'),
      h('div', { className: 'kp-chart__pane-label', style: { top: rTop + 4 + 'px' } }, 'RSI 14 ', h('b', null, rsiNow == null ? '—' : fmtNum(rsiNow, 1))),
      svg);
  }

  function signals(c, a) {
    var n = c.length - 1, px = c[n].c, s20 = a.sma20[n], s50 = a.sma50[n], s200 = a.sma200[n], r = a.rsi[n], va = a.volAvg[n], vw = a.vwap[n];
    var trend;
    if (s20 != null && s50 != null && px > s20 && s20 > s50 && (s200 == null || s50 > s200)) trend = { tone: 'up', verdict: 'Yükseliş eğilimi', detail: 'Fiyat kısa ve orta vadeli ortalamaların (SMA 20 / 50' + (s200 != null ? ' / 200' : '') + ') üstünde.' };
    else if (s20 != null && s50 != null && px < s20 && s20 < s50) trend = { tone: 'down', verdict: 'Düşüş eğilimi', detail: 'Fiyat ortalamaların altında; kısa vade orta vadenin gerisinde.' };
    else trend = { tone: 'flat', verdict: 'Karışık', detail: 'Fiyat ortalamaların arasında; net bir yön yok.' };
    var rs = r >= 70 ? { tone: 'warn', verdict: 'Isınmış · ' + fmtNum(r, 0), detail: 'Kısa sürede çok yükseldi; soğuma görmek sık olur.' }
      : r <= 30 ? { tone: 'info', verdict: 'Çok satılmış · ' + fmtNum(r, 0), detail: 'Kısa sürede çok düştü; tepki gelebilir ama garanti değil.' }
      : { tone: 'flat', verdict: 'Normal · ' + fmtNum(r, 0), detail: 'Aşırı alım ya da aşırı satım bölgesinde değil.' };
    var ratio = va ? c[n].v / va : 1;
    var vol = { tone: ratio >= 1.5 ? 'info' : 'flat', verdict: 'Ortalamanın ' + fmtNum(ratio, 1) + ' katı',
      detail: ratio >= 1.5 ? 'Son 20 mumun ortalamasından belirgin yüksek; hareket ilgi görüyor.' : ratio <= 0.6 ? 'Sakin işlem; hareketin arkasında güç zayıf.' : 'Son 20 mumun ortalamasına yakın.' };
    var diff = vw ? (px - vw) / vw * 100 : 0;
    var vwp = diff >= 0 ? { tone: 'up', verdict: 'VWAP üstünde', detail: 'Fiyat hacim ağırlıklı ortalamanın ' + fmtPct(diff) + ' üstünde.' }
      : { tone: 'down', verdict: 'VWAP altında', detail: 'Fiyat hacim ağırlıklı ortalamanın ' + fmtPct(diff) + ' altında.' };
    return [Object.assign({ title: 'Trend' }, trend), Object.assign({ title: 'RSI' }, rs), Object.assign({ title: 'Hacim' }, vol), Object.assign({ title: 'VWAP' }, vwp)];
  }

  function findSymbol(code) {
    for (var m in UNIVERSE) { var it = UNIVERSE[m].items; for (var i = 0; i < it.length; i++) if (it[i][0] === code) return { market: m, item: it[i] }; }
    return null;
  }

  function ChartPanel(p) {
    var mk = useState(p.market || 'bist'), sym = useState(p.symbol || UNIVERSE[mk[0]].items[0][0]), tfs = useState(p.tf || '1d');
    var ind = useState(p.indicators || { sma20: true, sma50: true, sma200: true, vwap: false });
    var found = findSymbol(sym[0]), market = found ? found.market : mk[0], cur = UNIVERSE[market].cur;
    var item = found ? found.item : [sym[0], '', 100];
    var candles = useMemo(function () { return p.getCandles ? p.getCandles(sym[0], tfs[0]) : demoCandles(sym[0], tfs[0], item[2], 220); }, [sym[0], tfs[0]]);
    var a = useMemo(function () { return analyse(candles, tfs[0]); }, [candles]);
    var n = candles.length - 1, lastC = candles[n].c;
    var back = Math.max(1, Math.round(86400e3 / (TF[tfs[0]] || TF['1d']).ms)), ref0 = candles[Math.max(0, n - back)].c;
    var dayChg = tfs[0] === '1w' ? (lastC / candles[n - 1].c - 1) * 100 : (lastC / ref0 - 1) * 100;
    function pickMarket(m) { mk[1](m); sym[1](UNIVERSE[m].items[0][0]); }
    function search(code) { if (!code) return; var f = findSymbol(code); if (f) mk[1](f.market); sym[1](code); }

    return h('div', { className: 'kp-chartpanel' },
      h('div', { className: 'kp-card kp-chartpanel__card' },
        h('div', { className: 'kp-chartpanel__top' },
          h('div', { className: 'kp-chartpanel__id' },
            h(Ticker, { symbol: sym[0], name: item[1], size: 'lg' }),
            h('div', { className: 'kp-chartpanel__price' },
              h('span', { className: 'kp-chartpanel__last' }, fmtPrice(lastC, cur)),
              h(ChangeBadge, { value: dayChg, label: tfs[0] === '1w' ? 'Hafta' : 'Gün', size: 'lg' }))),
          h('div', { className: 'kp-chartpanel__controls' },
            h(Segmented, { ariaLabel: 'Piyasa', value: market, onChange: pickMarket, options: Object.keys(UNIVERSE).map(function (m) { return { value: m, label: UNIVERSE[m].label }; }) }),
            h(SearchField, { onSubmit: search }))),
        h('div', { className: 'kp-chartpanel__bar' },
          h(Segmented, { ariaLabel: 'Zaman dilimi', value: tfs[0], onChange: tfs[1], options: Object.keys(TF).map(function (k) { return { value: k, label: TF[k].label }; }) }),
          h('div', { className: 'kp-chartpanel__chips' }, IND.map(function (d) {
            return h(Chip, { key: d.key, color: d.color, active: !!ind[0][d.key], onClick: function () { var o = Object.assign({}, ind[0]); o[d.key] = !o[d.key]; ind[1](o); } }, d.label);
          }))),
        h(CandleChart, { candles: candles, analysis: a, tf: tfs[0], indicators: ind[0], symbol: sym[0] }),
        h('p', { className: 'kp-chartpanel__note' }, 'Saatler İstanbul saatidir (UTC+3). Son mum henüz kapanmamış olabilir; değerleri değişebilir.')),
      h('div', { className: 'kp-signals' }, signals(candles, a).map(function (s) { return h(SignalCard, Object.assign({ key: s.title }, s)); })));
  }


  /* ================= app-level components ================= */

  /* ---------- icons: Kapanış's own minimal line set, 20px grid, 1.75 stroke, currentColor ---------- */
  var ICONS = {
    overview: [['rect', { x: 3, y: 3, width: 6, height: 6, rx: 1.5 }], ['rect', { x: 11, y: 3, width: 6, height: 6, rx: 1.5 }], ['rect', { x: 3, y: 11, width: 6, height: 6, rx: 1.5 }], ['rect', { x: 11, y: 11, width: 6, height: 6, rx: 1.5 }]],
    portfolio: [['circle', { cx: 10, cy: 10, r: 7 }], ['path', { d: 'M10 3v7h7' }]],
    chart: [['path', { d: 'M6.5 3v14M13.5 4v12' }], ['rect', { x: 5, y: 6, width: 3, height: 6, rx: 0.5 }], ['rect', { x: 12, y: 7, width: 3, height: 5, rx: 0.5 }]],
    signals: [['path', { d: 'M2 10h3.5l2-5 5 10 2-5H18' }]],
    alarm: [['path', { d: 'M5 14V9a5 5 0 0 1 10 0v5l1.5 2h-13L5 14z' }], ['path', { d: 'M8.5 18.5h3' }]],
    shield: [['path', { d: 'M10 2.5l6 2.3v4.7c0 3.9-2.6 6.6-6 8-3.4-1.4-6-4.1-6-8V4.8l6-2.3z' }]],
    check: [['path', { d: 'M5 10.5l3 3 7-7' }]],
    x: [['path', { d: 'M6 6l8 8M14 6l-8 8' }]],
    alert: [['path', { d: 'M10 5.5v6M10 14.5v.01' }]],
    info: [['path', { d: 'M10 9v5.5M10 5.5v.01' }]],
    chevron: [['path', { d: 'M6 8l4 4 4-4' }]],
    trash: [['path', { d: 'M4 6h12M8 6V4h4v2M6 6l.7 10h6.6L14 6' }]],
    plus: [['path', { d: 'M10 4v12M4 10h12' }]],
    back: [['path', { d: 'M12 5l-5 5 5 5' }]],
    logout: [['path', { d: 'M8 4H4v12h4M12 6l4 4-4 4M16 10H8' }]]
  };
  function Icon(p) {
    var s = p.size || 20;
    return h('svg', { viewBox: '0 0 20 20', width: s, height: s, fill: 'none', stroke: 'currentColor', strokeWidth: p.stroke || 1.75, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, className: cx('kp-icon', p.className) },
      (ICONS[p.name] || []).map(function (e, i) { return h(e[0], Object.assign({ key: i }, e[1])); }));
  }

  function BrandMark(p) {
    var size = p.size || 'md';
    return h('span', { className: cx('kp-brand', 'kp-brand--' + size) },
      h('span', { className: 'kp-brand__mark', 'aria-hidden': true },
        h('svg', { viewBox: '0 0 24 24' },
          h('rect', { x: 7.25, y: 3, width: 1.5, height: 15, rx: 0.75 }), h('rect', { x: 6, y: 6, width: 4, height: 8, rx: 1 }),
          h('rect', { x: 15.25, y: 7, width: 1.5, height: 14, rx: 0.75 }), h('rect', { x: 14, y: 10, width: 4, height: 8, rx: 1 }))),
      p.wordmark === false ? null : h('span', { className: 'kp-brand__word' }, 'Kapanış'));
  }

  var NAV = [['overview', 'Genel bakış', 'Genel', 'overview'], ['portfolio', 'Portföy', 'Portföy', 'portfolio'], ['chart', 'Grafik', 'Grafik', 'chart'],
    ['signals', 'Sinyaller', 'Sinyal', 'signals'], ['alarms', 'Alarmlar', 'Alarm', 'alarm'], ['discipline', 'Disiplin', 'Disiplin', 'shield']];
  var USER_NAV = [['portfolio', 'Portföyüm', 'Portföy', 'portfolio'], ['analysis', 'Grafik & Analiz', 'Analiz', 'chart'],
    ['macro', 'Makro', 'Makro', 'macro'], ['account', 'Hesap & Telegram', 'Hesap', 'account']];
  function AppShell(p) {
    var act = p.active || 'overview', items = p.items === 'user' ? USER_NAV : p.items || NAV;
    function go(k) { return function (e) { e.preventDefault(); p.onNavigate && p.onNavigate(k); }; }
    function badge(k) { return p.badges && p.badges[k] ? p.badges[k] : k === 'signals' && p.pending ? p.pending : k === 'alarms' && p.alarms ? p.alarms : null; }
    return h('div', { className: 'kp-shellwrap' }, h('div', { className: 'kp-shell' },
      h('aside', { className: 'kp-side' },
        h('div', { className: 'kp-side__brand' }, h(BrandMark, null)),
        h('nav', { className: 'kp-side__nav', 'aria-label': 'Ana menü' }, items.map(function (n) {
          var b = badge(n[0]);
          return h('a', { key: n[0], href: '#' + n[0], className: cx('kp-navlink', act === n[0] && 'is-active'), 'aria-current': act === n[0] ? 'page' : undefined, onClick: go(n[0]) },
            h(Icon, { name: n[3] }), h('span', { className: 'kp-navlink__label' }, n[1]), b ? h('span', { className: 'kp-navcount' }, b) : null);
        })),
        h('div', { className: 'kp-side__foot' }, p.status || null)),
      h('header', { className: 'kp-topbar' }, h(BrandMark, { size: 'sm' }), h('div', { className: 'kp-topbar__end' }, p.topbar || null)),
      h('main', { className: 'kp-main' }, h('div', { className: 'kp-main__inner' }, p.children, h(Disclaimer, null))),
      h('nav', { className: 'kp-bottomnav', 'aria-label': 'Ana menü' }, items.map(function (n) {
        return h('a', { key: n[0], href: '#' + n[0], className: cx('kp-tab', act === n[0] && 'is-active'), 'aria-current': act === n[0] ? 'page' : undefined, onClick: go(n[0]) },
          h('span', { className: 'kp-tab__icon' }, h(Icon, { name: n[3], size: 22 }), badge(n[0]) ? h('span', { className: 'kp-tab__dot' }, badge(n[0])) : null), n[2]);
      }))));
  }

  function LiveStatus(p) {
    return h('div', { className: 'kp-live' }, h('span', { className: cx('kp-live__dot', 'is-' + (p.tone || 'up')), 'aria-hidden': true }),
      h('div', null, h('div', { className: 'kp-live__label' }, p.label || 'Veri güncel'), h('div', { className: 'kp-live__time' }, p.time)));
  }

  function Tabs(p) {
    return h('div', { className: 'kp-tabs', role: 'tablist', 'aria-label': p.ariaLabel }, (p.tabs || []).map(function (t) {
      var on = t.value === p.value;
      return h('button', { key: t.value, type: 'button', role: 'tab', 'aria-selected': on, className: cx('kp-tabs__tab', on && 'is-active'), onClick: function () { p.onChange && p.onChange(t.value); } },
        t.label, t.count != null ? h('span', { className: 'kp-tabs__count' }, t.count) : null);
    }));
  }

  /* ---------- decision + gate ---------- */
  var DEC = { AL: 'up', TUT: 'info', BEKLE: 'warn', PAS: 'flat', 'BİLGİ': 'info' };
  function DecisionBadge(p) {
    var d = DEC[p.decision] ? p.decision : 'PAS';
    return h('span', { className: cx('kp-dec', 'kp-dec--' + DEC[d], p.size === 'lg' && 'kp-dec--lg'), title: 'Sinyal: ' + d },
      p.size === 'lg' && p.prefix !== false ? h('span', { className: 'kp-dec__pre' }, 'Sinyal') : null, d);
  }

  var GATE = { gecti: ['pass', 'check', 'Geçti'], kaldi: ['fail', 'x', 'Kaldı'], uyari: ['warn', 'alert', 'Uyarı'] };
  function GateList(p) {
    var items = p.items || [], n = { gecti: 0, kaldi: 0, uyari: 0 };
    items.forEach(function (i) { n[i.status] = (n[i.status] || 0) + 1; });
    return h('div', { className: 'kp-gate' },
      p.summary === false ? null : h('div', { className: 'kp-gate__sum' },
        h('span', { className: 'kp-gate__big' }, n.gecti + '/' + items.length), h('span', null, 'kural geçti'),
        n.kaldi ? h('span', { className: 'kp-gate__pill is-fail' }, n.kaldi + ' kaldı') : null,
        n.uyari ? h('span', { className: 'kp-gate__pill is-warn' }, n.uyari + ' uyarı') : null),
      h('ul', { className: 'kp-gate__list' }, items.map(function (it, i) {
        var g = GATE[it.status] || GATE.uyari;
        return h('li', { key: i, className: 'kp-gate__item is-' + g[0] },
          h('span', { className: 'kp-gate__icon' }, h(Icon, { name: g[1], size: 16, stroke: 2.25 })),
          h('div', { className: 'kp-gate__body' },
            h('div', { className: 'kp-gate__rule' }, it.rule, it.blocking === false ? h('span', { className: 'kp-gate__tag' }, 'engellemez') : null),
            it.detail ? h('div', { className: 'kp-gate__detail' }, it.detail) : null),
          h('span', { className: 'kp-gate__status' }, g[2]));
      })));
  }

  /* ---------- macro regime −5…+5 ---------- */
  function RegimeGauge(p) {
    var s = Math.max(-5, Math.min(5, Math.round(p.score || 0))), tone = s >= 2 ? 'up' : s <= -2 ? 'down' : 'flat';
    var label = p.label || (s >= 2 ? 'Risk-on' : s <= -2 ? 'Risk-off' : 'Nötr');
    var sub = s >= 2 ? 'Makro rüzgar arkada' : s <= -2 ? 'Makro rüzgar karşıda' : 'Belirgin bir rüzgar yok';
    var cells = [];
    for (var i = -5; i <= 5; i++) cells.push(h('span', { key: i, className: cx('kp-regime__cell', i === 0 && 'is-zero', s > 0 && i > 0 && i <= s && 'is-up', s < 0 && i < 0 && i >= s && 'is-down') }));
    return h('div', { className: 'kp-regime' },
      h('div', { className: 'kp-regime__head' },
        h('span', { className: 'kp-regime__score is-' + tone }, (s > 0 ? '+' : s < 0 ? '−' : '') + Math.abs(s)),
        h('div', null, h('div', { className: 'kp-regime__label' }, label), h('div', { className: 'kp-regime__sub' }, sub))),
      h('div', { className: 'kp-regime__scale', role: 'img', 'aria-label': 'Makro rejim skoru ' + s + ', −5 ile +5 arası' }, cells),
      h('div', { className: 'kp-regime__ends' }, h('span', null, '−5'), h('span', null, '0'), h('span', null, '+5')),
      p.components ? h('ul', { className: 'kp-regime__comps' }, p.components.map(function (c) {
        var t = c.value > 0 ? 'up' : c.value < 0 ? 'down' : 'flat';
        return h('li', { key: c.name }, h('span', { className: 'kp-regime__name' }, c.name), h('span', { className: 'kp-regime__detail' }, c.detail),
          h('span', { className: 'kp-regime__v is-' + t }, c.value > 0 ? '+1' : c.value < 0 ? '−1' : '0'));
      })) : null,
      p.note ? h('p', { className: 'kp-regime__note' }, p.note) : null);
  }

  /* ---------- allocation ring ---------- */
  function Donut(p) {
    var items = p.items || [], tot = items.reduce(function (a, b) { return a + b.value; }, 0) || 1, R = 42, C = 2 * Math.PI * R, off = 0, gap = items.length > 1 ? 1.2 : 0;
    return h('div', { className: 'kp-donut' },
      h('div', { className: 'kp-donut__ring' },
        h('svg', { viewBox: '0 0 100 100', role: 'img', 'aria-label': items.map(function (i) { return i.label + ' %' + fmtNum(i.value / tot * 100, 1); }).join(', ') },
          h('circle', { cx: 50, cy: 50, r: R, fill: 'none', stroke: 'var(--line)', strokeWidth: 11 }),
          items.map(function (it, i) {
            var len = Math.max(0, it.value / tot * C - gap);
            var el = h('circle', { key: i, cx: 50, cy: 50, r: R, fill: 'none', stroke: it.color, strokeWidth: 11, strokeDasharray: len + ' ' + (C - len), strokeDashoffset: -off, transform: 'rotate(-90 50 50)' });
            off += it.value / tot * C; return el;
          })),
        p.center ? h('div', { className: 'kp-donut__center' }, h('span', { className: 'kp-donut__cl' }, p.center.label), h('span', { className: 'kp-donut__cv' }, p.center.value)) : null),
      h('ul', { className: 'kp-donut__legend' }, items.map(function (it, i) {
        return h('li', { key: i }, h('i', { style: { background: it.color } }), h('span', { className: 'kp-donut__lbl' }, it.label),
          h('span', { className: 'kp-donut__pct' }, '%' + fmtNum(it.value / tot * 100, 1)), it.sub ? h('span', { className: 'kp-donut__sub' }, it.sub) : null);
      })));
  }

  function Callout(p) {
    var t = p.tone || 'warn';
    return h('div', { className: 'kp-callout kp-callout--' + t, role: t === 'down' ? 'alert' : 'note' },
      h('span', { className: 'kp-callout__icon' }, h(Icon, { name: t === 'info' ? 'info' : 'alert', size: 18, stroke: 2.25 })),
      h('div', { className: 'kp-callout__body' }, p.title ? h('div', { className: 'kp-callout__title' }, p.title) : null, p.children ? h('div', { className: 'kp-callout__text' }, p.children) : null),
      p.action || null);
  }

  var FRESH = { 'güncel': ['up', 'Güncel'], 'eski': ['warn', 'Eski'], 'bayat': ['down', 'Bayat'], 'yok': ['flat', 'Yok'] };
  function FreshnessList(p) {
    return h('ul', { className: 'kp-fresh' }, (p.items || []).map(function (it, i) {
      var f = FRESH[it.status] || FRESH.yok;
      return h('li', { key: i, className: 'kp-fresh__row' },
        h('span', { className: 'kp-fresh__dot is-' + f[0], 'aria-hidden': true }),
        h('div', { className: 'kp-fresh__main' },
          h('div', { className: 'kp-fresh__src' }, it.source, it.gate ? h('span', { className: 'kp-fresh__gate' }, 'kapıyı etkiler') : null),
          it.note ? h('div', { className: 'kp-fresh__note' }, it.note) : null),
        h('div', { className: 'kp-fresh__right' }, h('span', { className: 'kp-fresh__age' }, it.age || '—'), h('span', { className: 'kp-fresh__st is-' + f[0] }, f[1])));
    }));
  }

  function MiniChart(p) {
    var ref = useRef(null), w = useWidth(ref), c = p.candles || [], H = p.height || 160, n = c.length;
    if (!n) return h('div', { ref: ref, className: 'kp-mini' });
    var lo = Infinity, hi = -Infinity;
    c.forEach(function (k) { lo = Math.min(lo, k.l); hi = Math.max(hi, k.h); });
    var pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    var step = w / n, bw = Math.max(1, step * 0.6);
    function x(i) { return step * i + step / 2; }
    function y(v) { return (hi - v) / (hi - lo) * H; }
    var last = c[n - 1];
    return h('div', { ref: ref, className: 'kp-mini' },
      h('svg', { width: w, height: H, role: 'img', 'aria-label': (p.symbol || '') + ' küçük mum grafiği' },
        [0.25, 0.5, 0.75].map(function (f) { return h('line', { key: f, className: 'kp-ch-grid', x1: 0, x2: w, y1: H * f, y2: H * f }); }),
        c.map(function (k, i) {
          var up = k.c >= k.o, t = y(Math.max(k.o, k.c)), bh = Math.max(1, Math.abs(y(k.o) - y(k.c)));
          return h('g', { key: i, className: up ? 'kp-ch-up' : 'kp-ch-down' }, h('line', { x1: x(i), x2: x(i), y1: y(k.h), y2: y(k.l) }), h('rect', { x: x(i) - bw / 2, y: t, width: bw, height: bh }));
        }),
        h('line', { className: 'kp-ch-lastline ' + (last.c >= last.o ? 'kp-mini__up' : 'kp-mini__down'), x1: 0, x2: w, y1: y(last.c), y2: y(last.c) })));
  }

  /* ---------- discipline ---------- */
  function LimitMeter(p) {
    var pct = p.limit ? Math.min(1, Math.max(0, p.used / p.limit)) : 0, tone = pct >= 0.8 ? 'down' : pct >= 0.5 ? 'warn' : 'ok';
    return h('div', { className: 'kp-limit is-' + tone },
      h('div', { className: 'kp-limit__head' }, h('span', { className: 'kp-limit__label' }, p.label),
        h('span', { className: 'kp-limit__val' }, h('b', null, fmtPrice(p.used, p.cur, 2)), ' / ' + fmtPrice(p.limit, p.cur, 2))),
      h('div', { className: 'kp-limit__track', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': p.limit, 'aria-valuenow': p.used, 'aria-label': p.label },
        h('span', { className: 'kp-limit__fill', style: { width: pct * 100 + '%' } })),
      h('div', { className: 'kp-limit__foot' }, h('span', null, '%' + fmtNum(pct * 100, 0) + ' kullanıldı'), p.note ? h('span', null, p.note) : null));
  }

  function StreakStrip(p) {
    var rs = p.results || [], mx = Math.max.apply(null, rs.map(function (r) { return Math.abs(r.r); }).concat([1]));
    return h('div', { className: 'kp-streak' },
      h('ol', { className: 'kp-streak__list', 'aria-label': 'Son ' + rs.length + ' kapanış, eskiden yeniye' }, rs.map(function (r, i) {
        var up = r.r >= 0, ht = Math.max(6, Math.abs(r.r) / mx * 100) + '%';
        return h('li', { key: i, className: 'kp-streak__item is-' + (up ? 'up' : 'down'), title: (r.symbol || '') + ' ' + (r.date || '') },
          h('span', { className: 'kp-streak__pos' }, up ? h('span', { className: 'kp-streak__bar', style: { height: ht } }) : null),
          h('span', { className: 'kp-streak__neg' }, up ? null : h('span', { className: 'kp-streak__bar', style: { height: ht } })),
          h('span', { className: 'kp-streak__r' }, (up ? '+' : '−') + fmtNum(Math.abs(r.r), 1), h('span', { className: 'kp-streak__u' }, 'R')),
          r.symbol ? h('span', { className: 'kp-streak__sym' }, r.symbol) : null);
      })));
  }

  var FG = [[0, 25, 'Aşırı korku', 'down'], [25, 45, 'Korku', 'down'], [45, 55, 'Nötr', 'flat'], [55, 75, 'Açgözlülük', 'up'], [75, 100, 'Aşırı açgözlülük', 'up']];
  function arcPt(v, r) { var a = Math.PI * (1 - v / 100); return [100 + r * Math.cos(a), 100 - r * Math.sin(a)]; }
  function FearGreedGauge(p) {
    var v = Math.max(0, Math.min(100, Math.round(+p.value || 0))), seg = FG.filter(function (s) { return v >= s[0] && v <= s[1]; })[0] || FG[2], nd = arcPt(v, 60);
    return h('div', { className: 'kp-fg' },
      h('svg', { viewBox: '0 0 200 110', role: 'img', 'aria-label': 'Korku-açgözlülük endeksi ' + v + ', ' + seg[2] },
        FG.map(function (s) {
          var a = arcPt(s[0] + (s[0] ? 1 : 0), 80), b = arcPt(s[1] - (s[1] < 100 ? 1 : 0), 80);
          return h('path', { key: s[0], d: 'M' + a[0].toFixed(2) + ' ' + a[1].toFixed(2) + 'A80 80 0 0 1 ' + b[0].toFixed(2) + ' ' + b[1].toFixed(2), className: cx('kp-fg__seg', s === seg && 'is-' + s[3]) });
        }),
        h('line', { x1: 100, y1: 100, x2: nd[0], y2: nd[1], className: 'kp-fg__needle' }), h('circle', { cx: 100, cy: 100, r: 5, className: 'kp-fg__hub' })),
      h('div', { className: 'kp-fg__read' }, h('span', { className: 'kp-fg__val' }, v), h('span', { className: 'kp-fg__lbl' }, p.label || seg[2])),
      h('div', { className: 'kp-fg__ends' }, h('span', null, '0 · Aşırı korku'), h('span', null, '100 · Aşırı açgözlülük')),
      p.note ? h('p', { className: 'kp-fg__note' }, p.note) : null);
  }

  var SHIELD = { acik: ['up', 'Disiplin kalkanı açık'], uyari: ['warn', 'Kalkan uyarıda'], engel: ['down', 'Yeni giriş kapalı'], kapali: ['flat', 'Kalkan kapalı'] };
  function ShieldStatus(p) {
    var s = SHIELD[p.state] || SHIELD.acik;
    return h('div', { className: 'kp-card kp-shield is-' + s[0] },
      h('span', { className: 'kp-shield__icon' }, h(Icon, { name: 'shield', size: 28 })),
      h('div', { className: 'kp-shield__body' },
        h('div', { className: 'kp-shield__state' }, p.title || s[1]),
        p.detail ? h('p', { className: 'kp-shield__detail' }, p.detail) : null,
        p.until ? h('div', { className: 'kp-shield__until' }, p.until) : null,
        p.children || null));
  }

  function LineChart(p) {
    var ref = useRef(null), w = useWidth(ref), H = p.height || 220, ser = p.series || [];
    var n = Math.max.apply(null, ser.map(function (s) { return s.values.length; }).concat([2]));
    var all = [].concat.apply([0], ser.map(function (s) { return s.values; })), lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), pad = (hi - lo) * 0.1 || 1;
    lo -= pad; hi += pad;
    var axisW = 56, pw = Math.max(40, w - axisW);
    function x(i) { return i / (n - 1) * pw; }
    function y(v) { return (hi - v) / (hi - lo) * (H - 28) + 4; }
    var st = niceStep(hi - lo, 4), ticks = [];
    for (var t = Math.ceil(lo / st) * st; t <= hi; t += st) ticks.push(Math.round(t * 1e6) / 1e6);
    function sp(v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + '%' + fmtNum(Math.abs(v), Math.abs(v) >= 10 || st >= 1 ? 0 : 1); }
    return h('div', { ref: ref, className: 'kp-line' },
      h('div', { className: 'kp-line__legend' }, ser.map(function (s) {
        var last = s.values[s.values.length - 1];
        return h('span', { key: s.label }, h('i', { style: { background: s.color } }), s.label + ' ', h('b', null, (last >= 0 ? '+' : '−') + fmtPct(last)));
      })),
      h('svg', { width: w, height: H, role: 'img', 'aria-label': ser.map(function (s) { return s.label; }).join(' ve ') },
        ticks.map(function (t) {
          return h('g', { key: t }, h('line', { className: t === 0 ? 'kp-line__zero' : 'kp-ch-grid', x1: 0, x2: pw, y1: y(t), y2: y(t) }),
            h('text', { className: 'kp-ch-axis', x: pw + 8, y: y(t), dy: '0.35em' }, sp(t)));
        }),
        ser.map(function (s) { return h('path', { key: s.label, className: 'kp-ch-line', style: { stroke: s.color, strokeDasharray: s.dashed ? '6 5' : null }, d: pathOf(s.values, x, y) }); }),
        (p.labels || []).map(function (l, i) { return l ? h('text', { key: 'l' + i, className: 'kp-ch-axis', x: x(i), y: H - 4, textAnchor: i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle' }, l) : null; })));
  }

  /* ---------- tables and lists ---------- */
  function DataTable(p) {
    var cols = p.columns || [], rows = p.rows || [], click = !!p.onRowClick, key = p.rowKey || 'id';
    function cell(c, r) { return c.render ? c.render(r) : r[c.key]; }
    function act(r) { return click ? { tabIndex: 0, onClick: function () { p.onRowClick(r); }, onKeyDown: function (e) { if (e.key === 'Enter') p.onRowClick(r); } } : {}; }
    var first = cols[0], rest = cols.slice(1).filter(function (c) { return c.mobile !== false; });
    return h('div', { className: 'kp-dt' },
      h('div', { className: 'kp-tablewrap kp-dt__table' }, h('table', { className: 'kp-table' },
        p.caption ? h('caption', { className: 'kp-sr' }, p.caption) : null,
        h('thead', null, h('tr', null, cols.map(function (c) { return h('th', { key: c.key, className: c.num ? 'is-num' : null }, c.label); }))),
        h('tbody', null, rows.map(function (r, i) {
          return h('tr', Object.assign({ key: r[key] != null ? r[key] : i, className: click ? 'kp-row' : null }, act(r)),
            cols.map(function (c) { return h('td', { key: c.key, className: cx(c.num && 'is-num', c.strong && 'kp-price') }, cell(c, r)); }));
        })))),
      h('ul', { className: 'kp-dt__list' }, rows.map(function (r, i) {
        return h('li', Object.assign({ key: r[key] != null ? r[key] : i }, act(r), { className: cx('kp-dt__card', click && 'kp-row') }),
          h('div', { className: 'kp-dt__head' }, cell(first, r), p.mobileEnd ? h('div', { className: 'kp-dt__end' }, p.mobileEnd(r)) : null),
          h('dl', { className: 'kp-dt__kv' }, rest.map(function (c) { return h('div', { key: c.key }, h('dt', null, c.label), h('dd', null, cell(c, r))); })));
      })));
  }

  function MoverList(p) {
    return h('ul', { className: 'kp-movers' }, (p.items || []).map(function (it) {
      return h('li', { key: it.symbol, className: 'kp-movers__row kp-row', tabIndex: 0, onClick: function () { p.onOpen && p.onOpen(it); } },
        h(Ticker, { symbol: it.symbol, name: it.name, logo: it.logo }), h('span', { className: 'kp-movers__price' }, fmtPrice(it.price, it.cur)), h(ChangeBadge, { value: it.change }));
    }));
  }

  function PulseList(p) {
    return h('ul', { className: 'kp-pulse' }, (p.items || []).map(function (it) {
      return h('li', { key: it.label, className: 'kp-pulse__row' },
        h('div', { className: 'kp-pulse__name' }, h('i', { style: { background: it.color || 'var(--text-3)' } }), h('span', null, it.label), it.count != null ? h('span', { className: 'kp-pulse__count' }, it.count + ' varlık') : null),
        h('span', { className: 'kp-pulse__value' }, fmtPrice(it.value, it.cur, 2)),
        h('span', { className: 'kp-pulse__badges' }, h(ChangeBadge, { value: it.day, label: 'Gün' }), h(ChangeBadge, { value: it.total, label: 'Toplam' })));
    }));
  }

  function FeedList(p) {
    return h('ul', { className: 'kp-feed' }, (p.items || []).map(function (it, i) {
      return h('li', { key: i, className: 'kp-feed__item' },
        h('span', { className: 'kp-feed__time' }, it.time),
        h('div', { className: 'kp-feed__body' },
          h('div', { className: 'kp-feed__top' }, h('span', { className: 'kp-feed__kind is-' + (it.tone || 'flat') }, it.kind), it.symbol ? h('b', { className: 'kp-feed__sym' }, it.symbol) : null),
          h('div', { className: 'kp-feed__title' }, it.title),
          it.detail ? h('div', { className: 'kp-feed__detail' }, it.detail) : null));
    }));
  }

  /* ---------- signals ---------- */
  var SSTATE = { bekliyor: 'Karar bekliyor', aldim: 'Aldım', pas: 'Pas geçildi', doldu: 'Süresi doldu', izleniyor: 'İzleniyor', kapi: 'Kapı kaldı', bilgi: 'Kurallar geçti' };
  function SignalList(p) {
    return h('ul', { className: 'kp-slist', role: 'listbox', 'aria-label': 'Sinyaller' }, (p.items || []).map(function (it) {
      var on = it.id === p.value;
      function pick() { p.onSelect && p.onSelect(it.id); }
      return h('li', { key: it.id, role: 'option', 'aria-selected': on, tabIndex: 0, className: cx('kp-slist__item', on && 'is-active'), onClick: pick, onKeyDown: function (e) { if (e.key === 'Enter') pick(); } },
        h('div', { className: 'kp-slist__top' }, h(Ticker, { symbol: it.symbol, name: it.name }), h(DecisionBadge, { decision: it.decision })),
        h('div', { className: 'kp-slist__meta' }, h('span', null, it.time), h('span', null, 'Kapı ' + it.score),
          h('span', { className: 'kp-slist__state is-' + it.state }, SSTATE[it.state] || it.state)));
    }));
  }

  function AiNote(p) {
    var st = useState(p.defaultOpen !== false), open = st[0];
    return h('section', { className: cx('kp-ai', open && 'is-open') },
      h('button', { type: 'button', className: 'kp-ai__head', 'aria-expanded': open, onClick: function () { st[1](!open); } },
        h('span', { className: 'kp-ai__title' }, p.title || 'Yapay zekâ yorumu'),
        p.model ? h('span', { className: 'kp-ai__model' }, p.model) : null,
        p.time ? h('span', { className: 'kp-ai__time' }, p.time) : null,
        h(Icon, { name: 'chevron', className: 'kp-ai__chev' })),
      open ? h('div', { className: 'kp-ai__body' }, p.children,
        h('p', { className: 'kp-ai__foot' }, p.footnote || 'Model yalnız açıklar; kararı kod kapısı verir.')) : null);
  }

  function OutcomeBox(p) {
    return h('div', { className: 'kp-outcome' },
      h('div', { className: 'kp-outcome__title' }, p.title || 'Sonra ne oldu'),
      h('dl', { className: 'kp-outcome__grid' }, (p.rows || []).map(function (r, i) {
        return h('div', { key: i }, h('dt', null, r.label), h('dd', { className: r.tone ? 'is-' + r.tone : null }, r.value));
      })),
      p.note ? h('p', { className: 'kp-outcome__note' }, p.note) : null);
  }

  /* ---------- forms ---------- */
  function Field(p) {
    return h('label', { className: cx('kp-field', p.error && 'is-error', p.className) },
      h('span', { className: 'kp-field__label' }, p.label), p.children,
      p.error ? h('span', { className: 'kp-field__error', role: 'alert' }, p.error) : p.hint ? h('span', { className: 'kp-field__hint' }, p.hint) : null);
  }
  function TextInput(p) {
    var rest = Object.assign({}, p); delete rest.prefix; delete rest.suffix; delete rest.className;
    return h('span', { className: cx('kp-textinput', p.className) },
      p.prefix ? h('span', { className: 'kp-textinput__fix' }, p.prefix) : null, h('input', rest), p.suffix ? h('span', { className: 'kp-textinput__suf' }, p.suffix) : null);
  }
  function Select(p) {
    var rest = Object.assign({}, p); delete rest.options;
    return h('span', { className: 'kp-select' },
      h('select', rest, (p.options || []).map(function (o) { o = typeof o === 'string' ? { value: o, label: o } : o; return h('option', { key: o.value, value: o.value }, o.label); })),
      h(Icon, { name: 'chevron', size: 18, className: 'kp-select__chev' }));
  }
  /* Kapanış paneli düzeltmesi: tr-TR sayı. Virgül ondalıktır, nokta binlik ayırıcıdır:
     "500.000" = 500000, "84.500,50" = 84500.5, "1.234.567" = 1234567. Tek noktadan sonra 3 hane yoksa
     (ör. "0.5", "84500.5") nokta ondalık sayılır. */
  function parseTr(s) {
    if (s == null || s === '') return NaN;
    var t = String(s).trim().replace(/[\s₺$]/g, '');
    if (!/^[-+]?[0-9.,]+$/.test(t)) return NaN;
    if (t.indexOf(',') >= 0) t = t.replace(/\./g, '').replace(',', '.');
    else if ((t.match(/\./g) || []).length > 1) t = t.replace(/\./g, '');
    else if (/^[-+]?[1-9][0-9]{0,2}\.[0-9]{3}$/.test(t)) t = t.replace('.', '');
    return parseFloat(t);
  }

  /* ---------- alarms ---------- */
  var ASTATE = { kurulu: ['info', 'Kurulu'], tetiklendi: ['warn', 'Tetiklendi'], iptal: ['flat', 'İptal edildi'] };
  function AlarmCard(p) {
    var a = p.alarm, cur = a.cur || 'USD', status = a.status || 'kurulu', st = useState(!!p.defaultConfirm), confirm = st[0];
    var s = ASTATE[status] || ASTATE.kurulu, below = a.direction === 'BELOW';
    var dist = a.price ? (a.trigger / a.price - 1) * 100 : null;
    function kv(k, v, cls) { return h('div', { key: k }, h('dt', null, k), h('dd', { className: cls }, v)); }
    return h('article', { className: cx('kp-card kp-alarm', 'is-' + status) },
      h('div', { className: 'kp-alarm__head' }, h(Ticker, { symbol: a.symbol, name: a.name }), h('span', { className: 'kp-alarm__status is-' + s[0] }, s[1])),
      h('div', { className: 'kp-alarm__trigger' },
        h('span', { className: 'kp-alarm__dir' }, below ? 'Altına inerse (düşüş uyarısı)' : 'Üstüne çıkarsa (kırılım)'),
        h('span', { className: 'kp-alarm__price' }, fmtPrice(a.trigger, cur)),
        dist != null && status === 'kurulu' ? h('span', { className: 'kp-alarm__dist' }, 'şu anki fiyata %' + fmtNum(Math.abs(dist), 1) + ' uzaklıkta') : null),
      below ? null : h('dl', { className: 'kp-alarm__levels' },
        kv('İptal seviyesi', a.cancel ? fmtPrice(a.cancel, cur) : '—'), kv('Hedef', a.target ? fmtPrice(a.target, cur) : '—'),
        kv('R/R', a.rr != null ? fmtNum(a.rr, 2) : '—', a.rr != null && a.rr < (a.minRr || 1) ? 'is-down' : null)),
      a.note ? h('p', { className: 'kp-alarm__note' }, a.note) : null,
      status === 'tetiklendi' ? h('div', { className: 'kp-alarm__after' }, h('span', null, 'Tetiklendi ' + a.triggeredAt), a.gate ? h('span', null, 'Kod kapısı ' + a.gate) : null, a.after != null ? h('span', { className: 'kp-alarm__afterv' }, 'Sonra ', h(ChangeBadge, { value: a.after })) : null) : null,
      status === 'iptal' && a.reason ? h('div', { className: 'kp-alarm__after' }, a.reason) : null,
      h('div', { className: 'kp-alarm__foot' },
        h('span', { className: 'kp-alarm__created' }, 'Kuruldu ' + a.created),
        confirm ? h('div', { className: 'kp-confirm', role: 'group', 'aria-label': 'Silme onayı' },
            h('span', { className: 'kp-confirm__q' }, 'Silinsin mi?'),
            h(Button, { variant: 'ghost', onClick: function () { st[1](false); } }, 'Vazgeç'),
            h(Button, { variant: 'danger', onClick: function () { p.onDelete && p.onDelete(a.id); st[1](false); } }, 'Sil'))
          : status === 'kurulu' ? h(Button, { variant: 'ghost', icon: h(Icon, { name: 'trash', size: 18 }), onClick: function () { st[1](true); } }, 'Sil') : null));
  }

  function AlarmForm(p) {
    var coins = p.coins || [], cs = useState(coins[0] ? coins[0].symbol : 'BTC'), coin = coins.filter(function (c) { return c.symbol === cs[0]; })[0] || { symbol: cs[0], price: 0 };
    var dir = useState('ABOVE'), tr = useState(p.defaults ? p.defaults.trigger : ''), ca = useState(p.defaults ? p.defaults.cancel : ''), ta = useState(p.defaults ? p.defaults.target : ''), nt = useState('');
    var T = parseTr(tr[0]), I = parseTr(ca[0]), H = parseTr(ta[0]), minRr = p.riskOff ? 1.5 : 1.0, above = dir[0] === 'ABOVE';
    var errI = above && !isNaN(I) && !isNaN(T) && I >= T ? 'İptal seviyesi tetik fiyatının altında olmalı.' : null;
    var errH = above && !isNaN(H) && !isNaN(T) && H <= T ? 'Hedef tetik fiyatının üstünde olmalı.' : null;
    var rr = above && !errI && !errH && !isNaN(T) && !isNaN(I) && !isNaN(H) ? (H - T) / (T - I) : null;
    var risk = rr != null ? (T - I) / T * 100 : null, gain = rr != null ? (H - T) / T * 100 : null;
    var ok = !isNaN(T) && (above ? rr != null && rr >= minRr : true);
    var dist = coin.price && !isNaN(T) ? (T / coin.price - 1) * 100 : null;
    function submit(e) { e.preventDefault(); if (ok && p.onSubmit) p.onSubmit({ symbol: coin.symbol, direction: dir[0], trigger: T, cancel: above ? I : null, target: above ? H : null, rr: rr, note: nt[0] }); }
    return h('form', { className: 'kp-alarmform', onSubmit: submit, noValidate: true },
      h('div', { className: 'kp-alarmform__row' },
        h(Field, { label: 'Coin', hint: coin.price ? 'Şu an ' + fmtPrice(coin.price, 'USD') : null },
          h(Select, { value: cs[0], onChange: function (e) { cs[1](e.target.value); }, options: coins.map(function (c) { return { value: c.symbol, label: c.symbol + ' · ' + c.name }; }) })),
        h('div', { className: 'kp-field' }, h('span', { className: 'kp-field__label' }, 'Yön'),
          h(Segmented, { ariaLabel: 'Alarm yönü', value: dir[0], onChange: dir[1], options: [{ value: 'ABOVE', label: 'Üstüne çıkarsa' }, { value: 'BELOW', label: 'Altına inerse' }] }))),
      h('div', { className: 'kp-alarmform__levels' },
        h(Field, { label: 'Tetik fiyatı', hint: dist != null ? 'Fiyata %' + fmtNum(Math.abs(dist), 1) + (dist >= 0 ? ' yukarıda' : ' aşağıda') : '15 dk mum bu seviyenin ' + (above ? 'üstünde' : 'altında') + ' kapanırsa' },
          h(TextInput, { prefix: '$', inputMode: 'decimal', value: tr[0], placeholder: '0,00', onChange: function (e) { tr[1](e.target.value); } })),
        above ? h(Field, { label: 'İptal seviyesi', error: errI, hint: 'Senaryo bu seviyenin altında bozulur' },
          h(TextInput, { prefix: '$', inputMode: 'decimal', value: ca[0], placeholder: '0,00', onChange: function (e) { ca[1](e.target.value); } })) : null,
        above ? h(Field, { label: 'Hedef', error: errH },
          h(TextInput, { prefix: '$', inputMode: 'decimal', value: ta[0], placeholder: '0,00', onChange: function (e) { ta[1](e.target.value); } })) : null),
      above ? h('div', { className: cx('kp-rr', rr == null ? 'is-empty' : rr >= minRr ? 'is-ok' : 'is-low'), 'aria-live': 'polite' },
        h('div', { className: 'kp-rr__main' }, h('span', { className: 'kp-rr__label' }, 'R/R'), h('span', { className: 'kp-rr__val' }, rr == null ? '—' : fmtNum(rr, 2))),
        h('div', { className: 'kp-rr__side' },
          h('span', null, 'Risk ', h('b', null, risk == null ? '—' : '%' + fmtNum(risk, 2))),
          h('span', null, 'Kazanç ', h('b', null, gain == null ? '—' : '%' + fmtNum(gain, 2))),
          h('span', { className: 'kp-rr__rule' }, rr == null ? 'Kapı eşiği ' + fmtNum(minRr, 1) : rr >= minRr ? 'Kapı eşiğini geçiyor (' + fmtNum(minRr, 1) + ')' : 'Kapı eşiğinin altında (' + fmtNum(minRr, 1) + ')'))) :
        h(Callout, { tone: 'info' }, 'Altına inerse alarmı yalnız düşüş uyarısıdır; R/R ve kod kapısı çalışmaz.'),
      h(Field, { label: 'Not (isteğe bağlı)' }, h(TextInput, { value: nt[0], placeholder: 'Ör. 4h direnç kırılımı', onChange: function (e) { nt[1](e.target.value); } })),
      h('div', { className: 'kp-alarmform__foot' },
        h('span', { className: 'kp-alarmform__note' }, 'Alarm yalnız bildirim gönderir. Bot işlem yapmaz.'),
        h(Button, { variant: 'primary', type: 'submit', disabled: !ok }, 'Alarmı kur')));
  }

  /* ---------- portfolio ---------- */
  function MarketCard(p) {
    return h('div', { className: 'kp-card kp-market' },
      h('div', { className: 'kp-market__head' }, h('span', { className: 'kp-market__name' }, h('i', { style: { background: p.color || 'var(--text-3)' } }), p.label), h('span', { className: 'kp-market__cur' }, (p.cur === 'TRY' ? '₺ · TL' : '$ · USD') + (p.count != null ? ' · ' + p.count + ' varlık' : ''))),
      h('div', { className: 'kp-market__value' }, fmtPrice(p.value, p.cur, 2)),
      h('div', { className: 'kp-market__badges' }, h(ChangeBadge, { value: p.day, label: 'Gün' }), h(ChangeBadge, { value: p.total, label: 'Toplam' })),
      h('dl', { className: 'kp-market__kv' },
        h('div', null, h('dt', null, 'K/Z'), h('dd', { className: p.pl >= 0 ? 'is-up' : 'is-down' }, fmtSignedMoney(p.pl, p.cur))),
        h('div', null, h('dt', null, 'Yatırılan'), h('dd', null, fmtPrice(p.cost, p.cur, 2)))));
  }

  function CompareCard(p) {
    var diff = p.mine - p.value, ahead = diff >= 0;
    function sp(v) { return (v >= 0 ? '+' : '−') + fmtPct(v); }
    return h('div', { className: 'kp-card kp-compare' },
      h('div', { className: 'kp-compare__label' }, p.label),
      h('div', { className: 'kp-compare__val' }, sp(p.value)),
      h('div', { className: 'kp-compare__vs' }, h('span', { className: 'kp-compare__diff is-' + (ahead ? 'up' : 'down') }, (ahead ? '▲ ' : '▼ ') + fmtNum(Math.abs(diff), 1) + ' puan'), ahead ? ' öndesin' : ' gerindesin'),
      p.note ? h('div', { className: 'kp-compare__note' }, p.note) : null);
  }


  /* ================= public site + new-user panel ================= */
  Object.assign(ICONS, {
    account: [['circle', { cx: 10, cy: 7, r: 3.25 }], ['path', { d: 'M3.5 17c.9-3.3 3.4-5 6.5-5s5.6 1.7 6.5 5' }]],
    macro: [['circle', { cx: 10, cy: 10, r: 7 }], ['path', { d: 'M3 10h14M10 3c2 2 3 4.4 3 7s-1 5-3 7c-2-2-3-4.4-3-7s1-5 3-7z' }]],
    send: [['path', { d: 'M17 3L3 9l5.5 2.5L11 17l6-14z' }], ['path', { d: 'M8.5 11.5L12 8' }]],
    key: [['circle', { cx: 7, cy: 13, r: 3.5 }], ['path', { d: 'M9.5 10.5L16 4M13.5 6.5l2 2' }]],
    download: [['path', { d: 'M10 3v10M6 9l4 4 4-4M4 17h12' }]],
    copy: [['rect', { x: 7, y: 7, width: 10, height: 10, rx: 2 }], ['path', { d: 'M13 4H5a1 1 0 0 0-1 1v8' }]],
    menu: [['path', { d: 'M3 6h14M3 10h14M3 14h14' }]],
    mail: [['rect', { x: 2.5, y: 4.5, width: 15, height: 11, rx: 2 }], ['path', { d: 'M3 5.5l7 5.5 7-5.5' }]],
    lock: [['rect', { x: 4, y: 9, width: 12, height: 8.5, rx: 2 }], ['path', { d: 'M7 9V6.5a3 3 0 0 1 6 0V9' }]],
    arrow: [['path', { d: 'M4 10h12M11 5l5 5-5 5' }]],
    refresh: [['path', { d: 'M16 10a6 6 0 1 1-1.8-4.3M16 3.5v3.5h-3.5' }]],
    stopup: [['path', { d: 'M3 16h4v-4h4V8h4V4' }], ['path', { d: 'M12.5 4H15v2.5' }]],
    code: [['path', { d: 'M7 6l-4 4 4 4M13 6l4 4-4 4' }]]
  });

  /* ---------- public site ---------- */
  var SITE_NAV = [['ozellikler', 'Özellikler'], ['nasil-calisir', 'Nasıl çalışır'], ['kurallar', 'Kurallar'], ['sss', 'SSS']];
  function SiteHeader(p) {
    var st = useState(false), open = st[0];
    function go(k) { return function (e) { if (p.onNavigate) { e.preventDefault(); p.onNavigate(k); } st[1](false); }; }
    function links() {
      return SITE_NAV.map(function (n) {
        return h('a', { key: n[0], href: '/' + n[0], className: cx('kp-sitenav__link', p.active === n[0] && 'is-active'), 'aria-current': p.active === n[0] ? 'page' : undefined, onClick: go(n[0]) }, n[1]);
      });
    }
    return h('header', { className: 'kp-sitehead' },
      h('div', { className: 'kp-sitehead__inner' },
        h('a', { href: '/', className: 'kp-sitehead__brand', 'aria-label': 'Kapanış ana sayfa', onClick: go('') }, h(BrandMark, null)),
        h('nav', { className: 'kp-sitenav', 'aria-label': 'Site menüsü' }, links()),
        h('div', { className: 'kp-sitehead__actions' },
          h(Button, { variant: 'ghost', href: '/giris', onClick: go('giris') }, 'Giriş yap'),
          h(Button, { variant: 'primary', href: '/kayit', onClick: go('kayit') }, 'Ücretsiz hesap aç')),
        h('button', { type: 'button', className: 'kp-sitehead__menu', 'aria-expanded': open, 'aria-controls': 'kp-sitemenu', 'aria-label': open ? 'Menüyü kapat' : 'Menüyü aç', onClick: function () { st[1](!open); } },
          h(Icon, { name: open ? 'x' : 'menu', size: 22 }))),
      open ? h('div', { id: 'kp-sitemenu', className: 'kp-sitemenu' }, links(),
        h('div', { className: 'kp-sitemenu__actions' },
          h(Button, { variant: 'secondary', href: '/giris', onClick: go('giris') }, 'Giriş yap'),
          h(Button, { variant: 'primary', href: '/kayit', onClick: go('kayit') }, 'Ücretsiz hesap aç'))) : null);
  }

  function SiteFooter() {
    function col(t, items) {
      return h('div', { className: 'kp-sitefoot__col' }, h('div', { className: 'kp-sitefoot__h' }, t),
        items.map(function (i) { return h('a', { key: i[1], href: i[1], className: 'kp-sitefoot__link' }, i[0]); }));
    }
    return h('footer', { className: 'kp-sitefoot' }, h('div', { className: 'kp-sitefoot__inner' },
      h('div', { className: 'kp-sitefoot__brand' }, h(BrandMark, { size: 'sm' }), h('p', null, 'Dokunma değil, kapanış.')),
      h('nav', { className: 'kp-sitefoot__cols', 'aria-label': 'Alt menü' },
        col('Ürün', [['Özellikler', '/ozellikler'], ['Nasıl çalışır', '/nasil-calisir'], ['Kurallar', '/kurallar'], ['SSS', '/sss']]),
        col('Hesap', [['Giriş yap', '/giris'], ['Ücretsiz hesap aç', '/kayit']]),
        col('Yasal', [['Gizlilik ve KVKK', '/kvkk'], ['Kullanım koşulları', '/kosullar']])),
      h('p', { className: 'kp-sitefoot__legal' }, 'Yatırım tavsiyesi değildir. Bot işlem yapmaz. Kapanış aracı kurum şifresi istemez; fiyatlar gecikmeli olabilir.')));
  }

  function StepList(p) {
    return h('ol', { className: cx('kp-steps', p.layout === 'column' && 'kp-steps--col') }, (p.steps || []).map(function (s, i) {
      return h('li', { key: i, className: 'kp-steps__item' },
        h('span', { className: 'kp-steps__num', 'aria-hidden': true }, i + 1),
        h('div', { className: 'kp-steps__body' },
          h('div', { className: 'kp-steps__title' }, s.title),
          s.detail ? h('div', { className: 'kp-steps__detail' }, s.detail) : null,
          s.extra ? h('div', { className: 'kp-steps__extra' }, s.extra) : null));
    }));
  }

  function FeatureCard(p) {
    return h('div', { className: cx('kp-card kp-feature', p.className) },
      p.icon ? h('span', { className: 'kp-feature__icon' }, h(Icon, { name: p.icon, size: 22 })) : null,
      p.kicker ? h('div', { className: 'kp-feature__kicker' }, p.dot ? h('i', { style: { background: p.dot } }) : null, p.kicker) : null,
      h('h3', { className: 'kp-feature__title' }, p.title),
      p.children ? h('div', { className: 'kp-feature__text' }, p.children) : null,
      p.items ? h('ul', { className: 'kp-feature__list' }, p.items.map(function (t, i) { return h('li', { key: i }, h(Icon, { name: 'check', size: 16, stroke: 2.25 }), h('span', null, t)); })) : null,
      p.footer || null);
  }

  function RuleStrip(p) {
    return h('ul', { className: 'kp-rules' }, (p.items || []).map(function (r, i) {
      return h('li', { key: i, className: 'kp-rules__item' },
        h('span', { className: 'kp-rules__icon' }, h(Icon, { name: r.icon || 'check', size: 20, stroke: 2 })),
        h('div', null, h('div', { className: 'kp-rules__title' }, r.title), r.detail ? h('div', { className: 'kp-rules__detail' }, r.detail) : null));
    }));
  }

  function FaqList(p) {
    var st = useState(p.defaultOpen != null ? p.defaultOpen : -1), pre = p.id || 'faq';
    return h('div', { className: 'kp-faq' }, (p.items || []).map(function (it, i) {
      var open = st[0] === i, id = 'kp-' + pre + '-' + i;
      return h('div', { key: i, className: cx('kp-faq__item', open && 'is-open') },
        h('h3', { className: 'kp-faq__q' },
          h('button', { type: 'button', 'aria-expanded': open, 'aria-controls': id, onClick: function () { st[1](open ? -1 : i); } },
            h('span', null, it.q), h(Icon, { name: 'chevron', size: 20, className: 'kp-faq__chev' }))),
        open ? h('div', { id: id, className: 'kp-faq__a', role: 'region' }, it.a) : null);
    }));
  }

  function CloseRuleDiagram(p) {
    return h('figure', { className: 'kp-closerule' },
      h('svg', { viewBox: '0 0 320 168', role: 'img', 'aria-label': 'Solda fitili direnci geçen ama altında kapanan mum: sayılmaz. Sağda direncin üstünde kapanan mum: sayılır.' },
        h('line', { x1: 8, x2: 312, y1: 62, y2: 62, className: 'kp-closerule__level' }),
        h('text', { x: 10, y: 54, className: 'kp-ch-axis' }, p.levelLabel || 'Direnç'),
        h('line', { x1: 95, x2: 95, y1: 26, y2: 150, className: 'kp-closerule__wick' }),
        h('rect', { x: 80, y: 84, width: 30, height: 46, rx: 2, className: 'kp-closerule__body' }),
        h('circle', { cx: 95, cy: 30, r: 10, className: 'kp-closerule__ring is-no' }),
        h('line', { x1: 225, x2: 225, y1: 24, y2: 138, className: 'kp-closerule__wick' }),
        h('rect', { x: 210, y: 42, width: 30, height: 78, rx: 2, className: 'kp-closerule__body' }),
        h('circle', { cx: 225, cy: 42, r: 10, className: 'kp-closerule__ring is-yes' })),
      h('figcaption', { className: 'kp-closerule__cap' },
        h('div', null, h('span', { className: 'kp-closerule__tag is-no' }, h(Icon, { name: 'x', size: 14, stroke: 2.5 }), 'Sayılmaz'),
          h('p', null, 'Fitil direnci geçti, mum altında kapandı.')),
        h('div', null, h('span', { className: 'kp-closerule__tag is-yes' }, h(Icon, { name: 'check', size: 14, stroke: 2.5 }), 'Sayılır'),
          h('p', null, 'Mum direncin üstünde kapandı.'))));
  }

  function MessagePreview(p) {
    return h('div', { className: 'kp-msg', role: 'group', 'aria-label': 'Örnek bildirim' },
      h('div', { className: 'kp-msg__head' }, h(BrandMark, { size: 'sm', wordmark: false }), h('div', null, h('div', { className: 'kp-msg__from' }, p.from || 'Kapanış botu'), h('div', { className: 'kp-msg__time' }, p.time))),
      h('div', { className: 'kp-msg__body' }, p.children));
  }

  /* ---------- sign-in frame (the Clerk component mounts in the slot) ---------- */
  function AuthFrame(p) {
    return h('div', { className: 'kp-auth' }, h('div', { className: 'kp-auth__box' },
      h('a', { href: '/', className: 'kp-auth__brand', 'aria-label': 'Kapanış ana sayfa' }, h(BrandMark, { size: 'lg' })),
      h('p', { className: 'kp-auth__tag' }, p.tagline || 'Dokunma değil, kapanış.'),
      h('div', { className: 'kp-auth__slot' }, p.children),
      h('p', { className: 'kp-auth__foot' }, 'Bot işlem yapmaz', h('span', { 'aria-hidden': true }, ' · '), h('a', { href: '/kvkk', className: 'kp-link' }, 'Gizlilik ve KVKK'))));
  }
  function AuthBox(p) {
    var mode = p.mode || 'giris', step = useState(p.step || 'start'), em = useState(p.email || ''), code = useState('');
    var signup = mode === 'kayit';
    if (step[0] === 'code') {
      return h('div', { className: 'kp-card kp-authbox' },
        h('h1', { className: 'kp-authbox__title' }, 'E-postanı kontrol et'),
        h('p', { className: 'kp-authbox__sub' }, h('b', null, em[0] || 'ornek@eposta.com'), ' adresine 6 haneli doğrulama kodu gönderdik.'),
        h('form', { className: 'kp-authbox__form', onSubmit: function (e) { e.preventDefault(); } },
          h(Field, { label: 'Doğrulama kodu' }, h('input', { className: 'kp-otp', inputMode: 'numeric', autoComplete: 'one-time-code', maxLength: 6, placeholder: '000000', value: code[0], onChange: function (e) { code[1](e.target.value.replace(/\D/g, '').slice(0, 6)); } })),
          h(Button, { variant: 'primary', type: 'submit', disabled: code[0].length < 6, className: 'kp-authbox__submit' }, 'Doğrula')),
        h('div', { className: 'kp-authbox__row' },
          h('button', { type: 'button', className: 'kp-linkbtn', onClick: function () { step[1]('start'); } }, 'E-postayı değiştir'),
          h('span', { className: 'kp-authbox__muted' }, 'Yeni kod 0:45 sonra')),
        h('p', { className: 'kp-authbox__note' }, 'Kod 10 dakika geçerli. Gelmediyse gereksiz klasörüne bak.'));
    }
    return h('div', { className: 'kp-card kp-authbox' },
      h('h1', { className: 'kp-authbox__title' }, signup ? 'Ücretsiz hesap aç' : 'Giriş yap'),
      h('p', { className: 'kp-authbox__sub' }, signup ? 'Google ya da e-postanla. Şifre gerekmez.' : 'Hoş geldin. Kaldığın yerden devam et.'),
      h(Button, { variant: 'secondary', className: 'kp-authbox__google' }, 'Google ile devam et'),
      h('div', { className: 'kp-authbox__or' }, h('span', null, 'ya da e-postayla')),
      h('form', { className: 'kp-authbox__form', onSubmit: function (e) { e.preventDefault(); step[1]('code'); } },
        h(Field, { label: 'E-posta' }, h(TextInput, { type: 'email', autoComplete: 'email', placeholder: 'ornek@eposta.com', value: em[0], onChange: function (e) { em[1](e.target.value); } })),
        h(Button, { variant: 'primary', type: 'submit', className: 'kp-authbox__submit' }, 'Doğrulama kodu gönder')),
      signup ? h('p', { className: 'kp-authbox__legal' }, 'Devam ederek ', h('a', { href: '/kosullar', className: 'kp-link' }, 'Kullanım koşullarını'), ' ve ', h('a', { href: '/kvkk', className: 'kp-link' }, 'KVKK aydınlatma metnini'), ' okuduğunu kabul edersin.') : null,
      h('div', { className: 'kp-authbox__switch' }, signup ? 'Hesabın var mı? ' : 'Hesabın yok mu? ',
        h('a', { href: signup ? '/giris' : '/kayit', className: 'kp-link' }, signup ? 'Giriş yap' : 'Ücretsiz hesap aç')),
      h('p', { className: 'kp-authbox__note' }, h(Icon, { name: 'lock', size: 16 }), 'Giriş Clerk ile yapılır. Şifren ve kodun Kapanış’ta tutulmaz.'));
  }

  /* ---------- new-user panel ---------- */
  function SetupChecklist(p) {
    var steps = p.steps || [], done = steps.filter(function (s) { return s.done; }).length;
    return h('section', { className: 'kp-card kp-setup' },
      h('div', { className: 'kp-setup__head' },
        h('div', null, h('h2', { className: 'kp-card__title' }, p.title || 'İlk kurulum'), h('p', { className: 'kp-setup__sub' }, done + '/' + steps.length + ' adım tamamlandı')),
        h('div', { className: 'kp-setup__bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': steps.length, 'aria-valuenow': done, 'aria-label': 'Kurulum ilerlemesi' },
          steps.map(function (s, i) { return h('span', { key: i, className: cx('kp-setup__seg', s.done && 'is-done') }); }))),
      h('ol', { className: 'kp-setup__list' }, steps.map(function (s, i) {
        return h('li', { key: i, className: cx('kp-setup__item', s.done && 'is-done') },
          h('span', { className: 'kp-setup__mark', 'aria-hidden': true }, s.done ? h(Icon, { name: 'check', size: 16, stroke: 2.5 }) : i + 1),
          h('div', { className: 'kp-setup__body' },
            h('div', { className: 'kp-setup__title' }, s.title, s.optional ? h('span', { className: 'kp-gate__tag' }, 'isteğe bağlı') : null),
            s.detail ? h('div', { className: 'kp-setup__detail' }, s.detail) : null),
          h('div', { className: 'kp-setup__action' }, s.done ? h('span', { className: 'kp-setup__done' }, h(Icon, { name: 'check', size: 16, stroke: 2.5 }), 'Tamamlandı') : s.action || null));
      })));
  }

  function EmptyState(p) {
    var t = p.tone || 'flat';
    return h('div', { className: cx('kp-empty', 'is-' + t, p.bordered === false ? null : 'is-bordered'), role: t === 'down' ? 'alert' : undefined },
      p.icon ? h('span', { className: 'kp-empty__icon' }, h(Icon, { name: p.icon, size: 24 })) : null,
      h('div', { className: 'kp-empty__title' }, p.title),
      p.children ? h('div', { className: 'kp-empty__text' }, p.children) : null,
      p.action ? h('div', { className: 'kp-empty__action' }, p.action) : null);
  }

  function Skeleton(p) {
    var rows = p.rows == null ? 3 : p.rows, widths = [92, 74, 84, 58, 68];
    return h('div', { className: 'kp-skel', 'aria-busy': true },
      p.chart ? h('div', { className: 'kp-skel__block', style: { height: p.chart } }) : null,
      p.tiles ? h('div', { className: 'kp-skel__tiles' }, Array.apply(null, Array(p.tiles)).map(function (_, i) { return h('div', { key: i, className: 'kp-skel__tile' }); })) : null,
      Array.apply(null, Array(rows)).map(function (_, i) { return h('div', { key: i, className: 'kp-skel__line', style: { width: widths[i % 5] + '%' } }); }),
      h('div', { className: 'kp-skel__label', role: 'status' }, p.label || 'Yükleniyor…'));
  }

  function QuotaMeter(p) {
    var limit = p.limit || 5, used = Math.min(limit, p.used || 0), left = limit - used, empty = left === 0;
    return h('div', { className: cx('kp-quota', empty && 'is-empty') },
      limit <= 12 ? h('div', { className: 'kp-quota__cells', 'aria-hidden': true }, Array.apply(null, Array(limit)).map(function (_, i) { return h('span', { key: i, className: cx('kp-quota__cell', i < left && 'is-left') }); }))
        : h('div', { className: 'kp-limit__track', 'aria-hidden': true }, h('span', { className: 'kp-limit__fill', style: { width: left / limit * 100 + '%' } })),
      h('div', { className: 'kp-quota__text' },
        empty ? h('b', null, 'Bugünkü analiz hakkın doldu') : ['Bugün ', h('b', { key: 'b' }, left + '/' + limit), ' analiz hakkın kaldı'],
        p.ownLimit ? h('span', { className: 'kp-quota__own' }, p.ownKey ? ' · kendi anahtarınla' : ' · kendi anahtarınla ' + p.ownLimit) : null),
      p.reset ? h('div', { className: 'kp-quota__reset' }, p.reset) : null);
  }

  var BUY_MKTS = [{ value: 'kripto', label: 'Kripto', cur: 'USD', ph: 'BTC' }, { value: 'bist', label: 'BIST', cur: 'TRY', ph: 'THYAO' }, { value: 'abd', label: 'ABD', cur: 'USD', ph: 'AAPL' }];
  function BuyForm(p) {
    var d = p.defaults || {}, mk = useState(d.market || 'bist'), code = useState(d.code || ''), qty = useState(d.qty || ''), pr = useState(d.price || ''),
      sl = useState(d.stop || ''), tg = useState(d.target || ''), saved = useState(null);
    var m = BUY_MKTS.filter(function (x) { return x.value === mk[0]; })[0], cur = m.cur, sym = SYM[cur];
    var Q = parseTr(qty[0]), P = parseTr(pr[0]), S = parseTr(sl[0]), T = parseTr(tg[0]);
    var errC = code[0] && !/^[A-Z0-9.]{1,12}$/.test(code[0]) ? 'Kod yalnız harf ve rakam içerir.' : null;
    var errQ = !isNaN(Q) && Q <= 0 ? 'Adet sıfırdan büyük olmalı.' : mk[0] !== 'kripto' && !isNaN(Q) && Q % 1 ? 'Hissede adet tam sayı olmalı.' : null;
    var errS = !isNaN(S) && !isNaN(P) && S >= P ? 'Stop alış fiyatının altında olmalı.' : null;
    var errT = !isNaN(T) && !isNaN(P) && T <= P ? 'Hedef alış fiyatının üstünde olmalı.' : null;
    var total = Q > 0 && P > 0 ? Q * P : null, risk = total && S > 0 && !errS ? (P - S) * Q : null, rr = risk && T > 0 && !errT ? (T - P) / (P - S) : null;
    var ok = code[0] && !errC && Q > 0 && !errQ && P > 0 && S > 0 && !errS && !errT;
    function submit(e) {
      e.preventDefault(); if (!ok) return;
      var rec = { market: mk[0], code: code[0], qty: Q, price: P, stop: S, target: isNaN(T) ? null : T };
      if (p.onSubmit) p.onSubmit(rec);
      saved[1](code[0] + ' · ' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 8 }).format(Q) + ' adet kaydedildi.');
    }
    function money(v) { return v == null ? '—' : fmtPrice(v, cur, 2); }
    return h('form', { className: 'kp-buyform', onSubmit: submit, noValidate: true },
      h('div', { className: 'kp-field' }, h('span', { className: 'kp-field__label' }, 'Piyasa'),
        h(Segmented, { ariaLabel: 'Piyasa', value: mk[0], onChange: function (v) { mk[1](v); saved[1](null); }, options: BUY_MKTS })),
      h('div', { className: 'kp-buyform__grid' },
        h(Field, { label: 'Kod', error: errC, hint: mk[0] === 'kripto' ? 'Yalnız spot · USDT paritesi' : null },
          h(TextInput, { value: code[0], placeholder: m.ph, autoCapitalize: 'characters', onChange: function (e) { code[1](e.target.value.toUpperCase().replace(/\s/g, '')); saved[1](null); } })),
        h(Field, { label: 'Adet', error: errQ }, h(TextInput, { inputMode: 'decimal', value: qty[0], placeholder: mk[0] === 'kripto' ? '0,05' : '100', onChange: function (e) { qty[1](e.target.value); } })),
        h(Field, { label: 'Alış fiyatı' }, h(TextInput, { prefix: sym, inputMode: 'decimal', value: pr[0], placeholder: '0,00', onChange: function (e) { pr[1](e.target.value); } })),
        h(Field, { label: 'Stop', error: errS, hint: errS ? null : 'Zorunlu · sonra yalnız yukarı taşınır' }, h(TextInput, { prefix: sym, inputMode: 'decimal', value: sl[0], placeholder: '0,00', onChange: function (e) { sl[1](e.target.value); } })),
        h(Field, { label: 'Hedef', error: errT, hint: errT ? null : 'İsteğe bağlı' }, h(TextInput, { prefix: sym, inputMode: 'decimal', value: tg[0], placeholder: '0,00', onChange: function (e) { tg[1](e.target.value); } }))),
      h('dl', { className: 'kp-buyform__sum' },
        h('div', null, h('dt', null, 'Tutar'), h('dd', null, money(total))),
        h('div', null, h('dt', null, 'Stopa kadar risk'), h('dd', { className: risk ? 'is-down' : null }, risk ? '−' + fmtPrice(risk, cur, 2) : '—')),
        h('div', null, h('dt', null, 'R/R'), h('dd', null, rr == null ? '—' : fmtNum(rr, 2)))),
      saved[0] ? h('p', { className: 'kp-buyform__ok', role: 'status' }, h(Icon, { name: 'check', size: 16, stroke: 2.5 }), saved[0]) : null,
      h('div', { className: 'kp-buyform__foot' },
        h('span', { className: 'kp-buyform__note' }, 'Yalnız kayıttır. Kapanış işlem yapmaz; alımı aracı kurumunda sen yaparsın.'),
        h(Button, { variant: 'primary', type: 'submit', disabled: !ok }, 'Alımı kaydet')));
  }

  function TelegramLink(p) {
    var st = useState(p.state || 'bagli-degil'), copied = useState(false), code = p.code || 'KP-7Q4M2XHD', bot = p.bot || 'Kapanış botu';
    if (st[0] === 'bagli') {
      return h('div', { className: 'kp-tg' },
        h('div', { className: 'kp-tg__status' }, h('span', { className: 'kp-live__dot is-up', 'aria-hidden': true }),
          h('div', null, h('div', { className: 'kp-tg__title' }, 'Telegram bağlı'), h('div', { className: 'kp-tg__sub' }, (p.username || '@kullanici') + ' · ' + (p.since || '26 Eyl 2026') + ' tarihinden beri'))),
        h('p', { className: 'kp-tg__text' }, 'Analiz sonuçların ve kendi alımlarının stop / hedef uyarıları bu sohbete gelir.'),
        h('div', null, h(Button, { variant: 'ghost', onClick: function () { st[1]('bagli-degil'); } }, 'Bağlantıyı kaldır')));
    }
    if (st[0] === 'kod') {
      return h('div', { className: 'kp-tg' },
        h('ol', { className: 'kp-tg__steps' },
          h('li', null, 'Telegram’da ', h('b', null, bot), ' sohbetini aç.'),
          h('li', null, 'Aşağıdaki komutu olduğu gibi gönder.')),
        h('div', { className: 'kp-tg__code' },
          h('span', { className: 'kp-tg__cmd' }, '/bagla ' + code),
          h(Button, { variant: 'secondary', icon: h(Icon, { name: copied[0] ? 'check' : 'copy', size: 18 }), onClick: function () { try { navigator.clipboard.writeText('/bagla ' + code); } catch (e) { /* clipboard unavailable */ } copied[1](true); } }, copied[0] ? 'Kopyalandı' : 'Kopyala')),
        h('div', { className: 'kp-tg__meta' }, 'Tek kullanımlık kod · ', h('b', null, (p.expires || '9:42') + ' kaldı'), ' (10 dk geçerli)',
          h('button', { type: 'button', className: 'kp-linkbtn', onClick: function () { copied[1](false); } }, 'Yeni kod al')));
    }
    return h('div', { className: 'kp-tg' },
      h('div', { className: 'kp-tg__status' }, h('span', { className: 'kp-live__dot', 'aria-hidden': true }),
        h('div', null, h('div', { className: 'kp-tg__title' }, 'Telegram bağlı değil'), h('div', { className: 'kp-tg__sub' }, 'Bağlarsan analiz sonucu ve stop / hedef uyarıları telefonuna da gelir.'))),
      h('div', null, h(Button, { variant: 'secondary', icon: h(Icon, { name: 'send', size: 18 }), onClick: function () { st[1]('kod'); } }, 'Telegram’ı bağla')));
  }

  function ApiKeyRow(p) {
    var k = p.item, st = useState(k.last4 ? 'saved' : 'empty'), v = useState(''), conf = useState(false), last = useState(k.last4);
    return h('li', { className: 'kp-keys__row' },
      h('div', { className: 'kp-keys__head' },
        h('div', null, h('div', { className: 'kp-keys__name' }, k.provider), k.note ? h('div', { className: 'kp-keys__note' }, k.note) : null),
        h('span', { className: cx('kp-keys__state', st[0] === 'saved' && 'is-on') }, st[0] === 'saved' ? 'Kayıtlı' : 'Eklenmedi')),
      st[0] === 'saved'
        ? h('div', { className: 'kp-keys__saved' }, h('span', { className: 'kp-keys__mask', 'aria-label': 'Son dört hane ' + last[0] }, '••••' + last[0]),
            conf[0] ? h('div', { className: 'kp-confirm', role: 'group', 'aria-label': 'Silme onayı' }, h('span', { className: 'kp-confirm__q' }, 'Silinsin mi?'),
                h(Button, { variant: 'ghost', onClick: function () { conf[1](false); } }, 'Vazgeç'),
                h(Button, { variant: 'danger', onClick: function () { conf[1](false); st[1]('empty'); } }, 'Sil'))
              : h('div', { className: 'kp-keys__actions' },
                h(Button, { variant: 'ghost', onClick: function () { st[1]('edit'); } }, 'Değiştir'),
                h(Button, { variant: 'ghost', icon: h(Icon, { name: 'trash', size: 18 }), onClick: function () { conf[1](true); } }, 'Sil')))
        : h('form', { className: 'kp-keys__form', onSubmit: function (e) { e.preventDefault(); if (v[0].length >= 8) { last[1](v[0].slice(-4)); v[1](''); st[1]('saved'); } } },
            h(TextInput, { type: 'password', autoComplete: 'off', placeholder: 'Anahtarı yapıştır', 'aria-label': k.provider + ' API anahtarı', value: v[0], onChange: function (e) { v[1](e.target.value.trim()); } }),
            h(Button, { variant: 'secondary', type: 'submit', disabled: v[0].length < 8 }, 'Kaydet'),
            st[0] === 'edit' ? h(Button, { variant: 'ghost', onClick: function () { st[1]('saved'); } }, 'Vazgeç') : null));
  }
  function ApiKeyList(p) {
    return h('ul', { className: 'kp-keys' }, (p.keys || []).map(function (k) { return h(ApiKeyRow, { key: k.provider, item: k }); }));
  }

  function DangerZone(p) {
    var v = useState(''), word = p.word || 'SİL', ok = v[0].trim().toLocaleUpperCase('tr-TR') === word;
    return h('section', { className: 'kp-card kp-danger' },
      h('h2', { className: 'kp-card__title' }, p.title || 'Hesabımı sil'),
      h('p', { className: 'kp-danger__text' }, p.children || 'Portföyün, işlemlerin, analizlerin, kayıtlı anahtarların ve Telegram bağlantın kalıcı olarak silinir. Geri alınamaz. Önce verilerini indirmek isteyebilirsin.'),
      h('form', { className: 'kp-danger__form', onSubmit: function (e) { e.preventDefault(); if (ok && p.onDelete) p.onDelete(); } },
        h(Field, { label: 'Onaylamak için ' + word + ' yaz' }, h(TextInput, { value: v[0], autoComplete: 'off', placeholder: word, onChange: function (e) { v[1](e.target.value); } })),
        h(Button, { variant: 'danger', type: 'submit', disabled: !ok }, 'Hesabımı kalıcı olarak sil')));
  }

  var C = window;
  C.Kapanis = C.Kapanis || {};
  Object.assign(C.Kapanis, {
    PageHeader: PageHeader, Card: Card, StatCard: StatCard, SignalCard: SignalCard, ChangeBadge: ChangeBadge, Trend: Trend, RsiMeter: RsiMeter,
    RangeBar: RangeBar, Ticker: Ticker, TickerLogo: TickerLogo, Button: Button, Chip: Chip, Segmented: Segmented, SearchField: SearchField,
    FontScale: FontScale, ThemeToggle: ThemeToggle, WatchlistTable: WatchlistTable, PositionCard: PositionCard, CandleChart: CandleChart,
    ChartPanel: ChartPanel, Disclaimer: Disclaimer,
    AppShell: AppShell, LiveStatus: LiveStatus, BrandMark: BrandMark, Icon: Icon, Tabs: Tabs, DecisionBadge: DecisionBadge, GateList: GateList, SignalList: SignalList, AiNote: AiNote, OutcomeBox: OutcomeBox, RegimeGauge: RegimeGauge, FreshnessList: FreshnessList, FeedList: FeedList, MoverList: MoverList, PulseList: PulseList, MiniChart: MiniChart, MarketCard: MarketCard, DataTable: DataTable, Donut: Donut, Callout: Callout, CompareCard: CompareCard, AlarmCard: AlarmCard, AlarmForm: AlarmForm, Field: Field, TextInput: TextInput, Select: Select, ShieldStatus: ShieldStatus, LimitMeter: LimitMeter, StreakStrip: StreakStrip, FearGreedGauge: FearGreedGauge, LineChart: LineChart,
    LevelBar: LevelBar, SiteHeader: SiteHeader, SiteFooter: SiteFooter, StepList: StepList, FeatureCard: FeatureCard, RuleStrip: RuleStrip, FaqList: FaqList, CloseRuleDiagram: CloseRuleDiagram, MessagePreview: MessagePreview, AuthFrame: AuthFrame, AuthBox: AuthBox, SetupChecklist: SetupChecklist, EmptyState: EmptyState, Skeleton: Skeleton, QuotaMeter: QuotaMeter, BuyForm: BuyForm, TelegramLink: TelegramLink, ApiKeyList: ApiKeyList, DangerZone: DangerZone,
    util: { fmtNum: fmtNum, fmtPrice: fmtPrice, fmtPct: fmtPct, fmtSignedMoney: fmtSignedMoney, sma: sma, rsi: rsi, vwap: vwap, analyse: analyse, signals: signals, parseTr: parseTr, demoCandles: demoCandles, TF: TF, UNIVERSE: UNIVERSE }
  });
})();
