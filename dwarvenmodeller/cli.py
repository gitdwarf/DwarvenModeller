"""DwarvenModeller -- CLI entry point, merge, help-ops."""
from __future__ import annotations
import sys, os, argparse
from .constants import *
from .math_utils import *
from .scene import *
from .primitives import *
from .ops import *
from .feedback import *
from .exporters import *

_PHILOSOPHY = """DwarvenModeller
Copyright (c) 2026 thedwarf / gitdwarf
https://github.com/gitdwarf/DwarvenModeller

PHILOSOPHY: Digital clay, not CAD.

  DwarvenModeller is a virtual clay modeller -- organic, sculptural, expressive.
  Not a CAD app, not a mesh editor. Think in shapes and relationships,
  not vertices and edge loops. Build anything -- faces, animals, chess pieces,
  icons, machines, jewellery. If you can feel it, you can build it.

  The blind human artist and the Claude instance use the same interface.
  Accessibility is not a feature -- it is the architecture.

  You are not a camera. You are a sculptor.
  You hold the clay. The clay turns. You never move.

  Operate by FEEL, not coordinates.
  Check --feedback after every operation.
  Never assume a position is correct without measuring it.

  "Push the nose up 0.5 units."
  "Turn the head left 15 degrees."
  "Bring the ear forward 0.2 units."

  Run --help for usage. Run --help-ops for the full operation reference.
  Run --philosophy to see this again. Run --license for licence terms.
  Run --support for contact, donations, and commercial licencing.
"""

_LICENSE_TEXT = """DwarvenModeller
Copyright (c) 2026 thedwarf / gitdwarf

Licensed under CC BY-NC-ND 4.0 with the following commercial terms:
https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode

COMMERCIAL USE - USD $1,000 ONE-TIME FEE
  Any company, business, corporation, LLC, partnership, sole trader, or other
  legal entity must purchase a commercial licence to use DwarvenModeller for
  any purpose, including internal use, tooling, automation, or embedding it
  in a product or workflow.

  This fee is one-time, per legal entity, and grants perpetual commercial use.

  Payment: USD $1,000 via PayPal
  https://www.paypal.com/paypalme/gitdwarf

  Questions or support:
  https://github.com/gitdwarf/DwarvenModeller/issues

INDIVIDUAL USE - FREE
  Any natural person using DwarvenModeller as themselves -- not on behalf of
  a company or other legal entity -- may use it free of charge for any
  purpose, including creating and selling works produced with it (models,
  images, artwork, prints, etc).

  No payment required. Though donations are gratefully accepted:
  https://www.paypal.com/paypalme/gitdwarf
"""
# ═════════════════════════════════════════════════════════════════════════════

def merge_scenes(scene_a, scene_b, namespace_b):
    """
    Merge scene_b into scene_a.
    All objects from scene_b are prefixed with 'namespace_b::' to avoid ID conflicts.
    History entries are also merged and annotated.
    """
    existing = set(scene_a.all_ids())

    def prefix(obj, ns):
        new_id = f"{ns}::{obj.id}"
        if new_id in existing:
            i = 2
            while f"{new_id}_{i}" in existing: i += 1
            new_id = f"{new_id}_{i}"
        obj.id = new_id; existing.add(new_id)
        for child in obj.children: prefix(child, ns)

    imported = []
    for obj in scene_b.objects:
        obj_copy = copy.deepcopy(obj)
        prefix(obj_copy, namespace_b)
        scene_a.objects.append(obj_copy)
        imported.append(obj_copy.id)

    for entry in scene_b.history:
        scene_a.history.append(HistoryEntry(
            f"[merged from {namespace_b}] {entry.op}", entry.timestamp))

    return (f"Merged {len(imported)} object{'s' if len(imported)!=1 else ''} "
            f"from '{namespace_b}': {', '.join(imported)}.")


# ═════════════════════════════════════════════════════════════════════════════
# § HELP
# ═════════════════════════════════════════════════════════════════════════════

def print_help_ops():
  """Print the full operation reference -- screen-reader and AI friendly."""
  def h1(s): print(); print(s); print('=' * len(s))
  def h2(s): print(); print(s); print('-' * len(s))

  h1('DwarvenModeller -- Operation Reference')

  h2('ORIENTATION -- READ THIS FIRST')
  print('The scene sits inside an invisible sphere. You rotate the sphere')
  print('in your hands. The --feedback "Scene:" line shows your viewpoint.')

  h2('THE COMPASS RULE')
  print('  Think of +Z as North. YOU are fixed. The sphere rotates in your hands.')
  print()
  print('  yaw=0   -- Scene faces away from you (North = +Z points away).')
  print('             West (-X) is YOUR LEFT.  East (+X) is YOUR RIGHT.')
  print()
  print('  yaw=180 -- Scene faces you (North = +Z points toward you).')
  print('             DEFAULT starting position for all new scenes.')
  print('             West (-X) is YOUR RIGHT. East (+X) is YOUR LEFT.')
  print('             Left/right are MIRRORED -- like looking at someone face-to-face.')
  print()
  print('  Any other yaw: compass rotates with the sphere.')
  print('  ALWAYS check --feedback after every op. Never guess.')

  h2('MODEL-RELATIVE ANATOMY')
  print('  Model right = world -X  (subject faces +Z, right hand = -X)')
  print('  Model left  = world +X')
  print('  ear_right goes at world -X. ear_left at world +X.')
  print('  Matches medical convention: patient left, stage left.')

  h2('TURNTABLE CONTROLS')
  print('  turn left=N / right=N              -- spin the sphere left or right')
  print('  tilt toward=N / away=N             -- tip the sphere toward or away')
  print('  zoom in=N / out=N                  -- bring closer or push further')
  print('  move up/down/left/right/away/towards=N  -- pan the view centre')
  print('  roll clockwise=N / anticlockwise=N -- rotate view around the axis')
  print()
  print('  All directions are relative to YOU, the modeller.')
  print('  Add target=<id> to any of these to move an object instead of the scene.')

  h2('SHAPES (use with add type=SHAPE)')
  print('  sphere       radius=N [subdivisions=N]')
  print('  cube         width=N height=N depth=N')
  print('  cylinder     radius=N height=N [segments=N]')
  print('  cone         base_radius=N [top_radius=N] height=N [segments=N]')
  print('  capsule      radius=N height=N [segments=N]')
  print('  torus        outer_radius=N inner_radius=N [segments=N]')
  print('  plane        width=N depth=N')
  print('  text         content=<string> size=N [font=timrom.ttf|cyrvetic.ttf]')
  print('  icosahedron  radius=N [subdivisions=N]')
  print('  tetrahedron  radius=N')
  print('  octahedron   radius=N')
  print('  dodecahedron radius=N')
  print('  null         (invisible anchor point for grouping/parenting)')
  print()
  print('  All shapes accept: fill=#hex at=x,y,z rotate=x,y,z scale=x,y,z')
  print('  Colour names also work: fill=red, fill=navy, fill=coral ...')

  h2('ALL OPERATIONS')
  print('  Pattern:  --op "verb key=value key=value ..."')
  seen = set()
  for name in sorted(OPERATIONS.keys()):
    fn = OPERATIONS[name]
    if fn in seen: continue
    seen.add(fn)
    aliases = sorted(k for k,v in OPERATIONS.items() if v==fn and k!=name)
    print()
    print(f'  {name.upper()}')
    if aliases: print(f'    aliases: {", ".join(aliases)}')
    doc = fn.__doc__ or '  (no documentation)'
    doc_lines = doc.strip().splitlines()
    # Find minimum indent of non-empty continuation lines
    body = [l for l in doc_lines[1:] if l.strip()]
    min_ind = min((len(l)-len(l.lstrip()) for l in body), default=0) if body else 0
    for i, line in enumerate(doc_lines):
      if i == 0:
        stripped = line.strip()  # first line: just strip surrounding whitespace
      else:
        stripped = line[min_ind:] if len(line) > min_ind else line.lstrip()
      if stripped:
        print(f'  {stripped}')
      else:
        print()


# ═════════════════════════════════════════════════════════════════════════════
# § CLI
# ═════════════════════════════════════════════════════════════════════════════

def _install_samples():
    """Copy bundled .dms samples to ~/.dwarvenmodeller/samples/ if not already there.
    Creates the directory if needed. Existing files are never overwritten.
    Called on every run -- no-op if all samples already present.
    """
    import shutil, pathlib
    samples_dir = pathlib.Path.home() / '.dwarvenmodeller' / 'samples'
    samples_dir.mkdir(parents=True, exist_ok=True)
    # Look for samples next to this script
    script_dir = pathlib.Path(__file__).parent
    candidates = list(script_dir.glob('*.dms')) + \
                 list((script_dir / 'samples').glob('*.dms'))
    for src in candidates:
        dst = samples_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)


def main():
    parser = argparse.ArgumentParser(
        description='DwarvenModeller - headless stateless 3D modeller',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--file',     '-f',
                        metavar='SCENE.dms',
                        help='Scene file to work with (.dms format)')
    parser.add_argument('--new',
                        metavar='NEWFILE',
                        help='Create a new empty scene file. The .dms extension is added automatically if not given.')
    parser.add_argument('--op',       '-o',
                        metavar='OPERATION',
                        help='Operation to apply, for example: "add type=sphere id=head radius=5" or "move target=head up=2"')
    parser.add_argument('--feedback',       nargs='?', const='', metavar='target=ID',
                        help='Print a spatial description of the scene. Optionally: target=<id> for detail on one object')
    parser.add_argument('--list',           action='store_true',
                        help='List every object in the scene with its position and parent')
    parser.add_argument('--export',   '-e',
                        metavar='"format=FORMAT out=PATH"',
                        help='Export scene. format=<fmt> out=<path> [size=N]  '
                             f'(formats: {", ".join(sorted(set(EXPORT_FORMATS.keys())))})')
    parser.add_argument('--merge',    '-m',
                        metavar='FILE.dms',
                        help='Merge another .dms file into this scene (objects namespaced by filename)')
    parser.add_argument('--batch',    '-b',
                        metavar='OPS.txt',
                        help='Run a file of operations, one per line. Use a hyphen (-) to read from standard input')
    parser.add_argument('--strict',   action='store_true',
                        help='Used with --batch: stop on the first error and do not save')
    parser.add_argument('--no-save',        action='store_true',
                        help='Dry run: apply the operation and show feedback, but do not save the result')
    parser.add_argument('--up-axis',        default='Y', metavar='Y|Z',
                        help='Feedback display convention: Y (default, Y is up) or Z (Z is up, '
                             'for scenes modelled in Z-up space). Does not change geometry.')
    parser.add_argument('--undo',           action='store_true',
                        help='Undo the last operation: removes it from history and reverts the file')
    parser.add_argument('--help-ops',       action='store_true',
                        help='Print the full operation reference')
    parser.add_argument('--license', '-l',  action='store_true',
                        help='Print licence terms')
    parser.add_argument('--support', '--issues', '-s', '-i',
                        action='store_true',
                        help='Print support and contact information')
    parser.add_argument('--philosophy', '-p', action='store_true',
                        help='Print the DwarvenModeller philosophy')
    parser.add_argument('--readme', '-r',   action='store_true',
                        help='Print the README')

    args = parser.parse_args()
    _install_samples()

    if args.help_ops:
        print_help_ops(); return 0

    if args.philosophy:
        print(_PHILOSOPHY); return 0

    if args.readme:
        import pathlib
        candidates = [
            pathlib.Path(__file__).parent / 'README.md',       # bundled in package
            pathlib.Path(__file__).parent.parent / 'README.md', # dev install
        ]
        for readme in candidates:
            if readme.exists():
                print(readme.read_text())
                return 0
        print("README not found. See https://github.com/gitdwarf/DwarvenModeller")
        return 0

    if args.license:
        import pathlib
        candidates = [
            pathlib.Path(__file__).parent / 'LICENSE',          # bundled in package
            pathlib.Path(__file__).parent.parent / 'LICENSE',   # dev install
        ]
        for lf in candidates:
            if lf.exists():
                print(lf.read_text())
                return 0
        print(_LICENSE_TEXT)  # fallback: embedded copy
        return 0

    if args.support:
        print('Support & contact:')
        print()
        print('  Bug reports and questions:')
        print('  https://github.com/gitdwarf/DwarvenModeller/issues')
        print()
        print('  Commercial licencing: USD $1,000 one-time fee per legal entity.')
        print('  Run --license for full terms.')
        print('  Payment: https://www.paypal.com/paypalme/gitdwarf')
        print()
        print('  Donations gratefully accepted at the same link.')
        return 0

    # No arguments -- show philosophy
    if not any([args.file, args.new]):
        print(_PHILOSOPHY); return 0

    if args.new:
        newfile = args.new if args.new.endswith('.dms') else args.new + '.dms'
        scene = Scene.new(); scene.save(newfile)
        print(f"Created new scene: {newfile}"); return 0

    if not args.file:
        parser.print_help(); return 1

    # Resolve file: auto-add .dms, search current dir then ~/.dwarvenmodeller/samples/
    def _resolve_scene_file(name):
        import pathlib
        p = pathlib.Path(name)
        candidates = [p, p.with_suffix('.dms')] if p.suffix != '.dms' else [p]
        samples_dir = pathlib.Path.home() / '.dwarvenmodeller' / 'samples'
        for c in candidates:
            if c.exists(): return str(c)
        for c in candidates:
            s = samples_dir / c.name
            if s.exists(): return str(s)
        return str(candidates[0])   # return best guess for error message

    resolved_file = _resolve_scene_file(args.file)
    if not os.path.exists(resolved_file):
        # Build helpful error with suggestions
        import pathlib
        samples = list((pathlib.Path.home() / '.dwarvenmodeller' / 'samples').glob('*.dms'))
        print(f"Error: '{args.file}' not found.", file=sys.stderr)
        print(f"Create it with: dwarvenmodeller --new {args.file}", file=sys.stderr)
        if samples:
            names = ', '.join(s.stem for s in sorted(samples)[:8])
            print(f"Available samples: {names}", file=sys.stderr)
        return 1
    args.file = resolved_file

    try:
        scene = Scene.load(args.file)
    except ValueError as e:
        print(f"Error loading '{args.file}': {e}", file=sys.stderr); return 1

    # -- undo: replay history minus last entry ---------------------------------
    if args.undo:
        if not scene.history:
            print("Nothing to undo -- history is empty.")
            return 0
        removed = scene.history[-1]
        # Replay from scratch: fresh scene, all history except last.
        # Inject force=true into every op -- replaying known-good history,
        # intersection guards should not block it.
        ops_to_replay = [h.op for h in scene.history[:-1]]
        fresh = Scene.new()
        for op_str in ops_to_replay:
            try:
                verb, kwargs = parse_op(op_str)
                kwargs.setdefault('force', 'true')  # bypass intersection guards on replay
                handler = OPERATIONS.get(verb)
                if handler:
                    handler(fresh, kwargs)
                    fresh.history.append(HistoryEntry(op_str))
            except Exception:
                pass  # skip ops that genuinely can't replay
        if not args.no_save:
            fresh.save(args.file)
            print(f"Undone: '{removed.op}'. Scene reverted and saved.")
        else:
            print(f"Undone: '{removed.op}'. (not saved -- --no-save)")
        return 0

    result = None

    def _expand_targets(kwargs):
        """If target=@tagname, return list of matching object IDs. Else return [target]."""
        t = kwargs.get('target', '')
        if not t.startswith('@'):
            return [t] if t else []
        pattern = t[1:]  # strip @
        matches = []
        for obj in scene.all_objects():
            # Match on tag value, type, or id prefix
            if (pattern in obj.tags or
                any(tag.startswith(pattern + '=') or tag == pattern for tag in obj.tags) or
                obj.type == pattern or
                obj.id.startswith(pattern)):
                matches.append(obj.id)
        if not matches:
            raise ValueError(f"No objects matched '@{pattern}'. "
                             f"Try a tag name, type name, or id prefix.")
        return matches

    def run_op(op_str):
        verb, kwargs = parse_op(op_str)
        handler = OPERATIONS.get(verb)
        if not handler:
            close = difflib.get_close_matches(verb, OPERATIONS.keys(), n=1, cutoff=0.5)
            msg = f"Unknown operation '{verb}'."
            if close: msg += f" Did you mean '{close[0]}'?"
            msg += f" Valid: {', '.join(sorted(set(OPERATIONS.keys())))}."
            raise ValueError(msg)

        # Multi-target expansion: target=@tagname applies op to all matching objects
        if kwargs.get('target', '').startswith('@'):
            targets = _expand_targets(kwargs)
            results = []
            for tid in targets:
                kw = dict(kwargs); kw['target'] = tid
                results.append(handler(scene, kw))
            scene.history.append(HistoryEntry(op_str))
            return f"Applied to {len(targets)} objects ({', '.join(targets)}): {results[0] if len(results)==1 else str(len(results))+' results'}"

        r = handler(scene, kwargs)
        scene.history.append(HistoryEntry(op_str))
        return r

    if args.op:
        try:
            result = run_op(args.op)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr); return 1

    if args.batch:
        if args.batch == '-':
            lines_in = sys.stdin.read().splitlines()
        elif not os.path.exists(args.batch):
            print(f"Error: batch file '{args.batch}' not found.", file=sys.stderr); return 1
        else:
            with open(args.batch) as f:
                lines_in = f.read().splitlines()
        ops = [l.strip() for l in lines_in if l.strip() and not l.strip().startswith('#')]
        errors = 0
        aborted = False
        for i, op_str in enumerate(ops, 1):
            try:
                r = run_op(op_str); print(f"[{i}/{len(ops)}] {r}")
            except ValueError as e:
                print(f"[{i}/{len(ops)}] Error: {e}", file=sys.stderr)
                errors += 1
                if args.strict:
                    print(f"Batch aborted at op {i} (--strict mode). Scene NOT saved.",
                          file=sys.stderr)
                    aborted = True
                    break
        if errors and not aborted:
            print(f"\n{errors} error{'s' if errors!=1 else ''} in batch.", file=sys.stderr)
        if aborted:
            return 1
        result = f"Batch complete: {len(ops)-errors}/{len(ops)} operations succeeded."


    if args.merge:
        if not os.path.exists(args.merge):
            print(f"Error: merge file '{args.merge}' not found.", file=sys.stderr); return 1
        try:
            other = Scene.load(args.merge)
        except ValueError as e:
            print(f"Error loading merge file: {e}", file=sys.stderr); return 1
        ns     = os.path.splitext(os.path.basename(args.merge))[0]
        result = merge_scenes(scene, other, ns)
        scene.history.append(HistoryEntry(f"merge {args.merge}"))

    if args.export:
        _, ekwargs = parse_op('export ' + args.export)
        fmt  = ekwargs.get('format', 'svg').lower()
        # Map format name to correct file extension
        _fmt_ext = {
            'povray': 'pov', 'pov': 'pov',
            'png': 'png', 'png_native': 'png', 'svg': 'svg', 'svg_trace': 'svg',

            'obj': 'obj', 'stl': 'stl', 'gltf': 'gltf', 'glb': 'glb',
            'x3d': 'x3d', 'css': 'html', 'css3d': 'html', 'html': 'html',
            'txt': 'txt', 'text': 'txt', 'braille': 'txt', 'spatial': 'txt',
        }
        ext = _fmt_ext.get(fmt, fmt)
        # Default output: basename of source file in CWD, not DMS dir
        default_out = os.path.join(
            os.getcwd(),
            os.path.splitext(os.path.basename(args.file))[0] + f'.{ext}'
        )
        out  = ekwargs.get('out', default_out)
        size = int(ekwargs.get('size', 512))
        subs = int(ekwargs['subdivisions']) if 'subdivisions' in ekwargs else None
        try:
            result = run_export(scene, fmt, out, size, subdivisions=subs)
        except (ValueError, Exception) as e:
            print(f"Export error: {e}", file=sys.stderr); return 1

    if args.feedback is not None:
        tty = sys.stdout.isatty()
        fb_target = None
        fb_az = fb_el = None
        fb_mode = 'full'
        fb_view = 'top'
        if args.feedback:
            _, fkw = parse_op('feedback ' + args.feedback)
            fb_target = fkw.get('target') or fkw.get('id')
            if 'az'   in fkw: fb_az   = float(fkw['az'])
            if 'el'   in fkw: fb_el   = float(fkw['el'])
            if 'mode' in fkw: fb_mode = fkw['mode']
            if 'view' in fkw: fb_view = fkw['view']
        # --up-axis Z: rotate el by +90 so Z appears as vertical in ANSI render
        up_axis = args.up_axis.upper() if args.up_axis else 'Y'
        if up_axis == 'Z':
            fb_el = (fb_el if fb_el is not None else scene.active_viewpoint().el) + 90.0
        # Temporarily override viewpoint for feedback only (no file write)
        if fb_az is not None or fb_el is not None:
            vp = scene.active_viewpoint()
            orig_az, orig_el = vp.az, vp.el
            if fb_az is not None: vp.az = fb_az
            if fb_el is not None: vp.el = fb_el
            print(generate_feedback(scene, tty=tty, target_id=fb_target,
                                    mode=fb_mode, view=fb_view))
            vp.az, vp.el = orig_az, orig_el
        else:
            print(generate_feedback(scene, tty=tty, target_id=fb_target,
                                    mode=fb_mode, view=fb_view))

    if args.list:
        all_objs = scene.all_objects()
        if not all_objs:
            print("Scene is empty.")
        else:
            print(f"{'ID':<30} {'TYPE':<14} {'WORLD POSITION':<28} PARENT")
            print('-' * 80)
            for obj in all_objs:
                wp     = scene.world_pos(obj)
                parent = scene.find_parent(obj.id)
                ps     = f"→ {parent.id}" if parent else "(root)"
                pos    = f"({wp.x:.1f}, {wp.y:.1f}, {wp.z:.1f})"
                print(f"{obj.id:<30} {obj.type:<14} {pos:<28} {ps}")

    if result:
        print(result)

    should_save = (args.op or args.merge or args.batch) and not args.no_save
    if should_save:
        scene.save(args.file)

    # --no-save = dry-run: automatically show feedback so you can see the result
    # before deciding to re-run without --no-save to commit.
    if args.no_save and (args.op or args.merge or args.batch) and not args.feedback:
        print()
        print(generate_feedback(scene, tty=sys.stdout.isatty()))

    return 0


if __name__ == '__main__':
    sys.exit(main())
