#!/usr/bin/env python3
"""Legacy diagnostic/fallback BidTabs.NET SOAP data puller.

This talks directly to the BidTabs.NET SOAP service used by the Windows
ClickOnce app. It needs valid BidTabs license credentials for protected data
calls, and the protected path is not the default macOS pull path. Use
indot_public_bidtabs_puller.py for normal public INDOT Unit Tab Results pulls.

Required for protected calls:
  BIDTABS_CUSTOMER_ID
  BIDTABS_USER_ID
  BIDTABS_PASSWORD

Usually useful:
  BIDTABS_EMAIL
  BIDTABS_STATE_ID=IN
  BIDTABS_MACHINE_GUID=00000000-0000-0000-0000-000000000000
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

SERVICE_URL = "https://www.fieldmanagerpro.com/BidTabsWebService-4650/BidTabs.asmx"
SOAP_NS = "http://www.omanco.com/"
SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
DIFFGRAM_NS = "urn:schemas-microsoft-com:xml-diffgram-v1"
XML_SCHEMA_NS = "http://www.w3.org/2001/XMLSchema"
DATA_DIR_CANDIDATES = [
    Path.home() / "Projects/personal/BidTabsData/data/BidTabsData",
    Path.home() / "github/derek-betz/BidTabsData/data/BidTabsData",
    Path.home()
    / "Documents/Codex/2026-05-15/i-want-to-send-you-off/github/BidTabsData/data/BidTabsData",
]
PROGRAM_VERSION = "2.4.7.4650"
KEYCHAIN_SERVICES = {
    "BIDTABS_EMAIL": "bidtabs.email",
    "BIDTABS_PASSWORD": "bidtabs.password",
    "BIDTABS_CUSTOMER_ID": "bidtabs.customer_id",
    "BIDTABS_USER_ID": "bidtabs.user_id",
    "BIDTABS_SERIAL_NUMBER": "bidtabs.serial_number",
    "BIDTABS_MACHINE_GUID": "bidtabs.machine_guid",
}
KEY_ALIASES = {
    "EMAIL": "BIDTABS_EMAIL",
    "LOGIN": "BIDTABS_EMAIL",
    "LOGIN EMAIL": "BIDTABS_EMAIL",
    "PASSWORD": "BIDTABS_PASSWORD",
    "CUSTOMER ID": "BIDTABS_CUSTOMER_ID",
    "CUSTOMER_ID": "BIDTABS_CUSTOMER_ID",
    "USER ID": "BIDTABS_USER_ID",
    "USER_ID": "BIDTABS_USER_ID",
    "SERIAL NUMBER": "BIDTABS_SERIAL_NUMBER",
    "SERIAL_NUMBER": "BIDTABS_SERIAL_NUMBER",
    "MACHINE GUID": "BIDTABS_MACHINE_GUID",
    "MACHINE_GUID": "BIDTABS_MACHINE_GUID",
}


class BidTabsError(RuntimeError):
    """Raised for service-side faults or extraction failures."""


def _xml_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _soap_call(method: str, params: dict[str, object], *, timeout: int = 60) -> ET.Element:
    body = "".join(f"<{key}>{_xml_escape(value)}</{key}>" for key, value in params.items())
    envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="{SOAP_ENV}">
  <soap:Body>
    <{method} xmlns="{SOAP_NS}">{body}</{method}>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")
    request = urllib.request.Request(
        SERVICE_URL,
        data=envelope,
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{SOAP_NS}{method}"',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fault = _extract_fault(detail)
        raise BidTabsError(fault or f"HTTP {exc.code} from {method}") from exc
    except urllib.error.URLError as exc:
        raise BidTabsError(f"Could not reach BidTabs service: {exc}") from exc

    root = ET.fromstring(payload)
    fault = root.find(f".//{{{SOAP_ENV}}}Fault")
    if fault is not None:
        message = fault.findtext("faultstring") or "Unknown SOAP fault"
        raise BidTabsError(message)

    result_name = f"{method}Result"
    result = root.find(f".//{{{SOAP_NS}}}{result_name}")
    if result is None:
        response = root.find(f".//{{{SOAP_NS}}}{method}Response")
        if response is not None:
            return response
        raise BidTabsError(f"{method} response did not contain {result_name}")
    return result


def _extract_fault(payload: str) -> str | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    fault = root.find(f".//{{{SOAP_ENV}}}Fault")
    if fault is None:
        return None
    return fault.findtext("faultstring")


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _dataset_rows(result: ET.Element) -> list[dict[str, str]]:
    """Extract rows from a .NET DataSet/diffgram result element."""
    rows: list[dict[str, str]] = []
    for node in result.iter():
        if _strip_namespace(node.tag) in {"schema", "diffgram"}:
            continue
        if node.attrib.get(f"{{{DIFFGRAM_NS}}}id") is None:
            continue
        row: dict[str, str] = {}
        for child in list(node):
            if _strip_namespace(child.tag) == "rowOrder":
                continue
            row[_strip_namespace(child.tag)] = child.text or ""
        if row:
            rows.append(row)
    return rows


def _scalar_text(result: ET.Element) -> str:
    return "".join(result.itertext()).strip()


def _keychain_secret(service: str, account: str = "default") -> str:
    try:
        completed = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def _store_keychain_secret(service: str, value: str, account: str = "default") -> None:
    subprocess.run(
        ["security", "add-generic-password", "-U", "-a", account, "-s", service, "-w", value],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _secret(name: str) -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value
    service = KEYCHAIN_SERVICES.get(name)
    if service:
        return _keychain_secret(service)
    return ""


def _credential_presence() -> dict[str, bool]:
    return {name: bool(_secret(name)) for name in KEYCHAIN_SERVICES}


def _parse_dateish(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def _format_service_date(value: date) -> str:
    return f"{value.isoformat()}T00:00:00"


def _credentials(required: bool) -> tuple[str, str]:
    customer_id = _secret("BIDTABS_CUSTOMER_ID")
    user_id = _secret("BIDTABS_USER_ID")
    if required and (not customer_id or not user_id):
        raise BidTabsError(
            "Set BIDTABS_CUSTOMER_ID and BIDTABS_USER_ID before calling licensed BidTabs data methods."
        )
    return customer_id, user_id


def _default_data_dir() -> Path:
    env_dir = os.getenv("BIDTABS_OUTPUT_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    existing = [path for path in DATA_DIR_CANDIDATES if path.exists()]
    if not existing:
        return DATA_DIR_CANDIDATES[0]

    def sort_key(path: Path) -> tuple[date, int]:
        dates = _existing_date_stems(path)
        newest = max(dates) if dates else date.min
        return newest, DATA_DIR_CANDIDATES.index(path) * -1

    return max(existing, key=sort_key)


def _machine_guid() -> str:
    return _secret("BIDTABS_MACHINE_GUID") or "00000000-0000-0000-0000-000000000000"


def cmd_status(args: argparse.Namespace) -> int:
    presence = _credential_presence()
    labels = {
        "BIDTABS_EMAIL": "email",
        "BIDTABS_PASSWORD": "password",
        "BIDTABS_CUSTOMER_ID": "customer id",
        "BIDTABS_USER_ID": "user id",
        "BIDTABS_SERIAL_NUMBER": "serial number",
        "BIDTABS_MACHINE_GUID": "machine guid",
    }
    print(f"service: {SERVICE_URL}")
    print(f"state: {args.state}")
    print(f"output: {args.output_dir}")
    print("credentials:")
    for name, label in labels.items():
        print(f"  {label}: {'set' if presence.get(name) else 'missing'}")
    ready = presence["BIDTABS_PASSWORD"] and presence["BIDTABS_CUSTOMER_ID"] and presence["BIDTABS_USER_ID"]
    print(f"licensed date/metadata access: {'ready' if ready else 'not ready'}")
    print(
        "machine-bound app login: "
        + ("configured" if presence["BIDTABS_MACHINE_GUID"] else "not configured")
    )
    return 0


def cmd_metadata(args: argparse.Namespace) -> int:
    customer_id, user_id = _credentials(required=False)
    result = _soap_call("PopulateStates", {"customerid": customer_id, "userid": user_id})
    rows = _dataset_rows(result)
    if args.state:
        rows = [row for row in rows if row.get("StateID", "").upper() == args.state.upper()]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row.get('StateID',''):>2}  "
                f"{row.get('StateName',''):<24}  "
                f"data={row.get('DateDataUpdated','')}  "
                f"payitems={row.get('PayItemsUpdated','')}"
            )
    return 0


def cmd_dates(args: argparse.Namespace) -> int:
    dates = _available_dates(args.state)
    for letting_date in dates:
        print(letting_date.isoformat())
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    email = _secret("BIDTABS_EMAIL")
    password = _secret("BIDTABS_PASSWORD")
    if not email or not password:
        raise BidTabsError("Set BIDTABS_EMAIL and BIDTABS_PASSWORD or store them in macOS Keychain.")

    customer_id = args.customer_id or _secret("BIDTABS_CUSTOMER_ID")
    user_id = args.user_id or _secret("BIDTABS_USER_ID")
    if not customer_id or not user_id:
        raise BidTabsError(
            "Stored email/password are present, but the BidTabs data service also needs "
            "BIDTABS_CUSTOMER_ID and BIDTABS_USER_ID."
        )
    result = _soap_call(
        "VerifyUserPassword",
        {
            "customerID": customer_id,
            "userID": user_id,
            "password": password,
            "programVersion": PROGRAM_VERSION,
            "UseWindowsAuthentication": "false",
            "DomainName": "",
            "WindowsUserName": "",
            "MachineGuid": _machine_guid(),
            "MachineName": platform.node() or "mac",
        },
    )
    print(_scalar_text(result) or "<empty auth response>")
    return 0


def _read_credential_file(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return completed.stdout
    except (FileNotFoundError, subprocess.CalledProcessError, UnicodeDecodeError):
        return path.read_text(encoding="utf-8", errors="replace")


def _parse_credential_lines(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key = re.sub(r"\s+", " ", key.strip().upper())
        key = KEY_ALIASES.get(key, key)
        value = value.strip().strip('"“”\'')
        if key in KEYCHAIN_SERVICES and value and key not in parsed:
            parsed[key] = value
    return parsed


def cmd_import_credentials(args: argparse.Namespace) -> int:
    credential_path = args.file.expanduser()
    if not credential_path.exists():
        raise BidTabsError(f"Credential file does not exist: {credential_path}")

    values = _parse_credential_lines(_read_credential_file(credential_path))
    if not values:
        raise BidTabsError(
            "No supported BIDTABS_* entries found. Expected lines like BIDTABS_CUSTOMER_ID=..."
        )

    for name, value in sorted(values.items()):
        _store_keychain_secret(KEYCHAIN_SERVICES[name], value)
    print(f"stored {len(values)} BidTabs credential item(s) in macOS Keychain")
    print("stored keys: " + ", ".join(sorted(values)))
    return 0


def _available_dates(state: str) -> list[date]:
    customer_id, user_id = _credentials(required=True)
    result = _soap_call(
        "PopulateSpecificDates",
        {"stateID": state, "customerid": customer_id, "userid": user_id},
    )
    rows = _dataset_rows(result)
    dates: set[date] = set()
    for row in rows:
        for value in row.values():
            parsed = _parse_dateish(value)
            if parsed:
                dates.add(parsed)
                break
    if not dates:
        scalar = _scalar_text(result)
        for match in re.finditer(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}", scalar):
            parsed = _parse_dateish(match.group(0))
            if parsed:
                dates.add(parsed)
    return sorted(dates)


def _export_letting(state: str, letting_date: date, out_dir: Path) -> Path:
    customer_id, user_id = _credentials(required=True)
    params: dict[str, object] = {
        "userID": user_id,
        "stateID": state,
        "region": 0,
        "county": "",
        "startdate": _format_service_date(letting_date),
        "endDate": _format_service_date(letting_date),
        "projectType": "",
        "piCategory": 0,
        "piGroup": 0,
        "subTotal": "",
        "sizeFrom": 0,
        "sizeTo": 0,
        "breakDown": "",
        "options": 0,
        "userregion": 0,
        "populationarea": 0,
        "customerid": customer_id,
        "showEngineersEstimate": "false",
        "MachineGuid": _machine_guid(),
    }
    result = _soap_call("PopulateLettingReportExport", params, timeout=180)
    rows = _dataset_rows(result)
    if not rows:
        raise BidTabsError(f"No rows returned for {state} letting {letting_date.isoformat()}")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{letting_date.isoformat()}.csv"
    fieldnames = _ordered_fieldnames(rows)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def _ordered_fieldnames(rows: Iterable[dict[str, str]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def cmd_export(args: argparse.Namespace) -> int:
    letting_date = _parse_dateish(args.date)
    if not letting_date:
        raise BidTabsError(f"Could not parse date: {args.date}")
    out_path = _export_letting(args.state, letting_date, args.output_dir)
    print(f"exported {out_path}")
    return 0


def cmd_weekly(args: argparse.Namespace) -> int:
    out_dir = args.output_dir
    state = args.state
    remote_dates = _available_dates(state)
    if args.lookback_days:
        cutoff = date.today() - timedelta(days=args.lookback_days)
        remote_dates = [d for d in remote_dates if d >= cutoff]

    existing = _existing_date_stems(out_dir)
    if args.newer_than_existing and existing:
        newest_existing = max(existing)
        candidates = [d for d in remote_dates if d > newest_existing]
    else:
        candidates = [d for d in remote_dates if d not in existing]

    if not candidates:
        print(f"No new {state} letting dates to export.")
        return 0

    exported: list[str] = []
    for letting_date in candidates:
        path = _export_letting(state, letting_date, out_dir)
        exported.append(str(path))
        print(f"exported {path}")

    print(json.dumps({"state": state, "exported": exported}, indent=2))
    return 0


def _existing_date_stems(path: Path) -> set[date]:
    dates: set[date] = set()
    if not path.exists():
        return dates
    for file in path.iterdir():
        parsed = _parse_dateish(file.stem)
        if parsed:
            dates.add(parsed)
    return dates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        default=os.getenv("BIDTABS_STATE_ID", "IN"),
        help="BidTabs state ID, usually a two-letter DOT code. Default: env BIDTABS_STATE_ID or IN.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_data_dir(),
        help="Directory for exported CSV files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show local configuration without revealing secrets.")
    status.set_defaults(func=cmd_status)

    metadata = subparsers.add_parser("metadata", help="List public state update timestamps.")
    metadata.add_argument("--json", action="store_true", help="Print metadata as JSON.")
    metadata.set_defaults(func=cmd_metadata)

    dates = subparsers.add_parser("dates", help="List licensed letting dates for the configured state.")
    dates.set_defaults(func=cmd_dates)

    auth = subparsers.add_parser("auth", help="Verify stored login material against the BidTabs service.")
    auth.add_argument("--customer-id", default="", help="Override BIDTABS_CUSTOMER_ID for this auth check.")
    auth.add_argument("--user-id", default="", help="Override BIDTABS_USER_ID for this auth check.")
    auth.set_defaults(func=cmd_auth)

    import_credentials = subparsers.add_parser(
        "import-credentials",
        help="Store BIDTABS_* entries from a local text/RTF file into macOS Keychain.",
    )
    import_credentials.add_argument("file", type=Path, help="Credential file to import.")
    import_credentials.set_defaults(func=cmd_import_credentials)

    export = subparsers.add_parser("export", help="Export one letting date to CSV.")
    export.add_argument("date", help="Letting date, e.g. 2026-04-15.")
    export.set_defaults(func=cmd_export)

    weekly = subparsers.add_parser("weekly", help="Export new letting dates not already present locally.")
    weekly.add_argument(
        "--lookback-days",
        type=int,
        default=180,
        help="Only consider remote dates within this many days. Use 0 for no cutoff.",
    )
    weekly.add_argument(
        "--all-missing",
        action="store_false",
        dest="newer_than_existing",
        help="Export any missing date, not just dates newer than the newest local export.",
    )
    weekly.set_defaults(func=cmd_weekly)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BidTabsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
