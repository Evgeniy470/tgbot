pip install -r requirements.txt

Добавил ENABLE_PROFANITY_FILTER = False   # ← поставить True, чтобы включить

# 1. Пересоздать окружение (под тем же пользователем, что указан в сервисе)
cd ~/tgbot
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt     # или ручной список

# 2. Проверь вручную, что бот стартует
python weather_bot.py --once        # без sudo

# 3. Исправь/проверь сервис
sudo nano /etc/systemd/system/weatherbot.service
# должно быть:
# User=student
# ExecStart=/home/student/tgbot/venv/bin/python /home/student/tgbot/weather_bot.py

# 4. Перезагрузить конфигурацию и запустить
sudo systemctl daemon-reload
sudo systemctl restart weatherbot
systemctl status weatherbot         # должно быть active (running)
journalctl -u weatherbot -f         # «хвост» лога
