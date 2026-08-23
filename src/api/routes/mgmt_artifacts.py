"""
Management API routes: read-only artifact browser over data/output/.

Endpoints:
    GET    /mgmt/artifacts/tree    — three-level tree (service -> period -> files)
    GET    /mgmt/artifacts/file    — serve a single artifact file

Non-negotiable constraints (see spec RF-15..RF-18):
    - Path traversal is rejected with 4xx; the resolved candidate must stay
      inside the artifacts root (RF-15).
    - No on-demand office-document rendering process is ever invoked here —
      inline preview is limited to PNGs that already exist on disk (RF-16).
    - No DELETE method is exposed anywhere under this router (RF-17).
    - Loose files at the root of data/output/ are bucketed as "unclassified";
      period folders that do not match the YYYY-MM / YYYY-MM-DD convention
      are flagged anomalous instead of being silently reclassified (RF-18).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt")

# Default artifacts root — overridable via set_artifacts_root() for tests.
_ARTIFACTS_ROOT: Optional[Path] = None

_PERIOD_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_PERIOD_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Backup naming is owned by src/core/output_paths.py::prepare_accumulative_file,
# which writes `target_path.with_stem(stem + "_backup")`. The dated and ".bak"
# variants are hand-made backups that follow the same idea. Kept as a local
# regex rather than imported: output_paths.py builds names, it does not expose
# a predicate to recognize them, and this module must not push new API onto a
# module the report pipeline depends on.
_BACKUP_RE = re.compile(r"(_backup(-.+)?$|\.bak(\.|$))", re.IGNORECASE)

# PNG capture naming is owned by src/core/excel_manager.py, which writes
# f"{self.ruta_excel.stem}_{sheet_name}_{range_slug}.png" with range_slug being
# the A1:D10 range with ':' replaced by '_'. Only the trailing two cell refs are
# unambiguous — both the workbook stem and the sheet name may contain '_', so
# the boundary between them is recovered from the sibling workbook instead of
# guessed. See _png_metadata().
_PNG_TAIL_RE = re.compile(
    r"^(?P<prefix>.+)_(?P<top_left>[A-Za-z]+\d+)_(?P<bottom_right>[A-Za-z]+\d+)\.png$"
)


def set_artifacts_root(path: Optional[Path]) -> None:
    """Override the artifacts root directory (used in tests).

    Pass None to clear the override and fall back to config.settings.
    Tests MUST restore it, or the global stays pinned to a deleted tmp path
    for the rest of the pytest session and every later caller reads from
    nowhere.
    """
    global _ARTIFACTS_ROOT
    _ARTIFACTS_ROOT = Path(path) if path is not None else None


def _get_artifacts_root() -> Path:
    """Resolve the artifacts root, in precedence order.

    1. set_artifacts_root() — explicit, used by tests.
    2. ADMIN_PANEL_ARTIFACTS_ROOT — points the panel at a data/output/ tree
       outside this checkout (reviewing the production tree from a worktree)
       without editing config/settings.py. Read-only either way: this router
       exposes no write or delete method (RF-17).
    3. config.settings.DATA_OUTPUT — the checkout's own tree.
    """
    if _ARTIFACTS_ROOT is not None:
        return _ARTIFACTS_ROOT
    env_root = os.environ.get("ADMIN_PANEL_ARTIFACTS_ROOT")
    if env_root:
        return Path(env_root)
    import config.settings as _settings  # call-time bind for test patching
    return _settings.DATA_OUTPUT


def _mtime_iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _safe_listdir(directory: Path) -> Optional[list[Path]]:
    """List a directory, or return None when it cannot be read.

    data/output/ is written by the daily pipeline while the panel reads it, so
    a directory can vanish or be unreadable mid-scan. Returning None lets the
    caller mark that one node unreadable instead of failing the whole tree.
    """
    try:
        return sorted(directory.iterdir())
    except OSError:
        logger.warning("Could not list %s — reported as unreadable", directory, exc_info=True)
        return None


def _resolves_inside(root: Path, path: Path) -> bool:
    """True when `path` really lives under `root` after following symlinks."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        # RuntimeError covers a symlink loop; ValueError an embedded null byte.
        return False


def _safe_file_entry(
    root: Path, path: Path, workbook_stems: Optional[set[str]] = None
) -> Optional[dict]:
    """Build a file entry, or return None when the file must not be listed.

    A symlink pointing outside the artifacts root is dropped rather than
    described: stat() follows the link, so listing it would publish the
    target's size and mtime, and the download endpoint would reject it with
    400 anyway — a file the screen shows but can never open.
    """
    if not _resolves_inside(root, path):
        logger.warning("Skipping artifact resolving outside the root: %s", path)
        return None
    try:
        return _file_entry(root, path, workbook_stems)
    except OSError:
        logger.warning("Skipping unreadable artifact %s", path, exc_info=True)
        return None


def _is_valid_period(name: str) -> bool:
    return bool(_PERIOD_MONTH_RE.match(name) or _PERIOD_DAY_RE.match(name))


def _bucket_for(path: Path) -> str:
    """Classify a single artifact file into principal / imagenes / backups."""
    if path.suffix.lower() == ".bak":
        return "backups"
    # Matched on the stem only: ".bak" as a loose substring of the full name
    # would misfile something like "informe.bakery.xlsx" as a backup.
    if _BACKUP_RE.search(path.stem):
        return "backups"
    if path.suffix.lower() == ".png":
        return "imagenes"
    return "principal"


def _png_metadata(name: str, workbook_stems: set[str]) -> dict:
    """Recover the sheet and cell range a capture came from.

    The range is the trailing pair of cell refs and is unambiguous. The sheet
    is whatever sits between the workbook stem and that range — but both the
    stem and the sheet name may contain '_', so the split is only knowable by
    matching a workbook that actually sits in the same folder. Longest stem
    wins, since a longer match is the more specific one.

    When no sibling workbook confirms the split the sheet is omitted: a guess
    here would be rendered as a fact next to the image.
    """
    match = _PNG_TAIL_RE.match(name)
    if not match:
        return {}

    meta = {"range": f"{match.group('top_left')}:{match.group('bottom_right')}"}
    prefix = match.group("prefix")
    candidates = [s for s in workbook_stems if prefix.startswith(f"{s}_")]
    if candidates:
        stem = max(candidates, key=len)
        meta["sheet"] = prefix[len(stem) + 1:]
    return meta


def _file_entry(root: Path, path: Path, workbook_stems: Optional[set[str]] = None) -> dict:
    rel = path.relative_to(root)
    # One stat() per file: the tree walks thousands of entries and each extra
    # syscall is paid for every one of them.
    stat = path.stat()
    entry: dict = {
        "name": path.name,
        "path": str(rel).replace("\\", "/"),
        "kind": path.suffix.lstrip(".").lower() or "other",
        "size_bytes": stat.st_size,
        "mtime": _mtime_iso(stat.st_mtime),
    }
    if path.suffix.lower() == ".png":
        entry.update(_png_metadata(path.name, workbook_stems or set()))
    return entry


def _iter_period_files(period_dir: Path):
    """Yield every file under a period, including one level of subdirectory.

    graficos-cobertura writes ~50 PNGs per month into a `png/` subfolder
    (PNG_SUBDIR in src/services/graficos_cobertura/constants.py). A flat
    iterdir() would drop all of them, which is exactly the content the
    Archivos screen exists to show.
    """
    entries = _safe_listdir(period_dir)
    if entries is None:
        raise PermissionError(f"cannot list {period_dir}")
    for entry in entries:
        if entry.is_file():
            yield entry
        elif entry.is_dir():
            nested_entries = _safe_listdir(entry)
            if nested_entries is None:
                continue
            for nested in nested_entries:
                if nested.is_file():
                    yield nested


def _build_period_node(root: Path, period_dir: Path) -> dict:
    node: dict = {
        "periodo": period_dir.name,
        "anomalous": not _is_valid_period(period_dir.name),
        "unreadable": False,
        "principal": [],
        "imagenes": [],
        "backups": [],
    }
    try:
        file_paths = list(_iter_period_files(period_dir))
    except OSError:
        # Surfaced as an explicit flag, never as an empty period: an empty
        # month and an unreadable month mean very different things to whoever
        # is checking whether a report actually ran.
        node["unreadable"] = True
        return node

    # Collected first: a capture's sheet name can only be split off the
    # filename by matching the workbook that produced it (see _png_metadata).
    workbook_stems = {
        p.stem for p in file_paths if p.suffix.lower() in {".xlsx", ".xlsm", ".xls"}
    }

    for file_path in file_paths:
        entry = _safe_file_entry(root, file_path, workbook_stems)
        if entry is None:
            continue
        node[_bucket_for(file_path)].append(entry)
    return node


def _build_tree(root: Path, slug_filter: Optional[str], periodo_filter: Optional[str]) -> dict:
    if not root.exists():
        return {"services": [], "unclassified": []}

    services: list[dict] = []
    unclassified: list[dict] = []

    root_entries = _safe_listdir(root)
    if root_entries is None:
        return {"services": [], "unclassified": []}

    # A stray belongs to no period at all, so a period-filtered request must
    # not return one — otherwise the two buckets answer different questions
    # for the same query.
    collect_strays = periodo_filter is None

    for item in root_entries:
        if item.is_file():
            # Loose file at the root of data/output/ — RF-18 "Sin clasificar" bucket.
            if not collect_strays:
                continue
            entry = _safe_file_entry(root, item)
            if entry is not None:
                unclassified.append(entry)
            continue
        if not item.is_dir():
            continue

        slug = item.name
        if slug.startswith("_"):
            # Not a report service: data/output/_send_log/ holds the delivery
            # log, _trash/ is reserved. Listing them as services would invent
            # a report that does not exist.
            continue
        if slug_filter and slug != slug_filter:
            continue

        periods: list[dict] = []
        service_entries = _safe_listdir(item)
        if service_entries is None:
            services.append({"slug": slug, "periods": [], "unreadable": True})
            continue

        for period_dir in service_entries:
            if not period_dir.is_dir():
                # Loose file directly under the service dir, outside any period
                # folder. It belongs to no period, so it goes to the same
                # "Sin clasificar" bucket as root-level strays (RF-18) rather
                # than being dropped from the tree entirely.
                if not collect_strays:
                    continue
                entry = _safe_file_entry(root, period_dir)
                if entry is not None:
                    unclassified.append(entry)
                continue
            if periodo_filter and period_dir.name != periodo_filter:
                continue
            periods.append(_build_period_node(root, period_dir))

        services.append({"slug": slug, "periods": periods, "unreadable": False})

    return {"services": services, "unclassified": unclassified}


# ---------------------------------------------------------------------------
# GET /mgmt/artifacts/tree
# ---------------------------------------------------------------------------


@router.get("/artifacts/tree")
def get_artifacts_tree(slug: Optional[str] = None, periodo: Optional[str] = None):
    """Return the three-level artifacts tree, optionally filtered by slug/periodo."""
    root = _get_artifacts_root()
    return _build_tree(root, slug, periodo)


# ---------------------------------------------------------------------------
# GET /mgmt/artifacts/file — RF-15 path validation
# ---------------------------------------------------------------------------


@router.get("/artifacts/file")
def get_artifact_file(path: str):
    """Serve a single artifact file, rejecting anything outside the root."""
    try:
        root = _get_artifacts_root().resolve()
        candidate = (root / path).resolve()
        inside = candidate.is_relative_to(root)
    except (OSError, ValueError, RuntimeError):
        # `path` is user-controlled: an embedded null byte raises ValueError and
        # a symlink loop RuntimeError, both from resolve(). RF-15 says a bad
        # path is a 4xx, so neither may surface as an unhandled 500.
        raise HTTPException(status_code=400, detail="invalid path")

    if not inside:
        raise HTTPException(status_code=400, detail="path must resolve inside the artifacts root")

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    # PNGs are the inline preview (RF-16), so they must not be sent as an
    # attachment — <img> ignores the header today, but an <iframe> or a new
    # tab would download instead of showing. Everything else downloads.
    disposition = "inline" if candidate.suffix.lower() == ".png" else "attachment"
    return FileResponse(
        path=str(candidate),
        filename=candidate.name,
        content_disposition_type=disposition,
    )
