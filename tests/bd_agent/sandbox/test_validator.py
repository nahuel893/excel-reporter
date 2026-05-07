"""T-004: Failing tests for bd_agent/sandbox/validator.py — AST Python code validator.

TDD cycle: RED first (validator.py does not exist) -> GREEN -> REFACTOR.

Covers (RF-111, RF-112, RF-113, RF-114, RF-115):
- 10+ malicious payloads — all MUST be rejected
- 10+ legitimate scripts — all MUST be accepted
- ValidationResult dataclass contract
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Malicious payloads — MUST all be rejected
# ---------------------------------------------------------------------------

MALICIOUS_PAYLOADS = [
    # Blocked imports (RF-113)
    ("import subprocess", "subprocess import blocked"),
    ("import os", "os import blocked"),
    ("import socket", "socket import blocked"),
    ("import ctypes", "ctypes import blocked"),
    ("import pickle", "pickle import blocked"),
    ("import importlib", "importlib import blocked"),
    ("from sys import argv, path\nimport os", "sys combined with os blocked"),
    # Blocked builtins (RF-112)
    ("eval(\"os.system('rm -rf /')\")", "eval blocked"),
    ("exec('import os; os.remove(\"/etc/passwd\")')", "exec blocked"),
    ("__import__('os').system('rm -rf /')", "__import__ blocked"),
    ("compile('import os', '<string>', 'exec')", "compile blocked"),
    # Blocked dunder attributes (RF-112)
    ("x.__class__.__subclasses__()", "__subclasses__ blocked"),
    ("f.__globals__['__builtins__']", "__globals__ blocked"),
    # Path safety -- absolute paths outside allowed prefixes (RF-114)
    ("open('/etc/passwd', 'r')", "open /etc/passwd blocked"),
    ("open('/proc/self/environ', 'r')", "open /proc blocked"),
    # Path safety -- traversal (RF-114)
    ("open('../../secrets.env', 'r')", "path traversal blocked"),
    ("open('../escape', 'r')", "relative path traversal blocked"),
]

# ---------------------------------------------------------------------------
# Legitimate scripts — MUST all be accepted (RF-111, RF-115)
# ---------------------------------------------------------------------------

LEGITIMATE_SCRIPTS = [
    # pandas read + write Excel
    (
        "import pandas as pd\ndf = pd.read_parquet('/data/input.parquet')\ndf.to_excel('/output/report.xlsx', index=False)",
        "pandas read_parquet + to_excel",
    ),
    # matplotlib figure to output
    (
        "import matplotlib\nimport matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot([1,2,3],[4,5,6])\nfig.savefig('/output/chart.png')",
        "matplotlib figure saved to /output",
    ),
    # openpyxl workbook write
    (
        "import openpyxl\nwb = openpyxl.Workbook()\nws = wb.active\nws['A1'] = 'hello'\nwb.save('/output/report.xlsx')",
        "openpyxl workbook save",
    ),
    # numpy array operations
    (
        "import numpy as np\na = np.array([1, 2, 3])\nresult = np.sum(a)",
        "numpy array sum",
    ),
    # PIL image operations
    (
        "from PIL import Image\nimg = Image.new('RGB', (100, 100), color='red')\nimg.save('/output/image.png')",
        "PIL image save",
    ),
    # json and csv stdlib
    (
        "import json\nimport csv\ndata = json.dumps({'key': 'value'})",
        "json.dumps stdlib",
    ),
    # csv writer to output
    (
        "import csv\nwith open('/output/data.csv', 'w', newline='') as f:\n    writer = csv.writer(f)\n    writer.writerow(['a', 'b'])",
        "csv writer to /output",
    ),
    # open allowed output path
    (
        "with open('/output/report.xlsx', 'wb') as f:\n    f.write(b'dummy')",
        "open /output allowed",
    ),
    # datetime and math stdlib
    (
        "from datetime import datetime\nimport math\nnow = datetime.now()\nx = math.sqrt(2)",
        "datetime + math stdlib",
    ),
    # collections, itertools, functools
    (
        "from collections import defaultdict\nfrom itertools import chain\nfrom functools import reduce\nd = defaultdict(list)",
        "collections/itertools/functools",
    ),
    # typing and re
    (
        "from typing import List, Dict\nimport re\npattern = re.compile(r'\\d+')",
        "typing + re stdlib",
    ),
    # decimal and statistics
    (
        "from decimal import Decimal\nfrom statistics import mean\nval = Decimal('3.14')\navg = mean([1, 2, 3])",
        "decimal + statistics stdlib",
    ),
    # read from /data (allowed read path)
    (
        "with open('/data/input.parquet', 'rb') as f:\n    data = f.read()",
        "open /data/input.parquet read allowed",
    ),
]


# ---------------------------------------------------------------------------
# Tests -- RED: all fail because validator.py does not exist yet
# ---------------------------------------------------------------------------


class TestValidationResultContract:
    """ValidationResult dataclass must be importable with ok and reason fields."""

    def test_importable(self):
        from bd_agent.sandbox.validator import ValidationResult  # noqa: F401

    def test_ok_true_has_none_reason(self):
        from bd_agent.sandbox.validator import ValidationResult

        result = ValidationResult(ok=True, reason=None)
        assert result.ok is True
        assert result.reason is None

    def test_ok_false_has_reason_string(self):
        from bd_agent.sandbox.validator import ValidationResult

        result = ValidationResult(ok=False, reason="some error")
        assert result.ok is False
        assert result.reason == "some error"

    def test_frozen_immutable(self):
        from bd_agent.sandbox.validator import ValidationResult

        result = ValidationResult(ok=True, reason=None)
        with pytest.raises((AttributeError, TypeError)):
            result.ok = False  # type: ignore[misc]


class TestMaliciousPayloadsRejected:
    """All malicious payloads must be rejected (RF-112, RF-113, RF-114, RF-115)."""

    @pytest.mark.parametrize("code,label", MALICIOUS_PAYLOADS)
    def test_malicious_payload_rejected(self, code: str, label: str):
        from bd_agent.sandbox.validator import validate_python_code

        result = validate_python_code(code)
        assert result.ok is False, (
            f"Expected rejection for [{label}] but got ok=True.\nCode:\n{code}"
        )
        assert result.reason is not None, (
            f"Rejection for [{label}] must include a reason string"
        )
        assert len(result.reason) > 0, (
            f"Rejection reason for [{label}] must not be empty"
        )


class TestLegitimateScriptsAccepted:
    """All legitimate scripts must pass validation (RF-111, RF-115)."""

    @pytest.mark.parametrize("code,label", LEGITIMATE_SCRIPTS)
    def test_legitimate_script_accepted(self, code: str, label: str):
        from bd_agent.sandbox.validator import validate_python_code

        result = validate_python_code(code)
        assert result.ok is True, (
            f"Expected acceptance for [{label}] but got ok=False.\n"
            f"Reason: {result.reason}\nCode:\n{code}"
        )


class TestValidateReturnType:
    """validate_python_code always returns a ValidationResult."""

    def test_returns_validation_result_on_success(self):
        from bd_agent.sandbox.validator import ValidationResult, validate_python_code

        result = validate_python_code("import pandas as pd")
        assert isinstance(result, ValidationResult)

    def test_returns_validation_result_on_failure(self):
        from bd_agent.sandbox.validator import ValidationResult, validate_python_code

        result = validate_python_code("import subprocess")
        assert isinstance(result, ValidationResult)

    def test_empty_script_is_valid(self):
        """An empty script has no violations -- valid but useless."""
        from bd_agent.sandbox.validator import validate_python_code

        result = validate_python_code("")
        assert result.ok is True

    def test_syntax_error_returns_failure(self):
        """A script with a syntax error should fail validation gracefully."""
        from bd_agent.sandbox.validator import validate_python_code

        result = validate_python_code("def (")
        assert result.ok is False
        assert result.reason is not None


class TestPathSafetyEdgeCases:
    """Additional edge cases for path safety (RF-114)."""

    def test_output_subpath_accepted(self):
        """Writing to a sub-path under /output/ is allowed."""
        from bd_agent.sandbox.validator import validate_python_code

        code = "open('/output/subdir/report.xlsx', 'wb')"
        result = validate_python_code(code)
        assert result.ok is True

    def test_data_read_path_accepted(self):
        """Reading from /data/ is allowed."""
        from bd_agent.sandbox.validator import validate_python_code

        code = "open('/data/input.parquet', 'rb')"
        result = validate_python_code(code)
        assert result.ok is True

    def test_absolute_root_path_rejected(self):
        """Opening / itself is rejected."""
        from bd_agent.sandbox.validator import validate_python_code

        result = validate_python_code("open('/', 'r')")
        assert result.ok is False

    def test_home_path_rejected(self):
        """Opening /home/... is rejected (not under /data/ or /output/)."""
        from bd_agent.sandbox.validator import validate_python_code

        result = validate_python_code("open('/home/runner/.ssh/id_rsa', 'r')")
        assert result.ok is False
