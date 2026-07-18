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


# ---------------------------------------------------------------------------
# Ollama (local LLM) integration
# ---------------------------------------------------------------------------
# Default assumes running via docker-compose with extra_hosts set (see
# docker-compose.yml). If running directly on the host, use:
#   OLLAMA_HOST=http://localhost:11434
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")

# Models you've pulled with `ollama pull`. First one is the default for /ask.
AVAILABLE_MODELS = [
    "qwen2.5:3b",
    "tinyllama:latest",
    "hf.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q4_K_M",
]
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen2.5:3b")

# How long to wait for a model response before giving up (seconds).
# Larger/uncensored models are slower - bump this up if you switch to one.
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "60"))


# ---------------------------------------------------------------------------
# Proactive monitoring & alerts
# ---------------------------------------------------------------------------
MONITOR_ENABLED = os.environ.get("MONITOR_ENABLED", "true").lower() == "true"
MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", "300"))  # 5 min

CPU_ALERT_THRESHOLD = float(os.environ.get("CPU_ALERT_THRESHOLD", "90"))
MEM_ALERT_THRESHOLD = float(os.environ.get("MEM_ALERT_THRESHOLD", "90"))
DISK_ALERT_THRESHOLD = float(os.environ.get("DISK_ALERT_THRESHOLD", "90"))
TEMP_ALERT_THRESHOLD_C = float(os.environ.get("TEMP_ALERT_THRESHOLD_C", "80"))

# Alert when battery drops to or below this percent (only relevant if the
# server has a battery, e.g. a laptop-as-server or a UPS exposed via ACPI).
BATTERY_ALERT_THRESHOLD = float(os.environ.get("BATTERY_ALERT_THRESHOLD", "20"))

# Don't re-alert on the same metric more than once per this many seconds,
# so a sustained high-CPU period doesn't spam you every 5 minutes.
ALERT_COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "1800"))  # 30 min