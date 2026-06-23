#!/bin/bash
# Start the Arsenal Tracker dashboard (http://127.0.0.1:5057).
cd "$(dirname "$0")" || exit 1
exec ./venv/bin/python app.py
