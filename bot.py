"""
Captain Ryusuui - CasaOS Telegram Management Bot
==================================================
A Telegram bot to monitor and manage a CasaOS server (Ubuntu 24.04 LTS):
  - System stats (CPU, RAM, disk, temperature, uptime, load average)
  - Docker container management (list/start/stop/restart) - covers
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
import time as time_module
from datetime import timedelta
from functools import wraps

import psutil
import docker
import requests
from docker.errors import DockerException, NotFound

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
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

# Per-chat selected Ollama model (in-memory; resets on bot restart)
_chat_model_choice = {}

# Tracks last container status per container ID, for the watchdog job
_last_container_status = {}

# Tracks last alert timestamp per metric, to enforce cooldowns
_last_alert_time = {}

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


def get_battery_info():
    """Returns (percent, plugged_in) or None if no battery is present/exposed."""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return None
        return round(battery.percent, 1), battery.power_plugged
    except (AttributeError, NotImplementedError):
        return None


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
        "👋 *Captain Ryusuui*, reporting for duty.\n\n"
        "I'll keep watch over your server, run diagnostics, and carry out orders on request.\n"
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
        "/containers - List containers with action buttons\n\n"
        "🧠 *Local AI (Ollama)*\n"
        "/ask <question> - Ask your local model a question\n"
        "/model - Switch which model /ask uses\n\n"
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

    battery_str = None
    battery_info = get_battery_info()
    if battery_info is not None:
        pct, plugged = battery_info
        plug_emoji = "🔌" if plugged else "🔋"
        battery_str = f"{plug_emoji} {pct}% ({'charging/plugged in' if plugged else 'on battery'})"

    text = (
        "🖥️ *System Status*\n\n"
        f"*CPU:* {cpu_percent}% across {cpu_count} cores\n"
        f"*Load avg:* {load1:.2f}, {load5:.2f}, {load15:.2f} (1/5/15 min)\n"
        f"*Temperature:* {temp_str}\n"
    )
    if battery_str:
        text += f"*Battery:* {battery_str}\n"
    text += (
        "\n"
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
# Ollama (local LLM) integration
# ---------------------------------------------------------------------------
def _get_chat_model(chat_id: int) -> str:
    return _chat_model_choice.get(chat_id, config.DEFAULT_MODEL)


def _ollama_generate(model: str, prompt: str) -> str:
    """Blocking call to the local Ollama API. Run via asyncio.to_thread."""
    try:
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "(empty response)").strip()
    except requests.exceptions.ConnectionError:
        return (
            f"❌ Can't reach Ollama at {config.OLLAMA_HOST}. Is Ollama running, "
            "and is OLLAMA_HOST set correctly for your setup (Docker vs host)?"
        )
    except requests.exceptions.Timeout:
        return f"⏱️ Model took longer than {config.OLLAMA_TIMEOUT_SECONDS}s to respond. Try a smaller model with /model."
    except Exception as e:
        return f"❌ Ollama error: {e}"


@restricted
async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ask <your question>")
        return

    prompt = " ".join(context.args)
    model = _get_chat_model(update.effective_chat.id)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    thinking_msg = await update.message.reply_text(f"🤔 Asking *{model}*...", parse_mode=ParseMode.MARKDOWN)

    import asyncio
    answer = await asyncio.to_thread(_ollama_generate, model, prompt)

    # Telegram message limit is 4096 chars
    if len(answer) > 3900:
        answer = answer[:3900] + "\n\n...(truncated)"

    await thinking_msg.edit_text(f"🤖 *{model}*:\n\n{answer}", parse_mode=ParseMode.MARKDOWN)


@restricted
async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = _get_chat_model(update.effective_chat.id)
    buttons = []
    for m in config.AVAILABLE_MODELS:
        label = f"✅ {m}" if m == current else m
        buttons.append([InlineKeyboardButton(label, callback_data=f"setmodel:{m}")])
    await update.message.reply_text(
        f"Current model: *{current}*\n\nChoose a model for /ask:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def setmodel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id if query.from_user else None
    if user_id not in config.AUTHORIZED_USERS:
        await query.answer("🚫 Not authorized.", show_alert=True)
        return

    _, model = query.data.split(":", 1)
    _chat_model_choice[query.message.chat_id] = model
    await query.answer(f"Switched to {model}")
    await query.edit_message_text(f"✅ Now using *{model}* for /ask", parse_mode=ParseMode.MARKDOWN)


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
# Proactive monitoring (background job, no user interaction needed)
# ---------------------------------------------------------------------------
def _should_alert(key: str) -> bool:
    """Cooldown check so we don't spam the same alert every interval."""
    last = _last_alert_time.get(key, 0)
    now = time_module.time()
    if now - last >= config.ALERT_COOLDOWN_SECONDS:
        _last_alert_time[key] = now
        return True
    return False


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, text: str):
    for uid in config.AUTHORIZED_USERS:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning("Could not send alert to %s: %s", uid, e)


async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    # --- Resource thresholds ---
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent

    if cpu >= config.CPU_ALERT_THRESHOLD and _should_alert("cpu"):
        await _broadcast(context, f"⚠️ *High CPU usage:* {cpu}% (threshold {config.CPU_ALERT_THRESHOLD}%)")

    if mem >= config.MEM_ALERT_THRESHOLD and _should_alert("mem"):
        await _broadcast(context, f"⚠️ *High memory usage:* {mem}% (threshold {config.MEM_ALERT_THRESHOLD}%)")

    if disk >= config.DISK_ALERT_THRESHOLD and _should_alert("disk"):
        await _broadcast(context, f"⚠️ *High disk usage on /:* {disk}% (threshold {config.DISK_ALERT_THRESHOLD}%)")

    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ("coretemp", "cpu_thermal", "k10temp"):
                if key in temps and temps[key]:
                    current = temps[key][0].current
                    if current >= config.TEMP_ALERT_THRESHOLD_C and _should_alert("temp"):
                        await _broadcast(
                            context,
                            f"🌡️ *High temperature:* {current:.1f}°C (threshold {config.TEMP_ALERT_THRESHOLD_C}°C)",
                        )
                    break
    except (AttributeError, NotImplementedError):
        pass

    # --- Battery: alert when low AND not currently charging ---
    battery_info = get_battery_info()
    if battery_info is not None:
        pct, plugged = battery_info
        if pct <= config.BATTERY_ALERT_THRESHOLD and not plugged and _should_alert("battery"):
            await _broadcast(
                context,
                f"🔋 *Low battery:* {pct}% remaining and not charging - "
                f"connect the charger (threshold {config.BATTERY_ALERT_THRESHOLD}%)",
            )
        elif plugged:
            # Reset the cooldown once it's charging again, so the next time
            # it drops low you get a fresh alert instead of staying silent.
            _last_alert_time.pop("battery", None)

    # --- Container watchdog: alert on unexpected stop / restart loop ---
    if docker_client is not None:
        try:
            containers = docker_client.containers.list(all=True)
            for c in containers:
                prev = _last_container_status.get(c.id)
                if prev == "running" and c.status != "running":
                    if _should_alert(f"container:{c.id}"):
                        await _broadcast(
                            context,
                            f"🔴 *Container stopped unexpectedly:* {c.name} (status: {c.status})",
                        )
                _last_container_status[c.id] = c.status
        except DockerException as e:
            logger.warning("Monitor job could not list containers: %s", e)


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
    ("ask", "Ask your local Ollama model a question"),
    ("model", "Switch which Ollama model /ask uses"),
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
    application.add_handler(CallbackQueryHandler(container_callback, pattern="^(start|stop|restart):"))

    application.add_handler(CommandHandler("ask", ask_cmd))
    application.add_handler(CommandHandler("model", model_cmd))
    application.add_handler(CallbackQueryHandler(setmodel_callback, pattern="^setmodel:"))

    application.add_handler(CommandHandler("reboot", reboot_cmd))
    application.add_handler(CommandHandler("shutdown", shutdown_cmd))
    application.add_handler(CommandHandler("update", update_cmd))
    application.add_handler(CallbackQueryHandler(confirm_callback, pattern="^confirm:"))

    application.add_error_handler(error_handler)

    if config.MONITOR_ENABLED:
        if config.AUTHORIZED_USERS:
            application.job_queue.run_repeating(
                monitor_job, interval=config.MONITOR_INTERVAL_SECONDS, first=30
            )
            logger.info(
                "Proactive monitoring enabled (every %ss).", config.MONITOR_INTERVAL_SECONDS
            )
        else:
            logger.warning("MONITOR_ENABLED is true but AUTHORIZED_USERS is empty - skipping monitor job.")

    logger.info("Bot starting (polling mode)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()