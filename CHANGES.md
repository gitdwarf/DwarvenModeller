# DwarvenModeller Changelog

## 0.3.5 (2026-06)
- --export and --feedback now execute in the order they appear on the
  command line, not a fixed internal order. A failed --export after
  --feedback no longer prints before the feedback it was supposed to follow.

## 0.3.4 (2026-06)
- --export failure (e.g. missing format=) no longer aborts the whole run
- --feedback now always runs even if --export in the same invocation fails
- Exit code correctly reflects export failure (1) while still printing feedback

## 0.3.3 (2026-06)
- --export with empty or missing format= no longer silently defaults to svg
- Now shows an error with the full list of available export formats

## 0.3.2 (2026-06)
- Fixed crash: ansi_render circular import broke --feedback after package split
- Fixed crash: empty format= in --export caused FileNotFoundError on os.getcwd()
- --export now defaults cleanly to svg when format= is given with no value
- Graceful fallback if current working directory no longer exists

## 0.3.1 (2026-06)
- --support now mentions --license
- Philosophy footer now lists --license and --support clearly

## 0.3.0 (2026-06)
- Modular package split from monolithic script
- Tessellation-based native PNG renderer (cubes, spheres, all shapes)
- Per-face POV-Ray shading via native rotation convention
- Human-friendly op vocabulary: yaw/pitch/zoom/turn/tilt/place
- Colour name aliases (red, navy, coral...)
- --no-save is now a proper dry-run (auto-triggers feedback)
- --repl removed (anti-philosophy)
- New scene default yaw=180 (faces you)
- Sample scenes auto-installed to ~/.dwarvenmodeller/samples/
- File search path: current dir then ~/.dwarvenmodeller/samples/
- .dms extension auto-added if missing

## 0.2.0
- POV-Ray export with per-face shading
- SVG export via vtracer
- look_at centred in all renderers
- Compass rule established

## 0.1.0
- Initial release
