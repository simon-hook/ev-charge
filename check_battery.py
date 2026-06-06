#!/usr/bin/env python3
"""Thin entry point so cron can run `python check_battery.py`."""

from ev_charge.main import main

if __name__ == "__main__":
    main()
