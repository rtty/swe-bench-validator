# Agent Workforce Infrastructure

Infrastructure tools for agent-based projects with SWE-bench integration.

## Components

### 1. SWE-bench Data Downloader

A shell-based tool for downloading SWE-bench instances from Hugging Face datasets.

```bash
# Download specific instance
./scripts/download_swe_bench.sh --instance_id "django__django-12345"

# Download multiple instances from repository
./scripts/download_swe_bench.sh --repo "django/django" --limit 5

# Download with verbose output
./scripts/download_swe_bench.sh --instance_id "astropy__astropy-11693" --verbose
```

The downloaded JSON files can be placed directly into `data_points/` and validated.

### 2. SWE-bench Data Point Validator

The validator checks whether a SWE-bench data point is **actually correct**, by running its *golden patch* through the **official SWE-bench evaluation harness inside Docker**.

This is **not** a model benchmark. No model-generated patches are involved.

#### Requirements

- Python >= 3.10
- Docker (installed and running)
- 16GB RAM recommended

#### Quick Start

```bash
# Check Docker availability
uv run python -m swe_bench_validator --check-docker

# Validate a single data point
uv run python -m swe_bench_validator \
  --data-point data_points/astropy__astropy-11693.json \
  --verbose

# Validate all data points in directory
uv run python -m swe_bench_validator

# Validate with pattern filter
uv run python -m swe_bench_validator --pattern "astropy*.json"

# Save results to JSON
uv run python -m swe_bench_validator --output results.json
```

#### How It Works

The validator:
1. Loads data points from JSON files
2. Converts golden patches to prediction format
3. Runs SWE-bench evaluation in Docker containers
4. Validates that all `FAIL_TO_PASS` tests pass after applying the patch
5. Validates that all `PASS_TO_PASS` tests still pass (no regressions)

See [swe-bench-docker-architecture.md](swe-bench-docker-architecture.md) for detailed documentation.

#### Example Output

```
Validation Results Summary
══════════════════════════════════════════════════════════════════════
Instance ID                    Status   Patch  F2P    P2P    Time
astropy__astropy-11693         ✓ PASS   ✓      1/1    27/27  245.3s
astropy__astropy-11693-fail    ✗ FAIL   ✓      0/1    27/27  198.1s

Total: 2 | Passed: 1 | Failed: 1
```

#### Options

- `--data-point PATH` - Validate single file
- `--data-points-dir PATH` - Directory with data points (default: data_points/)
- `--pattern GLOB` - Filter files by glob pattern
- `--timeout SECONDS` - Timeout per instance (default: 900)
- `--force-rebuild` - Force rebuild Docker images
- `--cache-level LEVEL` - Docker cache level: none/base/env/instance (default: env)
- `--output PATH` - Save results to JSON file
- `--verbose, -v` - Verbose output
- `--check-docker` - Only check Docker availability

## Installation

This project uses [UV](https://github.com/astral-sh/uv) for dependency management:

```bash
# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Add new dependency
uv add <package-name>
```

## Development

```bash
# Run validator tests
uv run python test_validator_quick.py

# Format code (when configured)
uv run black .
uv run isort .

```

## Architecture

See documentation:
- [swe-bench-docker-architecture.md](swe-bench-docker-architecture.md) - Detailed Docker architecture

## Project Structure

```
.
├── data_points/                # SWE-bench data points
├── swe_bench_downloader/       # Downloader module
├── swe_bench_validator/        # Validator module ✓ NEW
├── scripts/                    # Utility scripts
├── pyproject.toml             # Project configuration
└── README.md                  # This file
```

## Data Point Format

Each data point is a JSON file with:

```json
{
  "instance_id": "repo__project-issue_number",
  "repo": "owner/repository",
  "base_commit": "git_commit_hash",
  "patch": "diff --git ...",
  "FAIL_TO_PASS": ["test::that::should::pass"],
  "PASS_TO_PASS": ["test::that::should::stay::passing"],
  ...
}
```

**Valid data point**: Patch successfully fixes all `FAIL_TO_PASS` tests without breaking `PASS_TO_PASS` tests.

**Invalid data point**: Patch fails to apply, doesn't fix tests, or causes regressions.

