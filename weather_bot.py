from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Final
from collections import defaultdict

import requests
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)
from zoneinfo import ZoneInfo

# ──────────────── CONFIG ────────────────
load_dotenv()

OWM_API_KEY: Final[str] = os.getenv("OWM_API_KEY", "")
# Берём токен из .env, иначе используем учебный токен по умолчанию
TELEGRAM_BOT_TOKEN: Final[str] = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Поддерживаем обе переменные: TELEGRAM_CHAT_IDS и старый TELEGRAM_CHAT_ID
chat_ids_env = os.getenv("TELEGRAM_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_ID") or ""
CHAT_IDS: Final[list[str]] = [cid.strip() for cid in chat_ids_env.split(",") if cid.strip()]

BAD_WORDS_FILE: Final[str] = os.getenv("BAD_WORDS_FILE", "bad_words.txt")

CITY_NAME: Final[str] = "Nizhny Novgorod"
TZ = ZoneInfo("Europe/Moscow")

if not OWM_API_KEY:
    raise SystemExit("⛔️ Укажите OWM_API_KEY в .env")
if not CHAT_IDS:
    raise SystemExit("⛔️ Укажите TELEGRAM_CHAT_IDS или TELEGRAM_CHAT_ID в .env")

# ──────────────── Мат‑фильтр ────────────────

def load_bad_regex() -> re.Pattern:
    path = Path(BAD_WORDS_FILE)
    if not path.is_file():
        path.write_text("# Добавьте нецензурные regex-паттерны, по одному в строке\n", encoding="utf-8")
        print(f"⚠️ Создан пустой {BAD_WORDS_FILE}. Добавьте слова и перезапустите бота.")
        return re.compile(r"$^")

    words = [ln.strip() for ln in path.read_text("utf-8").splitlines() if ln.strip() and not ln.startswith('#')]
    if not words:
        return re.compile(r"$^")
    combined = "|".join(fr"\b(?:{w})\b" for w in words)
    return re.compile(combined, re.IGNORECASE)

BAD_REGEX = load_bad_regex()

def censor(text: str) -> str:
    return BAD_REGEX.sub(lambda m: "*" * len(m.group(0)), text)

# ──────────────── Погода ────────────────

def fetch_weather() -> str:
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

    data = current.json()
    fdata = forecast.json()

    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    descr = data["weather"][0]["description"].capitalize()
    humidity = data["main"]["humidity"]
    wind = data["wind"]["speed"]
    sunrise = datetime.fromtimestamp(data["sys"]["sunrise"], tz=TZ).strftime("%H:%M")
    sunset = datetime.fromtimestamp(data["sys"]["sunset"], tz=TZ).strftime("%H:%M")
    today_fmt = datetime.now(tz=TZ).strftime("%Y-%m-%d")

    max_temp = max(
        f["main"]["temp_max"] for f in fdata["list"] if f["dt_txt"].startswith(today_fmt)
    )

    return (
        f"🌤 Погода в {CITY_NAME} на {datetime.now(tz=TZ).strftime('%d.%m.%Y')}:\n"
        f"Температура: {temp:.0f}°C (ощущается как {feels:.0f}°C)\n"
        f"{descr}. Влажность: {humidity}% | Ветер: {wind} м/с\n"
        f"🌡 Максимум днём: {max_temp:.0f}°C\n"
        f"🌅 Рассвет: {sunrise} | 🌇 Закат: {sunset}"
    )

# ──────────────── Модерация ────────────────

VIOLATIONS = defaultdict(int)
MAX_WARNINGS = 3

async def profanity_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg and msg.text and BAD_REGEX.search(msg.text):
        user_id = msg.from_user.id
        VIOLATIONS[user_id] += 1

        try:
            clean_text = censor(msg.text)
            await msg.delete()

            if VIOLATIONS[user_id] >= MAX_WARNINGS:
                await msg.chat.send_message(
                    text=f"🎁 {msg.from_user.first_name}, в честь ваших стараний — вам виртуальная розочка 🌹."
                )
                VIOLATIONS[user_id] = 0
            else:
                await msg.chat.send_message(
                    text=(
                        f"⚠️ {msg.from_user.first_name}, ваше сообщение нарушало правила и было удалено.\n"
                        f"Исправленный текст: {clean_text}\n"
                        f"Предупреждение {VIOLATIONS[user_id]} из {MAX_WARNINGS}"
                    )
                )
        except Exception as e:
            print(f"Ошибка при удалении сообщения или отправке предупреждения: {e}")

# ──────────────── Задачи ────────────────

async def weather_job(ctx: ContextTypes.DEFAULT_TYPE):
    text = fetch_weather()
    for chat_id in CHAT_IDS:
        await ctx.bot.send_message(chat_id=chat_id, text=text)

# ──────────────── Запуск ────────────────

def main() -> None:
    app: Application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, profanity_filter))

    job_queue = app.job_queue
    job_queue.run_daily(weather_job, time=dtime(hour=8, minute=0, tzinfo=TZ))
    job_queue.run_daily(weather_job, time=dtime(hour=14, minute=0, tzinfo=TZ))

    print("✅ Bot запущен (погода + фильтр мата). Нажмите Ctrl+C для остановки.")
    app.run_polling()

# ──────────────── Одноразовая отправка ────────────────

async def _send_once() -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    text = fetch_weather()
    for chat_id in CHAT_IDS:
        await bot.send_message(chat_id=chat_id, text=text)

if __name__ == "__main__":
    if "--once" in sys.argv:
        asyncio.run(_send_once())
        print("📨 Прогноз погоды успешно отправлен.")
    else:
        try:
            main()
        except (KeyboardInterrupt, SystemExit):
            print("🛑 Bot stopped.")
