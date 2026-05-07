"""bd_agent/sandbox/validator.py -- AST-based Python code whitelist validator.

Defense-in-depth layer (RF-111, RF-112, RF-113, RF-114). The real enforcement
boundary is the Docker container (network isolation + read-only rootfs + mount
constraints). This validator provides a fast pre-flight check before spawning
any container.

Strategy: stdlib ast.NodeVisitor -- no bandit dependency. Focused whitelist is
simpler, zero transitive deps, and Docker is the actual wall.

Zero imports from src.* or bd_agent.* (pure stdlib).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        "pandas",
        "numpy",
        "matplotlib",
        "openpyxl",
        "pyarrow",
        "PIL",
        "datetime",
        "math",
        "json",
        "csv",
        "decimal",
        "statistics",
        "collections",
        "itertools",
        "functools",
        "typing",
        "re",
    }
)

BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "compile",
        "globals",
        "locals",
        "vars",
        "delattr",
        "setattr",
        "getattr",
    }
)

BLOCKED_DUNDER_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__mro__",
        "__subclasses__",
        "__builtins__",
        "__globals__",
        "__import__",
        "__getattribute__",
        "__dict__",
        "__code__",
    }
)

# Allowed absolute path prefixes for open() calls (best-effort string literal check)
_ALLOWED_ABS_PREFIXES = ("/data/", "/output/")


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Result of AST code validation.

    Attributes:
        ok: True if the code passed all checks, False if any violation found.
        reason: Human-readable description of the first violation found, or
            None when ok=True.
    """

    ok: bool
    reason: str | None


# ---------------------------------------------------------------------------
# Internal visitor
# ---------------------------------------------------------------------------


class _Visitor(ast.NodeVisitor):
    """AST node visitor that collects the first policy violation found."""

    def __init__(self) -> None:
        self.violation: str | None = None

    def _fail(self, reason: str) -> None:
        """Record the first violation and stop further checking."""
        if self.violation is None:
            self.violation = reason

    # ------------------------------------------------------------------
    # Import checks (RF-111, RF-113)
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in ALLOWED_IMPORTS:
                self._fail(f"Blocked import: '{alias.name}' is not in the allowed list")
                return
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        top = module.split(".")[0]
        if top and top not in ALLOWED_IMPORTS:
            self._fail(f"Blocked import: '{module}' is not in the allowed list")
            return
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Call checks -- blocked builtins (RF-112)
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Check direct name calls: eval(...), exec(...), etc.
        if isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_BUILTINS:
                self._fail(f"Blocked builtin call: '{node.func.id}()'")
                return
            # open() path safety check (best-effort for string literal args)
            if node.func.id == "open" and node.args:
                self._check_open_path(node)
                return

        self.generic_visit(node)

    def _check_open_path(self, node: ast.Call) -> None:
        """Check the first argument of open() for path safety (RF-114)."""
        first_arg = node.args[0] if node.args else None
        if first_arg is None:
            self.generic_visit(node)
            return

        # Only inspect string literals -- dynamic expressions pass through
        # (Docker mount constraints are the actual enforcement)
        if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
            self.generic_visit(node)
            return

        path = first_arg.value

        # Reject traversal
        if ".." in path:
            self._fail(f"Blocked path: '{path}' contains '..' traversal")
            return

        # If absolute path, must start with an allowed prefix
        if path.startswith("/"):
            if not any(path.startswith(prefix) for prefix in _ALLOWED_ABS_PREFIXES):
                self._fail(
                    f"Blocked path: absolute path '{path}' is not under "
                    f"/data/ (read) or /output/ (write)"
                )
                return

        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Attribute access -- dunder attrs (RF-112)
    # ------------------------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr in BLOCKED_DUNDER_ATTRS:
            self._fail(f"Blocked attribute access: '.{node.attr}'")
            return
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_python_code(code: str) -> ValidationResult:
    """Validate Python source code against the sandbox whitelist.

    Performs AST-level checks (RF-111, RF-112, RF-113, RF-114). This is a
    best-effort pre-flight check; the Docker sandbox enforces real isolation.

    Args:
        code: Raw Python source code string.

    Returns:
        ValidationResult(ok=True, reason=None) on success, or
        ValidationResult(ok=False, reason=<description>) on the first violation.
    """
    if not code or not code.strip():
        return ValidationResult(ok=True, reason=None)

    # Parse AST -- SyntaxError yields a ValidationResult failure, not an exception
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ValidationResult(ok=False, reason=f"Syntax error: {exc}")

    visitor = _Visitor()
    visitor.visit(tree)

    if visitor.violation is not None:
        return ValidationResult(ok=False, reason=visitor.violation)

    return ValidationResult(ok=True, reason=None)
