"""Plan-first gate demo: offline tests only, no product implementation changes."""

from tradingagents.runapi.redact import Redactor


def test_demo_normal_text_is_preserved():
    assert Redactor().scrub("Ordinary research note.") == "Ordinary research note."


def test_demo_empty_and_missing_values_are_preserved():
    redactor = Redactor()
    assert redactor.scrub("") == ""
    assert redactor.scrub(None) is None


def test_demo_error_diagnostic_keeps_type_without_password():
    planted = "synthetic-demo-password-not-a-real-secret"
    result = Redactor().diagnostic(ValueError(f"password={planted}"))
    assert result.startswith("ValueError:")
    assert planted not in result
    assert "[REDACTED]" in result


def test_demo_nested_credentials_are_removed_without_mutating_input():
    planted = "synthetic-demo-token-not-a-real-secret"
    value = {"access_token": planted, "notes": [f"Bearer {planted}", "safe note"]}
    result = Redactor().scrub(value)
    assert result["access_token"] == "[REDACTED]"
    assert planted not in str(result)
    assert result["notes"][1] == "safe note"
    assert value["access_token"] == planted
    assert planted in value["notes"][0]
