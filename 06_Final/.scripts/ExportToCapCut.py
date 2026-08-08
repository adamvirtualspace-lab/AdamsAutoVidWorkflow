#!/usr/bin/env python3
"""
ExportToCapCut.py
Export the final timeline into a CapCut (Windows) draft project.

    06_Final\\FinalTimelineNoCap.otio  ->  a project under CapCut's drafts root

Captions are deliberately NOT exported.  CapCut has its own caption workflow,
and pushing 2955 one-word titles into it makes an unusable timeline -- so this
reads the NoCap timeline (edit + memes).  Pass --with-captions if you ever want
them anyway.

The heavy lifting is done by fcpxml_to_capcut2.py, which sits next to this file.
This script's job is to hand it an .fcpxml it can actually digest:

  * lane numbering.  fcpxml_to_capcut2 treats a MISSING lane attribute as lane 1,
    the same lane our first overlay would otherwise use -- so the edit and the
    memes would land on one CapCut track and get spilled apart as "overlapping".
    We re-emit with --lane-base 2 so the spine keeps the main track to itself and
    the memes get their own overlay track.

  * media paths.  It reads src straight off <asset>; Resolve wants a <media-rep>
    child.  OTIOtoFCPXML.py writes both, so one file satisfies both readers.

Flow:
    FinalTimelineNoCap.otio
        -> FinalTimelineNoCap.capcut.fcpxml   (lane-base 2, no titles)
        -> <CapCut drafts root>\\<project name>\\
        -> --verify pass over the result

Usage:
    python ExportToCapCut.py
    python ExportToCapCut.py --name "SnowRunner Part 02"
    python ExportToCapCut.py --dry-run
    python ExportToCapCut.py --force
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR  = Path(__file__).resolve().parent
FINAL_DIR    = SCRIPTS_DIR.parent
PROJECT_ROOT = FINAL_DIR.parent

OTIO_TO_FCPXML = SCRIPTS_DIR / "OTIOtoFCPXML.py"
FCPXML_TO_CAPCUT = SCRIPTS_DIR / "fcpxml_to_capcut2.py"

# Same folder the reference script defaults to.
DEFAULT_DRAFTS_ROOT = (
    Path.home() / "AppData" / "Local" / "CapCut" / "User Data"
    / "Projects" / "com.lveditor.draft"
)

# fcpxml_to_capcut2 reads a missing lane as lane 1, which is where our first
# overlay would sit.  Start overlays at 2 so the spine has the main track alone.
CAPCUT_LANE_BASE = 2


def run(cmd: list, label: str) -> bool:
    """Run a child script, echoing its output."""
    print(f"  > {' '.join(str(c) for c in cmd[1:])}")
    print()
    result = subprocess.run([str(c) for c in cmd])
    print()
    if result.returncode != 0:
        print(f"[ERROR] {label} failed (exit {result.returncode})", file=sys.stderr)
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Export the final timeline to a CapCut draft project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ExportToCapCut.py
  python ExportToCapCut.py --name "SnowRunner Part 02"
  python ExportToCapCut.py --dry-run
  python ExportToCapCut.py --force
        """
    )
    ap.add_argument("-n", "--name",
                    help="CapCut project name (default: the project folder name)")
    ap.add_argument("--drafts-root",
                    help="CapCut drafts root (default: CapCut's standard location)")
    ap.add_argument("--with-captions", dest="with_captions", action="store_true",
                    help="Use the WithCap timeline (not recommended - CapCut has "
                         "its own caption tools)")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite an existing CapCut project of the same name")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="Report what would be written without creating a project")
    ap.add_argument("--keep-fcpxml", dest="keep_fcpxml", action="store_true",
                    help="Keep the intermediate .capcut.fcpxml (kept by default "
                         "on failure regardless)")
    ap.add_argument("--no-probe", dest="no_probe", action="store_true",
                    help="Skip ffprobe (faster, but overlays get sequence size)")
    args = ap.parse_args()

    # ── Sanity ────────────────────────────────────────────────────────────
    for helper in (OTIO_TO_FCPXML, FCPXML_TO_CAPCUT):
        if not helper.exists():
            print(f"[ERROR] Missing helper script: {helper}", file=sys.stderr)
            sys.exit(1)

    src_name = ("FinalTimelineWithCap.otio" if args.with_captions
                else "FinalTimelineNoCap.otio")
    src = FINAL_DIR / src_name
    if not src.exists():
        print(f"[ERROR] {src.name} not found - run A_CombineFinalTimelines.bat first.",
              file=sys.stderr)
        sys.exit(1)

    drafts_root = Path(args.drafts_root) if args.drafts_root else DEFAULT_DRAFTS_ROOT
    if not drafts_root.exists():
        print(f"  [WARN] CapCut drafts root not found:\n         {drafts_root}")
        print( "         Pass --drafts-root if CapCut is installed elsewhere.")

    project_name = args.name or PROJECT_ROOT.name
    fcpxml = FINAL_DIR / (src.stem + ".capcut.fcpxml")

    print(f"  source       : {src.name}")
    print(f"  project name : {project_name}")
    print(f"  drafts root  : {drafts_root}")
    if args.with_captions:
        print( "  captions     : INCLUDED (--with-captions)")
    else:
        print( "  captions     : excluded (CapCut handles captions itself)")
    print()

    # ── 1. CapCut-flavoured fcpxml ────────────────────────────────────────
    print("[1/2] Writing a CapCut-compatible fcpxml ...")
    step1 = [sys.executable, OTIO_TO_FCPXML, src, "-o", fcpxml,
             "--lane-base", str(CAPCUT_LANE_BASE)]
    if not args.with_captions:
        step1.append("--no-titles")
    if not run(step1, "fcpxml conversion"):
        sys.exit(1)

    # ── 2. CapCut draft ───────────────────────────────────────────────────
    print("[2/2] Building the CapCut project ...")
    step2 = [sys.executable, FCPXML_TO_CAPCUT, fcpxml, "--name", project_name]
    if args.drafts_root:
        step2 += ["--drafts-root", str(drafts_root)]
    if args.force:
        step2.append("--force")
    if args.dry_run:
        step2.append("--dry-run")
    if args.no_probe:
        step2.append("--no-probe")

    ok = run(step2, "CapCut export")

    # ── Verify ────────────────────────────────────────────────────────────
    project_dir = drafts_root / project_name
    if ok and not args.dry_run and project_dir.exists():
        print("Verifying the written project ...")
        run([sys.executable, FCPXML_TO_CAPCUT, "--verify", project_dir],
            "verification")

    # The intermediate is only interesting when something went wrong.
    if ok and not args.keep_fcpxml and fcpxml.exists():
        fcpxml.unlink()
    elif fcpxml.exists():
        print(f"  intermediate kept: {fcpxml.name}")

    if not ok:
        sys.exit(1)

    if args.dry_run:
        print("(Dry run - no CapCut project written.)")
    else:
        print(f"Done. Open CapCut - the project appears as {project_name!r}.")


if __name__ == "__main__":
    main()
