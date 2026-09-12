#!/usr/bin/env bash
set -e

# Activate virtual environment
source /opt/pysetup/.venv/bin/activate

# Execute passed command
exec "$@"
