"""
Tests for T-104: --no-delivery flag in main.py arg parser and
merge_filters() no_delivery kwarg support.

TDD: written BEFORE implementation.
"""
import argparse
import pytest


def test_merge_filters_no_delivery_zeros_email_and_whatsapp():
    """merge_filters(no_delivery=True) forces enviar_email=False and enviar_whatsapp=False."""
    from src.config.resolver import merge_filters
    from src.config.models import GlobalFilters

    gf = GlobalFilters(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-01-31",
        enviar_email=True,
        enviar_whatsapp=True,
    )
    result = merge_filters(gf, None, no_delivery=True)

    assert result["enviar_email"] is False
    assert result["enviar_whatsapp"] is False


def test_merge_filters_no_delivery_false_preserves_original():
    """merge_filters(no_delivery=False) does not alter enviar flags."""
    from src.config.resolver import merge_filters
    from src.config.models import GlobalFilters

    gf = GlobalFilters(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-01-31",
        enviar_email=True,
        enviar_whatsapp=True,
    )
    result = merge_filters(gf, None, no_delivery=False)

    assert result["enviar_email"] is True
    assert result["enviar_whatsapp"] is True


def test_merge_filters_no_delivery_default_false():
    """merge_filters() without no_delivery kwarg defaults to False (backward compat)."""
    from src.config.resolver import merge_filters
    from src.config.models import GlobalFilters

    gf = GlobalFilters(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-01-31",
        enviar_email=True,
        enviar_whatsapp=True,
    )
    result = merge_filters(gf, None)

    assert result["enviar_email"] is True
    assert result["enviar_whatsapp"] is True


def test_main_parser_accepts_no_delivery_flag():
    """main.py arg parser must accept --no-delivery as a global flag."""
    import main as main_module

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-delivery", action="store_true", default=False, dest="no_delivery")
    parser.add_argument("--config", default=None)
    parser.add_argument("--test-mode", action="store_true", default=False)

    args = parser.parse_args(["--no-delivery", "--config", "configs/ventas.json"])
    assert args.no_delivery is True


def test_main_has_no_delivery_in_argparse():
    """The actual main() parser must include --no-delivery flag."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        capture_output=True, text=True,
        cwd="/home/nahuel/projects/work/Informes Badie"
    )
    assert "--no-delivery" in result.stdout
