import os, json, time, requests
from datetime import datetime, timedelta, timezone

BASE_URL  = "https://api.india.delta.exchange"
SYMBOL    = "XAUTUSD"
RR        = 2.0
STOP_MODE = "fixed"      # "fixed" or "range"
SL_DIST   = 5.0
SESSIONS  = [("Tokyo", 5, 30), ("New York", 18, 30)]   # name, hour, minute in IST
HOURS_ACTIVE    = 8      # how long after the range candle to keep looking
MAX_AGE         = 1800   # ignore signals older than 30 minutes
MAX_PER_SESSION = 5      # max alerts per session
STATE_FILE = "state.json"
IST = timezone(timedelta(hours=5, minutes=30))

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT  = os.environ["TELEGRAM_CHAT_ID"]

def tg(text):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": text}, timeout=15)
    print("Telegram:", r.status_code)

try:
    with open(STATE_FILE) as f:
        sent = set(json.load(f).get("sent", []))
except Exception:
    sent = set()

if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
    tg("Test message: gold alert bot is connected")

now = time.time()
today = datetime.now(IST)

for name, h, m in SESSIONS:
    for back in (0, 1):
        day = today - timedelta(days=back)
        start = int(day.replace(hour=h, minute=m, second=0, microsecond=0).timestamp())
        if now < start + 300 or now > start + HOURS_ACTIVE * 3600:
            continue
        try:
            r = requests.get(f"{BASE_URL}/v2/history/candles",
                             params={"resolution": "5m", "symbol": SYMBOL,
                                     "start": start, "end": int(now)},
                             headers={"User-Agent": "python-bot"}, timeout=20)
            print(name, "candles status:", r.status_code)
            r.raise_for_status()
            candles = sorted(r.json().get("result", []), key=lambda c: c["time"])
        except Exception as e:
            print(name, "error:", e); continue

        if not candles or candles[0]["time"] != start:
            print(name, "range candle not available"); continue
        hi, lo = float(candles[0]["high"]), float(candles[0]["low"])

        prev, n = "inside", 0
        for c in candles[1:]:
            if c["time"] + 300 > now:
                break                                  # candle not closed yet
            close = float(c["close"])
            cur = "above" if close > hi else "below" if close < lo else "inside"
            if cur != "inside" and cur != prev:        # a new break
                n += 1
                sid = f"{name}-{start}-{c['time']}-{cur}"
                age = now - (c["time"] + 300)
                if sid not in sent and age <= MAX_AGE and n <= MAX_PER_SESSION:
                    side, label = ("BUY", "BREAKOUT") if cur == "above" else ("SELL", "BREAKDOWN")
                    risk = SL_DIST if STOP_MODE == "fixed" else abs(close - (lo if side == "BUY" else hi))
                    sl = close - risk if side == "BUY" else close + risk
                    tp = close + RR * risk if side == "BUY" else close - RR * risk
                    t = datetime.fromtimestamp(c["time"] + 300, IST).strftime("%H:%M")
                    tg(f"{name} session {label} #{n} ({side})\n{SYMBOL}\n"
                       f"Range H {hi} / L {lo}\nCandle closed {t} IST at {close}\n"
                       f"Entry ~{close:.2f}\nSL {sl:.2f}\nTP {tp:.2f} (1:{RR:g})")
                    sent.add(sid)
            prev = cur
        print(name, "checked, breaks found:", n)

with open(STATE_FILE, "w") as f:
    json.dump({"sent": sorted(sent)[-200:]}, f)
