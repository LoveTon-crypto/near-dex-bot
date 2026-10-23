#!/bin/bash
# Запускается на сервере после скачивания новой версии (командой nearbot-update).
set -e
cd /opt/near-dex-bot
echo ">>> Обновляю библиотеки..."
venv/bin/pip install -q -r requirements.txt
cat > /usr/local/bin/nearbot-update <<'UPD'
#!/bin/bash
# Скачать свежую версию бота с GitHub и перезапустить его
set -e
cd /opt/near-dex-bot
git fetch -q origin main
git reset -q --hard origin/main
exec bash deploy.sh
UPD
chmod +x /usr/local/bin/nearbot-update
echo ">>> Перезапускаю бота..."
systemctl restart nearbot
sleep 8
if systemctl is-active --quiet nearbot; then
  echo "✅ Бот обновлён и работает. Версия: $(git log -1 --format='%h — %s')"
else
  echo "❌ Бот не запустился, последние строки лога:"
  journalctl -u nearbot -n 25 --no-pager
fi
