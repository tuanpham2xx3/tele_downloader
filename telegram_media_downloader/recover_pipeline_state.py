#!/usr/bin/env python3
"""Release transient CSV ownership before a clean multi-pipeline start."""

from pathlib import Path

from csv_status_store import reset_transient_statuses


if __name__ == "__main__":
    csv_path = Path(__file__).parent / "full_hoahoc.csv"
    count = reset_transient_statuses(csv_path)
    print(f"Recovered {count} transient pipeline claim(s).")
