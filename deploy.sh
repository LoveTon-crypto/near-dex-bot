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
cat > /usr/local/bin/nearbot-fastnear-key <<'KEY'
#!/bin/bash
# Сохранить API-ключ FastNEAR (для связей в bubble map) в .env и перезапустить бота
read -rp "Вставьте API-ключ FastNEAR и нажмите Enter: " K
K=$(echo "$K" | tr -d '[:space:]')
[ -z "$K" ] && { echo "Ключ пустой, ничего не изменено."; exit 1; }
cd /opt/near-dex-bot
grep -v '^FASTNEAR_API_KEY=' .env > .env.tmp || true
echo "FASTNEAR_API_KEY=$K" >> .env.tmp
mv .env.tmp .env && chmod 600 .env
systemctl restart nearbot && sleep 5
systemctl is-active --quiet nearbot && echo "✅ Ключ сохранён, бот перезапущен." || journalctl -u nearbot -n 20 --no-pager
KEY
chmod +x /usr/local/bin/nearbot-fastnear-key
echo ">>> Перезапускаю бота..."
systemctl restart nearbot
sleep 8
if systemctl is-active --quiet nearbot; then
  echo "✅ Бот обновлён и работает. Версия: $(git log -1 --format='%h — %s')"
else
  echo "❌ Бот не запустился, последние строки лога:"
  journalctl -u nearbot -n 25 --no-pager
fi
