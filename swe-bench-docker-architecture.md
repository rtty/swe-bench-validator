# SWE-bench Docker Architecture

## Overview

SWE-bench uses Docker to evaluate code patches in isolated, reproducible environments. This document describes the three-layer Docker system, evaluation flow, and key design decisions.

**Purpose**: Ensure consistent test execution across different machines and prevent test interference.

**Key Benefits**:
- **Reproducibility**: Identical environment on any machine
- **Isolation**: Each evaluation runs independently
- **Efficiency**: Smart layer caching minimizes rebuild time
- **Deterministic**: Same inputs always produce same outputs

---

## Three-Layer Docker System

SWE-bench builds Docker images in three layers. Each layer adds more specific setup, and layers are reused to save time.

```
┌─────────────────┐
│   Base Image    │  Ubuntu + basic tools (git, python, conda)
│  (sweb.base.*)  │  Built once per language
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Environment Img │  Specific Python version + common dependencies
│  (sweb.env.*)   │  Built once per repo version
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Instance Image  │  Actual repo code at specific commit
│  (sweb.eval.*)  │  Built once per test instance
└─────────────────┘
```

### Layer 1: Base Image

**What it contains:**
- Operating system and system utilities
- Language runtime and package managers
- Build tools

**When built:** Once per language/platform combination
**Naming:** `sweb.base.{language}.{arch}:latest`

### Layer 2: Environment Image

**What it contains:**
- Base Image + specific language version
- Common repository dependencies
- Isolated environment setup

**When built:** Once per unique environment configuration
**Naming:** `sweb.env.{language}.{arch}.{hash}:latest`

**Key point:** Dependencies shared across multiple instances are installed here for reuse.

### Layer 3: Instance Image

**What it contains:**
- Environment Image + repository code at specific commit
- Repository installed in development mode
- Instance-specific test dependencies

**When built:** Once per test instance
**Naming:** `sweb.eval.{instance_id}:latest`

**Key point:** The repository is cloned and installed here, ready to receive patches.

## How Images Are Built

### Smart Caching Strategy

Images are built **on-demand** (lazy loading), not all at once:

1. **Check if it exists**: Before building, check if we already have this image
2. **Reuse what we can**: If base and environment images exist, just build the instance image
3. **Build only what's needed**: Only missing layers are built

**Cache levels you can control:**
- `none` - Build everything from scratch
- `base` - Keep base, rebuild env and instance
- `env` - Keep base and env, rebuild only instance (recommended)
- `instance` - Keep all images

### Dependency Installation

**Environment Layer (Layer 2):**
- Common dependencies shared across instances
- Test frameworks and libraries
- Runs once and gets cached

**Instance Layer (Layer 3):**
- Repository-specific code and dependencies
- Installed in development/editable mode
- Per-instance, not cached

## Test Execution Flow

Here's what happens when you validate a data point:

### Step 1: Start Container

- Create a Docker container from the instance image
- The container has the full repository at the correct commit
- The Python environment is already activated and ready

### Step 2: Apply the Patch

The system tries three different methods to apply the patch (in order):
1. `git apply --verbose` - Tries a clean apply
2. `git apply --verbose --reject` - Tries with conflict markers
3. `patch --batch --fuzz=5` - Fuzzy matching for small differences

If all three fail, validation stops with an error.

### Step 3: Run Tests

- Copy an evaluation script into the container
- Execute the script with a timeout (default: 15 minutes)
- The script runs the tests specified in `FAIL_TO_PASS` and `PASS_TO_PASS`

**Timeout handling:** If tests take too long, the system kills the process and marks it as timed out.

### Step 4: Parse Results

- Collect the test output
- Parse which tests passed and which failed
- Check that:
  - All `FAIL_TO_PASS` tests now pass (the patch fixed them)
  - All `PASS_TO_PASS` tests still pass (no regressions)

### Step 5: Cleanup

- Stop and remove the container
- Optionally remove the instance image to save disk space

## Example: astropy__astropy-11693

**Data point overview:**
- Repository with astronomy calculation code
- 1 test that should pass after fix (`FAIL_TO_PASS`)
- 27 existing tests that must stay passing (`PASS_TO_PASS`)

**Evaluation flow:**
1. Build three layers (first time only)
2. Start container with repository code
3. Apply the golden patch
4. Run all specified tests
5. Parse results

**Expected outcome:**
- ✓ Patch applies cleanly
- ✓ FAIL_TO_PASS test now passes
- ✓ All PASS_TO_PASS tests still pass
- **Result: VALID data point**

## Validator Integration

The validator integrates with SWE-bench by:

### 1. Using the Official Harness Unmodified

**Decision:** Use `build_env_images()` and `run_instance()` from the official harness without modifying Docker images or test logic.

**Rationale:**
- Ensures behavioral parity with official SWE-bench evaluation
- Avoids subtle mismatches in environment or test execution
- Remains future-proof against harness changes

### 2. One Instance per Evaluation

**Decision:** Evaluate exactly one instance per `run_instance()` call.

**Rationale:**
- Clean log separation
- Deterministic failure attribution
- Per-instance timeout enforcement
- Easier debugging and reproducibility

### 3. Golden Patch Only

**Decision:** Always evaluate the golden patch provided by the dataset.

**Rationale:**
- Validates dataset integrity, not model quality
- Avoids conflating dataset errors with model failures

### 4. Report-Based Validation

**Decision:** Rely exclusively on the evaluation report for validation outcomes.

**Rationale:**
- Avoids fragile output parsing
- Matches official grading logic
- Produces stable, machine-readable results

## Common Issues

### Docker Problems

| Problem | Solution |
|---------|----------|
| Docker daemon not running | Start Docker service on your system |
| Permission denied | Add user to docker group |
| Out of disk space | Clean up with `docker system prune -af` |

### Evaluation Errors

| Problem | Solution |
|---------|----------|
| Patch won't apply | Verify base_commit matches repository state |
| Tests timeout | Increase timeout or investigate test issues |
| Import errors | Check patch doesn't break dependencies |

## Performance Considerations

**Caching:**
- Use `cache_level=env` for fastest re-runs
- First evaluation builds images (one-time cost)
- Subsequent evaluations reuse cached layers

**Parallelization:**
- Multiple instances can run concurrently
- Docker BuildKit handles concurrent builds safely
- Balance parallelism with system resources

## Validation Success Criteria

A data point is considered **valid** if and only if:

1. The patch was applied successfully
2. All `FAIL_TO_PASS` tests passed
3. All `PASS_TO_PASS` tests passed

Formally:
```
patch_applied
AND (all FAIL_TO_PASS passed)
AND (all PASS_TO_PASS passed)
```

Any violation results in validation failure with explicit error messages.

---

## Summary

The SWE-bench Docker architecture provides deterministic, reproducible evaluation through:

**Architecture:**
- Three-layer system: Base → Environment → Instance
- Smart caching reuses layers across evaluations
- Complete isolation per test instance

**Validator approach:**
- Uses official harness unmodified
- Evaluates one instance at a time
- Tests golden patches only
- Validates dataset integrity, not model performance

**Result:**
Consistent evaluation outcomes regardless of where tests run - laptop, server, or CI environment.