#!/bin/bash
# Complete the v2026-01-01 release
# Run this script after merging the PR to create and publish the GitHub release

set -e

REPO="derek-betz/BidTabsData"
VERSION="v2026-01-01"
ZIP_FILE="BidTabsData-v2026-01-01.zip"
RELEASE_TITLE="BidTabsData v2026-01-01"
# Using a here-document for multi-line release notes
read -r -d '' RELEASE_NOTES << 'EOF' || true
## Contents
- 53 BidTabs .xls exports in data/BidTabsData
- Date range: 2022-08-10 to 2025-12-10

## Changes from v2025-12-26
- Added 2025-12-10.xls (latest data)
- Total files increased from 52 to 53

## Data Summary
The release contains 53 Excel files spanning:
- 2022: 7 files
- 2023: 16 files
- 2024: 13 files
- 2025: 17 files
EOF

echo "============================================"
echo "BidTabsData v2026-01-01 Release Script"
echo "============================================"
echo ""

# Check if gh is authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ GitHub CLI is not authenticated."
    echo "Please run: gh auth login"
    exit 1
fi

echo "✓ GitHub CLI authenticated"
echo ""

# Check if we're in the right directory and the zip file exists
if [ ! -f "$ZIP_FILE" ]; then
    echo "❌ Release zip file not found: $ZIP_FILE"
    echo "Please run this script from the repository root."
    exit 1
fi

echo "✓ Found release zip file: $ZIP_FILE"
echo ""

# Check if tag exists locally
if ! git tag | grep -q "^$VERSION$"; then
    echo "❌ Git tag $VERSION not found locally."
    echo "Creating tag..."
    git tag "$VERSION" -m "Release $VERSION: BidTabsData with 53 Excel files from 2022-2025"
    echo "✓ Tag created"
fi

echo "✓ Git tag $VERSION exists"
echo ""

# Push the tag
echo "Pushing tag to GitHub..."
if git push origin "$VERSION"; then
    echo "✓ Tag pushed successfully"
else
    echo "⚠ Tag may already exist on remote (this is okay)"
fi

echo ""

# Check if release already exists
if gh release view "$VERSION" --repo "$REPO" &> /dev/null; then
    echo "⚠ Release $VERSION already exists"
    echo "To delete it, run: gh release delete $VERSION --repo $REPO --yes"
    exit 1
fi

echo "Creating GitHub release..."
gh release create "$VERSION" \
    --repo "$REPO" \
    --title "$RELEASE_TITLE" \
    --notes "$RELEASE_NOTES" \
    "$ZIP_FILE"

echo ""
echo "============================================"
echo "✓ Release published successfully!"
echo "============================================"
echo ""
echo "View the release at:"
echo "https://github.com/$REPO/releases/tag/$VERSION"
echo ""
echo "Download the asset:"
echo "https://github.com/$REPO/releases/download/$VERSION/$ZIP_FILE"
