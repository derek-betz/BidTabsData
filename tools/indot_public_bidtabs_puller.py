#!/usr/bin/env python3
"""Pull public INDOT Unit Tab Results into BidTabsData-shaped CSV files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path


INDEX_URL = "https://www.in.gov/indot/doing-business-with-indot/home/contracts/"
ARCHIVE_URL = "https://www.in.gov/indot/doing-business-with-indot/home/contracts/letting-archives2/"
MODERN_ARCHIVE_START = date(2018, 1, 1)

LEGACY_HEADERS = [
    "Pay Item",
    "Description",
    "Quantity",
    "Unit",
    "Unit Price",
    "Bid Date",
    "Bidder Name",
    "ProjectID",
    "Job Size",
    "Job Desc",
    "County",
    "Region",
    "Pos",
    "Extension",
    "Bidder2Name",
    "Bidder3Name",
    "Bidder2Total",
    "Bidder3Total",
    "JobFederalID",
    "PopulationArea",
    "StateID",
]
DISTRICT_HEADERS = ["DistrictIDs", "DistrictNames"]
HEADERS = [*LEGACY_HEADERS, *DISTRICT_HEADERS]
FINANCIAL_FIELDS = ["Unit Price", "Extension", "Job Size", "Bidder2Total", "Bidder3Total"]
COMPARE_KEY_FIELDS = ["ProjectID", "Pay Item", "Pos", "Quantity"]

DATA_DIR_CANDIDATES = [
    Path.home() / "Projects/personal/BidTabsData/data/BidTabsData",
    Path.home() / "github/derek-betz/BidTabsData/data/BidTabsData",
]

DISTRICT_CODES = {
    "CRAWFORDSVILLE": 1,
    "FORT WAYNE": 2,
    "GREENFIELD": 3,
    "LAPORTE": 4,
    "SEYMOUR": 5,
    "VINCENNES": 6,
}

MONTH_NUMBERS = {
    "JAN": 1,
    "JANUARY": 1,
    "FEB": 2,
    "FEBRUARY": 2,
    "MAR": 3,
    "MARCH": 3,
    "APR": 4,
    "APRIL": 4,
    "MAY": 5,
    "JUN": 6,
    "JUNE": 6,
    "JUL": 7,
    "JULY": 7,
    "AUG": 8,
    "AUGUST": 8,
    "SEP": 9,
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
}

UNIT_MAP = {
    "DOL": "$",
    "LS": "L.S.",
    "LFT": "L.F.",
    "CYS": "C.Y.",
    "SYS": "SYS",
    "SFT": "S.F.",
    "MG": "M.G.",
    "kGAL": "M.G.",
}

ITEM_RE = re.compile(r"^\s*(\d{4})\s+(\d{3}-\d+)\s+(.*)$")
NUM_RE = re.compile(r"\(\d+\)|\$?-?\d[\d,]*(?:\.\d+)?")
CONTRACT_RE = re.compile(r"Contract ID:\s+(.+?)\s+Counties:\s+(.+)$")
LETTING_RE = re.compile(r"Letting Date:\s+(.+?)\s+District\(s\):\s+(.+)$")
CALL_PROJECT_RE = re.compile(r"Call Order:\s+(.+?)\s+Project\(s\):\s+(.+)$")
DATE_TEXT_RE = re.compile(
    r"\b("
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?"
    r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(\d{4})",
    re.IGNORECASE,
)


class PullerError(RuntimeError):
    """Raised when a public INDOT export cannot be produced."""


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str


@dataclass(frozen=True)
class LettingPage:
    letting_date: date
    title: str
    url: str


@dataclass
class Item:
    line_no: str
    pay_item: str
    quantity: float
    description: str
    unit: str
    bids: dict[int, tuple[float, float]] = field(default_factory=dict)


@dataclass
class Contract:
    contract_id: str
    counties: str = ""
    letting_date: str = ""
    district: str = ""
    call_order: str = ""
    projects: str = ""
    description: str = ""
    bidder_names: dict[int, str] = field(default_factory=dict)
    totals: dict[int, float] = field(default_factory=dict)
    items: dict[tuple[str, str], Item] = field(default_factory=dict)


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[Anchor] = []
        self._href_stack: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href") or ""
        self._href_stack.append(href)
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href_stack:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        text = compact(" ".join(self._text_parts))
        if href and text:
            self.anchors.append(Anchor(href=href, text=text))
        self._text_parts = []


def fetch_text(url: str, *, timeout: int = 60) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "BidTabsData public puller"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_bytes(url: str, *, timeout: int = 180) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "BidTabsData public puller"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_anchors(html: str, base_url: str) -> list[Anchor]:
    parser = AnchorParser()
    parser.feed(html)
    return [Anchor(href=urllib.parse.urljoin(base_url, anchor.href), text=anchor.text) for anchor in parser.anchors]


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_letting_date(value: str) -> date | None:
    text = compact(value.replace("\u2014", " ").replace("\u2013", " "))
    match = DATE_TEXT_RE.search(text)
    if not match:
        return None
    try:
        month_token, day_token, year_token = match.groups()
        month_key = month_token.replace(".", "").upper()
        month = MONTH_NUMBERS.get(month_key) or MONTH_NUMBERS.get(month_key[:3])
        if not month:
            return None
        return date(int(year_token), month, int(day_token))
    except ValueError:
        return None


def parse_cli_date(value: str) -> date | None:
    parsed = parse_file_date(value)
    if parsed:
        return parsed
    return parse_letting_date(value)


def is_probable_letting_page(anchor: Anchor) -> bool:
    href = anchor.href.lower()
    if href.endswith((".pdf", ".txt", ".xls", ".xlsx", ".doc", ".docx")):
        return False
    if "#" in href and href.rstrip("/").endswith(tuple(f"#{year}" for year in range(1990, 2051))):
        return False
    return "contracts/letting" in href or "/home/contracts/" in href


def discover_letting_pages(
    index_url: str = INDEX_URL,
    archive_url: str | None = ARCHIVE_URL,
    *,
    min_date: date | None = MODERN_ARCHIVE_START,
    max_date: date | None = None,
) -> list[LettingPage]:
    source_urls = [index_url]
    if archive_url and archive_url not in source_urls:
        source_urls.append(archive_url)

    pages: dict[str, LettingPage] = {}
    for source_url in source_urls:
        html = fetch_text(source_url)
        for anchor in parse_anchors(html, source_url):
            text = compact(anchor.text)
            letting_date = parse_letting_date(text)
            if not letting_date or not is_probable_letting_page(anchor):
                continue
            if min_date and letting_date < min_date:
                continue
            if max_date and letting_date > max_date:
                continue
            page_url = anchor.href.rstrip("/")
            pages[page_url] = LettingPage(letting_date=letting_date, title=text, url=anchor.href)
    return sorted(pages.values(), key=lambda page: (page.letting_date, page.title, page.url))


def find_unit_tab_pdfs(page: LettingPage) -> list[str]:
    html = fetch_text(page.url)
    urls: list[str] = []
    for anchor in parse_anchors(html, page.url):
        href_without_query = anchor.href.split("?", 1)[0].lower()
        if "unit tab" in anchor.text.lower() and href_without_query.endswith(".pdf"):
            if anchor.href not in urls:
                urls.append(anchor.href)
    return urls


def find_unit_tab_pdf(page: LettingPage) -> str | None:
    pdfs = find_unit_tab_pdfs(page)
    return pdfs[0] if pdfs else None


def default_data_dir() -> Path:
    env_dir = os.getenv("BIDTABS_OUTPUT_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    for candidate in DATA_DIR_CANDIDATES:
        if candidate.exists():
            return candidate
    return DATA_DIR_CANDIDATES[0]


def existing_date_stems(path: Path) -> set[date]:
    dates: set[date] = set()
    if not path.exists():
        return dates
    for file in path.iterdir():
        parsed = parse_file_date(file.stem)
        if parsed:
            dates.add(parsed)
    return dates


def parse_file_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def convert_pdf_to_text(pdf_path: Path) -> str:
    if not shutil.which("pdftotext"):
        raise PullerError("pdftotext is required. Install Poppler, or run this on a Mac with pdftotext available.")
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), tmp.name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return Path(tmp.name).read_text(errors="replace")


def parse_money(token: str) -> float:
    token = token.strip().replace("$", "").replace(",", "")
    if token.startswith("(") and token.endswith(")"):
        return float(token[1:-1])
    return float(token)


def parse_quantity(token: str) -> float:
    return 1.0 if token.startswith("(") else parse_money(token)


def parse_bidder_columns(lines: list[str]) -> dict[int, str]:
    header_idx = next((i for i, line in enumerate(lines) if "Line No / Item ID" in line), None)
    if header_idx is None:
        return {}

    header = lines[header_idx]
    matches = list(re.finditer(r"\((\d+)\)\s+(.+?)(?=\s{2,}\(\d+\)|$)", header))
    if not matches:
        return {}

    starts = [max(0, m.start(0) - 6) for m in matches]
    ends = [max(0, matches[i + 1].start(0) - 6) for i in range(len(matches) - 1)] + [len(header) + 45]
    names: dict[int, list[str]] = {}

    for match in matches:
        names[int(match.group(1))] = [compact(match.group(2))]

    for line in lines[header_idx + 1 :]:
        if "Alt Set / Alt Member" in line:
            break
        if not line.strip():
            continue
        for match, start, end in zip(matches, starts, ends):
            fragment = compact(line[start:end])
            if fragment and fragment != "Item Description":
                names[int(match.group(1))].append(fragment)

    return {pos: compact(" ".join(parts)) for pos, parts in names.items()}


def parse_contract_header(lines: list[str]) -> tuple[str | None, dict[str, str]]:
    info: dict[str, str] = {}
    contract_id: str | None = None
    for i, line in enumerate(lines[:18]):
        if match := CONTRACT_RE.search(line):
            contract_id = compact(match.group(1))
            info["counties"] = compact(match.group(2))
        elif match := LETTING_RE.search(line):
            info["letting_date"] = compact(match.group(1))
            info["district"] = compact(match.group(2))
        elif match := CALL_PROJECT_RE.search(line):
            info["call_order"] = compact(match.group(1))
            info["projects"] = compact(match.group(2))
        elif "Contract Description:" in line:
            desc = line.split("Contract Description:", 1)[1].strip()
            extra_parts = []
            for extra in lines[i + 1 : min(i + 4, len(lines))]:
                stripped = extra.strip()
                if not stripped:
                    continue
                if any(
                    marker in stripped
                    for marker in (
                        "Line No / Item ID",
                        "Item Description",
                        "Alt Set",
                        "Section Totals:",
                        "Contract Item Totals",
                        "Contract Time Totals",
                        "Contract Grand Totals",
                        "Contract Life Cycle Costs Totals",
                        "( ) indicates item is bid as Lump Sum",
                    )
                ):
                    break
                if re.match(r"^(Contract ID|Letting Date|Call Order|Contract Time):", stripped):
                    break
                extra_parts.append(stripped)
            info["description"] = compact(" ".join([desc, *extra_parts]))
    return contract_id, info


def parse_item_description(lines: list[str]) -> tuple[str, str]:
    parts: list[str] = []
    unit = ""
    for line in lines:
        text = compact(line)
        if not text:
            continue
        tokens = text.split()
        maybe_unit = tokens[-1].strip()
        normalized = UNIT_MAP.get(maybe_unit, maybe_unit)
        if (maybe_unit.isupper() or maybe_unit in UNIT_MAP) and len(maybe_unit) <= 8 and not unit:
            unit = normalized
            text = compact(" ".join(tokens[:-1]))
        if text:
            parts.append(text)
    return compact(" ".join(parts)), unit


def item_following_lines(lines: list[str], start_idx: int) -> list[str]:
    out: list[str] = []
    for line in lines[start_idx + 1 :]:
        stripped = line.strip()
        if ITEM_RE.match(line):
            break
        if any(
            marker in stripped
            for marker in (
                "Section Totals:",
                "Contract Item Totals",
                "Contract Time Totals",
                "Contract Grand Totals",
                "Life Cycle Costs",
                "Section Total with LCC",
                "Indiana Department of Transportation",
                "Contract ID:",
                "Letting Date:",
                "Line No / Item ID",
                "Alt Set / Alt Member",
                "( ) indicates item is bid as Lump Sum",
            )
        ):
            break
        if stripped.startswith("SECTION:"):
            break
        out.append(line)
    return out


def parse_page_items(lines: list[str], bidder_positions: list[int]) -> list[Item]:
    items: list[Item] = []
    for idx, line in enumerate(lines):
        match = ITEM_RE.match(line)
        if not match:
            continue

        line_no, pay_item, tail = match.groups()
        tokens = NUM_RE.findall(tail)
        if len(tokens) < 1 + len(bidder_positions) * 2:
            continue

        quantity = parse_quantity(tokens[0])
        bid_tokens = tokens[1:]
        item = Item(line_no=line_no, pay_item=pay_item, quantity=quantity, description="", unit="")
        for bid_idx, pos in enumerate(bidder_positions):
            offset = bid_idx * 2
            if offset + 1 >= len(bid_tokens):
                break
            item.bids[pos] = (parse_money(bid_tokens[offset]), parse_money(bid_tokens[offset + 1]))

        desc, unit = parse_item_description(item_following_lines(lines, idx))
        item.description = desc
        item.unit = unit
        items.append(item)
    return items


def parse_grand_totals(lines: list[str], bidder_positions: list[int]) -> dict[int, float]:
    totals: dict[int, float] = {}
    for line in lines:
        if "Contract Grand Totals" not in line:
            continue
        numbers = re.findall(r"\$?\d[\d,]*\.\d{2}", line)
        for pos, value in zip(bidder_positions, numbers):
            totals[pos] = parse_money(value)
    return totals


def parse_pdf_text(text: str) -> list[Contract]:
    contracts: dict[str, Contract] = {}
    last_positions_by_contract: dict[str, list[int]] = {}
    for raw_page in text.split("\f"):
        lines = raw_page.splitlines()
        if not any(line.strip() for line in lines):
            continue

        contract_id, info = parse_contract_header(lines)
        if not contract_id:
            continue

        contract = contracts.setdefault(contract_id, Contract(contract_id=contract_id))
        for key, value in info.items():
            if value and not getattr(contract, key):
                setattr(contract, key, value)

        page_bidders = parse_bidder_columns(lines)
        if page_bidders:
            contract.bidder_names.update(page_bidders)
            last_positions_by_contract[contract_id] = sorted(page_bidders)
        bidder_positions = sorted(page_bidders) or last_positions_by_contract.get(contract_id, [])
        if not bidder_positions:
            continue

        contract.totals.update(parse_grand_totals(lines, bidder_positions))

        for page_item in parse_page_items(lines, bidder_positions):
            key = (page_item.line_no, page_item.pay_item)
            item = contract.items.get(key)
            if item is None:
                contract.items[key] = page_item
            else:
                if not item.description and page_item.description:
                    item.description = page_item.description
                if not item.unit and page_item.unit:
                    item.unit = page_item.unit
                item.bids.update(page_item.bids)

    return [contracts[key] for key in sorted(contracts)]


def format_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%B %d, %Y").strftime("%m/%d/%Y")
    except ValueError:
        return value


def district_membership(district: str) -> tuple[list[int], list[str]]:
    text = compact(district).upper()
    matches: list[tuple[int, str]] = []
    for name in DISTRICT_CODES:
        for match in re.finditer(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", text):
            matches.append((match.start(), name))

    names: list[str] = []
    seen: set[str] = set()
    for _, name in sorted(matches):
        if name not in seen:
            seen.add(name)
            names.append(name)

    if not names:
        parts = [compact(part).upper() for part in re.split(r"[,;/]+|\band\b", text) if compact(part)]
        for part in parts:
            if part in DISTRICT_CODES and part not in seen:
                seen.add(part)
                names.append(part)

    ids = [DISTRICT_CODES[name] for name in names]
    return ids, names


def region_for_district_ids(district_ids: list[int]) -> int | str:
    return district_ids[0] if district_ids else ""


def rows_for_contract(contract: Contract) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    district_ids, district_names = district_membership(contract.district)
    region = region_for_district_ids(district_ids)
    district_id_text = ",".join(str(district_id) for district_id in district_ids)
    district_name_text = ",".join(district_names)
    positions = sorted(contract.bidder_names)
    bidder2_name = contract.bidder_names.get(2, "")
    bidder3_name = contract.bidder_names.get(3, "")
    bidder2_total = contract.totals.get(2, "")
    bidder3_total = contract.totals.get(3, "")
    job_size = contract.totals.get(1, "")

    for item in sorted(contract.items.values(), key=lambda i: int(i.line_no)):
        for pos in positions:
            bid = item.bids.get(pos)
            if not bid:
                continue
            unit_price, extension = bid
            rows.append(
                {
                    "Pay Item": item.pay_item,
                    "Description": item.description,
                    "Quantity": item.quantity,
                    "Unit": item.unit,
                    "Unit Price": unit_price,
                    "Bid Date": format_date(contract.letting_date),
                    "Bidder Name": contract.bidder_names.get(pos, ""),
                    "ProjectID": contract.contract_id,
                    "Job Size": job_size,
                    "Job Desc": contract.description,
                    "County": contract.counties,
                    "Region": region,
                    "Pos": pos,
                    "Extension": extension,
                    "Bidder2Name": bidder2_name,
                    "Bidder3Name": bidder3_name,
                    "Bidder2Total": bidder2_total,
                    "Bidder3Total": bidder3_total,
                    "JobFederalID": contract.projects,
                    "PopulationArea": "",
                    "StateID": "IN",
                    "DistrictIDs": district_id_text,
                    "DistrictNames": district_name_text,
                }
            )
    return rows


def parse_pdf(pdf_path: Path) -> list[dict[str, object]]:
    contracts = parse_pdf_text(convert_pdf_to_text(pdf_path))
    rows: list[dict[str, object]] = []
    for contract in contracts:
        rows.extend(rows_for_contract(contract))
    return rows


def validate_rows(rows: list[dict[str, object]]) -> None:
    if not rows:
        raise PullerError("No bid rows were parsed from the Unit Tab Results PDF.")
    required = [
        "Pay Item",
        "Description",
        "Quantity",
        "Unit",
        "Unit Price",
        "Bid Date",
        "Bidder Name",
        "ProjectID",
        "Job Size",
        "Job Desc",
        "County",
        "Region",
        "Pos",
        "Extension",
        "JobFederalID",
        "StateID",
        "DistrictIDs",
        "DistrictNames",
    ]
    missing = {key: 0 for key in required}
    for row in rows:
        for key in required:
            if row.get(key) in ("", None):
                missing[key] += 1
    bad = {key: value for key, value in missing.items() if value}
    if bad:
        raise PullerError(f"Parsed rows have missing required fields: {bad}")


def write_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def legacy_public_csv_needs_upgrade(path: Path) -> bool:
    if not path.exists() or path.suffix.lower() != ".csv":
        return False
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle), [])
    except OSError:
        return False
    return header == LEGACY_HEADERS


def cache_file_name(pdf_url: str) -> str:
    parsed = urllib.parse.urlparse(pdf_url)
    original_name = urllib.parse.unquote(Path(parsed.path).name) or "unit-tab-results.pdf"
    suffix = Path(original_name).suffix or ".pdf"
    stem = Path(original_name).stem or "unit-tab-results"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "unit-tab-results"
    digest = hashlib.sha256(pdf_url.encode("utf-8")).hexdigest()[:12]
    return f"{safe_stem}-{digest}{suffix}"


def download_pdf(pdf_url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = cache_dir / cache_file_name(pdf_url)
    if not pdf_path.exists():
        pdf_path.write_bytes(fetch_bytes(pdf_url))
    return pdf_path


def sort_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    def key(row: dict[str, object]) -> tuple[str, str, int, str, str]:
        try:
            pos = int(float(str(row.get("Pos", "0"))))
        except ValueError:
            pos = 0
        return (
            str(row.get("ProjectID", "")),
            str(row.get("Pay Item", "")),
            pos,
            str(row.get("Bidder Name", "")),
            str(row.get("Extension", "")),
        )

    return sorted(rows, key=key)


def should_write_output(output_path: Path, *, overwrite: bool) -> bool:
    if overwrite or not output_path.exists():
        return True
    return legacy_public_csv_needs_upgrade(output_path)


def export_pages(pages: list[LettingPage], output_dir: Path, cache_dir: Path, *, overwrite: bool = False) -> Path | None:
    if not pages:
        return None

    letting_date = pages[0].letting_date
    output_path = output_dir / f"{letting_date.isoformat()}.csv"
    if not should_write_output(output_path, overwrite=overwrite):
        return None

    pdf_urls: list[str] = []
    for page in pages:
        for pdf_url in find_unit_tab_pdfs(page):
            if pdf_url not in pdf_urls:
                pdf_urls.append(pdf_url)
    if not pdf_urls:
        return None

    rows: list[dict[str, object]] = []
    for pdf_url in pdf_urls:
        pdf_path = download_pdf(pdf_url, cache_dir)
        rows.extend(parse_pdf(pdf_path))
    rows = sort_rows(rows)
    validate_rows(rows)
    write_csv(rows, output_path)
    return output_path


def export_page(page: LettingPage, output_dir: Path, cache_dir: Path, *, overwrite: bool = False) -> Path | None:
    return export_pages([page], output_dir, cache_dir, overwrite=overwrite)


def cmd_list(args: argparse.Namespace) -> int:
    pages = discover_letting_pages(
        args.index_url,
        args.archive_url,
        min_date=parse_cli_date(args.min_date) if args.min_date else None,
        max_date=parse_cli_date(args.max_date) if args.max_date else None,
    )
    for page in pages:
        if args.with_pdfs:
            pdf_count = len(find_unit_tab_pdfs(page))
            print(f"{page.letting_date.isoformat()}  pdfs={pdf_count}  {page.title}  {page.url}")
        else:
            print(f"{page.letting_date.isoformat()}  {page.title}  {page.url}")
    return 0


def cmd_parse_pdf(args: argparse.Namespace) -> int:
    rows = parse_pdf(args.pdf)
    validate_rows(rows)
    write_csv(rows, args.output)
    print(json.dumps({"rows": len(rows), "output": str(args.output)}, indent=2))
    return 0


def cmd_export_url(args: argparse.Namespace) -> int:
    letting_date = parse_file_date(args.date)
    if not letting_date:
        raise PullerError(f"Could not parse letting date: {args.date}")
    page = LettingPage(letting_date=letting_date, title=args.date, url=args.url)
    output = export_page(page, args.output_dir, args.cache_dir, overwrite=args.overwrite)
    if output:
        print(json.dumps({"exported": str(output)}, indent=2))
    else:
        print("No Unit Tab Results PDF found, or output already exists.")
    return 0


def pages_by_date(pages: list[LettingPage]) -> dict[date, list[LettingPage]]:
    grouped: dict[date, list[LettingPage]] = defaultdict(list)
    for page in pages:
        grouped[page.letting_date].append(page)
    return dict(grouped)


def discover_pages_for_args(args: argparse.Namespace) -> list[LettingPage]:
    min_date = parse_cli_date(args.min_date) if getattr(args, "min_date", None) else MODERN_ARCHIVE_START
    max_date = parse_cli_date(args.max_date) if getattr(args, "max_date", None) else None
    return discover_letting_pages(args.index_url, args.archive_url, min_date=min_date, max_date=max_date)


def cmd_export_date(args: argparse.Namespace) -> int:
    requested_dates = [parse_cli_date(value) for value in args.dates]
    bad_dates = [value for value, parsed in zip(args.dates, requested_dates) if parsed is None]
    if bad_dates:
        raise PullerError(f"Could not parse letting date(s): {', '.join(bad_dates)}")

    grouped = pages_by_date(discover_pages_for_args(args))
    exported: list[str] = []
    skipped: list[str] = []
    for letting_date in requested_dates:
        assert letting_date is not None
        output = export_pages(grouped.get(letting_date, []), args.output_dir, args.cache_dir, overwrite=args.overwrite)
        if output:
            exported.append(str(output))
            print(f"exported {output}")
        else:
            skipped.append(letting_date.isoformat())
    print(json.dumps({"exported": exported, "skipped": skipped}, indent=2))
    return 0


def cmd_weekly(args: argparse.Namespace) -> int:
    output_dir = args.output_dir
    existing = existing_date_stems(output_dir)
    pages = discover_pages_for_args(args)
    if args.lookback_days:
        cutoff = date.today() - timedelta(days=args.lookback_days)
        pages = [page for page in pages if page.letting_date >= cutoff]
    if not args.include_future:
        pages = [page for page in pages if page.letting_date <= date.today()]
    if args.newer_than_existing and existing:
        newest = max(existing)
        pages = [page for page in pages if page.letting_date > newest]
    elif not args.overwrite:
        pages = [
            page
            for page in pages
            if page.letting_date not in existing
            or legacy_public_csv_needs_upgrade(output_dir / f"{page.letting_date.isoformat()}.csv")
        ]

    exported: list[str] = []
    skipped: list[str] = []
    for letting_date, date_pages in sorted(pages_by_date(pages).items()):
        output = export_pages(date_pages, output_dir, args.cache_dir, overwrite=args.overwrite)
        if output:
            exported.append(str(output))
            print(f"exported {output}")
        else:
            skipped.append(letting_date.isoformat())

    print(json.dumps({"exported": exported, "skipped": skipped}, indent=2))
    return 0


def load_csv_rows(path: Path) -> tuple[list[str], list[dict[str, object]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def load_xls_rows(path: Path) -> tuple[list[str], list[dict[str, object]]]:
    try:
        import xlrd  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PullerError(
            "xlrd is required to compare legacy .xls exports. "
            "Install it with `python3 -m pip install xlrd` or use the repo's requirements file."
        ) from exc

    workbook = xlrd.open_workbook(path)
    sheet = workbook.sheet_by_index(0)
    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    rows: list[dict[str, object]] = []
    for row_idx in range(1, sheet.nrows):
        row: dict[str, object] = {}
        for col_idx, header in enumerate(headers):
            value = sheet.cell_value(row_idx, col_idx)
            if sheet.cell_type(row_idx, col_idx) == xlrd.XL_CELL_DATE:
                value = datetime(*xlrd.xldate_as_tuple(value, workbook.datemode)).strftime("%m/%d/%Y")
            row[header] = value
        rows.append(row)
    return headers, rows


def decimal_value(value: object) -> Decimal | None:
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def normalize_key_value(field: str, value: object) -> str:
    decimal = decimal_value(value)
    if decimal is not None:
        if field == "Pos":
            return str(int(decimal))
        if field == "Quantity":
            return str(decimal.normalize())
    return compact(str(value)).upper()


def compare_key(row: dict[str, object]) -> tuple[str, ...]:
    return tuple(normalize_key_value(field, row.get(field, "")) for field in COMPARE_KEY_FIELDS)


def financially_matches(
    old_row: dict[str, object],
    public_row: dict[str, object],
    *,
    tolerance: Decimal,
    fields: list[str] | None = None,
) -> bool:
    for field in fields or FINANCIAL_FIELDS:
        old_decimal = decimal_value(old_row.get(field, ""))
        public_decimal = decimal_value(public_row.get(field, ""))
        if old_decimal is None or public_decimal is None:
            if compact(str(old_row.get(field, ""))) != compact(str(public_row.get(field, ""))):
                return False
            continue
        if abs(old_decimal - public_decimal) > tolerance:
            return False
    return True


def count_financial_matches(
    old_rows: list[dict[str, object]],
    public_rows: list[dict[str, object]],
    *,
    tolerance: Decimal,
    fields: list[str] | None = None,
) -> int:
    public_by_key: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for row in public_rows:
        public_by_key[compare_key(row)].append(row)

    matches = 0
    for old_row in old_rows:
        key = compare_key(old_row)
        candidates = public_by_key.get(key, [])
        for index, candidate in enumerate(candidates):
            if financially_matches(old_row, candidate, tolerance=tolerance, fields=fields):
                matches += 1
                del candidates[index]
                break
    return matches


def required_field_missing_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    required = [
        "Pay Item",
        "Description",
        "Quantity",
        "Unit",
        "Unit Price",
        "Bid Date",
        "Bidder Name",
        "ProjectID",
        "Job Size",
        "Job Desc",
        "County",
        "Region",
        "Pos",
        "Extension",
        "JobFederalID",
        "StateID",
        "DistrictIDs",
        "DistrictNames",
    ]
    missing = {key: 0 for key in required}
    for row in rows:
        for key in required:
            if row.get(key) in ("", None):
                missing[key] += 1
    return {key: value for key, value in missing.items() if value}


def validate_csv_file(path: Path) -> dict[str, object]:
    headers, rows = load_csv_rows(path)
    missing_headers = [header for header in HEADERS if header not in headers]
    extra_headers = [header for header in headers if header not in HEADERS]
    missing_fields = required_field_missing_counts(rows)
    multi_district_rows = sum(1 for row in rows if "," in str(row.get("DistrictIDs", "")))
    return {
        "path": str(path),
        "rows": len(rows),
        "missing_headers": missing_headers,
        "extra_headers": extra_headers,
        "missing_required_fields": missing_fields,
        "multi_district_rows": multi_district_rows,
    }


def compare_public_to_xls(public_csv: Path, old_xls: Path) -> dict[str, object]:
    _, public_rows = load_csv_rows(public_csv)
    _, old_rows = load_xls_rows(old_xls)

    old_keys = [compare_key(row) for row in old_rows]
    public_keys = [compare_key(row) for row in public_rows]
    old_key_counts: dict[tuple[str, ...], int] = defaultdict(int)
    public_key_counts: dict[tuple[str, ...], int] = defaultdict(int)
    for key in old_keys:
        old_key_counts[key] += 1
    for key in public_keys:
        public_key_counts[key] += 1

    key_overlap = sum(min(old_key_counts[key], public_key_counts.get(key, 0)) for key in old_key_counts)
    old_contracts = {compact(str(row.get("ProjectID", ""))) for row in old_rows if row.get("ProjectID")}
    public_contracts = {compact(str(row.get("ProjectID", ""))) for row in public_rows if row.get("ProjectID")}
    exact_financial_matches = count_financial_matches(old_rows, public_rows, tolerance=Decimal("0"))
    penny_tolerant_financial_matches = count_financial_matches(old_rows, public_rows, tolerance=Decimal("0.01"))
    exact_extension_matches = count_financial_matches(
        old_rows,
        public_rows,
        tolerance=Decimal("0"),
        fields=["Extension"],
    )
    penny_tolerant_extension_matches = count_financial_matches(
        old_rows,
        public_rows,
        tolerance=Decimal("0.01"),
        fields=["Extension"],
    )
    validation = validate_csv_file(public_csv)

    return {
        "date": public_csv.stem,
        "old_rows": len(old_rows),
        "public_rows": len(public_rows),
        "old_rows_recovered_by_key": key_overlap,
        "old_rows_recovered_penny_tolerant": penny_tolerant_extension_matches,
        "old_rows_missing_by_key": len(old_rows) - key_overlap,
        "public_only_rows_by_key": len(public_rows) - key_overlap,
        "old_contracts": len(old_contracts),
        "public_contracts": len(public_contracts),
        "public_only_contracts": sorted(public_contracts - old_contracts),
        "exact_financial_matches": exact_financial_matches,
        "penny_tolerant_financial_matches": penny_tolerant_financial_matches,
        "exact_extension_matches": exact_extension_matches,
        "penny_tolerant_extension_matches": penny_tolerant_extension_matches,
        "missing_required_fields": validation["missing_required_fields"],
        "multi_district_rows": validation["multi_district_rows"],
    }


def cmd_validate_csv(args: argparse.Namespace) -> int:
    reports = [validate_csv_file(path) for path in args.csvs]
    print(json.dumps(reports, indent=2, sort_keys=True))
    has_error = any(report["missing_headers"] or report["missing_required_fields"] for report in reports)
    return 2 if has_error else 0


def cmd_compare_xls(args: argparse.Namespace) -> int:
    requested_dates = [parse_cli_date(value) for value in args.dates]
    bad_dates = [value for value, parsed in zip(args.dates, requested_dates) if parsed is None]
    if bad_dates:
        raise PullerError(f"Could not parse letting date(s): {', '.join(bad_dates)}")

    grouped = pages_by_date(discover_pages_for_args(args))
    reports: list[dict[str, object]] = []
    for letting_date in requested_dates:
        assert letting_date is not None
        public_csv = args.public_dir / f"{letting_date.isoformat()}.csv"
        old_xls = args.xls_dir / f"{letting_date.isoformat()}.xls"
        if not old_xls.exists():
            raise PullerError(f"Missing legacy .xls for comparison: {old_xls}")
        if args.refresh_public or not public_csv.exists():
            output = export_pages(grouped.get(letting_date, []), args.public_dir, args.cache_dir, overwrite=True)
            if not output:
                raise PullerError(f"No public Unit Tab Results PDF could be exported for {letting_date.isoformat()}")
        reports.append(compare_public_to_xls(public_csv, old_xls))

    totals = {
        "dates": len(reports),
        "old_rows": sum(int(report["old_rows"]) for report in reports),
        "public_rows": sum(int(report["public_rows"]) for report in reports),
        "old_rows_recovered_penny_tolerant": sum(
            int(report["old_rows_recovered_penny_tolerant"]) for report in reports
        ),
        "public_only_rows_by_key": sum(int(report["public_only_rows_by_key"]) for report in reports),
        "multi_district_rows": sum(int(report["multi_district_rows"]) for report in reports),
    }
    print(json.dumps({"totals": totals, "dates": reports}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-url", default=INDEX_URL, help="INDOT contracts index URL.")
    parser.add_argument("--archive-url", default=ARCHIVE_URL, help="INDOT letting archives URL.")
    parser.add_argument("--output-dir", type=Path, default=default_data_dir(), help="Directory for output CSV files.")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".bidtabs-cache/indot-public"),
        help="Directory for downloaded Unit Tab Results PDFs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cmd = subparsers.add_parser("list", help="List letting pages discovered on public INDOT pages.")
    list_cmd.add_argument("--index-url", default=INDEX_URL, help="INDOT contracts index URL.")
    list_cmd.add_argument("--archive-url", default=ARCHIVE_URL, help="INDOT letting archives URL.")
    list_cmd.add_argument("--min-date", default=MODERN_ARCHIVE_START.isoformat(), help="Earliest letting date to list.")
    list_cmd.add_argument("--max-date", default="", help="Latest letting date to list.")
    list_cmd.add_argument("--with-pdfs", action="store_true", help="Also count Unit Tab Results PDFs per page.")
    list_cmd.set_defaults(func=cmd_list)

    parse_pdf_cmd = subparsers.add_parser("parse-pdf", help="Parse a local Unit Tab Results PDF into CSV.")
    parse_pdf_cmd.add_argument("pdf", type=Path)
    parse_pdf_cmd.add_argument("output", type=Path)
    parse_pdf_cmd.set_defaults(func=cmd_parse_pdf)

    export_url = subparsers.add_parser("export-url", help="Export one letting page URL if Unit Tab Results exist.")
    export_url.add_argument("date", help="Letting date, e.g. 2026-05-07.")
    export_url.add_argument("url", help="INDOT letting page URL.")
    export_url.add_argument("--output-dir", type=Path, default=default_data_dir(), help="Directory for output CSV files.")
    export_url.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".bidtabs-cache/indot-public"),
        help="Directory for downloaded Unit Tab Results PDFs.",
    )
    export_url.add_argument("--overwrite", action="store_true", help="Overwrite the output CSV if it exists.")
    export_url.set_defaults(func=cmd_export_url)

    export_date = subparsers.add_parser("export-date", help="Export one or more public letting dates by discovery.")
    export_date.add_argument("dates", nargs="+", help="Letting date(s), e.g. 2026-05-07.")
    export_date.add_argument("--index-url", default=INDEX_URL, help="INDOT contracts index URL.")
    export_date.add_argument("--archive-url", default=ARCHIVE_URL, help="INDOT letting archives URL.")
    export_date.add_argument("--min-date", default=MODERN_ARCHIVE_START.isoformat(), help="Earliest discovery date.")
    export_date.add_argument("--max-date", default="", help="Latest discovery date.")
    export_date.add_argument("--output-dir", type=Path, default=default_data_dir(), help="Directory for output CSV files.")
    export_date.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".bidtabs-cache/indot-public"),
        help="Directory for downloaded Unit Tab Results PDFs.",
    )
    export_date.add_argument("--overwrite", action="store_true", help="Overwrite existing output CSV files.")
    export_date.set_defaults(func=cmd_export_date)

    weekly = subparsers.add_parser("weekly", help="Export new public INDOT Unit Tab Results.")
    weekly.add_argument("--index-url", default=INDEX_URL, help="INDOT contracts index URL.")
    weekly.add_argument("--archive-url", default=ARCHIVE_URL, help="INDOT letting archives URL.")
    weekly.add_argument("--min-date", default=MODERN_ARCHIVE_START.isoformat(), help="Earliest discovery date.")
    weekly.add_argument("--max-date", default="", help="Latest discovery date.")
    weekly.add_argument("--output-dir", type=Path, default=default_data_dir(), help="Directory for output CSV files.")
    weekly.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".bidtabs-cache/indot-public"),
        help="Directory for downloaded Unit Tab Results PDFs.",
    )
    weekly.add_argument(
        "--lookback-days",
        type=int,
        default=365,
        help="Only consider letting pages within this many days. Use 0 for no cutoff.",
    )
    weekly.add_argument(
        "--newer-than-existing",
        action="store_true",
        dest="newer_than_existing",
        help="Only export dates newer than the newest local data file.",
    )
    weekly.add_argument(
        "--all-missing",
        action="store_false",
        dest="newer_than_existing",
        help=argparse.SUPPRESS,
    )
    weekly.add_argument("--include-future", action="store_true", help="Consider future letting pages too.")
    weekly.add_argument("--overwrite", action="store_true", help="Overwrite existing output CSV files.")
    weekly.set_defaults(newer_than_existing=False)
    weekly.set_defaults(func=cmd_weekly)

    validate_csv = subparsers.add_parser("validate-csv", help="Validate public BidTabsData CSV headers and fields.")
    validate_csv.add_argument("csvs", nargs="+", type=Path)
    validate_csv.set_defaults(func=cmd_validate_csv)

    compare_xls = subparsers.add_parser("compare-xls", help="Compare public CSV output to legacy .xls exports.")
    compare_xls.add_argument("dates", nargs="+", help="Letting date(s), e.g. 2026-01-14.")
    compare_xls.add_argument("--index-url", default=INDEX_URL, help="INDOT contracts index URL.")
    compare_xls.add_argument("--archive-url", default=ARCHIVE_URL, help="INDOT letting archives URL.")
    compare_xls.add_argument("--min-date", default=MODERN_ARCHIVE_START.isoformat(), help="Earliest discovery date.")
    compare_xls.add_argument("--max-date", default="", help="Latest discovery date.")
    compare_xls.add_argument(
        "--public-dir",
        type=Path,
        default=Path(".bidtabs-cache/indot-public/compare-csv"),
        help="Directory for generated public CSVs used for comparison.",
    )
    compare_xls.add_argument("--xls-dir", type=Path, default=default_data_dir(), help="Directory with legacy .xls files.")
    compare_xls.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".bidtabs-cache/indot-public"),
        help="Directory for downloaded Unit Tab Results PDFs.",
    )
    compare_xls.add_argument("--refresh-public", action="store_true", help="Regenerate comparison CSVs first.")
    compare_xls.set_defaults(func=cmd_compare_xls)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, subprocess.CalledProcessError, urllib.error.URLError, PullerError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
