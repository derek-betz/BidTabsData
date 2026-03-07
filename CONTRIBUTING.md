# Contributing

## Repository hygiene baseline
- Keep changes small and reviewable.
- Avoid committing generated junk (`.DS_Store`, `*.tmp`, backup files, oversized logs).
- Run `scripts/check-repo-hygiene.sh` before opening a PR.
- For cron/logging scripts, prefer bounded logs (rotation/size caps) and dry-run clarity (`current` vs `proposed`).
