#!/usr/bin/env python3
"""Command-line storage health monitor for macOS and Linux."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    print("Missing dependency: psutil. Install it with: python3 -m pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def get_disk_partitions() -> list[dict[str, Any]]:
    """Return mounted filesystems with usable capacity information."""
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for partition in psutil.disk_partitions(all=False):
        key = (partition.device, partition.mountpoint)
        if key in seen:
            continue
        seen.add(key)

        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError):
            # Some system mounts may be inaccessible; skip them safely.
            continue

        percent = float(usage.percent)
        results.append({
            "device": partition.device,
            "mountpoint": partition.mountpoint,
            "filesystem": partition.fstype or "unknown",
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round(percent, 2),
        })

    return results


def get_io_counters() -> dict[str, Any] | None:
    """Return system-wide disk I/O counters when the OS exposes them."""
    try:
        counters = psutil.disk_io_counters()
    except (PermissionError, OSError, NotImplementedError):
        return None

    if counters is None:
        return None

    return {
        "read_bytes": counters.read_bytes,
        "write_bytes": counters.write_bytes,
        "read_count": counters.read_count,
        "write_count": counters.write_count,
    }


def collect_snapshot(threshold: float) -> dict[str, Any]:
    disks = get_disk_partitions()
    alerts = [
        {
            "mountpoint": disk["mountpoint"],
            "used_percent": disk["used_percent"],
            "message": f'{disk["mountpoint"]} is {disk["used_percent"]:.1f}% full',
        }
        for disk in disks
        if disk["used_percent"] >= threshold
    ]

    return {
        "timestamp": utc_now(),
        "system": platform.system(),
        "hostname": platform.node(),
        "disks": disks,
        "disk_io": get_io_counters(),
        "alerts": alerts,
    }


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    amount = float(value)
    for unit in units:
        if amount < 1000 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1000
    return f"{amount:.1f} PB"


def print_snapshot(snapshot: dict[str, Any]) -> None:
    print(f'\nStorage Health Report — {snapshot["timestamp"]}')
    print(f'System: {snapshot["system"]} | Host: {snapshot["hostname"]}')
    print("-" * 78)

    if not snapshot["disks"]:
        print("No accessible mounted filesystems were found.")
    else:
        print(f'{"MOUNT":<28} {"USED":>7} {"USED / TOTAL":>27}  FILESYSTEM')
        for disk in snapshot["disks"]:
            used_total = f'{format_bytes(disk["used_bytes"])} / {format_bytes(disk["total_bytes"])}'
            print(f'{disk["mountpoint"][:27]:<28} {disk["used_percent"]:>6.1f}% {used_total:>27}  {disk["filesystem"]}')

    io = snapshot["disk_io"]
    if io:
        print("\nSystem-wide disk I/O counters (cumulative since boot):")
        print(f'  Read: {format_bytes(io["read_bytes"])} across {io["read_count"]:,} operations')
        print(f'  Written: {format_bytes(io["write_bytes"])} across {io["write_count"]:,} operations')
    else:
        print("\nDisk I/O counters are not available on this system.")

    if snapshot["alerts"]:
        print("\nALERTS")
        for alert in snapshot["alerts"]:
            print(f'  [WARNING] {alert["message"]} (threshold reached)')
    else:
        print("\nNo capacity alerts. All accessible filesystems are below the configured threshold.")


def append_csv(snapshot: dict[str, Any], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    columns = [
        "timestamp", "system", "hostname", "device", "mountpoint", "filesystem",
        "total_bytes", "used_bytes", "free_bytes", "used_percent",
        "io_read_bytes", "io_write_bytes", "io_read_count", "io_write_count",
    ]
    io = snapshot["disk_io"] or {}
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if not file_exists:
            writer.writeheader()
        for disk in snapshot["disks"]:
            writer.writerow({
                "timestamp": snapshot["timestamp"],
                "system": snapshot["system"],
                "hostname": snapshot["hostname"],
                **disk,
                "io_read_bytes": io.get("read_bytes", ""),
                "io_write_bytes": io.get("write_bytes", ""),
                "io_read_count": io.get("read_count", ""),
                "io_write_count": io.get("write_count", ""),
            })


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monitor mounted filesystem capacity and record storage metrics."
    )
    parser.add_argument("--threshold", type=float, default=80.0,
                        help="Warn when filesystem usage reaches this percentage (default: 80).")
    parser.add_argument("--interval", type=float, default=0,
                        help="Repeat every N seconds and append each sample to CSV; 0 means one snapshot.")
    parser.add_argument("--csv", type=Path, default=Path("storage_history.csv"),
                        help="CSV output path (default: storage_history.csv).")
    parser.add_argument("--json", action="store_true",
                        help="Print the snapshot as JSON instead of a human-readable report.")
    args = parser.parse_args()

    if not 0 < args.threshold <= 100:
        parser.error("--threshold must be greater than 0 and at most 100.")
    if args.interval < 0:
        parser.error("--interval cannot be negative.")

    try:
        while True:
            snapshot = collect_snapshot(args.threshold)
            if args.json:
                print(json.dumps(snapshot, indent=2))
            else:
                print_snapshot(snapshot)

            append_csv(snapshot, args.csv)
            if args.interval == 0:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    except OSError as exc:
        print(f"Could not write CSV file: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
