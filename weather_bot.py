#!/usr/bin/env python
"""
Telegram-бот «Погода».
• 07:00 и 17:00 — текущая погода
• 21:00 — прогноз на завтра
• поддержка нескольких chat-id и (опц.) мат-фильтр
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Final

import requests
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ─── Загрузка переменных окружения ────────────────────────────────────────────
load_dotenv()

# обрезаем CR/LF и пробелы
OWM_API_KEY: Final[str] = (os.getenv("OWM_API_KEY") or "").strip()
TG_TOKEN:    Final[str] = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

# chat-id через запятую; отрезаем комментарии и пробелы
_raw_chat = os.getenv("TELEGRAM_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_ID") or ""
CHAT_IDS: Final[list[int]] = [
    int(part.split("#", 1)[0].strip())
    for part in _raw_chat.split(",")
    if part.split("#", 1)[0].strip()
]

CITY_NAME: Final[str] = (
    (os.getenv("CITY_NAME") or "Nizhny Novgorod").split("#", 1)[0].strip()
)

# часовой пояс
raw_tz = (os.getenv("TZ") or "Europe/Moscow").strip()
try:
    TZ = ZoneInfo(raw_tz)
except ZoneInfoNotFoundError:
    import tzdata  # noqa: F401

    TZ = ZoneInfo(raw_tz)

# (опц.) мат-фильтр
ENABLE_PROFANITY = os.getenv("ENABLE_PROFANITY_FILTER", "false").lower().startswith("t")
BAD_WORDS_FILE = os.getenv("BAD_WORDS_FILE", "bad_words.txt")

if not OWM_API_KEY:
    raise SystemExit("⛔️ В .env нет OWM_API_KEY")
if not TG_TOKEN:
    raise SystemExit("⛔️ В .env нет TELEGRAM_BOT_TOKEN")
if not CHAT_IDS:
    raise SystemExit("⛔️ В .env нет TELEGRAM_CHAT_ID(S)")

# ─── Мат-фильтр ───────────────────────────────────────────────────────────────
if ENABLE_PROFANITY:
    def _load_bad_regex() -> re.Pattern:
        path = Path(BAD_WORDS_FILE)
        if not path.is_file():
            return re.compile(r"$^")
        words = [
            w.strip()
            for w in path.read_text("utf-8").splitlines()
            if w.strip() and not w.startswith("#")
        ]
        return re.compile("|".join(fr"\b(?:{w})\b" for w in words), re.IGNORECASE)

    BAD_RGX = _load_bad_regex()
    VIOL: dict[int, int] = defaultdict(int)
    MAX_WARN = 3

    async def profanity(update, ctx):
        msg = update.message
        if msg and msg.text and BAD_RGX.search(msg.text):
            uid = msg.from_user.id
            VIOL[uid] += 1
            await msg.delete()
            warn = f"⚠️ {msg.from_user.first_name}, без мата!"
            if VIOL[uid] >= MAX_WARN:
                warn += " (мут 1 ч)"
                await msg.chat.restrict_member(
                    uid, until_date=datetime.now().timestamp() + 3600
                )
            await msg.chat.send_message(warn)
else:
    profanity = None  # заглушка

# ─── Вспомогательные функции ─────────────────────────────────────────────────
CARD = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def _wdir(deg: float | None) -> str:
    return "" if deg is None else CARD[round(deg / 45) % 8]


def _ico(desc: str) -> str:
    d = desc.lower()
    return (
        "☀️" if "ясно" in d
        else "⛅" if "облачно" in d
        else "☁️" if "пасмурно" in d
        else "🌧️" if "дожд" in d
        else "⛈️" if "гроза" in d
        else "❄️" if "снег" in d
        else "🌫️" if ("туман" in d or "дымка" in d)
        else "🌡️"
    )


def _get_json(url: str, params: dict) -> dict:
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        js = r.json()
        if str(js.get("cod")) != "200":
            raise ValueError(js.get("message", f"bad code={js.get('cod')}"))
        return js
    except Exception as exc:
        print(f"[weather] API error: {exc}", file=sys.stderr)
        return {}


# ─── Основная логика погоды ───────────────────────────────────────────────────
def fetch_weather() -> str:
    now = datetime.now(tz=TZ)

    cur = _get_json(
        "https://api.openweathermap.org/data/2.5/weather",
        dict(q=CITY_NAME, appid=OWM_API_KEY, units="metric", lang="ru"),
    )
    fc = _get_json(
        "https://api.openweathermap.org/data/2.5/forecast",
        dict(q=CITY_NAME, appid=OWM_API_KEY, units="metric", lang="ru"),
    )

    if not cur or not fc:
        return "⚠️ Не удалось получить данные погоды. Попробуйте позже."

    try:
        temp, feels = cur["main"]["temp"], cur["main"]["feels_like"]
        desc_raw = cur["weather"][0]["description"]
        descr = f"{_ico(desc_raw)} {desc_raw.capitalize()}"
        hum = cur["main"]["humidity"]

        wind = cur["wind"]["speed"]
        wdeg = cur["wind"].get("deg")
        wgust = cur["wind"].get("gust")
        wind_line = f"🌬️ Ветер: {wind:.0f} м/с {_wdir(wdeg)}" + (
            f", порывы до {wgust:.0f} м/с" if wgust else ""
        )

        sunrise = datetime.fromtimestamp(cur["sys"]["sunrise"], TZ).strftime("%H:%M")
        sunset = datetime.fromtimestamp(cur["sys"]["sunset"], TZ).strftime("%H:%M")

        today = now.strftime("%Y-%m-%d")
        today_points = [p for p in fc["list"] if p["dt_txt"].startswith(today)]
        max_temp = max(p["main"]["temp_max"] for p in today_points)
        gusts = [p["wind"].get("gust", 0) for p in today_points]
        max_gust_line = f"💨 Макс. порывы: до {max(gusts):.0f} м/с" if gusts else ""

        max_temp_line = (
            f"🌡 Максимум днём: {max_temp:.0f}°C\n" if now.hour < 14 else ""
        )

        # прогноз на завтра (21 ± 1 ч)
        fc_block = ""
        if (now.hour > 20) or (now.hour == 20 and now.minute >= 0):
            tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            slots = {"🌅 Утро": "06", "🌞 День": "12", "🌆 Вечер": "18", "🌙 Ночь": "21"}
            lines = []
            for lbl, h in slots.items():
                p = next(
                    (i for i in fc["list"] if i["dt_txt"] == f"{tomorrow} {h}:00:00"),
                    None,
                )
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

    except (KeyError, IndexError, TypeError) as exc:
        print(f"[weather] parse error: {exc}", file=sys.stderr)
        return "⚠️ Не удалось разобрать ответ погоды. Попробуйте позже."


# ─── Job-функция для JobQueue ─────────────────────────────────────────────────
async def send_weather(ctx: ContextTypes.DEFAULT_TYPE):
    text = fetch_weather()
    for cid in CHAT_IDS:
        await ctx.bot.send_message(cid, text, parse_mode="Markdown")


# ─── Запуск бота ──────────────────────────────────────────────────────────────
def main() -> None:
    app: Application = ApplicationBuilder().token(TG_TOKEN).build()

    if ENABLE_PROFANITY:
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, profanity))

    jq = app.job_queue
    jq.run_daily(send_weather, dtime(7, 0, tzinfo=TZ))
    jq.run_daily(send_weather, dtime(17, 0, tzinfo=TZ))
    jq.run_daily(send_weather, dtime(21, 0, tzinfo=TZ))

    print("✅ Бот запущен. Ctrl+C для выхода.")
    app.run_polling()


async def _once() -> None:
    bot = Bot(TG_TOKEN)
    txt = fetch_weather()
    for cid in CHAT_IDS:
        await bot.send_message(cid, txt, parse_mode="Markdown")
    print("📨 Прогноз отправлен.")


if __name__ == "__main__":
    if "--once" in sys.argv:
        asyncio.run(_once())
    else:
        main()
