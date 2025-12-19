"""
Command-line interface for the SWE-bench data point validator.
"""

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .result_parser import format_error_message
from .validator import SWEBenchValidator, ValidationError

console = Console()


@click.command()
@click.option(
    "--data-point",
    type=click.Path(exists=True, path_type=Path),
    help="Validate a single data point JSON file",
)
@click.option(
    "--data-points-dir",
    type=click.Path(exists=True, path_type=Path),
    default="data_points",
    help="Directory containing data point files (default: data_points/)",
)
@click.option(
    "--pattern", help="Glob pattern to filter data point files (e.g., 'astropy*.json')"
)
@click.option(
    "--timeout",
    type=int,
    default=900,
    help="Timeout per instance in seconds (default: 900 = 15 minutes)",
)
@click.option("--force-rebuild", is_flag=True, help="Force rebuild Docker images")
@click.option(
    "--cache-level",
    type=click.Choice(["none", "base", "env", "instance"]),
    default="env",
    help="Docker cache level (default: env)",
)
@click.option(
    "--output", type=click.Path(path_type=Path), help="Save results to JSON file"
)
@click.option(
    "--check-docker", is_flag=True, help="Only check if Docker is available and exit"
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def main(
    data_point,
    data_points_dir,
    pattern,
    timeout,
    force_rebuild,
    cache_level,
    output,
    check_docker,
    verbose,
):
    """
    Validate SWE-bench data points using the official evaluation harness.

    This validator runs the golden patch from each data point through the
    SWE-bench Docker evaluation system and verifies that all FAIL_TO_PASS
    and PASS_TO_PASS tests pass correctly.

    Examples:

        # Validate a single data point
        uv run python -m swe_bench_validator --data-point data_points/astropy__astropy-11693.json

        # Validate all data points in directory
        uv run python -m swe_bench_validator

        # Validate with pattern filter
        uv run python -m swe_bench_validator --pattern "astropy*.json"

        # Check Docker availability
        uv run python -m swe_bench_validator --check-docker

        # Save results to file
        uv run python -m swe_bench_validator --output results.json --verbose
    """
    try:
        # Initialize validator
        validator = SWEBenchValidator(
            data_points_dir=data_points_dir,
            timeout_per_instance=timeout,
            force_rebuild=force_rebuild,
            cache_level=cache_level,
            verbose=verbose,
        )

        # Check Docker availability
        docker_available, docker_error = validator.check_docker_available()

        if check_docker:
            # Just check Docker and exit
            if docker_available:
                console.print("[green]✓[/green] Docker is available and running")
                console.print(f"[dim]Ready to validate SWE-bench data points[/dim]")
                sys.exit(0)
            else:
                console.print(f"[red]✗[/red] Docker is not available")
                console.print(f"[red]Error:[/red] {docker_error}")
                console.print(
                    "\n[yellow]Please ensure Docker is installed and running:[/yellow]"
                )
                console.print("  • macOS: Start Docker Desktop")
                console.print("  • Linux: sudo systemctl start docker")
                console.print("  • Verify: docker info")
                sys.exit(1)

        if not docker_available:
            console.print(f"[red]✗[/red] Docker is not available: {docker_error}")
            console.print(
                "[yellow]Use --check-docker for troubleshooting tips[/yellow]"
            )
            sys.exit(1)

        # Determine which data points to validate
        if data_point:
            # Single file mode
            data_points = [data_point]
        else:
            # Directory mode
            data_points = validator.find_data_points(pattern)

            if not data_points:
                if pattern:
                    console.print(
                        f"[yellow]No data points found matching pattern '{pattern}' in {data_points_dir}[/yellow]"
                    )
                else:
                    console.print(
                        f"[yellow]No data points found in {data_points_dir}[/yellow]"
                    )
                sys.exit(0)

            console.print(
                f"\n[bold]Found {len(data_points)} data point(s) to validate[/bold]"
            )

        # Validate data points
        if len(data_points) == 1:
            # Single validation
            result = validator.validate_single(data_points[0])
            results = {result.instance_id: result}
        else:
            # Multiple validations
            results = validator.validate_multiple(data_points)

        # Display results summary
        console.print("\n" + "=" * 70)
        console.print("[bold]Validation Results Summary[/bold]")
        console.print("=" * 70)

        # Create summary table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Instance ID", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Patch", justify="center")
        table.add_column("F2P", justify="center")
        table.add_column("P2P", justify="center")
        table.add_column("Time", justify="right")

        success_count = 0
        failure_count = 0

        for instance_id, result in sorted(results.items()):
            # Status
            if result.success:
                status = "[green]✓ PASS[/green]"
                success_count += 1
            else:
                status = "[red]✗ FAIL[/red]"
                failure_count += 1

            # Patch status
            patch_status = (
                "[green]✓[/green]" if result.patch_applied else "[red]✗[/red]"
            )

            # F2P (FAIL_TO_PASS) status
            f2p_passed = result.fail_to_pass_count
            f2p_total = len(result.fail_to_pass_results)
            if f2p_passed == f2p_total:
                f2p_status = f"[green]{f2p_passed}/{f2p_total}[/green]"
            else:
                f2p_status = f"[red]{f2p_passed}/{f2p_total}[/red]"

            # P2P (PASS_TO_PASS) status
            p2p_passed = result.pass_to_pass_count
            p2p_total = len(result.pass_to_pass_results)
            if p2p_passed == p2p_total:
                p2p_status = f"[green]{p2p_passed}/{p2p_total}[/green]"
            else:
                p2p_status = f"[red]{p2p_passed}/{p2p_total}[/red]"

            # Time
            time_str = f"{result.execution_time:.1f}s"

            table.add_row(
                instance_id, status, patch_status, f2p_status, p2p_status, time_str
            )

        console.print(table)

        # Summary statistics
        total = len(results)
        console.print(
            f"\n[bold]Total:[/bold] {total} | "
            + f"[green]Passed:[/green] {success_count} | "
            + f"[red]Failed:[/red] {failure_count}"
        )

        # Show detailed errors for failed validations
        if failure_count > 0 and not verbose:
            console.print(
                "\n[yellow]Failed validations (use --verbose for full output):[/yellow]"
            )
            for instance_id, result in sorted(results.items()):
                if not result.success:
                    console.print(format_error_message(result))

        # Ensure output is flushed before exit (important for CI/GitHub Actions)
        sys.stdout.flush()
        sys.stderr.flush()

        # Save results to file if requested
        if output:
            results_dict = {
                "summary": {
                    "total": total,
                    "passed": success_count,
                    "failed": failure_count,
                },
                "results": {
                    instance_id: result.to_dict()
                    for instance_id, result in results.items()
                },
            }

            with open(output, "w") as f:
                json.dump(results_dict, f, indent=2)

            console.print(f"\n[green]✓[/green] Results saved to {output}")

        # Exit with appropriate code
        if failure_count > 0:
            console.print(
                f"\n[red]✗[/red] Validation failed for {failure_count} data point(s)"
            )
            sys.exit(1)
        else:
            console.print(f"\n[green]✓[/green] All validations passed!")
            sys.exit(0)

    except ValidationError as e:
        console.print(f"\n[red]✗ Validation Error:[/red] {str(e)}")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]✗ Unexpected Error:[/red] {str(e)}")
        if verbose:
            import traceback

            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
