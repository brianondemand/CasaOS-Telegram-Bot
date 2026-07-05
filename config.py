"""
Configuration for the CasaOS Telegram Bot.

Set these via environment variables (recommended, see .env.example / the
systemd unit file), or just hardcode them here for a quick test.
"""

import os

# Token you get from @BotFather on Telegram
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")

# Comma-separated list of Telegram numeric user IDs allowed to use the bot.
# Get your ID by messaging @userinfobot on Telegram.
# Example: AUTHORIZED_USERS=123456789,987654321
AUTHORIZED_USERS = [
    int(uid) for uid in os.environ.get("AUTHORIZED_USERS", "").split(",") if uid.strip()
]

# How many lines of container logs to show by default
LOG_TAIL_LINES = int(os.environ.get("LOG_TAIL_LINES", "30"))

# Commands used for power actions - must match sudoers config, see README.md
REBOOT_CMD = ["sudo", "/sbin/reboot"]
SHUTDOWN_CMD = ["sudo", "/sbin/shutdown", "-h", "now"]
APT_UPDATE_CMD = ["sudo", "/usr/bin/apt-get", "update"]
APT_UPGRADE_CMD = ["sudo", "/usr/bin/apt-get", "upgrade", "-y"]
