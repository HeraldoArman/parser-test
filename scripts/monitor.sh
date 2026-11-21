#!/usr/bin/env bash
# Append container resource samples to a pipe-separated log until stopped.
# Usage: scripts/monitor.sh [container] [interval_seconds] [logfile]
set -u

container="${1:-brp-run}"
interval="${2:-5}"
logfile="${3:-var/monitor/stats.log}"

mkdir -p "$(dirname "$logfile")"
if [ ! -s "$logfile" ]; then
  echo "timestamp|cpu_pct|mem_usage|mem_pct|net_io|block_io|pids" > "$logfile"
fi

while true; do
  line="$(docker stats "$container" --no-stream --format \
    '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}' 2>/dev/null)" \
    || line="container $container not running"
  printf '%s|%s\n' "$(date -Iseconds)" "$line" >> "$logfile"
  sleep "$interval"
done
