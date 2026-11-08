"""Build a simple NZ fuel price dashboard (dashboard.html) from the data in this repo.

Usage:  python dashboard.py

Inputs (same folder as this script):
  - weekly-table.csv                                   weekly price breakdown, 2004 to 2026
  - Fuel-price-monitoring-Data-to-27-October-2026.xlsx  daily retail price and refined cost, 2026

Needs: pandas, matplotlib, openpyxl.
"""
import io
import re
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
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
INK, MUTED, GRID = "#1f2933", "#6b7785", "#e4e8ec"

plt.rcParams.update({
    "svg.fonttype": "none",
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": INK,
})


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


# ---------------------------------------------------------------- chart helpers
def style(ax, ylabel=None):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    if ylabel:
        ax.set_ylabel(ylabel)


def to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    svg = buf.getvalue()
    svg = re.sub(r"<\?xml.*?\?>|<!DOCTYPE.*?>", "", svg, flags=re.S)
    # make the SVG scale to its container
    svg = re.sub(r'<svg[^>]*?width="[^"]*"[^>]*?height="[^"]*"', lambda m: re.sub(r'(width|height)="[^"]*"', "", m.group(0), count=2) + ' width="100%"', svg, count=1)
    return svg


# ---------------------------------------------------------------- charts
def chart_daily_prices(daily):
    fig, ax = plt.subplots(figsize=(9.6, 3.8))
    for f in FUELS:
        d = daily[daily.fuel == f]
        ax.plot(d.date, d.retail, color=COLOR[f], linewidth=1.8, label=LABEL[f])
        ax.annotate(f"{d.retail.iloc[-1]:.0f}", (d.date.iloc[-1], d.retail.iloc[-1]),
                    xytext=(6, 0), textcoords="offset points", color=COLOR[f], va="center", fontsize=9)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.margins(x=0.02)
    style(ax, "Retail price (NZD c/L)")
    ax.legend(frameon=False, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0))
    return to_svg(fig)


def chart_cost_vs_retail(daily):
    fig, axes = plt.subplots(1, 3, figsize=(9.6, 3.0), sharey=True)
    for ax, f in zip(axes, FUELS):
        d = daily[daily.fuel == f]
        ax.plot(d.date, d.refined, color=MUTED, linewidth=1.3, label="Refined cost")
        ax.plot(d.date, d.retail, color=COLOR[f], linewidth=1.6, label="Retail price")
        ax.set_title(LABEL[f], loc="left", fontsize=10, color=COLOR[f], fontweight="bold")
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[2, 4, 6, 8, 10]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        style(ax)
    axes[0].set_ylabel("NZD c/L")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    return to_svg(fig)


def chart_long_run(weekly):
    fig, ax = plt.subplots(figsize=(9.6, 3.6))
    for f in FUELS:
        d = weekly[(weekly.fuel == WEEKLY_NAME[f]) & (weekly["var"] == "Adjusted retail price")]
        ax.plot(d.date, d.value, color=COLOR[f], linewidth=1.4, label=LABEL[f])
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.margins(x=0.01)
    style(ax, "Adjusted retail price (NZD c/L)")
    ax.legend(frameon=False, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0))
    return to_svg(fig)


def chart_breakdown(weekly):
    latest = weekly.date.max()
    parts = [("Importer cost", "#2a6fdb"), ("Importer margin", "#7fb0f2"), ("Taxes", "#8a6bbf"),
             ("ETS", "#e0a030"), ("GST", "#9aa5b1")]
    wk = weekly[(weekly.date == latest) & weekly.fuel.notna()]
    fig, ax = plt.subplots(figsize=(9.6, 2.8))
    ypos = list(range(len(FUELS)))[::-1]
    for y, f in zip(ypos, FUELS):
        left = 0.0
        for name, color in parts:
            v = wk[(wk.fuel == WEEKLY_NAME[f]) & (wk["var"] == name)].value.iloc[0]
            ax.barh(y, v, left=left, color=color, height=0.55, label=name if y == ypos[0] else None)
            if v >= 14:
                ax.text(left + v / 2, y, f"{v:.0f}", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
            left += v
        ax.text(left + 4, y, f"{left:.0f}", va="center", fontsize=10, fontweight="bold")
    ax.set_yticks(ypos, [LABEL[f] for f in FUELS])
    ax.set_xlim(0, 420)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("NZD c/L")
    ax.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.2), fontsize=9)
    return to_svg(fig), latest


def chart_crude_fx(weekly):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 3.0))
    crude = weekly[(weekly["var"] == "Dubai crude price") & (weekly.Unit == "USD/bbl")]
    fx = weekly[weekly["var"] == "Exchange rate"]
    a1.plot(crude.date, crude.value, color="#444", linewidth=1.3)
    a1.set_title("Dubai crude (USD/bbl)", loc="left", fontsize=10)
    a2.plot(fx.date, fx.value, color="#8a6bbf", linewidth=1.3)
    a2.set_title("Exchange rate (USD per NZD)", loc="left", fontsize=10)
    for ax in (a1, a2):
        ax.xaxis.set_major_locator(mdates.YearLocator(4))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        style(ax)
    fig.tight_layout()
    return to_svg(fig)


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
TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NZ Fuel Prices Dashboard</title>
<style>
  :root { --ink:#1f2933; --muted:#6b7785; --line:#e4e8ec; --bg:#f6f8fa; --card:#fff; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  main { max-width:1040px; margin:0 auto; padding:28px 16px 48px; }
  h1 { font-size:26px; margin:0 0 4px; }
  .lead { color:var(--muted); margin:0 0 22px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin-bottom:22px; }
  .card { background:var(--card); border:1px solid var(--line); border-top:4px solid; border-radius:10px; padding:14px 16px; }
  .label { color:var(--muted); font-size:13px; text-transform:uppercase; letter-spacing:.04em; }
  .value { font-size:30px; font-weight:700; margin:2px 0; }
  .unit { font-size:14px; font-weight:400; color:var(--muted); }
  .delta { font-size:14px; font-weight:600; }
  .delta.up { color:#c0392b; } .delta.down { color:#1e8449; }
  .sub { color:var(--muted); font-size:13px; }
  section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px 10px; margin-bottom:18px; }
  h2 { font-size:17px; margin:0 0 2px; }
  .note { color:var(--muted); font-size:13px; margin:0 0 8px; }
  footer { color:var(--muted); font-size:12.5px; margin-top:20px; }
</style></head>
<body><main>
  <h1>NZ Fuel Prices</h1>
  <p class="lead">Daily retail prices to __DAILY_END__ and weekly price breakdown to __WEEKLY_END__. All prices in NZD cents per litre.</p>
  <div class="cards">__CARDS__</div>

  <section><h2>Daily retail price, 2026</h2>
    <p class="note">Average retail price per fuel, from the daily monitoring file.</p>__C1__</section>

  <section><h2>Refined cost vs retail price, 2026</h2>
    <p class="note">The gap between the grey and coloured lines is what is added after refining. It narrows or inverts when costs spike.</p>__C2__</section>

  <section><h2>What is in the pump price (week of __WEEKLY_END__)</h2>
    <p class="note">Importer cost + importer margin + taxes + ETS + GST add up to the adjusted retail price.</p>__C3__</section>

  <section><h2>Retail price since 2004</h2>
    <p class="note">Weekly adjusted retail price.</p>__C4__</section>

  <section><h2>Crude oil and the exchange rate</h2>
    <p class="note">The two main drivers of importer cost.</p>__C5__</section>

  <footer>Weekly figures from __PROV_START__ onward are marked Provisional in the source data. Generated __TODAY__ by dashboard.py.</footer>
</main></body></html>
"""


def main():
    daily, weekly = load_daily(), load_weekly()
    c3, wk_end = chart_breakdown(weekly)
    prov = weekly[weekly.Status == "Provisional"].date.min()
    html = (TEMPLATE
            .replace("__DAILY_END__", f"{daily.date.max():%d %b %Y}")
            .replace("__WEEKLY_END__", f"{wk_end:%d %b %Y}")
            .replace("__PROV_START__", f"{prov:%d %b %Y}")
            .replace("__TODAY__", f"{date.today():%d %b %Y}")
            .replace("__CARDS__", kpi_cards(daily, weekly))
            .replace("__C1__", chart_daily_prices(daily))
            .replace("__C2__", chart_cost_vs_retail(daily))
            .replace("__C3__", c3)
            .replace("__C4__", chart_long_run(weekly))
            .replace("__C5__", chart_crude_fx(weekly)))
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
