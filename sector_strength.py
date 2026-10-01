"""Theme strength board: relative strength of market themes vs SPY.

For each theme in themes.json:
  theme %      = the theme ETF's % change today (or the average of its leader stocks when it has no ETF)
  RS vs SPY    = theme % - SPY % change today
  best name    = the leader stock with the biggest % change today (the ETF when a theme has no stocks)
  day          = consecutive sessions, including today, with RS >= LEAD_RS (stored in history.json)
  action       = BUY WINDOW  RS >= BUY_RS, day 1-2, and the best name is above today's open
                 LEADING     RS >= LEAD_RS
                 WEAK        RS <= WEAK_RS
                 QUIET       everything else

Data: Alpaca market data snapshots (real-time IEX feed) when ALPACA_KEY_ID / ALPACA_SECRET_KEY are set;
any symbol Alpaca can't price (or every symbol, without keys) falls back to the TradingView screener
(free, ~15 min delayed).
Outputs (next to this script): sector_data.json, summary.txt, dashboard.html
Usage: python3 sector_strength.py
"""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BUY_RS, LEAD_RS, WEAK_RS = 2.0, 1.0, -1.0
US_EXCHANGES = ["NASDAQ", "NYSE", "AMEX", "CBOE"]
HERE = os.path.dirname(os.path.abspath(__file__))


def scan(names):
    query = {
        "filter": [{"left": "name", "operation": "in_range", "right": sorted(names)},
                   {"left": "exchange", "operation": "in_range", "right": US_EXCHANGES}],
        "columns": ["name", "close", "change", "change_from_open", "description", "time"],
        "range": [0, 1000],
    }
    # curl instead of urllib: the python.org build on this Mac has no CA certificates installed
    out = subprocess.run(["curl", "-s", "-m", "60", "-X", "POST", "https://scanner.tradingview.com/america/scan",
                          "-H", "Content-Type: application/json", "-d", json.dumps(query)],
                         capture_output=True, text=True, check=True).stdout
    rows = {}
    for r in json.loads(out)["data"]:
        name, close, chg, chg_open, desc, t = r["d"]
        if chg is not None and name not in rows:
            rows[name] = dict(symbol=r["s"], close=close, chg=chg, chg_open=chg_open, desc=desc, time=t)
    return rows


def parse_ts(s):
    # Alpaca timestamps look like 2026-10-01T13:44:59.123456789Z
    return datetime.fromisoformat(s.rstrip("Z")[:26] + "+00:00")


def alpaca(names):
    key, secret = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        return {}
    url = "https://data.alpaca.markets/v2/stocks/snapshots?feed=iex&symbols=" + ",".join(sorted(names))
    res = subprocess.run(["curl", "-s", "-m", "60", url, "-H", f"APCA-API-KEY-ID: {key}",
                          "-H", f"APCA-API-SECRET-KEY: {secret}"], capture_output=True, text=True)
    try:
        snaps = json.loads(res.stdout)
    except json.JSONDecodeError:
        print("Alpaca: unreadable response, using TradingView")
        return {}
    if not isinstance(snaps, dict) or "message" in snaps:
        print("Alpaca error:", snaps.get("message") if isinstance(snaps, dict) else snaps)
        return {}
    rows = {}
    for sym, s in snaps.items():
        try:
            last, day, prev = s["latestTrade"], s["dailyBar"], s["prevDailyBar"]
            px = last["p"]
            rows[sym] = dict(symbol=sym, close=px, chg=(px / prev["c"] - 1) * 100,
                             chg_open=(px / day["o"] - 1) * 100, desc="",
                             time=parse_ts(day["t"]).timestamp(), trade_time=parse_ts(last["t"]).timestamp())
        except (KeyError, TypeError, ZeroDivisionError):
            continue
    return rows


cfg = json.load(open(os.path.join(HERE, "themes.json")))
bench = cfg["benchmark"]
wanted = {bench} | {t["etf"] for t in cfg["themes"] if t["etf"]} | {n for t in cfg["themes"] for n in t["names"]}
q = alpaca(wanted)
source = "alpaca" if bench in q else "tradingview"
if source == "tradingview":
    q = {}
missing = wanted - set(q)
if missing:
    for name, row in scan(missing).items():
        q[name] = row
    if source == "alpaca":
        print(f"Alpaca had no live price for {len(missing)} symbols; used TradingView for: {', '.join(sorted(missing))}")
print(f"Data source: {source} ({len(q)} of {len(wanted)} symbols priced)")
spy = q[bench]
ny = ZoneInfo("America/New_York")
session = datetime.fromtimestamp(spy["time"], timezone.utc).astimezone(ny).strftime("%Y-%m-%d")

hist_path = os.path.join(HERE, "history.json")
try:
    history = json.load(open(hist_path))
except (FileNotFoundError, json.JSONDecodeError):
    history = {}

themes = []
for t in cfg["themes"]:
    members = [dict(name=n, **q[n]) for n in t["names"] if n in q]
    etf = q.get(t["etf"]) if t["etf"] else None
    if etf:
        theme_chg = etf["chg"]
    elif members:
        theme_chg = sum(m["chg"] for m in members) / len(members)
    else:
        continue
    best = max(members, key=lambda m: m["chg"]) if members else dict(name=t["etf"], **etf)
    themes.append(dict(theme=t["theme"], etf=t["etf"], theme_chg=round(theme_chg, 2),
                       rs=round(theme_chg - spy["chg"], 2), best=best["name"], best_chg=round(best["chg"], 2),
                       best_above_open=(best.get("chg_open") or 0) > 0,
                       members=[dict(name=m["name"], chg=round(m["chg"], 2)) for m in
                                sorted(members, key=lambda m: -m["chg"])]))

# Day counter: consecutive stored sessions (today included) with RS >= LEAD_RS
history[session] = {t["theme"]: t["rs"] for t in themes}
history = dict(sorted(history.items())[-60:])
json.dump(history, open(hist_path, "w"), indent=1)
sessions = sorted(history, reverse=True)
for t in themes:
    day = 0
    for s in sessions:
        if history[s].get(t["theme"], -99) >= LEAD_RS:
            day += 1
        else:
            break
    t["day"] = day
    if t["rs"] >= BUY_RS and 1 <= day <= 2 and t["best_above_open"]:
        t["action"] = "BUY WINDOW"
    elif t["rs"] >= LEAD_RS:
        t["action"] = "LEADING"
    elif t["rs"] <= WEAK_RS:
        t["action"] = "WEAK"
    else:
        t["action"] = "QUIET"

themes.sort(key=lambda t: -t["rs"])
leading = sum(t["rs"] >= LEAD_RS for t in themes)
lagging = sum(t["rs"] <= WEAK_RS for t in themes)
now = datetime.now(ny)
close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
if source == "alpaca":
    # Real-time: the time of SPY's latest trade
    price_time = datetime.fromtimestamp(spy["trade_time"], timezone.utc).astimezone(ny)
else:
    # Screener prices are ~15 min delayed; after the 16:00 close they are the closing prices
    price_time = min(now - timedelta(minutes=15), close_time)
data = dict(session=session, generated=now.strftime("%Y-%m-%d %H:%M ET"), source=source,
            data_time=price_time.strftime("%H:%M ET") if price_time < close_time else "close",
            spy_chg=round(spy["chg"], 2), spy_close=spy["close"], leading=leading, lagging=lagging,
            rules=dict(buy=BUY_RS, lead=LEAD_RS, weak=WEAK_RS), themes=themes)
json.dump(data, open(os.path.join(HERE, "sector_data.json"), "w"), indent=1)

# Short summary for the phone notification
top = [t for t in themes if t["action"] in ("BUY WINDOW", "LEADING")][:3]
weak = [t for t in themes if t["action"] == "WEAK"][-3:]
summary = (f"Themes {session}: SPY {spy['chg']:+.2f}% | "
           + ("Leading: " + ", ".join(f"{t['theme'].title()} {t['rs']:+.1f}% ({t['best']})" for t in top) if top else "No leaders")
           + (" | Weak: " + ", ".join(t["theme"].title() for t in weak) if weak else ""))
buys = [t["theme"].title() for t in themes if t["action"] == "BUY WINDOW"]
if buys:
    summary = "BUY WINDOW: " + ", ".join(buys) + " | " + summary
open(os.path.join(HERE, "summary.txt"), "w").write(summary + "\n")

# Dashboard: inject the data into the page template
tpl = open(os.path.join(HERE, "dashboard_template.html")).read()
open(os.path.join(HERE, "dashboard.html"), "w").write(tpl.replace("/*__DATA__*/null", json.dumps(data)))

print(summary)
for t in themes:
    print(f"{t['theme']:15s} RS {t['rs']:+6.2f}%  theme {t['theme_chg']:+6.2f}%  best {t['best']:5s} {t['best_chg']:+6.2f}%  day {t['day']}  {t['action']}")
