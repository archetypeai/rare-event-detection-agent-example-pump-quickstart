#!/bin/sh
# Stop everything this demo starts and verify its ports are free. The serving
# bridge cancels and deletes its platform agent on SIGTERM; give it a moment.
# npm starts the bridge and replayer with `--app red-serving`, which is what is
# matched: app/'s replayer and TEP's bridge share their script names.
HERE=$(cd "$(dirname "$0")/.." && pwd)
pkill -TERM -f "serving-bridge.js --app red-serving" 2>/dev/null
for i in 1 2 3 4 5 6 7 8 9 10; do
	pgrep -f "serving-bridge.js --app red-serving" >/dev/null 2>&1 || break
	sleep 1
done
pkill -f "mosquitto -c $HERE/mosquitto/mosquitto.conf" 2>/dev/null
pkill -f "replayer.js --app red-serving" 2>/dev/null
pkill -f "vite dev --port 5181" 2>/dev/null
sleep 1
busy=0
for p in 1891 9009 9101 5181; do
	if lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then
		echo "port $p still held by: $(lsof -nP -iTCP:$p -sTCP:LISTEN | awk 'NR==2{print $1" (pid "$2")"}')"
		busy=1
	fi
done
[ $busy -eq 0 ] && echo "all ports free (1891 · 9009 · 9101 · 5181)"
