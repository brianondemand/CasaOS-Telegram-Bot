# CasaOS Telegram Bot

A Telegram bot for monitoring and managing a CasaOS server running on Ubuntu 24.04 LTS.

## Features

| Command | Description |
|---|---|
| `/start`, `/help` | Show welcome message / command list |
| `/status` | CPU, RAM, disk, temperature, load average, uptime |
| `/diskusage` | Disk usage per mounted volume |
| `/processes` | Top 5 processes by CPU and by memory |
| `/network` | Local + public IP, bandwidth counters |
| `/containers` | List all Docker containers (CasaOS apps) with inline Start/Stop/Restart/Logs buttons |
| `/logs <name>` | Show recent logs for a container |
| `/update` | Run `apt-get update && apt-get upgrade -y` (with confirmation) |
| `/reboot` | Reboot the server (with confirmation) |
| `/shutdown` | Shut down the server (with confirmation) |

Only Telegram user IDs you explicitly whitelist can use the bot — everyone else gets a "not authorized" reply.

CasaOS apps are just Docker containers under the hood, so `/containers` gives you full control over everything CasaOS manages, without needing CasaOS's internal API.

## 1. Get a bot token

1. Message **@BotFather** on Telegram.
2. Send `/newbot` and follow the prompts.
3. Copy the token it gives you (looks like `123456789:AAExample...`).

## 2. Get your Telegram user ID

1. Message **@userinfobot** on Telegram.
2. It replies with your numeric user ID. Copy it.

This is your whitelist — only these IDs can control the bot.

## 3. Copy the bot files to your server

Copy this whole folder to your CasaOS server, e.g. `/home/<youruser>/casaos-bot/`.

## 4. Install dependencies

```bash
cd ~/casaos-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Give the bot Docker permissions

The bot controls containers via the Docker socket, so the user running it needs Docker group access:

```bash
sudo usermod -aG docker $USER
# then log out and back in (or reboot) for the group change to take effect
```

## 6. Allow passwordless reboot/shutdown/updates (least privilege)

Rather than running the bot as root, grant it just the specific commands it needs via `sudoers`:

```bash
sudo visudo -f /etc/sudoers.d/casaos-bot
```

Add (replace `youruser` with your actual username):

```
youruser ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown, /usr/bin/apt-get update, /usr/bin/apt-get upgrade -y
```

Save and exit. This lets the bot run *only* those exact commands without a password — nothing else.

## 7. Configure the bot

Set your token and user ID as environment variables (recommended), or edit `config.py` directly.

Quickest way to test manually:

```bash
export BOT_TOKEN="123456789:AAExampleTokenFromBotFather"
export AUTHORIZED_USERS="123456789"
python3 bot.py
```

Message your bot on Telegram — try `/start`.

## 8. Run it permanently as a systemd service

Edit `casaos-bot.service`:
- Replace `YOUR_LINUX_USERNAME` with your actual username (appears 3 times).
- Replace `PUT_YOUR_BOT_TOKEN_HERE` and `PUT_YOUR_TELEGRAM_USER_ID_HERE` with your real values.
- If you used a venv, change `ExecStart=` to point at `venv/bin/python3` instead of `/usr/bin/python3`.

Install it:

```bash
sudo cp casaos-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now casaos-bot
sudo systemctl status casaos-bot
```

View logs anytime with:

```bash
journalctl -u casaos-bot -f
```

## Security notes

- **Never share your bot token.** Anyone with it can control your server through this bot.
- The whitelist in `AUTHORIZED_USERS` is the only thing standing between "anyone on Telegram" and "full control of your server" — double check it's set before exposing the bot.
- The sudoers rule in step 6 is scoped to exactly 4 commands — avoid widening it (e.g. don't do `NOPASSWD: ALL`).
- Consider restricting who can even message the bot at the BotFather level isn't possible, so the in-code whitelist is your main defense — keep it tight.

## Extending it further

Ideas if you want to go further later:
- Direct CasaOS API integration (app store install/uninstall) via CasaOS's own REST API and a stored session token.
- Scheduled daily `/status` reports using `JobQueue` (built into `python-telegram-bot`).
- Alerting when CPU/RAM/disk crosses a threshold (a background job checking `psutil` and messaging you proactively).
- SMART disk health checks (`smartctl`) surfaced as a command.
