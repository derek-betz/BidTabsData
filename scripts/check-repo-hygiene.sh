#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_LOG_BYTES="${MAX_LOG_BYTES:-2097152}"  # 2 MiB

cd "$REPO_ROOT"

issues=0

echo "[hygiene] checking tracked macOS metadata files..."
tracked_ds_store="$(git ls-files | grep -E "\\.DS_Store$" || true)"
if [[ -n "$tracked_ds_store" ]]; then
  echo "❌ tracked .DS_Store files found:"
  printf "%s\n" "$tracked_ds_store"
  issues=$((issues + 1))
else
  echo "✅ no tracked .DS_Store files"
fi

echo "[hygiene] checking oversized logs (> ${MAX_LOG_BYTES} bytes)..."
oversized_logs="$(find logs -type f -name "*.log" -size +${MAX_LOG_BYTES}c -print 2>/dev/null || true)"
if [[ -n "$oversized_logs" ]]; then
  echo "❌ oversized log files found:"
  printf "%s\n" "$oversized_logs"
  issues=$((issues + 1))
else
  echo "✅ no oversized log files"
fi

echo "[hygiene] checking stray temp files..."
stray_tmp="$(find . \
  -path "./.git" -prune -o \
  -type f \( -name "*.tmp" -o -name "*.temp" -o -name "*~" -o -name ".#*" \) \
  -print | sed "s#^\\./##" || true)"
if [[ -n "$stray_tmp" ]]; then
  echo "❌ stray temp files found:"
  printf "%s\n" "$stray_tmp"
  issues=$((issues + 1))
else
  echo "✅ no stray temp files"
fi

if [[ "$issues" -gt 0 ]]; then
  echo "\nREPO_HYGIENE_FAIL (${issues} issue group(s))"
  exit 1
fi

echo "\nREPO_HYGIENE_PASS"
