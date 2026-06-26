# Data Directory

This directory contains BidTabsData exports.

## Contents

Historical files are legacy BidTabs/Oman `.xls` exports. New macOS-friendly
public INDOT pulls are stored as `.csv` files generated from public Unit Tab
Results PDFs.

## File Format

Legacy `.xls` files keep the original 21 BidTabsData columns. New public `.csv`
files keep those columns and append `DistrictIDs` and `DistrictNames`.

For new consumers, `DistrictIDs` is the authoritative district-membership field.
`Region` remains a single legacy numeric value for backward compatibility.
