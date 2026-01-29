#!/usr/bin/env python3
"""
Build Lahman SQLite database from SABR CSV data.

Downloads the Lahman Baseball Database CSV files and converts them to SQLite.
The Lahman Database is maintained by SABR (Society for American Baseball Research).

Official source: https://sabr.org/lahman-database
CSV data maintained at: https://www.seanlahman.com/baseball-archive/statistics/

Usage:
    python scripts/build_lahman_db.py [--output-path PATH]

Example:
    python scripts/build_lahman_db.py
    python scripts/build_lahman_db.py --output-path ./my_lahman.sqlite
"""

import argparse
import csv
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Download timeout in seconds (increased for slow connections)
DOWNLOAD_TIMEOUT = 120

# Primary source: Sean Lahman's CSV archive (SABR maintained)
# The URL pattern is: lahman_X-Y.zip where X-Y is the year range
CSV_SOURCES = [
    "https://www.seanlahman.com/files/database/lahman_1871-2024_csv.zip",
    "https://www.seanlahman.com/files/database/lahman_1871-2023_csv.zip",
]

# Fallback: Pre-built SQLite from GitHub releases (jknecht maintains this)
# This is used if CSV sources are unavailable
SQLITE_SOURCES = [
    "https://github.com/jknecht/baseball-archive-sqlite/releases/download/2022/lahman_1871-2022.sqlite",
]

# Required tables and their column mappings
# These must match what LahmanRepository expects
REQUIRED_TABLES = {
    "People": {
        "csv_name": "People.csv",
        "columns": [
            "playerID", "birthYear", "birthMonth", "birthDay", "birthCountry",
            "birthState", "birthCity", "deathYear", "deathMonth", "deathDay",
            "deathCountry", "deathState", "deathCity", "nameFirst", "nameLast",
            "nameGiven", "weight", "height", "bats", "throws", "debut",
            "finalGame", "retroID", "bbrefID"
        ],
        "primary_key": "playerID",
    },
    "Batting": {
        "csv_name": "Batting.csv",
        "columns": [
            "playerID", "yearID", "stint", "teamID", "lgID", "G", "AB", "R",
            "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "IBB",
            "HBP", "SH", "SF", "GIDP"
        ],
        "indexes": [
            ("batting_player_year_idx", ["playerID", "yearID"]),
            ("batting_team_year_idx", ["teamID", "yearID"]),
        ],
    },
    "Pitching": {
        "csv_name": "Pitching.csv",
        "columns": [
            "playerID", "yearID", "stint", "teamID", "lgID", "W", "L", "G",
            "GS", "CG", "SHO", "SV", "IPouts", "H", "ER", "HR", "BB", "SO",
            "BAOpp", "ERA", "IBB", "WP", "HBP", "BK", "BFP", "GF", "R", "SH", "SF"
        ],
        "indexes": [
            ("pitching_player_year_idx", ["playerID", "yearID"]),
            ("pitching_team_year_idx", ["teamID", "yearID"]),
        ],
    },
    "Teams": {
        "csv_name": "Teams.csv",
        "columns": [
            "yearID", "lgID", "teamID", "franchID", "divID", "Rank", "G", "Ghome",
            "W", "L", "DivWin", "WCWin", "LgWin", "WSWin", "R", "AB", "H",
            "2B", "3B", "HR", "BB", "SO", "SB", "CS", "HBP", "SF", "RA",
            "ER", "ERA", "CG", "SHO", "SV", "IPouts", "HA", "HRA", "BBA",
            "SOA", "E", "DP", "FP", "name", "park", "attendance", "BPF", "PPF"
        ],
        "indexes": [
            ("teams_team_year_idx", ["teamID", "yearID"]),
        ],
    },
}


def download_with_progress(url: str, desc: str = "Downloading", timeout: int = DOWNLOAD_TIMEOUT) -> bytes:
    """
    Download a URL with progress display.

    Args:
        url: URL to download
        desc: Description for progress display
        timeout: Timeout in seconds

    Returns:
        Downloaded content as bytes

    Raises:
        urllib.error.URLError: If download fails
    """
    print(f"{desc}: {url}")

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (baseball-sim-tui build script)"}
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            total_size = response.headers.get("Content-Length")
            if total_size:
                total_size = int(total_size)
                print(f"  Size: {total_size / 1024 / 1024:.1f} MB")

            chunks = []
            downloaded = 0
            chunk_size = 8192

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)

                if total_size:
                    pct = downloaded * 100 / total_size
                    bar_len = 40
                    filled = int(bar_len * downloaded / total_size)
                    bar = "=" * filled + "-" * (bar_len - filled)
                    print(f"\r  [{bar}] {pct:.1f}%", end="", flush=True)

            print()  # newline after progress
            return b"".join(chunks)

    except urllib.error.URLError as e:
        print(f"  Failed: {e}")
        raise


def download_with_redirect(url: str, desc: str = "Downloading", timeout: int = DOWNLOAD_TIMEOUT) -> bytes:
    """
    Download a URL following redirects (for GitHub releases).

    Args:
        url: URL to download
        desc: Description for progress display
        timeout: Timeout in seconds

    Returns:
        Downloaded content as bytes
    """
    print(f"{desc}: {url}")

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (baseball-sim-tui build script)",
                "Accept": "application/octet-stream",
            }
        )

        # Follow redirects manually for better progress display
        with urllib.request.urlopen(req, timeout=timeout) as response:
            # Check if we got redirected
            final_url = response.geturl()
            if final_url != url:
                print(f"  Redirected to: {final_url}")

            total_size = response.headers.get("Content-Length")
            if total_size:
                total_size = int(total_size)
                print(f"  Size: {total_size / 1024 / 1024:.1f} MB")

            chunks = []
            downloaded = 0
            chunk_size = 8192

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)

                if total_size:
                    pct = downloaded * 100 / total_size
                    bar_len = 40
                    filled = int(bar_len * downloaded / total_size)
                    bar = "=" * filled + "-" * (bar_len - filled)
                    print(f"\r  [{bar}] {pct:.1f}%", end="", flush=True)

            print()  # newline after progress
            return b"".join(chunks)

    except urllib.error.URLError as e:
        print(f"  Failed: {e}")
        raise


def try_download_csv(urls: List[str]) -> Optional[bytes]:
    """
    Try downloading CSV archive from multiple URLs.

    Args:
        urls: List of URLs to try

    Returns:
        Downloaded content or None if all failed
    """
    for url in urls:
        try:
            data = download_with_progress(url)
            # Verify it's a valid ZIP
            if data[:4] == b'PK\x03\x04':
                return data
            else:
                print("  Downloaded file is not a valid ZIP archive")
                continue
        except Exception as e:
            print(f"  Error: {e}")
            continue
    return None


def try_download_sqlite(urls: List[str], output_path: Path) -> bool:
    """
    Try downloading pre-built SQLite from multiple URLs.

    Args:
        urls: List of URLs to try
        output_path: Where to save the database

    Returns:
        True if download succeeded
    """
    for url in urls:
        try:
            data = download_with_redirect(url)
            # Verify it's a valid SQLite database
            if data[:16] == b'SQLite format 3\x00':
                # Write directly to output
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(data)
                return True
            else:
                print("  Downloaded file is not a valid SQLite database")
                continue
        except Exception as e:
            print(f"  Error: {e}")
            continue
    return False


def find_csv_in_zip(zip_data: bytes, csv_name: str) -> Optional[str]:
    """
    Find a CSV file in a ZIP archive, handling nested directories.

    Args:
        zip_data: ZIP file content
        csv_name: Name of CSV file to find (e.g., "People.csv")

    Returns:
        Path within ZIP to the CSV file, or None if not found
    """
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        for name in zf.namelist():
            if name.endswith(csv_name) or name.endswith(f"/{csv_name}"):
                return name
    return None


def read_csv_from_zip(zip_data: bytes, csv_path: str) -> List[Dict[str, str]]:
    """
    Read a CSV file from within a ZIP archive.

    Args:
        zip_data: ZIP file content
        csv_path: Path to CSV within the ZIP

    Returns:
        List of row dictionaries
    """
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        with zf.open(csv_path) as f:
            # Decode bytes to string for csv module
            text = io.TextIOWrapper(f, encoding="utf-8")
            reader = csv.DictReader(text)
            return list(reader)


def create_table(
    conn: sqlite3.Connection,
    table_name: str,
    columns: List[str],
    primary_key: Optional[str] = None,
) -> None:
    """
    Create a table with the specified columns.

    Args:
        conn: SQLite connection
        table_name: Name of table to create
        columns: List of column names
        primary_key: Optional primary key column
    """
    # Quote column names that might be reserved words or start with numbers
    quoted_cols = []
    for col in columns:
        if col[0].isdigit() or col.upper() in ("GROUP", "ORDER", "INDEX", "KEY"):
            quoted_cols.append(f'"{col}" TEXT')
        else:
            quoted_cols.append(f"{col} TEXT")

    pk_clause = ""
    if primary_key:
        pk_clause = f", PRIMARY KEY ({primary_key})"

    sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(quoted_cols)}{pk_clause})"
    conn.execute(sql)


def create_indexes(
    conn: sqlite3.Connection,
    table_name: str,
    indexes: List[Tuple[str, List[str]]],
) -> None:
    """
    Create indexes on a table.

    Args:
        conn: SQLite connection
        table_name: Name of table
        indexes: List of (index_name, [columns]) tuples
    """
    for index_name, columns in indexes:
        cols = ", ".join(columns)
        sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({cols})"
        conn.execute(sql)


def import_csv_to_table(
    conn: sqlite3.Connection,
    table_name: str,
    columns: List[str],
    rows: List[Dict[str, str]],
    batch_size: int = 1000,
) -> int:
    """
    Import CSV rows into a SQLite table.

    Args:
        conn: SQLite connection
        table_name: Target table name
        columns: List of columns to import
        rows: List of row dictionaries
        batch_size: Rows per commit batch

    Returns:
        Number of rows imported
    """
    if not rows:
        return 0

    # Quote column names that need it
    quoted_cols = []
    for col in columns:
        if col[0].isdigit():
            quoted_cols.append(f'"{col}"')
        else:
            quoted_cols.append(col)

    placeholders = ", ".join(["?" for _ in columns])
    sql = f"INSERT INTO {table_name} ({', '.join(quoted_cols)}) VALUES ({placeholders})"

    count = 0
    batch = []

    for row in rows:
        # Extract values, converting empty strings to None
        values = []
        for col in columns:
            val = row.get(col, "")
            if val == "" or val is None:
                values.append(None)
            else:
                values.append(val)

        batch.append(tuple(values))
        count += 1

        if len(batch) >= batch_size:
            conn.executemany(sql, batch)
            conn.commit()
            print(f"    Imported {count} rows...", end="\r")
            batch = []

    # Final batch
    if batch:
        conn.executemany(sql, batch)
        conn.commit()

    print(f"    Imported {count} rows")
    return count


def build_database_from_csv(zip_data: bytes, output_path: Path) -> Dict[str, int]:
    """
    Build SQLite database from ZIP of CSV files.

    Args:
        zip_data: ZIP file content
        output_path: Path for output SQLite file

    Returns:
        Dictionary of table_name -> row_count
    """
    # Remove existing database
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(str(output_path))
    stats = {}

    try:
        for table_name, config in REQUIRED_TABLES.items():
            csv_name = config["csv_name"]
            columns = config["columns"]

            print(f"  Processing {table_name}...")

            # Find CSV in ZIP
            csv_path = find_csv_in_zip(zip_data, csv_name)
            if not csv_path:
                print(f"    WARNING: {csv_name} not found in archive")
                continue

            print(f"    Found: {csv_path}")

            # Read CSV data
            rows = read_csv_from_zip(zip_data, csv_path)

            # Filter columns to only those present in CSV
            available_cols = set(rows[0].keys()) if rows else set()
            actual_columns = [c for c in columns if c in available_cols]

            if len(actual_columns) < len(columns):
                missing = set(columns) - set(actual_columns)
                print(f"    Note: Missing columns: {missing}")

            # Create table
            create_table(
                conn,
                table_name,
                actual_columns,
                config.get("primary_key"),
            )

            # Import data
            count = import_csv_to_table(conn, table_name, actual_columns, rows)
            stats[table_name] = count

            # Create indexes
            if "indexes" in config:
                create_indexes(conn, table_name, config["indexes"])

        conn.commit()

    finally:
        conn.close()

    return stats


def verify_database(db_path: Path) -> bool:
    """
    Verify the built database has expected tables and data.

    Args:
        db_path: Path to SQLite database

    Returns:
        True if verification passes
    """
    print("\nVerifying database...")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Check tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] for row in cursor.fetchall()]
        print(f"  Tables: {', '.join(tables)}")

        required = set(REQUIRED_TABLES.keys())
        if not required.issubset(set(tables)):
            missing = required - set(tables)
            print(f"  ERROR: Missing tables: {missing}")
            return False

        # Check data counts
        for table in REQUIRED_TABLES:
            cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            count = cursor.fetchone()["cnt"]
            print(f"  {table}: {count:,} rows")

            if count == 0:
                print(f"  ERROR: {table} is empty")
                return False

        # Check specific data (Babe Ruth should exist)
        cursor = conn.execute(
            "SELECT nameFirst, nameLast FROM People WHERE playerID = 'ruthba01'"
        )
        row = cursor.fetchone()
        if row:
            print(f"  Sample player: {row['nameFirst']} {row['nameLast']}")
        else:
            print("  WARNING: ruthba01 not found (may be older dataset)")

        # Check year range
        cursor = conn.execute("SELECT MIN(yearID), MAX(yearID) FROM Batting")
        row = cursor.fetchone()
        print(f"  Batting data range: {row[0]} - {row[1]}")

        return True

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Build Lahman SQLite database from SABR CSV data",
        epilog="Source: SABR (sabr.org/lahman-database) maintains the Lahman Database",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("data/lahman.sqlite"),
        help="Output path for SQLite database (default: data/lahman.sqlite)",
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Override download URL for CSV archive",
    )
    parser.add_argument(
        "--sqlite-url",
        type=str,
        help="Override download URL for pre-built SQLite (bypasses CSV build)",
    )
    parser.add_argument(
        "--local-zip",
        type=Path,
        help="Use a local ZIP file instead of downloading (e.g., data/lahman_1871-2025_csv.zip)",
    )

    args = parser.parse_args()

    # Ensure output directory exists
    args.output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Lahman Database Builder")
    print("Source: SABR (Society for American Baseball Research)")
    print("=" * 60)

    # If direct SQLite URL specified, use it
    if args.sqlite_url:
        print("\nStep 1: Downloading pre-built SQLite...")
        if try_download_sqlite([args.sqlite_url], args.output_path):
            print("\nStep 2: Verification...")
            if verify_database(args.output_path):
                print("\n" + "=" * 60)
                print("SUCCESS!")
                print(f"Database created: {args.output_path}")
                print(f"Size: {args.output_path.stat().st_size / 1024 / 1024:.1f} MB")
                print("=" * 60)
                return
        print("\nERROR: Failed to download or verify SQLite")
        sys.exit(1)

    # If local ZIP specified, use it
    if args.local_zip:
        print(f"\nStep 1: Reading local ZIP file: {args.local_zip}")
        if not args.local_zip.exists():
            print(f"ERROR: File not found: {args.local_zip}")
            sys.exit(1)

        with open(args.local_zip, "rb") as f:
            zip_data = f.read()

        # Verify it's a valid ZIP
        if zip_data[:4] != b'PK\x03\x04':
            print("ERROR: File is not a valid ZIP archive")
            sys.exit(1)

        print(f"  Size: {len(zip_data) / 1024 / 1024:.1f} MB")

        # Build database from CSV
        print("\nStep 2: Building SQLite database from CSV...")
        build_database_from_csv(zip_data, args.output_path)

        # Verify
        print("\nStep 3: Verification...")
        if verify_database(args.output_path):
            print("\n" + "=" * 60)
            print("SUCCESS!")
            print(f"Database created: {args.output_path}")
            print(f"Size: {args.output_path.stat().st_size / 1024 / 1024:.1f} MB")
            print("=" * 60)
            return

        print("\nERROR: Database verification failed")
        sys.exit(1)

    # Try CSV sources first (more up-to-date)
    print("\nStep 1: Downloading CSV archive...")

    if args.url:
        csv_urls = [args.url]
    else:
        csv_urls = CSV_SOURCES

    zip_data = try_download_csv(csv_urls)

    if zip_data:
        # Build database from CSV
        print("\nStep 2: Building SQLite database from CSV...")
        build_database_from_csv(zip_data, args.output_path)

        # Verify
        print("\nStep 3: Verification...")
        if verify_database(args.output_path):
            print("\n" + "=" * 60)
            print("SUCCESS!")
            print(f"Database created: {args.output_path}")
            print(f"Size: {args.output_path.stat().st_size / 1024 / 1024:.1f} MB")
            print("=" * 60)
            return

        print("\nERROR: Database verification failed")
        sys.exit(1)

    # CSV sources failed, try pre-built SQLite as fallback
    print("\nCSV sources unavailable, trying pre-built SQLite fallback...")

    if try_download_sqlite(SQLITE_SOURCES, args.output_path):
        print("\nStep 2: Verification...")
        if verify_database(args.output_path):
            print("\n" + "=" * 60)
            print("SUCCESS! (using pre-built SQLite fallback)")
            print(f"Database created: {args.output_path}")
            print(f"Size: {args.output_path.stat().st_size / 1024 / 1024:.1f} MB")
            print("=" * 60)
            print("\nNote: Used pre-built SQLite (data through 2022).")
            print("For newer data, visit https://sabr.org/lahman-database")
            return

    # All sources failed
    print("\n" + "=" * 60)
    print("ERROR: Failed to download from any source")
    print("=" * 60)
    print("\nPossible solutions:")
    print("  1. Check your internet connection")
    print("  2. Visit https://sabr.org/lahman-database to manually download")
    print("  3. Use --url to specify a custom CSV archive URL")
    print("  4. Use --sqlite-url to specify a pre-built SQLite URL")
    sys.exit(1)


if __name__ == "__main__":
    main()
