
#!/usr/bin/env python3
"""Command-line storage health monitor for macOS and Linux."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    print(
        "Missing dependency: psutil. Install it with: "
        "python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)


CSV_COLUMNS = [
    "timestamp", "system", "hostname", "device", "mountpoint",
    "filesystem", "total_bytes", "used_bytes", "free_bytes",
    "used_percent", "io_read_bytes", "io_write_bytes",
    "io_read_count", "io_write_count",
    "read_bytes_per_sec", "write_bytes_per_sec",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def get_disk_partitions() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Return accessible filesystems and report mounts that could not be read."""
    results = []
    skipped = []
    seen = set()

    try:
        partitions = psutil.disk_partitions(all=False)
    except (PermissionError, OSError, NotImplementedError) as exc:
        return [], [{
            "mountpoint": "*",
            "reason": f"Could not list partitions: {exc}",
        }]

    for partition in partitions:
        key = (partition.device, partition.mountpoint)
        if key in seen:
            continue
        seen.add(key)

        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError) as exc:
            skipped.append({
                "mountpoint": partition.mountpoint,
                "reason": f"{type(exc).__name__}: {exc}",
            })
            continue

        results.append({
            "device": partition.device,
            "mountpoint": partition.mountpoint,
            "filesystem": partition.fstype or "unknown",
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
            "used_percent": round(float(usage.percent), 2),
        })

    return results, skipped


def get_io_counters() -> dict[str, int] | None:
    """Return system-wide cumulative disk I/O counters if available."""
    try:
        counters = psutil.disk_io_counters()
    except (PermissionError, OSError, NotImplementedError):
        return None

    if counters is None:
        return None

    return {
        "read_bytes": int(getattr(counters, "read_bytes", 0) or 0),
        "write_bytes": int(getattr(counters, "write_bytes", 0) or 0),
        "read_count": int(getattr(counters, "read_count", 0) or 0),
        "write_count": int(getattr(counters, "write_count", 0) or 0),
    }


def calculate_io_rates(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
    elapsed: float | None,
) -> dict[str, float | None]:
    """Calculate system-wide read/write bytes per second."""
    rates = {
        "read_bytes_per_sec": None,
        "write_bytes_per_sec": None,
    }

    # The first sample is a baseline, not a rate measurement.
    if previous is None or current is None or elapsed is None or elapsed <= 0:
        return rates

    for counter, rate_name in (
        ("read_bytes", "read_bytes_per_sec"),
        ("write_bytes", "write_bytes_per_sec"),
    ):
        old_value = previous.get(counter)
        new_value = current.get(counter)

        # Counters may reset or become unavailable.
        if old_value is None or new_value is None or new_value < old_value:
            rates[rate_name] = None
        else:
            rates[rate_name] = round(
                (new_value - old_value) / elapsed, 2
            )

    return rates


def collect_snapshot(
    threshold: float,
    previous_io: dict[str, Any] | None = None,
    elapsed: float | None = None,
) -> dict[str, Any]:
    disks, skipped_mounts = get_disk_partitions()
    io = get_io_counters()
    rates = calculate_io_rates(previous_io, io, elapsed)

    alerts = [
        {
            "mountpoint": disk["mountpoint"],
            "used_percent": disk["used_percent"],
            "message": (
                f'{disk["mountpoint"]} is '
                f'{disk["used_percent"]:.1f}% full'
            ),
        }
        for disk in disks
        if disk["used_percent"] >= threshold
    ]

    return {
        "timestamp": utc_now(),
        "system": platform.system(),
        "hostname": platform.node(),
        "disks": disks,
        "skipped_mounts": skipped_mounts,
        "disk_io": io,
        "io_rates": rates,
        "alerts": alerts,
    }


def format_bytes(value: float | int) -> str:
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
            used_total = (
                f'{format_bytes(disk["used_bytes"])} / '
                f'{format_bytes(disk["total_bytes"])}'
            )
            print(
                f'{disk["mountpoint"][:27]:<28} '
                f'{disk["used_percent"]:>6.1f}% '
                f'{used_total:>27}  {disk["filesystem"]}'
            )

    io = snapshot["disk_io"]
    rates = snapshot["io_rates"]

    if io is None:
        print("\nSystem-wide disk I/O counters are unavailable.")
    else:
        print("\nSystem-wide disk I/O counters (cumulative since boot):")
        print(
            f'  Read: {format_bytes(io["read_bytes"])} '
            f'across {io["read_count"]:,} operations'
        )
        print(
            f'  Written: {format_bytes(io["write_bytes"])} '
            f'across {io["write_count"]:,} operations'
        )

        read_rate = rates["read_bytes_per_sec"]
        write_rate = rates["write_bytes_per_sec"]

        if read_rate is None or write_rate is None:
            print("  Throughput: unavailable (baseline or missing metrics)")
        else:
            print(
                f'  Throughput: read {format_bytes(read_rate)}/s | '
                f'write {format_bytes(write_rate)}/s'
            )

    if snapshot["skipped_mounts"]:
        print("\nMounts skipped:")
        for item in snapshot["skipped_mounts"]:
            print(f'  [INFO] {item["mountpoint"]}: {item["reason"]}')

    if snapshot["alerts"]:
        print("\nCAPACITY ALERTS")
        for alert in snapshot["alerts"]:
            print(f'  [WARNING] {alert["message"]}')
    else:
        print("\nNo capacity alerts for accessible filesystems.")


def append_csv(snapshot: dict[str, Any], csv_path: Path) -> None:
    """Append one row per mount; I/O metrics are system-wide."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0

    io = snapshot["disk_io"] or {}
    rates = snapshot["io_rates"]

    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)

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
                "read_bytes_per_sec": (
                    "" if rates["read_bytes_per_sec"] is None
                    else rates["read_bytes_per_sec"]
                ),
                "write_bytes_per_sec": (
                    "" if rates["write_bytes_per_sec"] is None
                    else rates["write_bytes_per_sec"]
                ),
            })


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monitor filesystem capacity and system-wide disk I/O."
    )
    parser.add_argument(
        "--threshold", type=float, default=80.0,
        help="Capacity warning percentage (default: 80).",
    )
    parser.add_argument(
        "--interval", type=float, default=0,
        help="Sampling interval in seconds; 0 means one snapshot.",
    )
    parser.add_argument(
        "--csv", type=Path, default=Path("storage_history.csv"),
        help="CSV output path.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print each snapshot as JSON.",
    )
    args = parser.parse_args()

    if not 0 < args.threshold <= 100:
        parser.error("--threshold must be greater than 0 and at most 100.")
    if args.interval < 0:
        parser.error("--interval cannot be negative.")

    previous_io = None
    previous_time = None

    try:
        while True:
            sample_time = time.monotonic()
            elapsed = (
                None if previous_time is None
                else sample_time - previous_time
            )

            snapshot = collect_snapshot(
                args.threshold,
                previous_io=previous_io,
                elapsed=elapsed,
            )

            if args.json:
                print(json.dumps(snapshot, indent=2))
            else:
                print_snapshot(snapshot)

            try:
                append_csv(snapshot, args.csv)
            except (OSError, csv.Error) as exc:
                print(f"CSV logging failed: {exc}", file=sys.stderr)
                return 1

            previous_io = snapshot["disk_io"]
            previous_time = sample_time

            if args.interval == 0:
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    except (OSError, RuntimeError) as exc:
        print(f"Monitoring failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
