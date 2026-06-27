# DwarvenModeller Changelog

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
