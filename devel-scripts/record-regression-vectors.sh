#!/usr/bin/env bash
# Purpose: regenerate recordings/ — one short pcap + raw recording per CGF scenario (CR-004),
# fault-free, as regression vectors for moving-map-display. Overwrites recordings/*.{pcap,bin}.
# Runs the four scenarios in parallel in real time (~60 s). Run from anywhere.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p recordings

# scenario  seconds  port — durations keep each file under 1 MB and cover the scenario's events
record() {
    local name="$1" seconds="$2" port="$3"
    rm -f "recordings/$name.pcap" "recordings/$name.bin"
    python3 -m cgf.runner "scenarios/$name.json" --duration "$seconds" --port "$port" \
        --record "recordings/$name.pcap" --record-raw "recordings/$name.bin" > "recordings/.$name.log"
}

echo "===== recording (≤ 60 s) ====="
record ottawa-mixed 30 3901 &
record lifecycle 60 3902 &
record load-200 15 3903 &
record zone-crossing 60 3904 &
wait

echo "===== result ====="
rm -f recordings/.*.log
ls -l recordings/
