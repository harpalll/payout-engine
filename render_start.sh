#!/usr/bin/env bash
set -e

gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
