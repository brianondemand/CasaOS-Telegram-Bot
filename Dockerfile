FROM python:3.12-slim

# nsenter (from util-linux) lets the container reach the host's PID/mount/net
# namespace for reboot/shutdown/apt commands. docker.io CLI is not required
# since we talk to the Docker daemon via the mounted socket + python SDK,
# but curl/procps are handy for debugging.
RUN apt-get update && apt-get install -y --no-install-recommends \
    util-linux \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py config.py ./

# Runs as root by design: nsenter into the host PID namespace and reaching
# the Docker socket both require elevated privileges. Access is still gated
# by the Telegram user whitelist (AUTHORIZED_USERS) at the application layer.
CMD ["python", "bot.py"]
