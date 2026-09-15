#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Backend: create venv and install editable package with test extras.
cd "${ROOT}/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[test]"

# Frontend: install pinned dependencies.
cd "${ROOT}/frontend"
npm ci
