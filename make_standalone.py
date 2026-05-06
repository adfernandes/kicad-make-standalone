#!/usr/bin/env python3
"""Make a KiCad 10 project self-contained / redistributable.

Just run it; the script auto-detects the project (walks up from cwd to find a
.kicad_pro) and re-execs itself with KiCad's bundled Python if pcbnew is missing.

  python3 tools/make_standalone.py [--project-dir DIR] [--lib-name NAME] [--dry-run] [--force]

Override Python discovery: set the KICAD_PYTHON env var to KiCad's python3.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import cast

KICAD_SYM_FORMAT_VERSION = "20251024"


def _default_prefs() -> Path:
    """KiCad 10 preferences directory, per OS."""
    sys_name = platform.system()
    if sys_name == "Darwin":
        return Path.home() / "Library/Preferences/kicad/10.0"
    if sys_name == "Windows":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / "AppData/Roaming")
        return base / "kicad/10.0"
    # Linux / Unix (XDG)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".config")
    return base / "kicad/10.0"


def _hardcoded_fallback_candidates() -> dict[str, list[Path]]:
    """Last-resort candidate paths for KiCad 10 library roots, per OS.

    The resolver tries each in order and uses the first that exists. Used only
    when neither kicad_common.json nor os.environ define the variable.
    """
    sys_name = platform.system()
    home = Path.home()
    if sys_name == "Darwin":
        return {
            "KICAD10_3DMODEL_DIR": [
                home / "Documents/KiCad/10.0/3dmodels",
                Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"),
            ],
            "KICAD10_FOOTPRINT_DIR": [
                home / "Documents/KiCad/10.0/footprints",
                Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),
            ],
        }
    if sys_name == "Windows":
        return {
            "KICAD10_3DMODEL_DIR": [
                Path("C:/Program Files/KiCad/10.0/share/kicad/3dmodels"),
                Path("C:/Program Files (x86)/KiCad/10.0/share/kicad/3dmodels"),
            ],
            "KICAD10_FOOTPRINT_DIR": [
                Path("C:/Program Files/KiCad/10.0/share/kicad/footprints"),
                Path("C:/Program Files (x86)/KiCad/10.0/share/kicad/footprints"),
            ],
        }
    # Linux / other Unix
    return {
        "KICAD10_3DMODEL_DIR": [
            Path("/usr/share/kicad/3dmodels"),
            Path("/usr/local/share/kicad/3dmodels"),
            home / ".local/share/kicad/3dmodels",
        ],
        "KICAD10_FOOTPRINT_DIR": [
            Path("/usr/share/kicad/footprints"),
            Path("/usr/local/share/kicad/footprints"),
            home / ".local/share/kicad/footprints",
        ],
    }


DEFAULT_PREFS = _default_prefs()
HARDCODED_FALLBACKS = _hardcoded_fallback_candidates()


# ---------------------------------------------------------------------------
# KiCad Python discovery + auto re-exec
# ---------------------------------------------------------------------------


def find_kicad_python() -> Path | None:
    """Locate KiCad's bundled python3 across macOS / Linux / Windows."""
    candidates: list[Path] = []

    if env := os.environ.get("KICAD_PYTHON"):
        candidates.append(Path(env))

    system = platform.system()
    if system == "Darwin":
        for app in ("/Applications/KiCad/KiCad.app", "/Applications/KiCad.app"):
            candidates.append(
                Path(app)
                / "Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
            )
    elif system == "Linux":
        candidates += [Path("/usr/bin/python3"), Path("/usr/local/bin/python3")]
    elif system == "Windows":
        for pf in ("C:/Program Files/KiCad", "C:/Program Files (x86)/KiCad"):
            base = Path(pf)
            if base.exists():
                # KiCad-10 only — match "10.*" first; sort lexicographically does
                # NOT order versions correctly across major versions ("9.0" > "10.0").
                candidates += sorted(base.glob("10.*/bin/python.exe"), reverse=True)
                candidates += sorted(base.glob("*/bin/python.exe"), reverse=True)

    cli = shutil.which("kicad-cli") or shutil.which("kicad-cli.exe")
    if cli:
        cli_path = Path(cli).resolve()
        if system == "Darwin":
            candidates.append(
                cli_path.parent.parent
                / "Frameworks/Python.framework/Versions/Current/bin/python3"
            )
        elif system == "Linux":
            candidates.append(cli_path.parent / "python3")
        elif system == "Windows":
            candidates.append(cli_path.parent / "python.exe")

    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            res = subprocess.run(
                [str(cand), "-c", "import pcbnew"], capture_output=True
            )
            if res.returncode == 0:
                return cand.resolve()
    return None


def ensure_kicad_python() -> None:
    """If pcbnew is not importable, find KiCad's Python and re-exec ourselves."""
    try:
        import pcbnew  # type: ignore[import-not-found]  # noqa: F401

        return
    except ImportError:
        pass

    kp = find_kicad_python()
    if kp is None:
        sys.exit(
            "pcbnew module not found and KiCad's Python could not be located.\n"
            "Set KICAD_PYTHON env var to KiCad's python3, or install KiCad. Common paths:\n"
            "  macOS:   /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3\n"
            "  Linux:   /usr/bin/python3 (with KiCad system package installed)\n"
            "  Windows: C:\\Program Files\\KiCad\\<ver>\\bin\\python.exe"
        )
    print(f"[make_standalone] re-execing with KiCad's Python: {kp}", file=sys.stderr)
    argv = [str(kp), str(Path(__file__).resolve()), *sys.argv[1:]]
    if platform.system() == "Windows":
        # os.execv on Windows goes through the MS CRT which mis-quotes paths with
        # spaces (e.g. "C:\Program Files\..."); subprocess.run uses CreateProcessW
        # and quotes correctly.
        sys.exit(subprocess.run(argv).returncode)
    os.execv(str(kp), argv)


def find_project_dir(start: Path) -> Path:
    """Walk up from `start` (max 4 levels) until a directory contains a .kicad_pro."""
    cur = start.resolve()
    for _ in range(4):
        if list(cur.glob("*.kicad_pro")):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


# ---------------------------------------------------------------------------
# S-expression utilities (paren-aware, string-aware) — no external deps
# ---------------------------------------------------------------------------


def find_block(text: str, head: str, start: int = 0) -> tuple[int, int] | None:
    """Find `(head ...)` block and return (start_paren_idx, end_paren_idx_exclusive)."""
    needle = "(" + head
    i = text.find(needle, start)
    if i < 0:
        return None
    return i, find_matching_paren(text, i) + 1


def find_matching_paren(text: str, open_idx: int) -> int:
    """Given index of '(', return index of matching ')'. Respects "..." with \\\" escapes."""
    assert text[open_idx] == "("
    depth = 0
    in_str = False
    escape = False
    i = open_idx
    while i < len(text):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    raise ValueError("unbalanced parens")


def iter_top_level_children(
    text: str, block_start: int, block_end: int, head: str
) -> Iterable[tuple[int, int]]:
    """Iterate (start, end_exclusive) for direct `(head ...)` children of a block.

    block_start..block_end are the bounds of the parent block (including the outer parens).
    """
    inner_start = block_start + 1  # skip '('
    inner_end = block_end - 1  # before ')'
    # Skip the head token of the parent
    i = text.find(head, inner_start, inner_end)
    if i < 0:
        return
    i += len(head)
    needle = "(" + head + " "
    while True:
        # find next direct child opening at depth 0 relative to the block body
        j = text.find(needle, i, inner_end)
        if j < 0:
            return
        # Confirm depth 0 between i and j (no unmatched opens)
        if _balanced_between(text, i, j):
            end = find_matching_paren(text, j) + 1
            yield j, end
            i = end
        else:
            i = j + 1


def _balanced_between(text: str, a: int, b: int) -> bool:
    """True if parens between a and b (exclusive) are balanced (no nesting carry-over)."""
    depth = 0
    in_str = False
    escape = False
    for k in range(a, b):
        c = text[k]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth < 0:
                    return False
    return depth == 0


# ---------------------------------------------------------------------------
# KiCad path-variable resolver
# ---------------------------------------------------------------------------


def _read_kicad_env_vars(common: Path) -> dict[str, str]:
    """Read environment.vars from kicad_common.json. Returns {} on any failure."""
    try:
        data = json.loads(common.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    env = cast("dict[str, object]", data).get("environment")
    if not isinstance(env, dict):
        return {}
    raw = cast("dict[str, object]", env).get("vars")
    if not isinstance(raw, dict):
        return {}
    return dict(cast("dict[str, str]", raw))


class VarResolver:
    def __init__(self, project_dir: Path, warnings: list[str]):
        self.project_dir = project_dir.resolve()
        self.warnings = warnings
        self.vars: dict[str, str] = {}
        self._unresolved_seen: set[str] = set()

        common = DEFAULT_PREFS / "kicad_common.json"
        if common.exists():
            self.vars.update(_read_kicad_env_vars(common))

    def resolve_var(self, name: str) -> str | None:
        if name == "KIPRJMOD":
            return str(self.project_dir)
        if name in self.vars:
            return self.vars[name]
        env = os.environ.get(name)
        if env:
            return env
        if name in HARDCODED_FALLBACKS:
            for cand in HARDCODED_FALLBACKS[name]:
                if cand.exists():
                    return str(cand)
        # KICAD9_* fallback to KICAD10_*
        if name.startswith("KICAD9_"):
            sub = "KICAD10_" + name[len("KICAD9_") :]
            v = self.resolve_var(sub)
            if v is not None:
                if name not in self._unresolved_seen:
                    self.warnings.append(f"{name} not defined; using {sub} fallback")
                    self._unresolved_seen.add(name)
                return v
        return None

    _PAT = re.compile(r"\$\{([A-Z0-9_]+)\}")

    def expand(self, s: str) -> str:
        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            v = self.resolve_var(name)
            if v is None:
                if name not in self._unresolved_seen:
                    self.warnings.append(f"unresolved variable ${{{name}}}")
                    self._unresolved_seen.add(name)
                return m.group(0)
            return v

        return self._PAT.sub(sub, s)


# ---------------------------------------------------------------------------
# fp-lib-table resolver (handles type="Table" recursion)
# ---------------------------------------------------------------------------

_LIB_RE = re.compile(
    r'\(lib\s+\(name\s+"([^"]+)"\)\s+\(type\s+"([^"]+)"\)\s+\(uri\s+"([^"]+)"\)'
)


def load_fp_lib_table(
    path: Path, resolver: VarResolver, seen: set[Path] | None = None
) -> dict[str, str]:
    """Return {libName: prettyDir} from a (possibly recursive) fp-lib-table file."""
    seen = seen or set()
    real = path.resolve()
    if real in seen:
        return {}
    seen.add(real)
    if not path.exists():
        return {}
    text = path.read_text()
    out: dict[str, str] = {}
    for m in _LIB_RE.finditer(text):
        name, ltype, uri = m.group(1), m.group(2), m.group(3)
        expanded = resolver.expand(uri)
        if ltype == "Table":
            out.update(load_fp_lib_table(Path(expanded), resolver, seen))
        elif ltype == "KiCad":
            out[name] = expanded
    return out


# ---------------------------------------------------------------------------
# Symbol library extraction from .kicad_sch
# ---------------------------------------------------------------------------


def build_kicad_sym(
    sch_text: str, lib_name: str, warnings: list[str]
) -> tuple[str, list[str]]:
    """Return (.kicad_sym file content, list of kept symbol names)."""
    block = find_block(sch_text, "lib_symbols")
    if block is None:
        raise RuntimeError("(lib_symbols ...) block not found in schematic")
    block_start, block_end = block

    kept: list[tuple[str, str]] = []  # (name, raw_block_text)
    skipped_power = 0
    skipped_no_colon = 0

    for cs, ce in iter_top_level_children(sch_text, block_start, block_end, "symbol"):
        child = sch_text[cs:ce]
        m = re.match(r'\(symbol\s+"([^"]+)"', child)
        if not m:
            continue
        full_name = m.group(1)
        if ":" not in full_name:
            skipped_no_colon += 1
            continue
        prefix, short = full_name.split(":", 1)
        if prefix == "power":
            skipped_power += 1
            continue
        # Rewrite the name token in the child text
        new_child = child.replace(f'"{full_name}"', f'"{short}"', 1)
        kept.append((short, new_child))

    if skipped_power:
        pass  # informational, surfaced via report
    if skipped_no_colon:
        warnings.append(
            f"skipped {skipped_no_colon} unprefixed symbol entries in lib_symbols (likely power instances)"
        )

    body_parts: list[str] = []
    for _, raw in kept:
        # Re-indent: each child is currently indented for its position inside (lib_symbols ...).
        # The raw text starts at "(symbol ..." with no leading whitespace; we add a tab for the
        # top-level placement under (kicad_symbol_lib ...).
        body_parts.append("\t" + raw)
    body = "\n".join(body_parts)

    out = (
        "(kicad_symbol_lib\n"
        f"\t(version {KICAD_SYM_FORMAT_VERSION})\n"
        '\t(generator "make_standalone")\n'
        '\t(generator_version "10.0")\n' + body + "\n)\n"
    )
    return out, [n for n, _ in kept]


# ---------------------------------------------------------------------------
# Footprint copy + 3D model handling
# ---------------------------------------------------------------------------

_FP_REF_RE = re.compile(r'\(footprint\s+"([^"]+)"')
_MODEL_RE = re.compile(r'\(model\s+"([^"]+)"')


def collect_pcb_footprints(pcb_text: str) -> set[tuple[str, str]]:
    """Return {(libName, fpName)} for each (footprint "LIB:NAME" ...) in the PCB."""
    out: set[tuple[str, str]] = set()
    for m in _FP_REF_RE.finditer(pcb_text):
        ref = m.group(1)
        if ":" in ref:
            lib, name = ref.split(":", 1)
            out.add((lib, name))
    return out


def copy_footprint(
    lib: str, name: str, fp_lib_table: dict[str, str], dest_dir: Path
) -> Path:
    if lib not in fp_lib_table:
        raise RuntimeError(f"footprint lib '{lib}' not found in any fp-lib-table")
    src = Path(fp_lib_table[lib]) / f"{name}.kicad_mod"
    if not src.exists():
        raise RuntimeError(f"footprint file missing: {src}")
    dest = dest_dir / f"{name}.kicad_mod"
    shutil.copy2(src, dest)
    return dest


def collect_models_from_kicad_mod(path: Path) -> list[str]:
    return _MODEL_RE.findall(path.read_text())


def copy_3d_model(
    uri: str,
    resolver: VarResolver,
    dest_dir: Path,
    warnings: list[str],
    copied: dict[str, Path],
) -> str | None:
    """Resolve URI, copy the file (and optional sibling .wrl/.stp/.step) into dest_dir.
    Returns the destination basename to use in the remapped (model "...") line, or None on failure."""
    expanded = resolver.expand(uri)
    src = Path(expanded)
    if not src.exists():
        # Try basename scan under KICAD10_3DMODEL_DIR if URI used KICAD9_*
        root = resolver.resolve_var("KICAD10_3DMODEL_DIR")
        if root:
            for cand in Path(root).rglob(src.name):
                src = cand
                break
        if not src.exists():
            warnings.append(f"3D model not found, skipped: {uri}")
            return None
    base = src.name
    if uri in copied:
        return copied[uri].name
    dest = dest_dir / base
    if dest.exists() and dest.resolve() != src.resolve():
        # Different source mapped to same dest name
        stem = src.parent.name.replace(".3dshapes", "")
        dest = dest_dir / f"{src.stem}__{stem}{src.suffix}"
        warnings.append(f"3D model name collision; renamed to {dest.name}")
    shutil.copy2(src, dest)
    copied[uri] = dest

    # Probe siblings: .wrl/.stp/.step variants
    for ext in (".wrl", ".step", ".stp"):
        sib = src.with_suffix(ext)
        if sib.exists() and sib != src:
            sib_dest = dest.with_suffix(ext)
            if not sib_dest.exists():
                shutil.copy2(sib, sib_dest)
    return dest.name


# ---------------------------------------------------------------------------
# File remap (regex)
# ---------------------------------------------------------------------------


def _lib_sub(lib_name: str) -> Callable[[re.Match[str]], str]:
    return lambda m: m.group(0).replace(
        f'"{m.group(1)}:{m.group(2)}"', f'"{lib_name}:{m.group(2)}"'
    )


def remap_kicad_sch(text: str, lib_name: str) -> str:
    # (symbol "LIB:NAME"  — definitions inside lib_symbols
    text = re.sub(r'\(symbol "(?!power:)([^":]+):([^"]+)"', _lib_sub(lib_name), text)
    # (lib_id "LIB:NAME")  — instance references
    text = re.sub(r'\(lib_id "(?!power:)([^":]+):([^"]+)"\)', _lib_sub(lib_name), text)
    # (property "Footprint" "LIB:NAME"
    text = re.sub(
        r'\(property "Footprint" "(?!power:)([^":]+):([^"]+)"',
        lambda m: m.group(0).replace(
            f'"{m.group(1)}:{m.group(2)}"', f'"{lib_name}:{m.group(2)}"'
        ),
        text,
    )
    return text


def remap_kicad_pcb(text: str, lib_name: str) -> str:
    text = re.sub(r'\(footprint "(?!power:)([^":]+):([^"]+)"', _lib_sub(lib_name), text)
    text = re.sub(
        r'\(property "Footprint" "(?!power:)([^":]+):([^"]+)"',
        lambda m: m.group(0).replace(
            f'"{m.group(1)}:{m.group(2)}"', f'"{lib_name}:{m.group(2)}"'
        ),
        text,
    )
    text = remap_model_paths(text, lib_name)
    return text


def remap_model_paths(text: str, lib_name: str) -> str:
    """Rewrite (model "${KICAD..._3DMODEL_DIR}/Subdir.3dshapes/file.ext" ...) → project-relative."""
    return re.sub(
        r'\(model "\$\{KICAD\d+_3DMODEL_DIR\}/[^/"]+\.3dshapes/([^"]+)"',
        lambda m: f'(model "${{KIPRJMOD}}/{lib_name}.3dshapes/{m.group(1)}"',
        text,
    )


# ---------------------------------------------------------------------------
# Library tables (project-level)
# ---------------------------------------------------------------------------

SYM_LIB_TABLE_TPL = """(sym_lib_table
\t(version 7)
\t(lib (name "{lib}") (type "KiCad") (uri "${{KIPRJMOD}}/{lib}.kicad_sym") (options "") (descr ""))
)
"""

FP_LIB_TABLE_TPL = """(fp_lib_table
\t(version 7)
\t(lib (name "{lib}") (type "KiCad") (uri "${{KIPRJMOD}}/{lib}.pretty") (options "") (descr ""))
)
"""


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def detect_project(project_dir: Path) -> Path:
    pros = list(project_dir.glob("*.kicad_pro"))
    if len(pros) != 1:
        raise SystemExit(
            f"expected exactly one .kicad_pro in {project_dir}, found {len(pros)}"
        )
    return pros[0]


def preflight(
    project_dir: Path, lib_name: str, force: bool
) -> tuple[Path, Path, Path, Path]:
    import pcbnew  # type: ignore[import-not-found]

    version = str(pcbnew.Version())  # type: ignore[attr-defined]
    if not version.startswith("10."):
        print(f"warning: pcbnew version {version} (expected 10.x)", file=sys.stderr)

    sch = project_dir / (detect_project(project_dir).stem + ".kicad_sch")
    pcb = project_dir / (detect_project(project_dir).stem + ".kicad_pcb")
    sym_tbl = project_dir / "sym-lib-table"
    fp_tbl = project_dir / "fp-lib-table"
    for f in (sch, pcb):
        if not f.exists():
            raise SystemExit(f"missing required file: {f}")

    locks = list(project_dir.glob("*.kicad_pro-lock"))
    if locks and not force:
        raise SystemExit(
            f"KiCad appears open (lock file: {locks[0]}). Close it or use --force"
        )

    # Idempotence guard
    if sch.exists():
        count = sch.read_text().count(f'"{lib_name}:')
        count += pcb.read_text().count(f'"{lib_name}:')
        if count > 5 and not force:
            raise SystemExit(
                f"project looks already converted ({count} '{lib_name}:' refs). "
                "Use --force to re-run."
            )
    return sch, pcb, sym_tbl, fp_tbl


def backup(p: Path, force: bool) -> Path | None:
    if not p.exists():
        return None
    bak = p.with_suffix(p.suffix + ".bak")
    if bak.exists() and not force:
        raise SystemExit(f"backup already exists: {bak} (use --force to overwrite)")
    shutil.copy2(p, bak)
    return bak


def cleanup_stale(project_dir: Path) -> list[str]:
    removed: list[str] = []
    for name in ("Library.kicad_sym",):
        p = project_dir / name
        if p.exists():
            p.unlink()
            removed.append(name)
    for name in ("Library.pretty", "Library.3dshapes"):
        p = project_dir / name
        if p.exists() and p.is_dir():
            shutil.rmtree(p)
            removed.append(name)
    return removed


def run(args: argparse.Namespace) -> int:
    project_dir = (
        Path(args.project_dir) if args.project_dir else find_project_dir(Path.cwd())
    ).resolve()
    pro = detect_project(project_dir)
    lib_name = args.lib_name or f"{pro.stem}_Lib"

    warnings: list[str] = []
    sch, pcb, sym_tbl, fp_tbl = preflight(project_dir, lib_name, args.force)
    resolver = VarResolver(project_dir, warnings)

    # Resolve global fp-lib-table
    global_fp_tbl = DEFAULT_PREFS / "fp-lib-table"
    fp_lib_map = load_fp_lib_table(global_fp_tbl, resolver)
    if args.verbose:
        print(f"loaded {len(fp_lib_map)} libs from global fp-lib-table chain")

    # Inventory
    sch_text = sch.read_text()
    pcb_text = pcb.read_text()
    used_fps = collect_pcb_footprints(pcb_text)

    if args.dry_run:
        print(f"== DRY RUN — project: {project_dir.name} -> lib '{lib_name}'")
        print(f"  schematic: {sch.name} ({len(sch_text)} bytes)")
        print(f"  pcb:       {pcb.name} ({len(pcb_text)} bytes)")
        print(f"  used footprint refs: {len(used_fps)}")
        for lib, name in sorted(used_fps):
            located = lib in fp_lib_map
            print(f"    [{'OK' if located else 'MISS'}] {lib}:{name}")
        # Inventory 3D models referenced from those footprints
        models: list[tuple[str, str]] = []
        for lib, name in used_fps:
            if lib in fp_lib_map:
                fp_path = Path(fp_lib_map[lib]) / f"{name}.kicad_mod"
                if fp_path.exists():
                    for m in collect_models_from_kicad_mod(fp_path):
                        models.append((m, str(fp_path.name)))
        print(
            f"  3D models referenced: {len(models)} ({len({m for m, _ in models})} unique)"
        )
        for uri in sorted({m for m, _ in models}):
            resolved = resolver.expand(uri)
            ok = Path(resolved).exists()
            print(f"    [{'OK' if ok else 'MISS'}] {uri}")
        if warnings:
            print("\nWARNINGS:")
            for w in warnings:
                print(f"  - {w}")
        return 0

    # Backups
    backups: list[Path] = []
    for f in (sch, pcb, sym_tbl, fp_tbl):
        b = backup(f, args.force)
        if b:
            backups.append(b)

    # Cleanup stale Library.*
    removed = cleanup_stale(project_dir)
    if removed and args.verbose:
        print(f"removed stale: {', '.join(removed)}")

    # Build .kicad_sym
    sym_lib_path = project_dir / f"{lib_name}.kicad_sym"
    sym_content, kept_syms = build_kicad_sym(sch_text, lib_name, warnings)
    sym_lib_path.write_text(sym_content)
    if args.verbose:
        print(f"wrote {sym_lib_path.name} ({len(kept_syms)} symbols)")

    # Create .pretty and copy footprints
    pretty_dir = project_dir / f"{lib_name}.pretty"
    pretty_dir.mkdir(exist_ok=True)
    fp_files: list[Path] = []
    for lib, name in sorted(used_fps):
        try:
            fp_files.append(copy_footprint(lib, name, fp_lib_map, pretty_dir))
        except RuntimeError as e:
            warnings.append(str(e))
    if args.verbose:
        print(f"copied {len(fp_files)} footprints to {pretty_dir.name}/")

    # Create .3dshapes and copy 3D models referenced by copied footprints
    shapes_dir = project_dir / f"{lib_name}.3dshapes"
    shapes_dir.mkdir(exist_ok=True)
    copied_models: dict[str, Path] = {}
    for fp_file in fp_files:
        for uri in collect_models_from_kicad_mod(fp_file):
            copy_3d_model(uri, resolver, shapes_dir, warnings, copied_models)
    if args.verbose:
        print(f"copied {len(copied_models)} 3D models to {shapes_dir.name}/")

    # Remap copied .kicad_mod files (3D model paths)
    for fp_file in fp_files:
        text = fp_file.read_text()
        new_text = remap_model_paths(text, lib_name)
        if new_text != text:
            fp_file.write_text(new_text)

    # Remap schematic and PCB
    sch.write_text(remap_kicad_sch(sch_text, lib_name))
    pcb.write_text(remap_kicad_pcb(pcb_text, lib_name))

    # Rewrite project library tables
    sym_tbl.write_text(SYM_LIB_TABLE_TPL.format(lib=lib_name))
    fp_tbl.write_text(FP_LIB_TABLE_TPL.format(lib=lib_name))

    # Final report
    ext_counts: dict[str, int] = {}
    for p in copied_models.values():
        ext_counts[p.suffix.lower()] = ext_counts.get(p.suffix.lower(), 0) + 1
    ext_str = ", ".join(f"{k}:{v}" for k, v in sorted(ext_counts.items())) or "none"

    print()
    print("== Build self-contained ==")
    print(f"  Project           : {pro.stem}")
    print(f"  Lib name          : {lib_name}")
    print(
        f"  Symbols copied    : {len(kept_syms)} (skipped power: kept system-referenced)"
    )
    print(f"  Footprints copied : {len(fp_files)}")
    print(f"  3D models copied  : {len(copied_models)} ({ext_str})")
    print(
        "  Files modified    : 4 (.kicad_sch, .kicad_pcb, sym-lib-table, fp-lib-table)"
    )
    print(f"  Backups           : {len(backups)} (*.bak)")
    if warnings:
        print()
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ensure_kicad_python()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--project-dir",
        default=None,
        help="path to KiCad project (default: walk up from cwd to find a .kicad_pro)",
    )
    p.add_argument(
        "--lib-name",
        default=None,
        help="override lib name (default: <ProjectName>_Lib)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report inventory and resolution, no writes",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite backups, ignore lock files / idempotence guard",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
