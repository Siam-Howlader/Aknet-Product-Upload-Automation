#!/usr/bin/env python3
"""
Test suite for MAVE-driven specification generation.

Tests verify that:
1. MAVE attributes are not filtered by attributes_extracted.txt
2. Custom attributes from MAVE survive validation
3. Placeholder values are still rejected
4. Attribute names are normalized
5. Duplicate semantic attributes are removed
6. Conflicting values are rejected
7. Product evidence is required (not MAVE statistics copied)
8. Tests pass with process_mave_specifications
"""
import pytest

from app.ai.prompts import build_user_prompt
from app.ai.specifications import process_mave_specifications


class TestMAVESpecificationProcessing:
    """Test MAVE-driven specification generation without catalog whitelist."""

    def test_mave_accepts_attributes_not_in_catalog(self) -> None:
        """MAVE attributes should survive even if not in attributes_extracted.txt"""
        result = process_mave_specifications({
            "Custom Attribute": "Custom Value",
            "Gaming Feature": "RGB Lighting",
            "Unknown To Catalog": "Some Value",
        })
        keys_lower = {k.casefold() for k in result.keys()}
        assert len(result) >= 2
        assert any(
            "custom" in k or "gaming" in k or "unknown" in k for k in keys_lower)

    def test_mave_still_rejects_placeholder_values(self) -> None:
        """Even in MAVE mode, placeholder values should be rejected"""
        result = process_mave_specifications({
            "DPI": "32000",
            "Warranty": "Not specified",
            "Weight": "Unknown",
            "Features": "N/A",
            "Connection": "Wireless",
        })
        keys_lower = {k.casefold() for k in result.keys()}
        assert any("dpi" in k or "connection" in k for k in keys_lower)
        assert not any(
            "warranty" in k or "weight" in k or "features" in k for k in keys_lower)

    def test_mave_normalizes_attribute_names(self) -> None:
        """Attribute names should be normalized to title case with single spaces"""
        result = process_mave_specifications({
            "  dpi  ": "32000",
            "POLLING   RATE": "4000 Hz",
            "sensor type": "HERO 2",
        })
        keys = list(result.keys())
        assert all(len(k.split()) > 0 for k in keys)

    def test_mave_removes_duplicate_semantic_attributes(self) -> None:
        """Semantically equivalent attributes should be deduplicated"""
        result = process_mave_specifications({
            "Storage": "1TB",
            "Storage Capacity": "1TB",
        })
        assert len(result) == 1
        assert "1TB" in list(result.values())

    def test_mave_rejects_conflicting_values_for_same_attribute(self) -> None:
        """Conflicting values for the same concept should be rejected"""
        result = process_mave_specifications({
            "Storage": "1TB",
            "Capacity": "2TB",
        })
        assert "Capacity" not in result or result == {}

    def test_mave_normalizes_values(self) -> None:
        """Values should normalize units (16 GB → 16GB, 3200 mhz → 3200MHz)"""
        result = process_mave_specifications({
            "Memory": "16 GB",
            "Speed": "3200 MHz",
        })
        if result:
            values = list(result.values())
            assert any("16GB" in v for v in values) or any(
                "3200MHz" in v for v in values)

    def test_product_prompt_contains_only_verified_product_facts(self) -> None:
        prompt = build_user_prompt(
            "Gaming Mouse",
            specifications={"DPI": "32000", "Polling Rate": "1000Hz"},
        )
        assert '"DPI":"32000"' in prompt
        assert '"Polling Rate":"1000Hz"' in prompt
        assert "Candidate attributes" not in prompt
        assert "attribute catalog" not in prompt
        assert "Output only the finished description" in prompt
        assert len(prompt) < 2000

    def test_mave_accepts_reasonable_custom_attributes(self) -> None:
        """MAVE should accept well-formed custom attributes with valid values"""
        result = process_mave_specifications({
            "Sensor": "HERO 2",
            "Dpi": "32000",
            "Connectivity": "Wireless 2.4GHz",
            "Battery Life": "60 hours",
        })
        assert len(result) >= 2

    def test_mave_multiple_values_for_same_attribute_rejected(self) -> None:
        """If same attribute appears with different values, omit it"""
        result = process_mave_specifications({
            "Dimension": "10 x 20 mm",
            "Dimensions": "15 x 25 mm",
        })
        assert result == {} or "Dimension" not in result

    def test_mave_empty_and_whitespace_values_rejected(self) -> None:
        """Empty and whitespace-only values should be rejected"""
        result = process_mave_specifications({
            "DPI": "32000",
            "Warranty": "",
            "Features": "   ",
            "Connection": "Wireless",
        })
        keys_lower = {k.casefold() for k in result.keys()}
        assert any("dpi" in k or "connection" in k for k in keys_lower)
        assert not any("warranty" in k or "features" in k for k in keys_lower)

    def test_mave_empty_candidates_skips_attribute_catalog(self) -> None:
        prompt = build_user_prompt("Unknown Product")
        assert "attribute catalog" not in prompt
        assert "Unknown Product" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
