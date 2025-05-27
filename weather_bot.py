from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, time as dtime
from typing import Final

import requests
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, ApplicationBuilder, ContextTypes
from zoneinfo import ZoneInfo

# ──────────────── CONFIG ────────────────
load_dotenv()

OWM_API_KEY: Final[str] = os.getenv("OWM_API_KEY", "")
TELEGRAM_BOT_TOKEN: Final[str] = os.getenv("TELEGRAM_BOT_TOKEN", "")
chat_ids_env = os.getenv("TELEGRAM_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_ID") or ""
CHAT_IDS: Final[list[str]] = [cid.strip() for cid in chat_ids_env.split(",") if cid.strip()]

CITY_NAME: Final[str] = "Nizhny Novgorod"
TZ = ZoneInfo("Europe/Moscow")

# Включить мат‑фильтр? True / False
ENABLE_PROFANITY_FILTER = False  # измените на True, если нужно
BAD_WORDS_FILE: Final[str] = os.getenv("BAD_WORDS_FILE", "bad_words.txt")

if not OWM_API_KEY:
    raise SystemExit("⛔️ Укажите OWM_API_KEY в .env")
if not CHAT_IDS:
    raise SystemExit("⛔️ Укажите TELEGRAM_CHAT_IDS или TELEGRAM_CHAT_ID в .env")

# ──────────────── (Опционально) Мат‑фильтр ────────────────
if ENABLE_PROFANITY_FILTER:
    import re
    from collections import defaultdict
    from pathlib import Path
    from telegram.ext import MessageHandler, filters

    def load_bad_regex() -> re.Pattern:
        path = Path(BAD_WORDS_FILE)
        if not path.is_file():
            return re.compile(r"$^")
        words = [ln.strip() for ln in path.read_text("utf-8").splitlines() if ln.strip() and not ln.startswith('#')]
        return re.compile("|".join(fr"\\b(?:{w})\\b" for w in words), re.IGNORECASE)

    BAD_REGEX = load_bad_regex()
    VIOLATIONS = defaultdict(int)
    MAX_WARNINGS = 3

    async def profanity_filter(update, ctx):
        msg = update.message
        if msg and msg.text and BAD_REGEX.search(msg.text):
            user_id = msg.from_user.id
            VIOLATIONS[user_id] += 1
            await msg.delete()
            await msg.chat.send_message(text=f"⚠️ {msg.from_user.first_name}, без мата!")
else:
    # заглушка, чтобы код ниже не ломался
    profanity_filter = None

# ──────────────── Погода ────────────────

from datetime import datetime
import requests

# Предполагается, что переменные CITY_NAME, OWM_API_KEY и TZ определяются во внешнем контексте

CARDINAL = ['С', 'СВ', 'В', 'ЮВ', 'Ю', 'ЮЗ', 'З', 'СЗ']

def wind_direction(deg: float) -> str:
    """Преобразует направление ветра в градусах (0–360) в одну из 8 румб."""
    if deg is None:
        return ""
    idx = round(deg / 45) % 8
    return CARDINAL[idx]


def fetch_weather() -> str:
    """Возвращает строку‑сводку о текущей погоде и прогнозе на день (RU)."""
    current = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"q": CITY_NAME, "appid": OWM_API_KEY, "units": "metric", "lang": "ru"},
        timeout=10,
    )
    forecast = requests.get(
        "https://api.openweathermap.org/data/2.5/forecast",
        params={"q": CITY_NAME, "appid": OWM_API_KEY, "units": "metric", "lang": "ru"},
        timeout=10,
    )
    current.raise_for_status()
    forecast.raise_for_status()
    data, fdata = current.json(), forecast.json()

    # Текущие параметры
    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    descr = data["weather"][0]["description"].capitalize()
    humidity = data["main"]["humidity"]
    wind = data["wind"]["speed"]
    wind_deg = data["wind"].get("deg")
    wind_gust = data["wind"].get("gust")  # может отсутствовать

    # Время рассвета/заката
    sunrise = datetime.fromtimestamp(data["sys"]["sunrise"], tz=TZ).strftime("%H:%M")
    sunset = datetime.fromtimestamp(data["sys"]["sunset"], tz=TZ).strftime("%H:%M")

    # Дата ISO для сегодняшнего дня в TZ
    day_iso = datetime.now(tz=TZ).strftime("%Y-%m-%d")

    # Максимум температуры за день
    max_temp = max(f["main"]["temp_max"] for f in fdata["list"] if f["dt_txt"].startswith(day_iso))

    # Максимальные порывы ветра по прогнозу на день
    gusts_today = [f["wind"].get("gust", 0) for f in fdata["list"] if f["dt_txt"].startswith(day_iso)]
    max_gust = max(gusts_today) if gusts_today else None

    # Формируем строку про ветер
    dir_str = wind_direction(wind_deg)
    gust_str_current = f", порывы до {wind_gust:.0f} м/с" if wind_gust else ""
    wind_info = f"Ветер: {wind:.0f} м/с {dir_str}{gust_str_current}"

    # Строка про максимальные порывы
    gust_max_line = f"💨 Максимальные порывы сегодня: до {max_gust:.0f} м/с" if max_gust else ""

    # Отключаем строку про максимум температуры, если сейчас 14:00
    is_two_pm = datetime.now(tz=TZ).hour == 14
    max_temp_line = "" if is_two_pm else f"🌡 Максимум днём: {max_temp:.0f}°C\n"

    return (
        f"🌤 Погода в {CITY_NAME} на {datetime.now(tz=TZ).strftime('%d.%m.%Y')}:\n"
        f"Температура: {temp:.0f}°C (ощущается как {feels:.0f}°C)\n"
        f"{descr}. Влажность: {humidity}% | {wind_info}\n"
        f"{gust_max_line}\n"
        f"{max_temp_line}"
        f"🌅 Рассвет: {sunrise} | 🌇 Закат: {sunset}"
    )


# ──────────────── Задача отправки ────────────────

async def weather_job(ctx: ContextTypes.DEFAULT_TYPE):
    text = fetch_weather()
    for cid in CHAT_IDS:
        await ctx.bot.send_message(chat_id=cid, text=text)

# ──────────────── Запуск ────────────────

def main() -> None:
    app: Application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    if ENABLE_PROFANITY_FILTER:
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, profanity_filter))

    job_queue = app.job_queue
    job_queue.run_daily(weather_job, time=dtime(hour=7,  tzinfo=TZ))  # 07:00
    job_queue.run_daily(weather_job, time=dtime(hour=17, tzinfo=TZ))  # 17:00

    print("✅ Bot запущен (погода)" + (" + мат-фильтр" if ENABLE_PROFANITY_FILTER else "") + ". Ctrl+C для остановки.")
    app.run_polling()

async def _once() -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    text = fetch_weather()
    for cid in CHAT_IDS:
        await bot.send_message(chat_id=cid, text=text)

if __name__ == "__main__":
    if "--once" in sys.argv:
        asyncio.run(_once()); print("📨 Прогноз отправлен.")
    else:
        main()
