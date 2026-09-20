#!/usr/bin/env bash

set -e
set -x

coverage run -m pytest tests/ tests_pipeline/
coverage report
coverage html --title "${@-coverage}"
