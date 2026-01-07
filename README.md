# 3x-ui Shop Bot

Telegram bot for selling VPN keys (VLESS) from the 3x-ui panel.

## Features
- 🛒 Auto-sale of keys via YooMoney, YooKassa, UnitPay, FreeKassa, Enot.io
- 💰 Balance system, referral program, promo codes
- 📊 Admin panel (Web UI) for management
- 🌍 Support for multiple 3x-ui servers
- 🚀 Speed test display (from 3x-ui metrics)
- 📝 Technical support via forum topics

## Installation (Docker Compose) - Recommended

1. **Prerequisites**: Docker & Docker Compose installed.
2. **Clone repo**:
   ```bash
   git clone <repo_url>
   cd 3xui-shopbot-main
   ```
3. **Configure**:
   - Edit `docker-compose.yml` if needed (ports, volumes).
   - Ensure `nginx_vless.conf` has your domain `vless.24x7.hk`.

4. **Run**:
   ```bash
   docker compose up -d --build
   ```

5. **Access Admin Panel**:
   - Open `http://your-server-ip:1488` (or your domain if configured).
   - Default login/pass: `admin` / `admin`.

## Payment Setup (YooMoney)

1. **Register/Login** to [YooMoney](https://yoomoney.ru).
2. **Get Client ID (for OAuth - optional)**:
   - Only needed if you want automatic token issuing.
   - Redirect URI: `https://vless.24x7.hk/yoomoney/callback`
3. **HTTP Notifications (REQUIRED for auto-payments)**:
   - Go to YooMoney Settings -> HTTP Notifications.
   - URL: `https://vless.24x7.hk/yoomoney-webhook`
   - Secret: Copy the secret and paste it into Bot Admin Panel -> Settings -> Payment Systems -> YooMoney Secret.

## Troubleshooting

### "My Keys" Error
Fixed in latest version. Update `src/shop_bot/bot/handlers.py`.

### SSL Error (ERR_CERT_COMMON_NAME_INVALID)
Your server's SSL certificate does not match `vless.24x7.hk`.
- If using Nginx Proxy Manager, request a new Let's Encrypt cert for this specific domain.
- If using manual Certbot: `certbot --nginx -d vless.24x7.hk`.

### 404 Not Found on Webhook
- Ensure you deployed the latest code (check `src/shop_bot/webhook_server/app.py`).
- Use the correct URL: `/yoomoney-webhook` (NOT `/yoomoney/callback` for payments).

## Development (Local)

1. Create venv: `python -m venv .venv`
2. Activate: `.\.venv\Scripts\Activate` (Windows) or `source .venv/bin/activate` (Linux)
3. Install: `pip install -r requirements.txt`
4. Run: `python -m shop_bot`
