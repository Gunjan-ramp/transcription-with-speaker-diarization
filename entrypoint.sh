#!/bin/bash
set -e

# --- 1. Cleanup ---
rm -f /tmp/.X99-lock
rm -rf /tmp/pulse-*
rm -rf /tmp/pulse-runtime

# --- 2. Setup D-Bus ---
mkdir -p /var/run/dbus
dbus-uuidgen > /var/lib/dbus/machine-id 2>/dev/null || true
dbus-daemon --config-file=/usr/share/dbus-1/system.conf --print-address --fork || true

# --- 3. Start Xvfb ---
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
sleep 2

# --- 4. Start PulseAudio ---
mkdir -p /tmp/pulse-runtime
chmod 700 /tmp/pulse-runtime
export XDG_RUNTIME_DIR=/tmp/pulse-runtime
export PULSE_RUNTIME_PATH=/tmp/pulse-runtime
export PULSE_SERVER=unix:/tmp/pulse-runtime/native

pulseaudio --start \
  --exit-idle-time=-1 \
  --disallow-exit \
  --log-target=stderr \
  --log-level=notice

# Wait for PA
for i in $(seq 1 15); do
  if pactl info > /dev/null 2>&1; then break; fi
  sleep 1
done

# --- 5. Create Virtual Sink AND Source ---
# Create the null-sink (Speaker)
pactl load-module module-null-sink sink_name=virtsink sink_properties=device.description="Virtual_Speaker"
pactl set-default-sink virtsink

# Create a virtual source (Microphone) by monitoring the sink
# This tricks Teams into thinking there is a working mic
pactl load-module module-virtual-source source_name=virtsource master=virtsink.monitor source_properties=device.description="Virtual_Mic"
pactl set-default-source virtsource

# Configure ALSA to use PulseAudio (Essential for Chromium)
echo "pcm.!default { type pulse } ctl.!default { type pulse }" > /etc/asound.conf

# Set volume
pactl set-sink-volume virtsink 100% || true

# --- 6. Execute ---
echo "[Entrypoint] Starting application..."
exec "$@"
