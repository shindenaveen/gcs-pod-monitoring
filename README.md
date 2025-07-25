# GCS Pod Monitoring

This Python script monitors Kubernetes pod status and key service URLs. If a pod is not running or a service is down, it logs the event and optionally sends email alerts.

## Features
- Monitors multiple namespaces and services
- Detects pod crashes, restarts, and unavailability
- Sends alert emails with tabular summaries
- Configurable via external input files

## Requirements
- Python 3.x
- `kubectl` CLI installed
- `requests` package
- `sendmail` (for email alerts)

## Usage
1. Modify the script with correct paths, email IDs, and Kubernetes config.
2. Run the script on a schedule (e.g., using cron).

## Disclaimer
This script is a sanitized version. Update paths and values according to your environment.
