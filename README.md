# Captain Ryusuui - CasaOS Telegram Bot

> To also change the bot's actual display name/photo on Telegram itself, message **@BotFather** → `/setname` (and `/setuserpic` for an avatar) and select your bot. The code-side name is already set to "Captain Ryusuui" in the welcome message.

A Telegram bot for monitoring and managing a CasaOS server running on Ubuntu 24.04 LTS.

## Features

| Command           | Description                                                                                           |
| ----------------- | ----------------------------------------------------------------------------------------------------- |
| `/start`, `/help` | Show welcome message / command list                                                                   |
| `/status`         | CPU, RAM, disk, temperature, battery (if present), load average, uptime                               |
| `/diskusage`      | Disk usage per mounted volume                                                                         |
| `/processes`      | Top 5 processes by CPU and by memory                                                                  |
| `/network`        | Local + public IP, bandwidth counters                                                                 |
| `/containers`     | List all Docker containers (CasaOS apps) with inline Start/Stop/Restart buttons                       |
| `/ask <question>` | Ask your local Ollama model a question, right from Telegram (remembers context within a conversation) |
| `/model`          | Switch which Ollama model `/ask` uses                                                                 |
| `/clear`          | Clear the AI conversation history and start fresh                                                     |
| `/update`         | Run `apt-get update && apt-get upgrade -y` (with confirmation)                                        |
| `/reboot`         | Reboot the server (with confirmation)                                                                 |
| `/shutdown`       | Shut down the server (with confirmation)                                                              |

The bot also **proactively messages you** (no command needed) if CPU, RAM, disk, temperature, or battery crosses a threshold, or if a container stops unexpectedly - see "Proactive monitoring" below.

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

---

## Option A: Run with Docker (recommended)

This is the easiest way to run it on your CasaOS server and keeps everything self-contained.

### A.1. Create your `.env` file

```bash
cd ~/casaos-bot
cp .env.example .env
nano .env
```

Fill in your real `BOT_TOKEN` and `AUTHORIZED_USERS`, save, exit.

### A.2. Build and start the container

```bash
docker compose up -d --build
```

That's it. Check it's running and see logs:

```bash
docker compose logs -f
```

You should see `Bot starting (polling mode)...` and `Command menu registered with Telegram.`

### A.3. Why the container needs elevated privileges

Two things in `docker-compose.yml` need explaining, since they're more access than a typical container gets:

- **`/var/run/docker.sock` mount** — lets the bot talk to the host's Docker daemon so `/containers` can see and control your _other_ containers (your CasaOS apps), not just itself.
- **`privileged: true` + `pid: host`** — lets the bot use `nsenter` to "step into" the host's process namespace so `/reboot`, `/shutdown`, and `/update` actually affect the real server, not just the container (a container can't reboot its own host by default).

Together, these effectively give the bot root-level control over your server. That's the tradeoff for having a single containerized app do all of this. **This is exactly why the `AUTHORIZED_USERS` whitelist matters so much** — it's the only thing standing between "anyone on Telegram" and full server control. Double-check it's set correctly before leaving this running.

If you'd rather not grant this level of access, skip Docker and use **Option B** below — running directly on the host with a narrowly-scoped `sudoers` rule (just 4 specific commands) is more restrictive and arguably safer.

### A.4. Managing the container

```bash
docker compose stop          # stop it
docker compose start         # start it again
docker compose down          # stop and remove it
docker compose up -d --build # rebuild after editing bot.py
docker compose logs -f       # follow logs
```

It's already set to `restart: unless-stopped`, so it comes back automatically after a server reboot or crash.

---

## Option B: Run directly on the host (no Docker, more restrictive)

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

## 5b. Important: turn off container-mode power commands

`config.py` defaults to using `nsenter` for reboot/shutdown/update, which only works inside the Docker setup (Option A). Since you're running directly on the host here, disable it:

```bash
export USE_NSENTER=false
```

(Also add this line to your `casaos-bot.service` file in step 8, and to your shell profile / systemd `Environment=` line so it persists.)

## 6. Allow passwordless reboot/shutdown/updates (least privilege)

Rather than running the bot as root, grant it just the specific commands it needs via `sudoers`:

```bash
sudo visudo -f /etc/sudoers.d/casaos-bot
```

Add (replace `youruser` with your actual username):

```
youruser ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown, /usr/bin/apt-get update, /usr/bin/apt-get upgrade -y
```

Save and exit. This lets the bot run _only_ those exact commands without a password — nothing else.

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

## Local AI chat (Ollama)

The bot can talk to models you've already pulled with Ollama, directly from Telegram.

- `/ask <question>` - sends your question to the currently selected model and replies with the answer. Remembers the last several exchanges in that chat, so you can ask follow-up questions naturally (e.g. "what about the second one?").
- `/model` - shows buttons to switch between your downloaded models (defaults to `qwen2.5:3b` for speed). Switching models automatically clears history, since a new model can't make sense of another model's conversation.
- `/clear` - wipes the conversation history for the current chat without switching models. Useful when you want to start a fresh topic.

**Setup:**

1. Make sure Ollama is running on your CasaOS host (not inside this bot's container) and has at least one model pulled (`ollama pull qwen2.5:3b`).
2. If using Docker (Option A), `docker-compose.yml` already maps `host.docker.internal` to your real host via `extra_hosts`, so no changes are usually needed.
3. If running directly on the host (Option B), set `OLLAMA_HOST=http://localhost:11434` instead.
4. Add or remove models from the `AVAILABLE_MODELS` list in `config.py` to match what you've actually pulled - run `ollama list` on the host and copy the exact `NAME` column (name and tag must match exactly, e.g. `qwen3:8b` not `qwen3`).

**Note on the "Uncensored/Aggressive" model:** larger/uncensored models will be noticeably slower to respond. If you plan to use it regularly, increase `OLLAMA_TIMEOUT_SECONDS` in your `.env` so the bot doesn't give up waiting.

**Troubleshooting a 404 from Ollama:** this means Ollama responded, but didn't recognize the model name. Run `ollama list` on the host and confirm the name in `config.py`'s `AVAILABLE_MODELS` matches character-for-character, including the tag after the colon. If you're still stuck, test directly from inside the container:

```bash
docker exec -it casaos-bot curl http://host.docker.internal:11434/api/tags
```

This should list your models in JSON. If it fails to connect at all, the issue is network reachability (check `OLLAMA_HOST` and the `extra_hosts` mapping), not the model name.

## Proactive monitoring & alerts

The bot checks system health every `MONITOR_INTERVAL_SECONDS` (default: 5 minutes) and messages every authorized user automatically if:

- CPU usage crosses `CPU_ALERT_THRESHOLD` (default 90%)
- Memory usage crosses `MEM_ALERT_THRESHOLD` (default 90%)
- Disk usage on `/` crosses `DISK_ALERT_THRESHOLD` (default 90%)
- Temperature crosses `TEMP_ALERT_THRESHOLD_C` (default 80°C)
- Battery drops to or below `BATTERY_ALERT_THRESHOLD` (default 20%) while not plugged in - handy if this runs on a laptop-as-server or behind a UPS that exposes battery status
- Any container that was running unexpectedly stops

To avoid spam, each alert type has a cooldown (`ALERT_COOLDOWN_SECONDS`, default 30 minutes) - so a sustained high-CPU period notifies you once, not every 5 minutes.

Tune all of this in your `.env` file, or set `MONITOR_ENABLED=false` to turn it off entirely.

## Customizing the CasaOS tile

The dashboard tile's title and icon come from the `x-casaos` block near the bottom of `docker-compose.yml`, not from the container name. It's currently set to:

```yaml
x-casaos:
  icon: "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/2693.png"
  title:
    en_us: Ryusuui
```

**To use your own icon:** replace the `icon:` URL (in both the `labels:` and `x-casaos:` sections - keep them matching) with a link to any square PNG/SVG you have hosted somewhere reachable (GitHub raw link, Imgur, your own file server, etc.). CasaOS just needs a working image URL - it doesn't have to be an emoji.

**To change the title:** edit the `en_us:` value under `title:`.

**Applying changes:** because this changes container metadata, do a full recreate rather than just `up -d`:

```bash
docker compose down
docker compose up -d --build
```

Then refresh the CasaOS dashboard in your browser (a hard refresh / cache clear helps if the old icon still shows).

If CasaOS's built-in editor (the pencil/settings icon on the tile) still shows blank required fields and won't let you save, that's expected - it's designed for its own App Store format, not for editing a hand-written compose file's build config directly. Editing `docker-compose.yml` and recreating the container (as above) is the reliable way to change metadata for this app.

## Security notes

- **Never share your bot token.** Anyone with it can control your server through this bot.
- The whitelist in `AUTHORIZED_USERS` is the only thing standing between "anyone on Telegram" and "full control of your server" — double check it's set before exposing the bot.
- The sudoers rule in step 6 is scoped to exactly 4 commands — avoid widening it (e.g. don't do `NOPASSWD: ALL`).
- Consider restricting who can even message the bot at the BotFather level isn't possible, so the in-code whitelist is your main defense — keep it tight.

## Extending it further

Ideas if you want to go further later:

- Direct CasaOS API integration (app store install/uninstall) via CasaOS's own REST API and a stored session token.
- Scheduled daily `/status` digest (reusing the `JobQueue` already added for monitoring).
- SMART disk health checks (`smartctl`) surfaced as a command.
- Pagination for `/containers` if you end up with many CasaOS apps installed.
- Natural-language command routing - use Ollama to interpret free-text like "restart the plex container" into the right bot action.
- Audit log of every command run, saved to a file, for accountability.
