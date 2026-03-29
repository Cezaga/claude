"""Output formatting and grouping for checked accounts."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from models import AccountResult
from config import RANKED_TIERS


def save_results(results: list[AccountResult], output_dir: str = "results"):
    """Save all results grouped into categorized files."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(output_dir, timestamp)
    os.makedirs(base, exist_ok=True)

    valid = [r for r in results if r.status == "VALID"]
    invalid = [r for r in results if r.status == "INVALID"]
    banned = [r for r in results if r.status == "BANNED"]
    errors = [r for r in results if r.status in ("ERROR", "RATE_LIMITED")]
    twofa = [r for r in results if r.status == "VALID" and "2FA" in r.error_message]

    # Write main category files
    _write_lines(f"{base}/valid.txt", [r.summary_line() for r in valid])
    _write_lines(f"{base}/invalid.txt", [r.combo for r in invalid])
    _write_lines(f"{base}/banned.txt", [r.summary_line() for r in banned])
    _write_lines(f"{base}/errors.txt", [f"{r.combo} | {r.error_message}" for r in errors])
    _write_lines(f"{base}/2fa.txt", [f"{r.combo} | {r.error_message}" for r in twofa])

    # Grouped files
    _save_by_region(valid, base)
    _save_by_rank(valid, base)
    _save_by_level(valid, base)
    _save_by_skins(valid, base)
    _save_by_rp(valid, base)
    _save_by_be(valid, base)

    # Full detailed report
    _save_full_report(valid, base)

    return base


def _save_by_region(accounts: list[AccountResult], base: str):
    """Group valid accounts by server region."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in accounts:
        region = r.region or "UNKNOWN"
        grouped[region].append(r.summary_line())

    region_dir = os.path.join(base, "by_region")
    os.makedirs(region_dir, exist_ok=True)
    for region, lines in sorted(grouped.items()):
        _write_lines(f"{region_dir}/{region}.txt", lines)


def _save_by_rank(accounts: list[AccountResult], base: str):
    """Group valid accounts by ranked tier."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in accounts:
        tier = r.rank.split()[0] if r.rank != "UNRANKED" else "UNRANKED"
        grouped[tier].append(r.summary_line())

    rank_dir = os.path.join(base, "by_rank")
    os.makedirs(rank_dir, exist_ok=True)
    for tier, lines in sorted(
        grouped.items(),
        key=lambda x: RANKED_TIERS.get(x[0], -1),
        reverse=True,
    ):
        _write_lines(f"{rank_dir}/{tier}.txt", lines)


def _save_by_level(accounts: list[AccountResult], base: str):
    """Group valid accounts by level ranges."""
    ranges = [
        ("1-30", 1, 30),
        ("31-50", 31, 50),
        ("51-100", 51, 100),
        ("101-200", 101, 200),
        ("201-500", 201, 500),
        ("500+", 501, 99999),
    ]
    level_dir = os.path.join(base, "by_level")
    os.makedirs(level_dir, exist_ok=True)

    for label, lo, hi in ranges:
        lines = [r.summary_line() for r in accounts if lo <= r.level <= hi]
        if lines:
            _write_lines(f"{level_dir}/{label}.txt", lines)


def _save_by_skins(accounts: list[AccountResult], base: str):
    """Group valid accounts by skin count ranges."""
    ranges = [
        ("0_skins", 0, 0),
        ("1-10_skins", 1, 10),
        ("11-50_skins", 11, 50),
        ("51-100_skins", 51, 100),
        ("100+_skins", 101, 99999),
    ]
    skin_dir = os.path.join(base, "by_skins")
    os.makedirs(skin_dir, exist_ok=True)

    for label, lo, hi in ranges:
        lines = [r.summary_line() for r in accounts if lo <= r.skin_count <= hi]
        if lines:
            _write_lines(f"{skin_dir}/{label}.txt", lines)


def _save_by_rp(accounts: list[AccountResult], base: str):
    """Group valid accounts by RP amount."""
    ranges = [
        ("0_rp", 0, 0),
        ("1-500_rp", 1, 500),
        ("501-2000_rp", 501, 2000),
        ("2000+_rp", 2001, 9999999),
    ]
    rp_dir = os.path.join(base, "by_rp")
    os.makedirs(rp_dir, exist_ok=True)

    for label, lo, hi in ranges:
        lines = [r.summary_line() for r in accounts if lo <= r.rp <= hi]
        if lines:
            _write_lines(f"{rp_dir}/{label}.txt", lines)


def _save_by_be(accounts: list[AccountResult], base: str):
    """Group valid accounts by Blue Essence amount."""
    ranges = [
        ("0-1000_be", 0, 1000),
        ("1001-10000_be", 1001, 10000),
        ("10001-50000_be", 10001, 50000),
        ("50000+_be", 50001, 9999999),
    ]
    be_dir = os.path.join(base, "by_blue_essence")
    os.makedirs(be_dir, exist_ok=True)

    for label, lo, hi in ranges:
        lines = [r.summary_line() for r in accounts if lo <= r.blue_essence <= hi]
        if lines:
            _write_lines(f"{be_dir}/{label}.txt", lines)


def _save_full_report(accounts: list[AccountResult], base: str):
    """Save a detailed report of every valid account."""
    lines = []
    for r in accounts:
        lines.append("=" * 60)
        lines.append(f"Account   : {r.combo}")
        lines.append(f"Region    : {r.region}")
        lines.append(f"Summoner  : {r.summoner_name}")
        lines.append(f"Level     : {r.level}")
        lines.append(f"Rank      : {r.rank}")
        lines.append(f"RP        : {r.rp}")
        lines.append(f"Blue Ess. : {r.blue_essence}")
        lines.append(f"Skins     : {r.skin_count}")
        lines.append(f"Champions : {r.champion_count}")
        lines.append(f"Email Ver.: {r.email_verified}")
        if r.ban_status:
            lines.append(f"Ban       : {r.ban_status}")
        lines.append("")

    _write_lines(f"{base}/full_report.txt", lines)


def _write_lines(path: str, lines: list[str]):
    """Write lines to a file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
