# 🌤 Telegram Weather Bot

Бот присылает актуальную погоду из OpenWeather и краткий прогноз на завтра.  
Рассылает сообщения **два раза в день** — в 07:00 и 17:00, а вечером в 21:00 публикует прогноз на следующий день.  
Работает в любом чате / группе, поддерживает несколько chat-id и (опционально) мат-фильтр.

---

## ⚙ Возможности

| Функция | Описание |
|---------|----------|
| Текущая погода | температура «как ощущается», влажность, ветер, порывы, восход / закат |
| Эмодзи-иконки  | ☀️ ясно, 🌧️ дождь, 🌬️ ветер, 💧 влажность и др. |
| Прогноз на завтра | утром / днём / вечером / ночью (показывается в 21 ч) |
| Планировщик `job_queue` | ежедневные рассылки 07 – 17 – 21 |
| Одноразовая отправка | `python tgbot_weather.py --once` |
| Поддержка нескольких чатов | переменная `TELEGRAM_CHAT_IDS=-100..,123456...` |
| Мат-фильтр (опция) | удаляет сообщения с нецензурой и выдаёт предупреждения |

---

## 🏃‍♂️ Быстрый старт

```bash
git clone https://github.com/your-name/weather-bot.git
cd weather-bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt        # python-telegram-bot, python-dotenv, requests, pytz
cp .env.example .env                   # и заполните токены
python tgbot_weather.py                # запуск


sudo systemctl daemon-reload

sudo systemctl restart weatherbot

systemctl status weatherbot         # должно быть active (running)

journalctl -u weatherbot -f         # «хвост» лога
