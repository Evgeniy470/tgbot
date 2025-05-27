# tgbot_weather.py
from __future__ import annotations

import asyncio, os, sys, re, requests, pytz
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Final

from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    MessageHandler, filters,
)
from zoneinfo import ZoneInfo

# ─────────── CONFIG ───────────
load_dotenv()

OWM_API_KEY : Final[str] = os.getenv("OWM_API_KEY", "")
TG_TOKEN    : Final[str] = os.getenv("TELEGRAM_BOT_TOKEN", "")
CITY_NAME   : Final[str] = os.getenv("CITY_NAME", "Nizhny Novgorod")
TZ          = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))

chat_ids = os.getenv("TELEGRAM_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_ID") or ""
CHAT_IDS : Final[list[int]] = [int(cid.strip()) for cid in chat_ids.split(",") if cid.strip()]

ENABLE_PROFANITY = os.getenv("ENABLE_PROFANITY_FILTER", "false").lower() == "true"
BAD_WORDS_FILE   = os.getenv("BAD_WORDS_FILE", "bad_words.txt")

if not OWM_API_KEY:
    raise SystemExit("⛔️  Укажите OWM_API_KEY в .env")
if not TG_TOKEN:
    raise SystemExit("⛔️  Укажите TELEGRAM_BOT_TOKEN в .env")
if not CHAT_IDS:
    raise SystemExit("⛔️  Укажите TELEGRAM_CHAT_ID(S) в .env")

# ─────────── мат-фильтр (опц.) ───────────
if ENABLE_PROFANITY:
    def _load_regex() -> re.Pattern:
        p = Path(BAD_WORDS_FILE)
        if not p.is_file():                       # нет файла — нет фильтра
            return re.compile(r"$^")
        words = [w.strip() for w in p.read_text("utf-8").splitlines()
                 if w and not w.startswith("#")]
        return re.compile("|".join(fr"\b(?:{w})\b" for w in words), re.IGNORECASE)

    BAD_RGX  = _load_regex()
    VIOL     = defaultdict(int)
    WARN_MAX = 3

    async def profanity(update, ctx):
        m = update.message
        if m and m.text and BAD_RGX.search(m.text):
            uid = m.from_user.id
            VIOL[uid] += 1
            await m.delete()
            warn = f"⚠️ {m.from_user.first_name}, без мата!"
            if VIOL[uid] >= WARN_MAX:
                warn += " (мут 1 ч)"
                await m.chat.restrict_member(uid, until_date=datetime.now().timestamp()+3600)
            await m.chat.send_message(warn)
else:
    profanity = None   # заглушка

# ─────────── Погода ───────────
CARD = ['С','СВ','В','ЮВ','Ю','ЮЗ','З','СЗ']
def _wdir(deg: float|None) -> str:
    return "" if deg is None else CARD[round(deg/45)%8]

def _ico(desc: str) -> str:
    d = desc.lower()
    return ("☀️" if "ясно"     in d else
            "⛅" if "облачно"   in d else
            "☁️" if "пасмурно" in d else
            "🌧️" if "дожд"     in d else
            "⛈️" if "гроза"    in d else
            "❄️" if "снег"     in d else
            "🌫️" if "туман" in d or "дымка" in d else
            "🌡️")

def fetch_weather() -> str:
    now = datetime.now(tz=TZ)

    cur = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"q": CITY_NAME, "appid": OWM_API_KEY,
                "units": "metric", "lang": "ru"},
        timeout=10,
    ).json()
    fc  = requests.get(
        "https://api.openweathermap.org/data/2.5/forecast",
        params={"q": CITY_NAME, "appid": OWM_API_KEY,
                "units": "metric", "lang": "ru"},
        timeout=10,
    ).json()

    temp, feels = cur["main"]["temp"], cur["main"]["feels_like"]
    desc_raw = cur["weather"][0]["description"]
    descr    = f"{_ico(desc_raw)} {desc_raw.capitalize()}"
    hum = cur["main"]["humidity"]

    wind      = cur["wind"]["speed"]
    wdeg      = cur["wind"].get("deg")
    wgust     = cur["wind"].get("gust")
    wind_line = f"🌬️ Ветер: {wind:.0f} м/с {_wdir(wdeg)}" + (f", порывы до {wgust:.0f} м/с" if wgust else "")

    sunrise = datetime.fromtimestamp(cur["sys"]["sunrise"], TZ).strftime("%H:%M")
    sunset  = datetime.fromtimestamp(cur["sys"]["sunset"], TZ).strftime("%H:%M")

    today = now.strftime("%Y-%m-%d")
    max_temp = max(p["main"]["temp_max"] for p in fc["list"] if p["dt_txt"].startswith(today))
    gusts = [p["wind"].get("gust",0) for p in fc["list"] if p["dt_txt"].startswith(today)]
    max_gust_line = (f"💨 Максимальные порывы сегодня: до {max(gusts):.0f} м/с"
                     if gusts else "")

    # 🌡 Максимум днём — показывать только до 14:00
    max_temp_line = (f"🌡 Максимум днём: {max_temp:.0f}°C\n"
                     if now.hour < 14 else "")

    # Прогноз на завтра (добавляется в 21:00 ±1 ч)
    fc_block = ""
    if 20 <= now.hour <= 22:
        tomorrow = (now+timedelta(days=1)).strftime("%Y-%m-%d")
        slots = {"🌅 Утро":"06","🌞 День":"12","🌆 Вечер":"18","🌙 Ночь":"21"}
        lines=[]
        for lbl,h in slots.items():
            p = next((i for i in fc["list"] if i["dt_txt"]==f"{tomorrow} {h}:00:00"),None)
            if p:
                t = p["main"]["temp"]
                d = p["weather"][0]["description"]
                lines.append(f"{lbl}: {t:.0f}°C, {_ico(d)} {d.capitalize()}")
        if lines:
            fc_block = "\n\n📅 *Прогноз на завтра:*\n" + "\n".join(lines)

    return (
        f"🌤 *Погода в {CITY_NAME} на {now:%d.%m.%Y}:*\n"
        f"🌡 Температура: {temp:.0f}°C _(ощущается {feels:.0f}°C)_\n"
        f"{max_temp_line}"
        f"{descr}\n"
        f"💧 Влажность: {hum}%\n"
        f"{wind_line}\n"
        f"{max_gust_line}\n"
        f"🌅 Рассвет: {sunrise} | 🌇 Закат: {sunset}"
        f"{fc_block}"
    )

# ─────────── Рассылка ───────────
async def send_weather(ctx: ContextTypes.DEFAULT_TYPE):
    text = fetch_weather()
    for cid in CHAT_IDS:
        await ctx.bot.send_message(cid, text, parse_mode="Markdown")

# ─────────── Запуск ───────────
def main() -> None:
    app: Application = ApplicationBuilder().token(TG_TOKEN).build()
    if ENABLE_PROFANITY:
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, profanity))
    jq = app.job_queue
    jq.run_daily(send_weather, dtime(7,  0, tzinfo=TZ))
    jq.run_daily(send_weather, dtime(17, 0, tzinfo=TZ))
    jq.run_daily(send_weather, dtime(21, 0, tzinfo=TZ))

    print("✅ Бот запущен. Ctrl+C для выхода.")
    app.run_polling()

async def _once() -> None:
    bot = Bot(TG_TOKEN)
    txt = fetch_weather()
    for cid in CHAT_IDS:
        await bot.send_message(cid, txt, parse_mode="Markdown")
    print("📨  Прогноз отправлен.")

if __name__ == "__main__":
    if "--once" in sys.argv:
        asyncio.run(_once())
    else:
        main()
