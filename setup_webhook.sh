#!/bin/bash
# ─── Setup Telegram Webhook ──────────────────────────────────────────
# Jalankan sekali setelah deploy bot ke Railway/Render
# Usage: bash setup_webhook.sh

echo "=============================="
echo "  TELEGRAM WEBHOOK SETUP"
echo "=============================="
echo ""

read -p "Masukkan TELEGRAM_TOKEN kamu: " TOKEN
read -p "Masukkan URL server kamu (contoh: https://finance-bot.railway.app): " SERVER_URL

WEBHOOK_URL="${SERVER_URL}/webhook"

echo ""
echo "Mendaftarkan webhook: $WEBHOOK_URL"

RESPONSE=$(curl -s "https://api.telegram.org/bot${TOKEN}/setWebhook" \
  -d "url=${WEBHOOK_URL}" \
  -d "allowed_updates=[\"message\"]")

echo ""
echo "Response Telegram:"
echo $RESPONSE | python3 -m json.tool 2>/dev/null || echo $RESPONSE

echo ""
echo "────────────────────────────────────"
echo "Verifikasi webhook:"
curl -s "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python3 -m json.tool 2>/dev/null
