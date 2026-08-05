"""Placeholder so pytest has something to collect during Phase 0.

Delete this once real tests exist for ml/greenwashing_risk_model.py and
guardrails/validators.py (both are pure-function-friendly and should be the first
things unit-tested, ahead of any agent/MCP integration test).
"""


def test_package_imports():
    import greenlux_sentinel

    assert greenlux_sentinel.__version__ == "0.1.0"
