#!/usr/bin/env python3
"""
Create a release zip file from the BidTabsData repository.

This script packages the data/ directory into a zip file suitable for
distribution as a GitHub Release asset.

Usage:
    python create_release_zip.py --version v2024-12-26
    python create_release_zip.py --version v2024-12-26 --output /tmp/release.zip
"""

import argparse
import os
import sys
import zipfile
from pathlib import Path


def validate_structure(data_dir):
    """
    Validate the data directory structure.
    
    Args:
        data_dir: Path to the data directory
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not data_dir.exists():
        print(f"ERROR: Data directory does not exist: {data_dir}")
        return False
    
    if not data_dir.is_dir():
        print(f"ERROR: Data path is not a directory: {data_dir}")
        return False
    
    # Check for at least one .xls or .xlsx file
    xls_files = list(data_dir.glob("**/*.xls")) + list(data_dir.glob("**/*.xlsx"))
    
    if not xls_files:
        print(f"WARNING: No .xls or .xlsx files found in {data_dir}")
        print("The data directory appears to be empty.")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            return False
    else:
        print(f"Found {len(xls_files)} Excel file(s):")
        for xls_file in xls_files[:10]:  # Show first 10
            print(f"  - {xls_file.relative_to(data_dir)}")
        if len(xls_files) > 10:
            print(f"  ... and {len(xls_files) - 10} more")
    
    return True


def create_zip(data_dir, output_file, base_name="data"):
    """
    Create a zip file from the data directory.
    
    Args:
        data_dir: Path to the data directory
        output_file: Path to the output zip file
        base_name: Base directory name in the zip file
    """
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in data_dir.rglob("*"):
            if file_path.is_file():
                # Calculate the archive name (relative path within the zip)
                arcname = Path(base_name) / file_path.relative_to(data_dir)
                zipf.write(file_path, arcname)
                print(f"  Adding: {arcname}")
    
    file_size = output_file.stat().st_size
    print(f"\nCreated {output_file} ({file_size:,} bytes)")


def main():
    parser = argparse.ArgumentParser(
        description="Create a BidTabsData release zip file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_release_zip.py --version v2024-12-26
  python create_release_zip.py --version v2024-12-26 --output /tmp/release.zip
  python create_release_zip.py --version v2024-12-26 --data-dir custom/data
        """
    )
    
    parser.add_argument(
        "--version",
        required=True,
        help="Release version tag (e.g., v2024-12-26)"
    )
    
    parser.add_argument(
        "--output",
        help="Output zip file path (default: BidTabsData-{version}.zip)"
    )
    
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Path to data directory (default: data)"
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    data_dir = repo_root / args.data_dir
    
    # Determine output file
    if args.output:
        output_file = Path(args.output)
    else:
        output_file = repo_root / f"BidTabsData-{args.version}.zip"
    
    print(f"BidTabsData Release Zip Creator")
    print(f"================================")
    print(f"Version: {args.version}")
    print(f"Data directory: {data_dir}")
    print(f"Output file: {output_file}")
    print()
    
    # Always validate (validation is important for release integrity)
    print("Validating data directory structure...")
    if not validate_structure(data_dir):
        print("\nValidation failed. Exiting.")
        sys.exit(1)
    print("Validation passed.\n")
    
    # Create the zip file
    print("Creating release zip file...")
    try:
        create_zip(data_dir, output_file, base_name="data")
        print("\nSuccess! Release zip file created.")
        print(f"\nNext steps:")
        print(f"1. Create and push git tag: git tag {args.version} && git push origin {args.version}")
        print(f"2. Create GitHub release at: https://github.com/derek-betz/BidTabsData/releases/new")
        print(f"3. Upload {output_file.name} as a release asset")
    except Exception as e:
        print(f"\nERROR: Failed to create zip file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
