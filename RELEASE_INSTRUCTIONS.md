# Release Instructions for v2026-01-01

## Release Preparation Completed ✓

The following items have been prepared for the v2026-01-01 release:

### 1. Release Artifact Created ✓
- **File**: `BidTabsData-v2026-01-01.zip`
- **Size**: 21,786,980 bytes (21 MB)
- **Contents**: 53 Excel files from data/BidTabsData directory
- **Date Range**: 2022-08-10 to 2025-12-10

### 2. Git Tag Created ✓
- **Tag**: `v2026-01-01`
- **Commit**: ca4c0f9
- **Message**: "Release v2026-01-01: BidTabsData with 53 Excel files from 2022-2025"

## Steps to Complete the Release

Since GitHub authentication is not available in the automated environment, complete the release manually:

### Option 1: Using GitHub Web Interface

1. **Push the tag to GitHub**:
   ```bash
   git push origin v2026-01-01
   ```

2. **Navigate to**: https://github.com/derek-betz/BidTabsData/releases/new

3. **Fill in the release form**:
   - **Tag**: Select `v2026-01-01` from dropdown
   - **Release title**: `BidTabsData v2026-01-01`
   - **Description**:
     ```markdown
     ## Contents
     - 53 BidTabs .xls exports in data/BidTabsData
     - Date range: 2022-08-10 to 2025-12-10
     
     ## Changes from v2025-12-26
     - Added 2025-12-10.xls (latest data)
     - Total files increased from 52 to 53
     ```

4. **Upload the release asset**:
   - Click "Attach binaries by dropping them here or selecting them"
   - Upload `BidTabsData-v2026-01-01.zip`

5. **Publish the release**

### Option 2: Using GitHub CLI

```bash
# Ensure you're authenticated
gh auth login

# Push the tag
git push origin v2026-01-01

# Create the release with multi-line notes
gh release create v2026-01-01 \
  --title "BidTabsData v2026-01-01" \
  --notes "## Contents
- 53 BidTabs .xls exports in data/BidTabsData
- Date range: 2022-08-10 to 2025-12-10

## Changes from v2025-12-26
- Added 2025-12-10.xls (latest data)
- Total files increased from 52 to 53" \
  BidTabsData-v2026-01-01.zip
```

## Verification

After creating the release, verify:

1. Tag `v2026-01-01` is visible at: https://github.com/derek-betz/BidTabsData/tags
2. Release is published at: https://github.com/derek-betz/BidTabsData/releases/tag/v2026-01-01
3. Release asset `BidTabsData-v2026-01-01.zip` is downloadable
4. Asset size is approximately 21 MB

## Data Summary

The release contains 53 Excel files:
- 2022: 7 files (Aug-Dec)
- 2023: 16 files (Jan-Dec)
- 2024: 13 files (Jan-Dec)
- 2025: 17 files (Jan-Dec)

Latest file: 2025-12-10.xls
