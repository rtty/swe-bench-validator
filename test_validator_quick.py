"""Quick test of validator functionality without running full evaluation."""

import json
from pathlib import Path

from swe_bench_validator import SWEBenchValidator


def test_data_point_loading():
    """Test that data points can be loaded and validated structurally."""
    validator = SWEBenchValidator(verbose=True)

    print("\n=== Testing Data Point Loading ===\n")

    # Test valid data point
    print("1. Testing valid data point:")
    try:
        valid_path = Path("data_points/astropy__astropy-11693.json")
        data_point = validator.load_data_point(valid_path)
        print(f"   ✓ Successfully loaded {data_point['instance_id']}")
        print(f"   - Repo: {data_point['repo']}")
        # FAIL_TO_PASS and PASS_TO_PASS are JSON strings, parse them
        fail_to_pass = json.loads(data_point["FAIL_TO_PASS"])
        pass_to_pass = json.loads(data_point["PASS_TO_PASS"])
        print(f"   - FAIL_TO_PASS: {len(fail_to_pass)} tests")
        print(f"   - PASS_TO_PASS: {len(pass_to_pass)} tests")
        print(f"   - Patch size: {len(data_point['patch'])} characters")

        # Test conversion to prediction format
        prediction = validator.convert_to_prediction(data_point)
        print(f"   ✓ Converted to prediction format")
        print(f"   - instance_id: {prediction['instance_id']}")
        print(f"   - model_name_or_path: {prediction['model_name_or_path']}")
        print(f"   - patch size: {len(prediction['model_patch'])} characters")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    # Test invalid data point
    print("\n2. Testing invalid data point:")
    try:
        invalid_path = Path("data_points/astropy__astropy-11693-fail.json")
        data_point = validator.load_data_point(invalid_path)
        print(f"   ✓ Successfully loaded {data_point['instance_id']}")
        print(f"   - This data point has an intentionally broken patch")
        print(f"   - Validation will fail when run through SWE-bench")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    # Test finding data points
    print("\n3. Testing data point discovery:")
    data_points = validator.find_data_points()
    print(f"   ✓ Found {len(data_points)} data point(s)")
    for dp in data_points:
        print(f"   - {dp.name}")

    print("\n=== All Tests Passed ===\n")
    return True


if __name__ == "__main__":
    success = test_data_point_loading()
    exit(0 if success else 1)
