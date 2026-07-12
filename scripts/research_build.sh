#!/usr/bin/env bash
set -euo pipefail

if [[ "${VERCEL_GIT_COMMIT_REF:-}" == "research-public-price" ]]; then
  echo "[research] downloading official 2025 nationwide public-price ZIP"
  mkdir -p tmp
  curl --fail --location --retry 5 --retry-delay 5 \
    --connect-timeout 30 --max-time 2400 \
    --user-agent 'Mozilla/5.0 public-price-research' \
    'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003525375&fileDetailSn=1&insertDataPrcus=N' \
    --output tmp/public_price_2025.zip
  ls -lh tmp/public_price_2025.zip
  python -m pip install --disable-pip-version-check duckdb
  python scripts/research_public_price.py
  mkdir -p public/research/public_price_2025
  cp research_output/public_price_2025/summary.json public/research/public_price_2025/summary.json
  cp research_output/public_price_2025/q2_area_bins.csv public/research/public_price_2025/q2_area_bins.csv
fi

npx vite build
