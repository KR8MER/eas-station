"""Tests for GPIO behavior matrix environment persistence."""

import json
import os
import tempfile
from pathlib import Path


def test_gpio_behavior_matrix_env_save():
    """Test that GPIO behavior matrix can be saved to and loaded from environment."""
    from app_utils.gpio import (
        GPIOBehavior,
        load_gpio_behavior_matrix_from_env,
        serialize_gpio_behavior_matrix,
    )
    
    # Create a behavior matrix
    original_matrix = {
        17: {GPIOBehavior.DURATION_OF_ALERT},
        18: {GPIOBehavior.PLAYOUT, GPIOBehavior.FLASH},
        22: {GPIOBehavior.INCOMING_ALERT},
    }
    
    # Serialize it
    serialized = serialize_gpio_behavior_matrix(original_matrix)
    assert serialized
    assert isinstance(serialized, str)
    
    # Verify it's valid JSON
    parsed = json.loads(serialized)
    assert "17" in parsed
    assert "18" in parsed
    assert "22" in parsed
    
    # Set it in environment
    os.environ["GPIO_PIN_BEHAVIOR_MATRIX"] = serialized
    
    # Load it back
    loaded_matrix = load_gpio_behavior_matrix_from_env()
    
    # Verify all pins and behaviors are preserved
    assert 17 in loaded_matrix
    assert 18 in loaded_matrix
    assert 22 in loaded_matrix
    
    assert GPIOBehavior.DURATION_OF_ALERT in loaded_matrix[17]
    assert GPIOBehavior.PLAYOUT in loaded_matrix[18]
    assert GPIOBehavior.FLASH in loaded_matrix[18]
    assert GPIOBehavior.INCOMING_ALERT in loaded_matrix[22]
    
    # Clean up
    del os.environ["GPIO_PIN_BEHAVIOR_MATRIX"]
    print("✓ test_gpio_behavior_matrix_env_save passed")


def test_gpio_behavior_matrix_empty_handling():
    """Test that empty behavior matrix is handled correctly."""
    from app_utils.gpio import load_gpio_behavior_matrix_from_env
    
    # Test with empty string
    os.environ["GPIO_PIN_BEHAVIOR_MATRIX"] = ""
    matrix = load_gpio_behavior_matrix_from_env()
    assert matrix == {}
    
    # Test with empty JSON object
    os.environ["GPIO_PIN_BEHAVIOR_MATRIX"] = "{}"
    matrix = load_gpio_behavior_matrix_from_env()
    assert matrix == {}
    
    # Clean up
    del os.environ["GPIO_PIN_BEHAVIOR_MATRIX"]
    print("✓ test_gpio_behavior_matrix_empty_handling passed")


def test_env_file_write_and_read():
    """Test that environment variables can be written and read from .env file."""
    import sys
    from pathlib import Path
    
    # Add parent directory to path to import webapp modules
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    
    from webapp.admin.environment import read_env_file, write_env_file
    
    # Create a temporary .env file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.env') as tmp:
        tmp_path = Path(tmp.name)
        tmp.write("# Test .env file\n")
        tmp.write("TEST_VAR=original_value\n")
        tmp.write("ANOTHER_VAR=another_value\n")
    
    try:
        # Mock the get_env_file_path to return our temp file
        import webapp.admin.environment as env_module
        original_get_path = env_module.get_env_file_path
        env_module.get_env_file_path = lambda: tmp_path
        
        # Read the file
        env_vars = read_env_file()
        assert env_vars["TEST_VAR"] == "original_value"
        assert env_vars["ANOTHER_VAR"] == "another_value"
        
        # Update a variable
        env_vars["TEST_VAR"] = "updated_value"
        env_vars["NEW_VAR"] = "new_value"
        
        # Write it back
        write_env_file(env_vars)
        
        # Read again to verify
        env_vars = read_env_file()
        assert env_vars["TEST_VAR"] == "updated_value"
        assert env_vars["ANOTHER_VAR"] == "another_value"
        assert env_vars["NEW_VAR"] == "new_value"
        
        # Verify the file still has comments
        with open(tmp_path, 'r') as f:
            content = f.read()
            assert "# Test .env file" in content
        
        # Restore original function
        env_module.get_env_file_path = original_get_path
        
    finally:
        # Clean up temp file
        if tmp_path.exists():
            tmp_path.unlink()
    
    print("✓ test_env_file_write_and_read passed")


def test_gpio_behavior_matrix_with_single_behavior():
    """Test behavior matrix with single behavior per pin (common case from UI)."""
    from app_utils.gpio import GPIOBehavior, load_gpio_behavior_matrix_from_env
    
    # Simulate what the UI sends - single behavior in array
    matrix_json = '{"17": ["duration_of_alert"], "18": ["playout"]}'
    os.environ["GPIO_PIN_BEHAVIOR_MATRIX"] = matrix_json
    
    matrix = load_gpio_behavior_matrix_from_env()
    
    assert 17 in matrix
    assert 18 in matrix
    assert GPIOBehavior.DURATION_OF_ALERT in matrix[17]
    assert GPIOBehavior.PLAYOUT in matrix[18]
    
    # Clean up
    del os.environ["GPIO_PIN_BEHAVIOR_MATRIX"]
    print("✓ test_gpio_behavior_matrix_with_single_behavior passed")


def test_gpio_behavior_matrix_invalid_json():
    """Test that invalid JSON is handled gracefully."""
    from app_utils.gpio import load_gpio_behavior_matrix_from_env
    
    # Invalid JSON should return empty dict without crashing
    os.environ["GPIO_PIN_BEHAVIOR_MATRIX"] = "not valid json {"
    matrix = load_gpio_behavior_matrix_from_env()
    assert matrix == {}
    
    # Clean up
    del os.environ["GPIO_PIN_BEHAVIOR_MATRIX"]
    print("✓ test_gpio_behavior_matrix_invalid_json passed")


if __name__ == "__main__":
    print("Running GPIO behavior matrix save tests...\n")
    
    try:
        test_gpio_behavior_matrix_env_save()
        test_gpio_behavior_matrix_empty_handling()
        test_env_file_write_and_read()
        test_gpio_behavior_matrix_with_single_behavior()
        test_gpio_behavior_matrix_invalid_json()
        
        print("\n✅ All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise

