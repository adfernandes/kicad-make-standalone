# make_standalone

Make a **KiCad 10** project self-contained and redistributable. The script extracts every symbol, footprint and 3D model used by your project from your global / system libraries, copies them into the project directory, and rewrites the schematic, PCB and library tables so the project no longer depends on anything outside its own folder.

After running it, you can zip the project, send it to a colleague (or commit it to a repo) and it will open and build identically on any machine that has KiCad 10 installed — no library setup required.

## What it does

1. **Symbols** — extracts every used symbol from the schematic's `(lib_symbols ...)` block and writes a project-local `<Project>_Lib.kicad_sym`. Power symbols (`power:*`) are kept as system references.
2. **Footprints** — resolves `fp-lib-table` (recursively, including nested `Table` entries), copies every `.kicad_mod` actually used on the PCB into `<Project>_Lib.pretty/`.
3. **3D models** — parses each copied footprint, resolves `${KICAD10_3DMODEL_DIR}` (and `${KICAD9_*}` fallbacks), copies every model file plus its `.wrl` / `.step` / `.stp` siblings into `<Project>_Lib.3dshapes/`, and rewrites the `(model ...)` paths to `${KIPRJMOD}/...`.
4. **Library tables** — rewrites the project's `sym-lib-table` and `fp-lib-table` so they only reference the local library.
5. **References** — rewrites every `(symbol "LIB:NAME"`, `(lib_id "LIB:NAME")`, `(footprint "LIB:NAME"` and `(property "Footprint" "LIB:NAME"` to use the new local library name.

Original files are backed up next to themselves as `*.bak`.

## Requirements

- **KiCad 10.x** installed (the script imports `pcbnew` from KiCad's bundled Python).
- Python 3 — but you don't need to point at KiCad's Python yourself. The script auto-detects it on macOS / Linux / Windows and re-execs itself with the right interpreter if `pcbnew` is missing in the current one.

To override the Python discovery, set the `KICAD_PYTHON` environment variable to KiCad's `python3` binary.

## Usage

From inside (or anywhere under) a KiCad project directory:

```bash
python3 make_standalone.py
```

The script walks up from the current directory (max 4 levels) until it finds a `.kicad_pro`.

### Options

| Flag | Description |
|---|---|
| `--project-dir DIR` | Path to the KiCad project (default: walk up from cwd) |
| `--output-dir DIR` | Copy the project to this dir and convert there; the source is left untouched |
| `--lib-name NAME` | Override the local library name (default: `<ProjectName>_Lib`) |
| `--dry-run` | Inventory and resolution report only, no writes |
| `--force` | Overwrite existing `.bak` files, ignore lock files and the idempotence guard |
| `--verbose`, `-v` | Verbose output |

### Recommended workflow

1. **Close KiCad** on the project (the script refuses to run if a `*.kicad_pro-lock` is present, unless you pass `--force`).
2. Run a dry run first:
   ```bash
   python3 make_standalone.py --dry-run
   ```
   Check the report — anything marked `[MISS]` is a missing footprint or 3D model in your local KiCad install.
3. Run for real:
   ```bash
   python3 make_standalone.py
   ```
4. Reopen the project in KiCad and re-run DRC / 3D viewer to confirm everything resolved.

### Convert to a separate directory (keep the original)

Use `--output-dir` to copy the project to a new location and convert there. Your original project (still wired to your global libraries) is left untouched, so you can keep working on it normally and only ship the converted copy:

```bash
python3 make_standalone.py --output-dir /path/to/MyProject_to_send
```

In this mode no `*.bak` files are created (the source is the backup). If `--output-dir` already exists, the script refuses to run unless you pass `--force` (which wipes and recreates it).

## Output layout

After conversion, your project directory contains:

```
MyProject/
├── MyProject.kicad_pro
├── MyProject.kicad_sch        (rewritten, original at .bak)
├── MyProject.kicad_pcb        (rewritten, original at .bak)
├── sym-lib-table              (rewritten, original at .bak)
├── fp-lib-table               (rewritten, original at .bak)
├── MyProject_Lib.kicad_sym    (new — all used symbols)
├── MyProject_Lib.pretty/      (new — all used footprints)
└── MyProject_Lib.3dshapes/    (new — all referenced 3D models)
```

## Notes & limitations

- **KiCad 10 only.** The symbol library format version is hard-coded to KiCad 10's. The script will warn (but still run) if `pcbnew.Version()` does not start with `10.`.
- **Idempotent guard**: re-running the script on an already-converted project is detected (>5 references to the local lib) and refused without `--force`.
- **Power symbols** are intentionally not localized — they are part of KiCad's standard library and remain as `power:*` references.
- Missing 3D models are reported as warnings, not errors — the conversion still completes.

## License

MIT
