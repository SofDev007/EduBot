#!/bin/bash

# EduBot Flask Application Launcher
# Usage: ./run.sh

cd "$(dirname "$0")"
source venv/bin/activate
python start.py
