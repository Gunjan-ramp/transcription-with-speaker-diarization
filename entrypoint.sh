#!/bin/bash
set -e

# Ensure DBUS is ready
mkdir -p /var/run/dbus
dbus-uuidgen > /var/lib/dbus/machine-id 2>/dev/null || true
dbus-daemon --config-file=/usr/share/dbus-1/system.conf --print-address --fork || true

# Start Xvfb (Virtual Screen) first
Xvfb :99 -screen 0 1920x1080x24 &
sleep 2

# Start PulseAudio in user mode (avoids "Connection failure: Access denied")
mkdir -p /tmp/pulse-runtime
export XDG_RUNTIME_DIR=/tmp/pulse-runtime
export PULSE_RUNTIME_PATH=/tmp/pulse-runtime

pulseaudio --start \
  --exit-idle-time=-1 \
  --disallow-exit \
  --log-target=stderr \
  --log-level=notice \
  2>&1 || true

# Wait for PulseAudio to be ready
echo "Waiting for PulseAudio..."
for i in $(seq 1 15); do
  if pactl info > /dev/null 2>&1; then
    echo "PulseAudio is ready."
    break
  fi
  echo "  attempt $i/15..."
  sleep 1
done

# Create the virtual sink for recording
if pactl load-module module-virtual-sink sink_name=virtsink; then
  pactl set-default-sink virtsink
  echo "Virtual sink 'virtsink' created and set as default."
else
  echo "WARNING: Could not create virtual sink. Audio capture may not work."
fi

# Start the FastAPI application
echo "Starting FastAPI Server..."
exec python -m app.main
