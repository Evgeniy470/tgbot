import os
from aiogram import Bot, Dispatcher, executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from weather import fetch_weather  # это твоя функция

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("ID"))  # chat_id, куда отправлять погоду

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

scheduler = AsyncIOScheduler()

# ===== ЗАДАЧИ =====

async def send_morning_weather():
    text = fetch_weather()
    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")

async def send_evening_weather():
    text = fetch_weather()
    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")

# ===== ПЛАНИРОВАНИЕ =====

scheduler.add_job(send_morning_weather, 'cron', hour=7, minute=0)
scheduler.add_job(send_evening_weather, 'cron', hour=17, minute=0)
scheduler.add_job(send_evening_weather, 'cron', hour=21, minute=0)

# (fetch_weather сам покажет прогноз на завтра в 21:00)

scheduler.start()

# ===== СТАРТ БОТА =====

if __name__ == "__main__":
    executor.start_polling(dp)
