#!/usr/bin/env python3
"""Maintain best-effort ~5-minute PS5 Pro checks within a live Actions runner.

GitHub cron may start late, but once this job begins it runs repeated checks
without waiting for another scheduled workflow. No login or purchase actions.
"""
import argparse
import subprocess
import sys
import time

import monitor_window

INTERVAL_SECONDS = 300
DEFAULT_DURATION_MINUTES = 140
COMMANDS = {
    "retail": ("retail_watch.py",),
    "promo": ("promo_watch.py", "catalog_watch.py", "dcinside_watch.py"),
}


def next_tick(start, now, interval=INTERVAL_SECONDS):
    """Compute next check on the runner's five-minute monotonic cadence."""
    if interval <= 0:
        raise ValueError("interval must be positive")
    return start + (max(0, int((now - start) // interval)) + 1) * interval


def check_once(mode, runner=subprocess.run):
    """Run each independent monitor; preserve partial coverage on failure."""
    failed = []
    for script in COMMANDS[mode]:
        print(f"[watch] Running {script}", flush=True)
        try:
            result = runner([sys.executable, "-u", script], timeout=210, check=False)
            if result.returncode != 0:
                failed.append(f"{script} exit={result.returncode}")
        except subprocess.TimeoutExpired:
            failed.append(f"{script} timeout after 210s")
        except Exception as exc:
            failed.append(f"{script} {type(exc).__name__}: {exc}")
    return failed


def run(mode, duration_minutes=DEFAULT_DURATION_MINUTES, interval_seconds=INTERVAL_SECONDS):
    if duration_minutes <= 0:
        raise ValueError("duration must be positive")
    start = time.monotonic()
    end = start + duration_minutes * 60
    count = 0
    failed_rounds = 0
    print(f"[watch] mode={mode} interval={interval_seconds}s duration={duration_minutes}m", flush=True)
    while time.monotonic() < end and monitor_window.is_active_at():
        count += 1
        print(f"[watch] Cycle #{count} started, mode={mode}", flush=True)
        failures = check_once(mode)
        if failures:
            failed_rounds += 1
            print("[watch] Partial/failed cycle: " + "; ".join(failures), flush=True)
        else:
            print(f"[watch] Cycle #{count} completed", flush=True)
        remaining = end - time.monotonic()
        if remaining <= 0 or not monitor_window.is_active_at():
            break
        delay = min(remaining, max(0, next_tick(start, time.monotonic(), interval_seconds) - time.monotonic()))
        if delay:
            print(f"[watch] Next check in {delay:.0f}s", flush=True)
            time.sleep(delay)
    print(f"[watch] Finished {count} cycles; cycles with failures={failed_rounds}", flush=True)
    # Workflow should be red when checks entirely fail repeatedly, rather than
    # claiming everything worked. Partial failures remain logged as such.
    return 1 if count and failed_rounds == count else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(COMMANDS))
    parser.add_argument("--duration-minutes", type=float, default=DEFAULT_DURATION_MINUTES)
    parser.add_argument("--interval-seconds", type=int, default=INTERVAL_SECONDS)
    args = parser.parse_args()
    return run(args.mode, args.duration_minutes, args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
