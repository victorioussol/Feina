#!/usr/bin/env bash
# Local disposable proof; no client computer, model call or account credentials.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm \
  --mount "type=bind,source=$ROOT,target=/src,readonly" \
  python:3.12-slim sh -ec '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends procps util-linux >/dev/null
    mkdir /work
    cp -R /src/files /src/tests /src/ops /src/build_template.py /work/
    cd /work
    python -m venv .venv
    .venv/bin/pip -q install -r tests/requirements.txt
    .venv/bin/python -m pytest -q -p no:cacheprovider
  '
