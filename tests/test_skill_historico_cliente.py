"""The Hermes skill and the CLI it documents must not drift apart.

The skill lives in the repo and is symlinked into ~/.hermes/skills/, so both
sides always read the same bytes. That fixes stale *copies*, not stale *text*:
adding a flag to the wrapper without documenting it leaves the agent calling
the command wrong. These tests fail on that.
"""
import importlib.util
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_SKILL = _RAIZ / "skills" / "historico-cliente-badie" / "SKILL.md"
_CLI = _RAIZ / "scripts" / "historico_cliente_cli.py"


def _texto_skill() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _flags_del_cli() -> set[str]:
    """Long options declared in the wrapper's argparse."""
    return set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', _CLI.read_text(encoding="utf-8")))


def test_la_skill_vive_en_el_repo():
    """Versioned next to the code it documents, not only under ~/.hermes."""
    assert _SKILL.is_file(), f"falta {_SKILL}"


def test_la_skill_documenta_todos_los_flags_del_cli():
    """A flag the agent cannot see is a flag it will never use."""
    texto = _texto_skill()
    faltantes = sorted(f for f in _flags_del_cli() if f not in texto)
    assert not faltantes, f"flags sin documentar en la skill: {faltantes}"


def test_la_skill_no_inventa_flags():
    """The reverse drift: documenting an option the wrapper does not accept."""
    reales = _flags_del_cli()
    citados = set(re.findall(r"`(--[a-z0-9-]+)`", _texto_skill()))
    inventados = sorted(citados - reales)
    assert not inventados, f"la skill cita flags inexistentes: {inventados}"


def test_la_skill_apunta_al_script_real():
    """The command in the skill must be the path that actually exists."""
    assert "scripts/historico_cliente_cli.py" in _texto_skill()
    assert _CLI.is_file()


def test_frontmatter_tiene_nombre_y_descripcion():
    """Hermes needs both to index and trigger the skill."""
    texto = _texto_skill()
    assert texto.startswith("---"), "falta el frontmatter YAML"
    cabecera = texto.split("---", 2)[1]
    assert re.search(r"^name:\s*historico-cliente-badie\s*$", cabecera, re.M)
    assert re.search(r"^description:\s*\S", cabecera, re.M)


def test_la_skill_declara_el_default_de_cargos():
    """Regression: the agent kept adding --solo-con-cargo on its own.

    The default is to sum everything; the filter is opt-in and only on an
    explicit request. The skill has to say so or the mistake repeats.
    """
    # Espacios colapsados: el markdown parte las frases en varias lineas y eso
    # no cambia lo que el agente lee.
    texto = re.sub(r"\s+", " ", _texto_skill().lower())
    assert "por default se suma todo" in texto
    assert "no agregues `--solo-con-cargo` por tu cuenta" in texto
