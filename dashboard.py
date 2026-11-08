"""Build an interactive NZ fuel price dashboard (dashboard.html) from the data in this repo.

Usage:  python dashboard.py

Inputs (same folder as this script):
  - weekly-table.csv                                   weekly price breakdown, 2004 to 2026
  - Fuel-price-monitoring-Data-to-27-October-2026.xlsx  daily retail price and refined cost, 2026

Needs: pandas, openpyxl.

pandas prepares the data and the summary cards. The page itself is one self-contained HTML
file: the data is embedded as JSON and the charts are drawn by a small piece of plain
JavaScript (no CDN, no extra libraries), so it also works offline.

Chart controls: hover for values, drag across a chart to zoom, double-click to reset,
click a legend entry to hide or show a line.
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WEEKLY_CSV = HERE / "weekly-table.csv"
DAILY_XLSX = next(HERE.glob("Fuel-price-monitoring-Data-to-*.xlsx"))
OUT = HERE / "dashboard.html"

# One consistent colour and label per fuel across every chart.
# Daily file uses 91 / 95 / Diesel, weekly file uses Regular / Premium 95R / Diesel.
FUELS = ["91", "95", "Diesel"]
WEEKLY_NAME = {"91": "Regular Petrol", "95": "Premium Petrol 95R", "Diesel": "Diesel"}
LABEL = {"91": "91 Regular", "95": "95 Premium", "Diesel": "Diesel"}
COLOR = {"91": "#2a6fdb", "95": "#d9534f", "Diesel": "#3a9d5d"}
# Components that add up to the adjusted retail price.
PARTS = [("Importer cost", "#2a6fdb"), ("Importer margin", "#7fb0f2"), ("Taxes", "#8a6bbf"),
         ("ETS", "#e0a030"), ("GST", "#9aa5b1")]
EPOCH = pd.Timestamp("1970-01-01")


# ---------------------------------------------------------------- data
def load_daily() -> pd.DataFrame:
    df = pd.read_excel(DAILY_XLSX)
    df["date"] = pd.to_datetime(df["DATE"], dayfirst=True)
    df = df.rename(columns={"FUEL_TYPE": "fuel", "REFINED_COSTS": "refined", "RETAIL_PRICES_AVG": "retail"})
    df["fuel"] = df["fuel"].astype(str)
    return df[["date", "fuel", "refined", "retail"]].sort_values("date")


def load_weekly() -> pd.DataFrame:
    df = pd.read_csv(WEEKLY_CSV, parse_dates=["Date"])
    return df.rename(columns={"Date": "date", "Fuel": "fuel", "Variable": "var", "Value": "value"})


def ms(ts) -> int:
    """Timestamp -> milliseconds since 1970 (what the JavaScript side uses)."""
    return int((pd.Timestamp(ts) - EPOCH) / pd.Timedelta(milliseconds=1))


def vals(s: pd.Series, nd: int = 2) -> list:
    return [None if pd.isna(v) else round(float(v), nd) for v in s]


def build_data(daily: pd.DataFrame, weekly: pd.DataFrame) -> dict:
    # daily: one aligned series per fuel
    didx = pd.DatetimeIndex(sorted(daily.date.unique()))
    d = {"x": [ms(t) for t in didx], "retail": {}, "refined": {}}
    for f in FUELS:
        s = daily[daily.fuel == f].groupby("date")[["retail", "refined"]].first().reindex(didx)
        d["retail"][f] = vals(s.retail, 1)
        d["refined"][f] = vals(s.refined, 1)
    both = [v for f in FUELS for v in d["retail"][f] + d["refined"][f] if v is not None]
    cost_domain = [int(min(both) // 50 * 50), int(-(-max(both) // 50) * 50)]

    # weekly: long-run retail price, crude and exchange rate, all on the same dates
    widx = pd.DatetimeIndex(sorted(weekly.date.unique()))

    def wk(mask):
        return weekly[mask].groupby("date").value.first().reindex(widx)

    w = {"x": [ms(t) for t in widx], "retail": {}}
    for f in FUELS:
        w["retail"][f] = vals(wk((weekly.fuel == WEEKLY_NAME[f]) & (weekly["var"] == "Adjusted retail price")), 1)
    w["crude"] = vals(wk((weekly["var"] == "Dubai crude price") & (weekly.Unit == "USD/bbl")), 1)
    w["fx"] = vals(wk(weekly["var"] == "Exchange rate"), 4)

    # latest-week breakdown of the pump price
    latest = weekly.date.max()
    rows = []
    for f in FUELS:
        parts = []
        for name, color in PARTS:
            v = weekly[(weekly.date == latest) & (weekly.fuel == WEEKLY_NAME[f]) & (weekly["var"] == name)].value.iloc[0]
            parts.append({"name": name, "value": round(float(v), 2), "color": color})
        rows.append({"label": LABEL[f], "total": round(sum(p["value"] for p in parts), 2), "parts": parts})

    return {
        "daily": d, "weekly": w, "costDomain": cost_domain,
        "breakdown": {"parts": [{"name": n, "color": c} for n, c in PARTS], "rows": rows},
        "labels": LABEL, "colors": COLOR,
    }


# ---------------------------------------------------------------- KPI cards
def pct(a, b):
    return (a / b - 1) * 100


def kpi_cards(daily, weekly):
    cards = []
    for f in FUELS:
        d = daily[daily.fuel == f].set_index("date").retail
        last, last_date = d.iloc[-1], d.index[-1]
        d30 = d[d.index <= last_date - pd.Timedelta(days=30)].iloc[-1]
        d0 = d.iloc[0]
        ch30, ch0 = pct(last, d30), pct(last, d0)
        cards.append(f"""
        <div class="card" style="border-top-color:{COLOR[f]}">
          <div class="label">{LABEL[f]}</div>
          <div class="value">{last:.1f}<span class="unit"> c/L</span></div>
          <div class="delta {'up' if ch30 > 0 else 'down'}">{ch30:+.1f}% vs 30 days ago</div>
          <div class="sub">{ch0:+.1f}% since {d.index[0]:%d %b} &middot; peak {d.max():.0f}</div>
        </div>""")
    crude = weekly[(weekly["var"] == "Dubai crude price") & (weekly.Unit == "USD/bbl")].sort_values("date")
    fx = weekly[weekly["var"] == "Exchange rate"].sort_values("date")
    cards.append(f"""
        <div class="card" style="border-top-color:#444">
          <div class="label">Dubai crude</div>
          <div class="value">{crude.value.iloc[-1]:.0f}<span class="unit"> USD/bbl</span></div>
          <div class="delta {'up' if crude.value.iloc[-1] > crude.value.iloc[-5] else 'down'}">{pct(crude.value.iloc[-1], crude.value.iloc[-5]):+.1f}% vs 4 weeks ago</div>
          <div class="sub">NZD/USD {fx.value.iloc[-1]:.3f}</div>
        </div>""")
    return "".join(cards)


# ---------------------------------------------------------------- page
CSS = """
  :root { --ink:#1f2933; --muted:#6b7785; --line:#e4e8ec; --bg:#f6f8fa; --card:#fff; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  main { max-width:1040px; margin:0 auto; padding:28px 16px 48px; }
  h1 { font-size:26px; margin:0 0 4px; }
  .lead { color:var(--muted); margin:0 0 6px; }
  .hint { color:var(--muted); font-size:13px; margin:0 0 20px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin-bottom:22px; }
  .card { background:var(--card); border:1px solid var(--line); border-top:4px solid; border-radius:10px; padding:14px 16px; }
  .label { color:var(--muted); font-size:13px; text-transform:uppercase; letter-spacing:.04em; }
  .value { font-size:30px; font-weight:700; margin:2px 0; }
  .unit { font-size:14px; font-weight:400; color:var(--muted); }
  .delta { font-size:14px; font-weight:600; }
  .delta.up { color:#c0392b; } .delta.down { color:#1e8449; }
  .sub { color:var(--muted); font-size:13px; }
  section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px 12px; margin-bottom:18px; }
  h2 { font-size:17px; margin:0 0 2px; }
  .note { color:var(--muted); font-size:13px; margin:0 0 8px; }
  footer { color:var(--muted); font-size:12.5px; margin-top:20px; }
  .grid3 { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }
  .grid2 { display:grid; grid-template-columns:repeat(2,1fr); gap:14px; }
  .grid3 > div, .grid2 > div { min-width:0; }
  @media (max-width:760px) { .grid3, .grid2 { grid-template-columns:1fr; } }
  .ctitle { font-size:14px; font-weight:700; margin-bottom:2px; }
  /* chart parts */
  .plot { width:100%; }
  .bar { display:flex; flex-wrap:wrap; align-items:center; gap:4px 14px; margin:2px 0 6px; font-size:13px; min-height:28px; }
  .spacer { flex:1; }
  .bar.slim { min-height:0; margin:0; }
  .unit-l { color:var(--muted); }
  .btn { font:inherit; font-size:13px; border:1px solid var(--line); background:#fff; color:var(--ink); border-radius:6px; padding:3px 9px; cursor:pointer; }
  .btn:hover { background:#eef1f4; }
  .btn.active { background:var(--ink); color:#fff; border-color:var(--ink); }
  .leg { display:inline-flex; align-items:center; gap:6px; border:0; background:none; padding:2px 4px; font:inherit; color:var(--ink); cursor:pointer; }
  .leg.off { opacity:.4; }
  .leg.static { cursor:default; }
  .sw { display:inline-block; width:10px; height:10px; border-radius:2px; flex:none; }
  #tip { position:fixed; display:none; pointer-events:none; background:#1f2933; color:#fff; font-size:13px; line-height:1.45; padding:8px 10px; border-radius:8px; box-shadow:0 4px 14px rgba(0,0,0,.25); z-index:20; max-width:270px; }
  .thead { font-weight:600; margin-bottom:3px; }
  .trow { display:flex; align-items:center; gap:7px; }
  .trow .tn { flex:1; margin-right:10px; }
  .tmuted { color:#c3cbd3; margin-top:3px; font-size:12px; }
  /* stacked bars */
  .srow { display:flex; align-items:center; margin:10px 0; }
  .slabel { width:110px; flex:none; font-size:14px; }
  .swrap { flex:1; display:flex; align-items:center; min-width:0; }
  .sbar { display:flex; height:40px; border-radius:4px; overflow:hidden; }
  .seg { display:flex; align-items:center; justify-content:center; color:#fff; font-weight:700; font-size:13px; min-width:2px; overflow:hidden; }
  .seg:hover { filter:brightness(1.12); }
  .stotal { margin-left:8px; font-weight:700; }
"""

JS = r"""
(function () {
  var NS = 'http://www.w3.org/2000/svg', DAY = 864e5, uid = 0;
  var MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  var MUTED = '#6b7785', GRID = '#e4e8ec';
  var DATA = __DATA__;
  var tip = document.getElementById('tip');

  function svgEl(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function html(tag, cls, text, parent) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function fmtDate(ms) {
    var d = new Date(ms);
    return DOW[d.getUTCDay()] + ' ' + d.getUTCDate() + ' ' + MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
  }
  function showTip(h, cx, cy) {
    tip.innerHTML = h; tip.style.display = 'block';
    var w = tip.offsetWidth, ht = tip.offsetHeight;
    var left = cx + 16; if (left + w > window.innerWidth - 8) left = cx - w - 16;
    var top = cy - ht - 12; if (top < 8) top = cy + 16;
    tip.style.left = Math.max(8, left) + 'px'; tip.style.top = top + 'px';
  }
  function hideTip() { tip.style.display = 'none'; }
  function row(color, name, value) {
    return '<div class="trow"><span class="sw" style="background:' + color + '"></span><span class="tn">' + name + '</span><b>' + value + '</b></div>';
  }

  function niceTicks(lo, hi, n) {
    var raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), r = raw / mag;
    var step = (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * mag, out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
    out.dec = step < 1 ? Math.ceil(-Math.log10(step) - 1e-9) : 0;
    return out;
  }

  var STEPS = [{t:'d',n:1},{t:'d',n:2},{t:'d',n:7},{t:'d',n:14},{t:'m',n:1},{t:'m',n:2},{t:'m',n:3},
               {t:'m',n:6},{t:'m',n:12},{t:'m',n:24},{t:'m',n:48},{t:'m',n:120}];
  function timeTicks(x0, x1, w) {
    var target = Math.max(3, Math.floor(w / 75)), span = (x1 - x0) / DAY, st = STEPS[STEPS.length - 1], out = [], i, t;
    for (i = 0; i < STEPS.length; i++) {
      var len = STEPS[i].t === 'd' ? STEPS[i].n : STEPS[i].n * 30.44;
      if (span / len <= target) { st = STEPS[i]; break; }
    }
    if (st.t === 'd') {
      for (t = Math.ceil(x0 / DAY / st.n) * st.n * DAY; t <= x1; t += st.n * DAY) {
        var dd = new Date(t); out.push({x: t, label: dd.getUTCDate() + ' ' + MON[dd.getUTCMonth()]});
      }
    } else {
      var d0 = new Date(x0), y = d0.getUTCFullYear(), m = d0.getUTCMonth();
      if (st.n >= 12) { var yn = st.n / 12; y = Math.floor(y / yn) * yn; m = 0; } else { m = Math.floor(m / st.n) * st.n; }
      for (var g = 0; g < 500; g++) {
        t = Date.UTC(y, m, 1);
        if (t > x1) break;
        if (t >= x0) out.push({x: t, label: st.n >= 12 ? String(y) : (m === 0 || !out.length ? MON[m] + ' ' + y : MON[m])});
        m += st.n; y += Math.floor(m / 12); m = m % 12;
      }
    }
    return out;
  }

  /* Line chart with hover tooltip, drag-to-zoom, legend toggles and optional range buttons. */
  function lineChart(root, cfg) {
    var H = cfg.height || 320, M = {t: 10, r: cfg.padR == null ? 16 : cfg.padR, b: 26, l: cfg.padL || 52};
    var x = cfg.x, full = [x[0], x[x.length - 1]], dom = full.slice(), id = 'clip' + (++uid), W = 0;
    var S = cfg.series.map(function (s) { return {name: s.name, color: s.color, y: s.y, on: true, width: s.width || 1.8}; });
    root.innerHTML = '';
    var bar = html('div', 'bar', null, root), box = html('div', 'plot', null, root);
    if (cfg.noLegend && !cfg.yLabel && !cfg.ranges) bar.classList.add('slim');
    if (cfg.yLabel) html('span', 'unit-l', cfg.yLabel, bar);
    if (S.length > 1 && !cfg.noLegend) {
      S.forEach(function (s) {
        var b = html('button', 'leg', null, bar); b.type = 'button'; b.title = 'Click to hide or show';
        var sw = html('span', 'sw', null, b); sw.style.background = s.color; html('span', null, s.name, b);
        b.addEventListener('click', function () { s.on = !s.on; b.classList.toggle('off', !s.on); draw(); });
      });
    }
    html('span', 'spacer', null, bar);
    var rbtns = [];
    (cfg.ranges || []).forEach(function (r) {
      var b = html('button', 'btn', r.label, bar); b.type = 'button'; rbtns.push(b);
      b.addEventListener('click', function () {
        dom = r.days ? [Math.max(full[0], full[1] - r.days * DAY), full[1]] : full.slice();
        syncUi(b); draw();
      });
    });
    var reset = html('button', 'btn', 'Reset zoom', bar); reset.type = 'button'; reset.style.display = 'none';
    reset.addEventListener('click', function () { dom = full.slice(); syncUi(null); draw(); });
    function syncUi(active) {
      var zoomed = dom[0] !== full[0] || dom[1] !== full[1];
      reset.style.display = zoomed && !active ? '' : 'none';
      rbtns.forEach(function (b) { b.classList.toggle('active', b === active); });
      if (active && !zoomed) active.classList.add('active');
    }

    function lower(v) { var lo = 0, hi = x.length; while (lo < hi) { var m = (lo + hi) >> 1; if (x[m] < v) lo = m + 1; else hi = m; } return lo; }
    function nearest(v) { var i = lower(v); if (i > 0 && (i >= x.length || v - x[i - 1] < x[i] - v)) i--; return Math.min(i, x.length - 1); }

    function draw() {
      hideTip();
      W = box.clientWidth || 600; box.innerHTML = '';
      var iw = W - M.l - M.r, ih = H - M.t - M.b;
      var i0 = lower(dom[0]), i1 = Math.min(x.length - 1, lower(dom[1] + 1) - 1); if (i1 < i0) i1 = i0;
      var lo = Infinity, hi = -Infinity;
      [true, false].forEach(function (onlyOn) {
        if (lo !== Infinity) return;
        S.forEach(function (s) {
          if (onlyOn && !s.on) return;
          for (var i = i0; i <= i1; i++) { var v = s.y[i]; if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } }
        });
      });
      if (cfg.yDomain) { lo = cfg.yDomain[0]; hi = cfg.yDomain[1]; }
      else { var pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad; }
      var sx = function (v) { return M.l + (v - dom[0]) / (dom[1] - dom[0]) * iw; };
      var sy = function (v) { return M.t + ih - (v - lo) / (hi - lo) * ih; };

      var svg = svgEl('svg', {width: W, height: H, viewBox: '0 0 ' + W + ' ' + H}, box); svg.style.display = 'block';
      var cp = svgEl('clipPath', {id: id}, svgEl('defs', {}, svg));
      svgEl('rect', {x: M.l, y: M.t, width: iw, height: ih}, cp);
      var yt = niceTicks(lo, hi, 5);
      yt.forEach(function (v) {
        var y = sy(v); svgEl('line', {x1: M.l, x2: M.l + iw, y1: y, y2: y, stroke: GRID}, svg);
        svgEl('text', {x: M.l - 8, y: y + 4, 'text-anchor': 'end', fill: MUTED, 'font-size': 12}, svg).textContent = v.toFixed(yt.dec);
      });
      timeTicks(dom[0], dom[1], iw).forEach(function (tk) {
        svgEl('text', {x: sx(tk.x), y: H - 6, 'text-anchor': 'middle', fill: MUTED, 'font-size': 12}, svg).textContent = tk.label;
      });

      var g = svgEl('g', {'clip-path': 'url(#' + id + ')'}, svg);
      S.forEach(function (s) {
        if (!s.on) return;
        var d = '', pen = false;
        for (var i = Math.max(0, i0 - 1); i <= Math.min(x.length - 1, i1 + 1); i++) {
          var v = s.y[i]; if (v == null) { pen = false; continue; }
          d += (pen ? 'L' : 'M') + sx(x[i]).toFixed(1) + ' ' + sy(v).toFixed(1); pen = true;
        }
        svgEl('path', {d: d, fill: 'none', stroke: s.color, 'stroke-width': s.width, 'stroke-linejoin': 'round'}, g);
      });
      if (cfg.endLabels && i1 === x.length - 1) {
        S.forEach(function (s) {
          var v = s.y[i1]; if (!s.on || v == null) return;
          svgEl('text', {x: sx(x[i1]) + 6, y: sy(v) + 4, fill: s.color, 'font-size': 12, 'font-weight': 600}, svg).textContent = v.toFixed(0);
        });
      }

      var hv = svgEl('g', {}, svg); hv.style.display = 'none';
      var vl = svgEl('line', {y1: M.t, y2: M.t + ih, stroke: '#9aa5b1', 'stroke-dasharray': '3 3'}, hv);
      var dots = S.map(function (s) { return svgEl('circle', {r: 4, fill: s.color, stroke: '#fff', 'stroke-width': 1.5}, hv); });
      var sel = svgEl('rect', {y: M.t, height: ih, fill: 'rgba(42,111,219,.15)', stroke: '#2a6fdb', 'stroke-width': 1}, svg); sel.style.display = 'none';
      var ov = svgEl('rect', {x: M.l, y: M.t, width: iw, height: ih, fill: 'transparent'}, svg);
      ov.style.cursor = 'crosshair'; ov.style.touchAction = 'pan-y';
      var drag = null;
      function px(e) { return e.clientX - svg.getBoundingClientRect().left; }
      function clampX(v) { return Math.max(M.l, Math.min(M.l + iw, v)); }
      function hover(e) {
        var v = dom[0] + (px(e) - M.l) / iw * (dom[1] - dom[0]);
        var i = Math.max(i0, Math.min(i1, nearest(v))), xx = sx(x[i]), rows = '';
        hv.style.display = ''; vl.setAttribute('x1', xx); vl.setAttribute('x2', xx);
        S.forEach(function (s, k) {
          var yv = s.y[i];
          if (!s.on || yv == null) { dots[k].style.display = 'none'; return; }
          dots[k].style.display = ''; dots[k].setAttribute('cx', xx); dots[k].setAttribute('cy', sy(yv));
          rows += row(s.color, s.name, cfg.fmt ? cfg.fmt(yv) : yv.toFixed(1));
        });
        showTip('<div class="thead">' + fmtDate(x[i]) + '</div>' + rows + (cfg.extra ? cfg.extra(i) : ''), e.clientX, e.clientY);
      }
      ov.addEventListener('pointermove', function (e) {
        if (drag !== null) {
          var a = clampX(drag), b = clampX(px(e));
          sel.style.display = ''; sel.setAttribute('x', Math.min(a, b)); sel.setAttribute('width', Math.abs(b - a));
          hideTip(); hv.style.display = 'none';
        } else hover(e);
      });
      ov.addEventListener('pointerleave', function () { hv.style.display = 'none'; hideTip(); });
      ov.addEventListener('pointerdown', function (e) {
        if (e.pointerType === 'touch' || e.button !== 0) return;
        drag = px(e); ov.setPointerCapture(e.pointerId);
      });
      ov.addEventListener('pointerup', function (e) {
        if (drag === null) return;
        var a = clampX(drag), b = clampX(px(e)); drag = null;
        try { ov.releasePointerCapture(e.pointerId); } catch (err) {}
        sel.style.display = 'none';
        if (Math.abs(b - a) > 8) {
          var va = dom[0] + (Math.min(a, b) - M.l) / iw * (dom[1] - dom[0]);
          var vb = dom[0] + (Math.max(a, b) - M.l) / iw * (dom[1] - dom[0]);
          if (lower(vb + 1) - lower(va) >= 4) { dom = [va, vb]; syncUi(null); draw(); }
        }
      });
      ov.addEventListener('dblclick', function () { dom = full.slice(); syncUi(null); draw(); });
    }
    draw();
    if (window.ResizeObserver) new ResizeObserver(function () { if (box.clientWidth !== W) draw(); }).observe(box);
  }

  /* Stacked horizontal bars for the pump price breakdown, with hover tooltips. */
  function stacked(root, data) {
    root.innerHTML = '';
    var leg = html('div', 'bar', null, root);
    data.parts.forEach(function (p) {
      var b = html('span', 'leg static', null, leg), sw = html('span', 'sw', null, b);
      sw.style.background = p.color; html('span', null, p.name, b);
    });
    var max = Math.max.apply(null, data.rows.map(function (r) { return r.total; }));
    data.rows.forEach(function (r) {
      var rw = html('div', 'srow', null, root); html('div', 'slabel', r.label, rw);
      var wrap = html('div', 'swrap', null, rw), bar = html('div', 'sbar', null, wrap);
      bar.style.width = (r.total / max * 90) + '%';
      r.parts.forEach(function (p) {
        var seg = html('div', 'seg', p.value >= 14 ? String(Math.round(p.value)) : '', bar);
        seg.style.background = p.color; seg.style.flex = p.value + ' 1 0';
        seg.addEventListener('pointermove', function (e) {
          showTip('<div class="thead">' + r.label + '</div>' + row(p.color, p.name, p.value.toFixed(1) + ' c/L') +
                  '<div class="tmuted">' + (p.value / r.total * 100).toFixed(1) + '% of the ' + r.total.toFixed(0) + ' c/L pump price</div>', e.clientX, e.clientY);
        });
        seg.addEventListener('pointerleave', hideTip);
      });
      html('div', 'stotal', r.total.toFixed(0), wrap);
    });
  }

  var D = DATA, F = ['91', '95', 'Diesel'], byId = function (i) { return document.getElementById(i); };

  lineChart(byId('c-daily'), {
    x: D.daily.x, height: 340, padR: 44, endLabels: true, yLabel: 'Retail price, NZD c/L',
    series: F.map(function (f) { return {name: D.labels[f], color: D.colors[f], y: D.daily.retail[f]}; })
  });

  F.forEach(function (f) {
    lineChart(byId('c-cost-' + f), {
      x: D.daily.x, height: 250, padR: 10, padL: 44, yDomain: D.costDomain, noLegend: true,
      series: [{name: 'Refined cost', color: '#8a94a0', y: D.daily.refined[f], width: 1.4},
               {name: 'Retail price', color: D.colors[f], y: D.daily.retail[f]}],
      extra: function (i) {
        var r = D.daily.retail[f][i], c = D.daily.refined[f][i];
        return (r == null || c == null) ? '' : '<div class="tmuted">Retail minus refined cost: ' + (r - c).toFixed(1) + ' c/L</div>';
      }
    });
  });

  stacked(byId('c-break'), D.breakdown);

  lineChart(byId('c-long'), {
    x: D.weekly.x, height: 340, yLabel: 'Adjusted retail price, NZD c/L',
    ranges: [{label: '5Y', days: 365 * 5}, {label: '10Y', days: 3652}, {label: 'All'}],
    series: F.map(function (f) { return {name: D.labels[f], color: D.colors[f], y: D.weekly.retail[f], width: 1.5}; })
  });

  lineChart(byId('c-crude'), {
    x: D.weekly.x, height: 250, padL: 44, padR: 10, noLegend: true, yLabel: 'USD per barrel',
    series: [{name: 'Dubai crude', color: '#444', y: D.weekly.crude, width: 1.4}], fmt: function (v) { return v.toFixed(1) + ' USD/bbl'; }
  });
  lineChart(byId('c-fx'), {
    x: D.weekly.x, height: 250, padL: 44, padR: 10, noLegend: true, yLabel: 'USD per NZD',
    series: [{name: 'Exchange rate', color: '#8a6bbf', y: D.weekly.fx, width: 1.4}], fmt: function (v) { return v.toFixed(3); }
  });
})();
"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NZ Fuel Prices Dashboard</title>
<style>__CSS__</style></head>
<body><main>
  <h1>NZ Fuel Prices</h1>
  <p class="lead">Daily retail prices to __DAILY_END__ and weekly price breakdown to __WEEKLY_END__. All prices in NZD cents per litre.</p>
  <p class="hint">Hover a chart for values &middot; drag across it to zoom &middot; double-click to reset &middot; click a legend entry to hide a line.</p>
  <div class="cards">__CARDS__</div>

  <section><h2>Daily retail price, 2026</h2>
    <p class="note">Average retail price per fuel, from the daily monitoring file.</p>
    <div id="c-daily"></div></section>

  <section><h2>Refined cost vs retail price, 2026</h2>
    <p class="note">Grey is the refined cost, coloured is the retail price. The gap is what is added after refining. It narrows or inverts when costs spike.</p>
    <div class="grid3">__COST_PANELS__</div></section>

  <section><h2>What is in the pump price (week of __WEEKLY_END__)</h2>
    <p class="note">Importer cost + importer margin + taxes + ETS + GST add up to the adjusted retail price. Hover a block for its share.</p>
    <div id="c-break"></div></section>

  <section><h2>Retail price since 2004</h2>
    <p class="note">Weekly adjusted retail price. Use the buttons for a quick range, or drag to zoom into any period.</p>
    <div id="c-long"></div></section>

  <section><h2>Crude oil and the exchange rate</h2>
    <p class="note">The two main drivers of importer cost.</p>
    <div class="grid2">
      <div><div class="ctitle">Dubai crude (USD/bbl)</div><div id="c-crude"></div></div>
      <div><div class="ctitle">Exchange rate (USD per NZD)</div><div id="c-fx"></div></div>
    </div></section>

  <footer>Weekly figures from __PROV_START__ onward are marked Provisional in the source data. Generated __TODAY__ by dashboard.py.</footer>
</main>
<div id="tip"></div>
<script>__JS__</script>
</body></html>
"""


def main():
    daily, weekly = load_daily(), load_weekly()
    data = json.dumps(build_data(daily, weekly), separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    cost_panels = "".join(
        f'<div><div class="ctitle" style="color:{COLOR[f]}">{LABEL[f]}</div><div id="c-cost-{f}"></div></div>'
        for f in FUELS)
    prov = weekly[weekly.Status == "Provisional"].date.min()
    page = (TEMPLATE
            .replace("__CSS__", CSS)
            .replace("__DAILY_END__", f"{daily.date.max():%d %b %Y}")
            .replace("__WEEKLY_END__", f"{weekly.date.max():%d %b %Y}")
            .replace("__PROV_START__", f"{prov:%d %b %Y}")
            .replace("__TODAY__", f"{date.today():%d %b %Y}")
            .replace("__CARDS__", kpi_cards(daily, weekly))
            .replace("__COST_PANELS__", cost_panels)
            .replace("__JS__", JS.replace("__DATA__", data)))
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
