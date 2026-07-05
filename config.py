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

# Commands used for power actions.
#
# RUNNING DIRECTLY ON THE HOST (not in Docker): use these, and see the
# sudoers setup in README.md.
#   REBOOT_CMD      = ["sudo", "/sbin/reboot"]
#   SHUTDOWN_CMD    = ["sudo", "/sbin/shutdown", "-h", "now"]
#   APT_UPDATE_CMD  = ["sudo", "/usr/bin/apt-get", "update"]
#   APT_UPGRADE_CMD = ["sudo", "/usr/bin/apt-get", "upgrade", "-y"]
#
# RUNNING INSIDE THE DOCKER CONTAINER (default below): a container can't
# reboot its host directly. Instead we use `nsenter` to "step into" the
# host's process namespace (PID 1) and run the command there. This only
# works if the container is started with --privileged and --pid=host
# (already set in docker-compose.yml). See README.md "Docker" section.
USE_NSENTER = os.environ.get("USE_NSENTER", "true").lower() == "true"

if USE_NSENTER:
    _NSENTER_PREFIX = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "--"]
    REBOOT_CMD = _NSENTER_PREFIX + ["reboot"]
    SHUTDOWN_CMD = _NSENTER_PREFIX + ["shutdown", "-h", "now"]
    APT_UPDATE_CMD = _NSENTER_PREFIX + ["apt-get", "update"]
    APT_UPGRADE_CMD = _NSENTER_PREFIX + ["apt-get", "upgrade", "-y"]
else:
    REBOOT_CMD = ["sudo", "/sbin/reboot"]
    SHUTDOWN_CMD = ["sudo", "/sbin/shutdown", "-h", "now"]
    APT_UPDATE_CMD = ["sudo", "/usr/bin/apt-get", "update"]
    APT_UPGRADE_CMD = ["sudo", "/usr/bin/apt-get", "upgrade", "-y"]
