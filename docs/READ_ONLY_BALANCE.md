# Read-only Delta balance button

Telegram now exposes a compact `💰 Balance` button. It calls only `GET /v2/wallet/balances` using signed Delta India v2 authentication.

Render environment variables required:

- `DELTA_API_KEY`
- `DELTA_API_SECRET`

Use a read-only API key for balance access when possible. The module contains no order, leverage, modify, cancel, or square-off calls. Auto-trading remains disabled.
