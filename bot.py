"""
CasaOS Telegram Management Bot
================================
A Telegram bot to monitor and manage a CasaOS server (Ubuntu 24.04 LTS):
  - System stats (CPU, RAM, disk, temperature, uptime, load average)
  - Docker container management (list/start/stop/restart/logs) - covers
    CasaOS apps since they run as Docker containers
  - Power control (reboot / shutdown) with confirmation
  - Network info (local + public IP, bandwidth counters)
  - Top processes by CPU / memory
  - System update (apt update && apt upgrade)

Only Telegram user IDs listed in config.AUTHORIZED_USERS may use the bot.

Run:
    python3 bot.py
"""

import logging
import subprocess
import socket
from datetime import timedelta
from functools import wraps

import psutil
import docker
from docker.errors import DockerException, NotFound

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("casaos-bot")

# ---------------------------------------------------------------------------
# Docker client (lazy-safe: server still runs status/power commands even if
# the docker daemon is unreachable for some reason)
# ---------------------------------------------------------------------------
try:
    docker_client = docker.from_env()
except DockerException as e:
    docker_client = None
    logger.warning("Could not connect to Docker daemon: %s", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def restricted(func):
    """Decorator: only allow whitelisted Telegram user IDs to use a handler."""

    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not config.AUTHORIZED_USERS:
            logger.warning("AUTHORIZED_USERS is empty - rejecting all requests. "
                            "Add your Telegram user ID to config.py or the "
                            "AUTHORIZED_USERS env var.")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⚠️ Bot is not configured yet (no authorized users set)."
                )
            return
        if user_id not in config.AUTHORIZED_USERS:
            logger.warning("Unauthorized access attempt by user_id=%s", user_id)
            if update.effective_message:
                await update.effective_message.reply_text("🚫 You are not authorized to use this bot.")
            return
        return await func(update, context, *args, **kwargs)

    return wrapped


def human_bytes(n: float) -> str:
    """Convert bytes to a human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} EB"


def human_uptime() -> str:
    import time
    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)
    return str(timedelta(seconds=uptime_seconds))


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def run_shell(cmd: list, timeout: int = 60) -> str:
    """Run a command and return combined stdout/stderr, capped in length."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "⏱️ Command timed out."
    except FileNotFoundError:
        return f"❌ Command not found: {cmd[0]}"
    except Exception as e:
        return f"❌ Error running command: {e}"


# ---------------------------------------------------------------------------
# Basic commands
# ---------------------------------------------------------------------------
@restricted
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *CasaOS Server Bot*\n\n"
        "I can help you monitor and manage your server.\n"
        "Use /help to see everything I can do."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@restricted
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Available commands*\n\n"
        "🖥️ *System*\n"
        "/status - CPU, RAM, disk, temperature, uptime\n"
        "/processes - Top processes by CPU & memory\n"
        "/network - IP addresses & bandwidth counters\n"
        "/diskusage - Disk usage per mounted volume\n\n"
        "🐳 *Docker / CasaOS apps*\n"
        "/containers - List containers with action buttons\n"
        "/logs <name> - Show recent logs for a container\n\n"
        "🔧 *Maintenance*\n"
        "/update - Run apt update && apt upgrade\n"
        "/reboot - Reboot the server (confirmation required)\n"
        "/shutdown - Shut down the server (confirmation required)\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@restricted
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    load1, load5, load15 = psutil.getloadavg()

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")

    temp_str = "N/A"
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ("coretemp", "cpu_thermal", "k10temp"):
                if key in temps and temps[key]:
                    temp_str = f"{temps[key][0].current:.1f}°C"
                    break
            else:
                first_key = next(iter(temps))
                if temps[first_key]:
                    temp_str = f"{temps[first_key][0].current:.1f}°C"
    except (AttributeError, NotImplementedError):
        pass

    text = (
        "🖥️ *System Status*\n\n"
        f"*CPU:* {cpu_percent}% across {cpu_count} cores\n"
        f"*Load avg:* {load1:.2f}, {load5:.2f}, {load15:.2f} (1/5/15 min)\n"
        f"*Temperature:* {temp_str}\n\n"
        f"*RAM:* {human_bytes(mem.used)} / {human_bytes(mem.total)} ({mem.percent}%)\n"
        f"*Swap:* {human_bytes(swap.used)} / {human_bytes(swap.total)} ({swap.percent}%)\n\n"
        f"*Disk (/):* {human_bytes(disk.used)} / {human_bytes(disk.total)} ({disk.percent}%)\n\n"
        f"*Uptime:* {human_uptime()}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@restricted
async def diskusage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["💾 *Disk Usage*\n"]
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        lines.append(
            f"`{part.mountpoint}` ({part.fstype})\n"
            f"  {human_bytes(usage.used)} / {human_bytes(usage.total)} ({usage.percent}%)"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def processes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    top_cpu = sorted(procs, key=lambda x: x["cpu_percent"] or 0, reverse=True)[:5]
    top_mem = sorted(procs, key=lambda x: x["memory_percent"] or 0, reverse=True)[:5]

    lines = ["⚙️ *Top processes by CPU*"]
    for p in top_cpu:
        lines.append(f"  `{p['pid']:>6}` {p['name']:<20} {p['cpu_percent']:.1f}%")

    lines.append("\n🧠 *Top processes by Memory*")
    for p in top_mem:
        lines.append(f"  `{p['pid']:>6}` {p['name']:<20} {p['memory_percent']:.1f}%")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def network_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    local_ip = get_local_ip()

    public_ip = "unknown"
    try:
        import urllib.request
        with urllib.request.urlopen("https://api.ipify.org", timeout=3) as resp:
            public_ip = resp.read().decode().strip()
    except Exception:
        pass

    io_counters = psutil.net_io_counters()
    text = (
        "🌐 *Network*\n\n"
        f"*Local IP:* `{local_ip}`\n"
        f"*Public IP:* `{public_ip}`\n\n"
        f"*Sent:* {human_bytes(io_counters.bytes_sent)}\n"
        f"*Received:* {human_bytes(io_counters.bytes_recv)}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Docker container management
# ---------------------------------------------------------------------------
def _container_keyboard(container) -> InlineKeyboardMarkup:
    cid = container.id[:12]
    is_running = container.status == "running"
    buttons = []
    if is_running:
        buttons.append(InlineKeyboardButton("⏹ Stop", callback_data=f"stop:{cid}"))
        buttons.append(InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{cid}"))
    else:
        buttons.append(InlineKeyboardButton("▶️ Start", callback_data=f"start:{cid}"))
    buttons.append(InlineKeyboardButton("📜 Logs", callback_data=f"logs:{cid}"))
    return InlineKeyboardMarkup([buttons])


@restricted
async def containers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if docker_client is None:
        await update.message.reply_text(
            "❌ Cannot reach the Docker daemon. Make sure this bot's user is "
            "in the `docker` group and the daemon is running."
        )
        return

    containers = docker_client.containers.list(all=True)
    if not containers:
        await update.message.reply_text("No containers found.")
        return

    await update.message.reply_text(f"🐳 Found {len(containers)} container(s):")
    for c in containers:
        status_emoji = "🟢" if c.status == "running" else "🔴"
        image = c.image.tags[0] if c.image.tags else c.image.short_id
        text = f"{status_emoji} *{c.name}*\n`{image}`\nstatus: {c.status}"
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=_container_keyboard(c)
        )


@restricted
async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if docker_client is None:
        await update.message.reply_text("❌ Cannot reach the Docker daemon.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /logs <container_name_or_id>")
        return

    name = context.args[0]
    try:
        c = docker_client.containers.get(name)
    except NotFound:
        await update.message.reply_text(f"❌ Container '{name}' not found.")
        return

    raw = c.logs(tail=config.LOG_TAIL_LINES).decode(errors="replace")
    if not raw.strip():
        raw = "(no log output)"
    # Telegram message limit is 4096 chars
    snippet = raw[-3500:]
    await update.message.reply_text(
        f"📜 *Last {config.LOG_TAIL_LINES} lines - {c.name}*\n```\n{snippet}\n```",
        parse_mode=ParseMode.MARKDOWN,
    )


async def container_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id if query.from_user else None
    if user_id not in config.AUTHORIZED_USERS:
        await query.answer("🚫 Not authorized.", show_alert=True)
        return

    await query.answer()
    action, cid = query.data.split(":", 1)

    if docker_client is None:
        await query.edit_message_text("❌ Cannot reach the Docker daemon.")
        return

    try:
        c = docker_client.containers.get(cid)
    except NotFound:
        await query.edit_message_text("❌ Container no longer exists.")
        return

    try:
        if action == "start":
            c.start()
            msg = f"▶️ Started *{c.name}*"
        elif action == "stop":
            c.stop()
            msg = f"⏹ Stopped *{c.name}*"
        elif action == "restart":
            c.restart()
            msg = f"🔄 Restarted *{c.name}*"
        elif action == "logs":
            raw = c.logs(tail=config.LOG_TAIL_LINES).decode(errors="replace")
            snippet = (raw.strip() or "(no log output)")[-3500:]
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📜 *Last {config.LOG_TAIL_LINES} lines - {c.name}*\n```\n{snippet}\n```",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        else:
            msg = "Unknown action."
    except DockerException as e:
        msg = f"❌ Error: {e}"

    c.reload()
    status_emoji = "🟢" if c.status == "running" else "🔴"
    image = c.image.tags[0] if c.image.tags else c.image.short_id
    text = f"{status_emoji} *{c.name}*\n`{image}`\nstatus: {c.status}\n\n{msg}"
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=_container_keyboard(c)
    )


# ---------------------------------------------------------------------------
# Power management (reboot / shutdown) - require inline confirmation
# ---------------------------------------------------------------------------
def _confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, confirm", callback_data=f"confirm:{action}"),
                InlineKeyboardButton("❌ Cancel", callback_data="confirm:cancel"),
            ]
        ]
    )


@restricted
async def reboot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚠️ Are you sure you want to *reboot* the server?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_confirm_keyboard("reboot"),
    )


@restricted
async def shutdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚠️ Are you sure you want to *shut down* the server? "
        "You will need physical/remote power access to turn it back on.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_confirm_keyboard("shutdown"),
    )


@restricted
async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚠️ Run `apt-get update && apt-get upgrade -y`? This may take a while "
        "and could restart services.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_confirm_keyboard("update"),
    )


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id if query.from_user else None
    if user_id not in config.AUTHORIZED_USERS:
        await query.answer("🚫 Not authorized.", show_alert=True)
        return

    await query.answer()
    _, action = query.data.split(":", 1)

    if action == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    if action == "reboot":
        await query.edit_message_text("🔄 Rebooting now...")
        run_shell(config.REBOOT_CMD, timeout=10)
    elif action == "shutdown":
        await query.edit_message_text("🛑 Shutting down now...")
        run_shell(config.SHUTDOWN_CMD, timeout=10)
    elif action == "update":
        await query.edit_message_text("📦 Running apt-get update...")
        out1 = run_shell(config.APT_UPDATE_CMD, timeout=120)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"```\n{out1[-3500:]}\n```",
            parse_mode=ParseMode.MARKDOWN,
        )
        await context.bot.send_message(chat_id=query.message.chat_id, text="📦 Running apt-get upgrade...")
        out2 = run_shell(config.APT_UPGRADE_CMD, timeout=1800)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✅ Upgrade finished:\n```\n{out2[-3500:]}\n```",
            parse_mode=ParseMode.MARKDOWN,
        )


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update %s caused error: %s", update, context.error, exc_info=context.error)


# ---------------------------------------------------------------------------
# Command menu (the "/" button list shown in the Telegram chat box)
# ---------------------------------------------------------------------------
BOT_COMMANDS = [
    ("start", "Show welcome message"),
    ("help", "Show all commands"),
    ("status", "CPU, RAM, disk, temperature, uptime"),
    ("diskusage", "Disk usage per mounted volume"),
    ("processes", "Top processes by CPU and memory"),
    ("network", "IP addresses and bandwidth"),
    ("containers", "List Docker containers with controls"),
    ("logs", "Show recent logs for a container"),
    ("update", "Run apt update and upgrade"),
    ("reboot", "Reboot the server"),
    ("shutdown", "Shut down the server"),
]


async def _post_init(application: Application):
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Command menu registered with Telegram.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if config.BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit(
            "Please set BOT_TOKEN in config.py or the BOT_TOKEN environment variable."
        )

    application = Application.builder().token(config.BOT_TOKEN).post_init(_post_init).build()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("diskusage", diskusage_cmd))
    application.add_handler(CommandHandler("processes", processes_cmd))
    application.add_handler(CommandHandler("network", network_cmd))

    application.add_handler(CommandHandler("containers", containers_cmd))
    application.add_handler(CommandHandler("logs", logs_cmd))
    application.add_handler(CallbackQueryHandler(container_callback, pattern="^(start|stop|restart|logs):"))

    application.add_handler(CommandHandler("reboot", reboot_cmd))
    application.add_handler(CommandHandler("shutdown", shutdown_cmd))
    application.add_handler(CommandHandler("update", update_cmd))
    application.add_handler(CallbackQueryHandler(confirm_callback, pattern="^confirm:"))

    application.add_error_handler(error_handler)

    logger.info("Bot starting (polling mode)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
