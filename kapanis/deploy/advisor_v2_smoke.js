// Kripto Danışman V2: smoke test with the REAL session. Paste into the browser console on the live site while signed in
// (admin: every step should pass; any other account: every call must answer 403). It only reads and analyses:
// no order exists to be sent. Prints one JSON summary without any secret; copy it back as the test record.
// What it leaves behind: audit rows, at most one paper row for the BTC setup, and one BTC protection state for a made-up
// entry (a real BTC position has another entry price, so that state is dropped the first time it is looked at).
(async () => {
  const token = async () => (window.Clerk && window.Clerk.session ? window.Clerk.session.getToken() : null);
  const call = async (method, path, body) => {
    const t = await token();                       // a fresh short-lived session token for every request
    const started = performance.now();
    const r = await fetch("/api/admin/advisor" + path, {
      method, credentials: "include",
      headers: { "Content-Type": "application/json", ...(t ? { Authorization: "Bearer " + t } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let json = null;
    try { json = await r.json(); } catch (e) { /* not JSON */ }
    return { status: r.status, ms: Math.round(performance.now() - started), json };
  };
  const out = { site: location.host, at: new Date().toISOString(), session: window.Clerk && window.Clerk.session ? "clerk" : "cookie / none" };

  const h = await call("GET", "/health");
  out.health = { status: h.status };
  if (h.status !== 200) {             // not the admin: the rest must be refused as well
    out.analyze = (await call("POST", "/analyze", { symbol: "BTC", with_ai: false })).status;
    out.macro = (await call("GET", "/macro")).status;
    out.history = (await call("GET", "/consensus-history")).status;
    out.verdict = [out.health.status, out.analyze, out.macro, out.history].every((s) => s === 401 || s === 403) ? "REFUSED_AS_EXPECTED_FOR_NON_ADMIN" : "CHECK";
    console.log(JSON.stringify(out, null, 1));
    return out;
  }
  const H = h.json;
  Object.assign(out.health, { version: H.advisor_version, ruleset_hash: H.ruleset_hash, git_commit: (H.git_commit || "").slice(0, 10),
    deepseek_configured: H.providers_configured.deepseek, analysts_configured: H.analysts_configured,
    distinct_models: H.model_diversity.distinct_models, openbb_mode: H.openbb.mode, admin_list_set: H.admin_list_set,
    session: H.session, auto_trading: H.auto_trading, orders_sent: H.orders_sent, timeouts: H.timeouts });

  // 1) the full run: snapshot, rule engine, three analysts in parallel, consensus
  const a = await call("POST", "/analyze", { symbol: "BTC" });
  const R = a.json || {};
  const agents = R.agents || {};
  const each = Object.fromEntries(Object.entries(agents).map(([k, v]) => [k, { status: v.status, verdict: v.verdict, ms: v.latency_ms, error: v.error }]));
  const sum = Object.values(agents).reduce((x, v) => x + (v.latency_ms || 0), 0);
  const plan = R.buy_plan || R.unreleased_plan || (R.engine || {}).withheld_plan || null;
  out.analyze = { status: a.status, request_ms: a.ms, final: R.final, engine: R.engine && R.engine.status, setup: R.engine && R.engine.setup,
    consensus: R.consensus && R.consensus.consensus, plan_released: R.consensus && R.consensus.plan_released, analysts: each,
    parallel: R.latency ? R.latency.agents_ms < sum * 0.85 : null, latency: R.latency,
    snapshot: R.snapshot && { market_timestamp: R.snapshot.market_timestamp, hash: R.snapshot_hash, stale: R.snapshot.stale,
      data_age_s: R.snapshot.data_age_seconds, price_source: R.snapshot.price_source, macro_status: R.snapshot.macro.macro_status },
    levels: plan && { type: plan.type, trigger: plan.trigger, limit: plan.limit, stop: plan.technical_stop, invalidation: plan.technical_invalidation },
    why_not: (R.why_not_trade || []).slice(0, 4), paper_logged: R.paper_logged, order_sent: R.order_sent, auto_trading: R.auto_trading };

  // 2) the same coin again without the analysts: the engine's levels must be the same (prices come from code),
  //    no plan may be released, and the same setup on the same candle must not be logged twice
  const b = await call("POST", "/analyze", { symbol: "BTC", with_ai: false });
  const B = b.json || {};
  const p2 = B.buy_plan || B.unreleased_plan || (B.engine || {}).withheld_plan || null;
  const same = R.snapshot && B.snapshot && R.snapshot.market_timestamp === B.snapshot.market_timestamp;
  out.engine_only = { status: b.status, request_ms: b.ms, consensus: B.consensus && B.consensus.consensus, buy_plan_is_null: B.buy_plan === null,
    same_candle: same, levels_identical: same && plan && p2 ? ["trigger", "limit", "technical_stop", "technical_invalidation"].every((k) => plan[k] === p2[k]) : null,
    paper_logged_again: B.paper_logged };

  // 3) protection, calculation only: an entry 3 % under the price, first without a first stop (R is an estimate), then with one
  const price = R.snapshot ? R.snapshot.current_price : null;
  if (price) {
    const entry = Math.round(price * 0.97);
    const pick = (x) => { const p = (x.json || {}).sell_plan || {}; return { status: x.status, action: p.action, state: p.state, current_R: p.current_R,
      estimated: p.current_R_estimated, r_basis: p.r_basis, stop: p.stop_loss, stop_source: p.stop_source, take_profit: p.take_profit,
      tp_source: p.take_profit_source, invalidation: p.technical_invalidation, exit_reasons: (p.exit_reasons || []).map((e) => e.code),
      order_sent: p.order_sent }; };
    out.protection_unknown_stop = pick(await call("POST", "/sell-plan", { symbol: "BTC", entry_price: entry, with_ai: false, use_portfolio: false }));
    out.protection_known_stop = pick(await call("POST", "/sell-plan", { symbol: "BTC", entry_price: entry, initial_stop: Math.round(entry * 0.98), with_ai: false, use_portfolio: false }));
  }

  // 4) what was stored, and macro without OpenBB
  const st = await call("GET", "/paper-stats?origin=LIVE");
  out.paper = { status: st.status, v2_ruleset: st.json && st.json.ruleset_hash, live_records: st.json && st.json.exit_styles.records, setups: st.json && st.json.exit_styles.setups };
  const hi = await call("GET", "/consensus-history?limit=5");
  out.history = { status: hi.status, rows: Array.isArray(hi.json) ? hi.json.length : null,
    last: Array.isArray(hi.json) && hi.json[0] ? { symbol: hi.json[0].symbol, final: hi.json[0].final, order_sent: hi.json[0].order_sent, has_email: JSON.stringify(hi.json[0]).includes("@") } : null };
  const m = await call("GET", "/macro");
  out.macro = { status: m.status, macro_status: m.json && m.json.macro_status, events: m.json && m.json.economic_events.length, caution: m.json && m.json.caution };
  console.log(JSON.stringify(out, null, 1));
  return out;
})();
