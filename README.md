# Storage Health Monitor

A small command-line project that monitors mounted filesystem capacity on **macOS and Linux**, reports capacity alerts, and saves timestamped measurements to CSV. It uses Python and `psutil`; no Docker, Prometheus, or Grafana is required.

## Features

- Lists accessible mounted filesystems and their total, used, and free capacity.
- Warns when a filesystem reaches a configurable usage threshold.
- Shows system-wide cumulative disk I/O counters when the operating system exposes them.
- Logs periodic measurements to CSV for later analysis.
- Offers JSON output for scripting and further processing.
- Skips inaccessible mounts rather than crashing.

## Requirements

- Python 3.10 or newer recommended
- macOS or Linux
- `pip`

## Run on macOS

Open Terminal in this folder, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python storage_monitor.py
```

The first run prints a snapshot and creates `storage_history.csv`.

## Examples

Warn at 90% capacity:

```bash
python storage_monitor.py --threshold 90
```

Sample every 10 seconds and save a history:

```bash
python storage_monitor.py --interval 10 --csv storage_history.csv
```

Print JSON:

```bash
python storage_monitor.py --json
```

Stop continuous monitoring with `Ctrl+C`.

## Notes and limitations

- This is a local storage-capacity and metrics monitor, not a distributed storage system.
- macOS and Linux expose different filesystem and I/O details. Disk I/O counters may be unavailable on some systems.
- The I/O values are cumulative counters since boot, not per-second throughput measurements.
- Filesystems that cannot be queried due to permissions or OS restrictions are skipped.
- Run and validate the tool on your own machine before describing its measured behavior on a resume.

## Suggested next improvements

1. Calculate read/write throughput by comparing successive I/O counter samples.
2. Add unit tests for threshold logic and CSV output.
3. Add an option to monitor a specific mount point.
4. Add a summary command that reports historical capacity growth from the CSV.
5. Test on a Linux VM and document differences from macOS.

## Repository structure

```text
storage-health-monitor/
├── storage_monitor.py
├── requirements.txt
├── README.md
└── .gitignore
```

## Publish to GitHub

1. Create a new repository at https://github.com/new, for example `storage-health-monitor`.
2. In Terminal, from this project folder, run:

```bash
git init
git add .
git commit -m "Build storage health monitor"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/storage-health-monitor.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username. The repository is not published until you run these commands successfully.
