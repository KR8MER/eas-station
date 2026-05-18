from pathlib import Path


DASHBOARD_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "admin" / "gps_dashboard.html"


def test_headline_peak_jitter_thresholds_match_help_ranges():
    """The screenshot regression: 14.65 µs peak jitter must not render as fault."""
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")

    assert "jitterPeakNs <= 20_000) ? 'ok'" in source
    assert "jitterPeakNs <= 200_000) ? 'warn'" in source
    assert "jitterPeakNs <= 500) ? 'ok'" not in source
    assert "jitterPeakNs <= 5000) ? 'warn'" not in source
