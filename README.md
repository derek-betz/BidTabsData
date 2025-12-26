# BidTabsData

Shared versioned dataset of BidTabs .xls files distributed via GitHub Releases for consuming repos.

## Purpose

This repository serves as a centralized location for versioned BidTabs data files exported from the BidTabs system. The primary goals are:

- **Single Source of Truth**: Maintain all BidTabs .xls exports in one repository
- **Version Control**: Track changes to data files over time with Git
- **Reliable Distribution**: Provide versioned releases for consuming repositories to depend on specific data snapshots
- **Reproducibility**: Enable consuming projects to pin specific data versions for consistent builds and testing

## Repository Structure

```
BidTabsData/
├── data/                    # BidTabs .xls data files
│   ├── project1/           # Organize by project or category
│   ├── project2/
│   └── ...
├── tools/                   # Utilities for working with BidTabs data
│   └── create_release_zip.py
└── README.md
```

### Recommended Structure Under `data/`

Organize your .xls files logically within the `data/` directory:

- **By Project**: `data/ProjectName/BidTabs_Export.xls`
- **By Date**: `data/2024-01/BidTabs_Export.xls`
- **By Category**: `data/erosion-control/BidTabs_Export.xls`

Choose a structure that best fits your workflow. Consuming repositories will receive the entire `data/` directory contents.

## Git LFS for .xls Files

**Recommended**: Use Git LFS (Large File Storage) for managing .xls files if they grow large or become numerous.

### Setting up Git LFS

```bash
# Install Git LFS (one-time setup)
git lfs install

# Track .xls and .xlsx files
git lfs track "*.xls"
git lfs track "*.xlsx"

# Commit the .gitattributes file
git add .gitattributes
git commit -m "Track Excel files with Git LFS"
```

This keeps your repository lightweight and improves performance when cloning or fetching.

## Publishing a Versioned Release

Releases use a date-based versioning scheme: `vYYYY-MM-DD`

### Step 1: Prepare Your Data

Ensure all .xls files in the `data/` directory are up-to-date and committed:

```bash
git add data/
git commit -m "Update BidTabs data for release vYYYY-MM-DD"
git push
```

### Step 2: Create a Release Zip

Use the provided tool to create the release artifact:

```bash
python tools/create_release_zip.py --version vYYYY-MM-DD
```

This creates `BidTabsData-vYYYY-MM-DD.zip` containing the `data/` directory contents.

### Step 3: Tag and Push

Create and push a git tag:

```bash
git tag vYYYY-MM-DD
git push origin vYYYY-MM-DD
```

### Step 4: Create GitHub Release

1. Go to https://github.com/derek-betz/BidTabsData/releases/new
2. Select the tag `vYYYY-MM-DD`
3. Set release title: `BidTabsData vYYYY-MM-DD`
4. Add release notes describing what data is included or what changed
5. Upload the `BidTabsData-vYYYY-MM-DD.zip` file as a release asset
6. Publish the release

### Example Release Notes

```markdown
## BidTabsData v2024-12-26

### Contents
- Project A BidTabs export (updated)
- Project B BidTabs export (new)
- Erosion control data (updated)

### Changes
- Added new project B data
- Updated Project A with latest bid information
```

## Adding a New Consuming Repository

To use BidTabsData in another repository, follow these steps:

### Step 1: Add the Fetch Script

Create `scripts/fetch_bidtabsdata.py` in your repository:

```python
#!/usr/bin/env python3
"""
Fetch BidTabsData release from GitHub and extract to local directory.

Environment Variables:
    BIDTABSDATA_REPO: GitHub repository (default: derek-betz/BidTabsData)
    BIDTABSDATA_VERSION: Required. Release version to fetch (e.g., v2024-12-26)
    BIDTABSDATA_OUT_DIR: Output directory (default: data-sample/BidTabsData)
    GITHUB_TOKEN: Optional. GitHub token for private releases
"""

import os
import sys
import urllib.request
import zipfile
import shutil
from pathlib import Path

def fetch_bidtabsdata():
    # Configuration from environment
    repo = os.environ.get('BIDTABSDATA_REPO', 'derek-betz/BidTabsData')
    version = os.environ.get('BIDTABSDATA_VERSION')
    out_dir = os.environ.get('BIDTABSDATA_OUT_DIR', 'data-sample/BidTabsData')
    github_token = os.environ.get('GITHUB_TOKEN')
    
    if not version:
        print("ERROR: BIDTABSDATA_VERSION environment variable is required")
        sys.exit(1)
    
    out_path = Path(out_dir)
    marker_file = out_path / '.bidtabsdata_version'
    
    # Check if already fetched (idempotent)
    if marker_file.exists():
        existing_version = marker_file.read_text().strip()
        if existing_version == version:
            print(f"BidTabsData {version} already fetched. Skipping.")
            return
    
    # Download release asset
    asset_name = f"BidTabsData-{version}.zip"
    download_url = f"https://github.com/{repo}/releases/download/{version}/{asset_name}"
    
    print(f"Downloading {asset_name} from {repo}...")
    
    request = urllib.request.Request(download_url)
    if github_token:
        request.add_header('Authorization', f'Bearer {github_token}')
    
    try:
        with urllib.request.urlopen(request) as response:
            zip_path = Path(f"/tmp/{asset_name}")
            with open(zip_path, 'wb') as f:
                f.write(response.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR: Failed to download release: {e}")
        print(f"URL: {download_url}")
        sys.exit(1)
    
    # Extract to temporary location
    temp_extract = Path(f"/tmp/bidtabsdata-{version}")
    if temp_extract.exists():
        shutil.rmtree(temp_extract)
    temp_extract.mkdir(parents=True)
    
    print(f"Extracting to {out_dir}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_extract)
    
    # Move to target directory
    if out_path.exists():
        shutil.rmtree(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if extraction created a subdirectory or extracted directly
    extracted_items = list(temp_extract.iterdir())
    if len(extracted_items) == 1 and extracted_items[0].is_dir():
        # Zip contained a single directory, move its contents
        shutil.move(str(extracted_items[0]), str(out_path))
    else:
        # Zip contained files directly, move the temp directory
        shutil.move(str(temp_extract), str(out_path))
    
    # Write marker file
    marker_file.write_text(version)
    print(f"Successfully fetched BidTabsData {version}")
    
    # Cleanup
    zip_path.unlink()

if __name__ == '__main__':
    fetch_bidtabsdata()
```

Make it executable:

```bash
chmod +x scripts/fetch_bidtabsdata.py
```

### Step 2: Update .gitignore

Add to your repository's `.gitignore`:

```gitignore
# BidTabsData - fetched at build time
data-sample/BidTabsData/
```

### Step 3: Update Documentation

Add to your README or setup instructions:

```markdown
## BidTabsData Setup

This project depends on BidTabsData releases for sample/test data.

### Fetch BidTabsData

Set the version and run the fetch script:

```bash
export BIDTABSDATA_VERSION=v2024-12-26
python scripts/fetch_bidtabsdata.py
```

The data will be downloaded to `data-sample/BidTabsData/`.
```

### Step 4: Add GitHub Actions Workflow

Create `.github/workflows/bidtabsdata.yml`:

```yaml
name: Fetch BidTabsData

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  fetch-data:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.x'
    
    - name: Cache BidTabsData
      uses: actions/cache@v3
      with:
        path: data-sample/BidTabsData
        key: bidtabsdata-${{ env.BIDTABSDATA_VERSION }}
    
    - name: Fetch BidTabsData
      env:
        BIDTABSDATA_VERSION: v2024-12-26  # Update this version as needed
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      run: |
        python -m pip install --upgrade pip
        python scripts/fetch_bidtabsdata.py
    
    - name: Verify BidTabsData
      run: |
        ls -la data-sample/BidTabsData/
        cat data-sample/BidTabsData/.bidtabsdata_version
```

### Step 5: Usage in Your Code

Access the data files from your code:

```python
from pathlib import Path

bidtabs_data_dir = Path("data-sample/BidTabsData/data")
for xls_file in bidtabs_data_dir.glob("**/*.xls"):
    print(f"Processing {xls_file}")
    # Your processing logic here
```

## Tools

### create_release_zip.py

Creates a release artifact zip file from the `data/` directory.

```bash
python tools/create_release_zip.py --version v2024-12-26
```

Options:
- `--version`: Release version tag (e.g., v2024-12-26)
- `--output`: Output zip file path (default: BidTabsData-{version}.zip)
- `--data-dir`: Path to data directory (default: data)

Note: The script always validates the data directory structure before creating the zip.

See `tools/create_release_zip.py --help` for more details.

## Contributing

1. Add or update .xls files in the `data/` directory
2. Commit your changes with descriptive messages
3. Create a new release following the versioning guidelines above

## License

[Specify your license here]
