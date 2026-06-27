# DwarvenModeller

**Headless, stateless 3D clay modeller. Part of the [DwarvenSuite](https://github.com/gitdwarf).**

Text-first. No GUI. No viewport. No mouse required.
The blind human artist and the Claude AI instance use the same interface.
Accessibility is not a feature -- it is the architecture.

## Philosophy

- **Digital clay, not CAD** -- think in shapes and relationships, not vertices and edge loops
- **Stateless** -- every operation is a single command; no persistent process, no session state
- **Text-first** -- all feedback is readable by screen readers, AI instances, and humans equally
- **Headless** -- runs anywhere: terminal, cron, AI tool calls, CI pipelines

## What it does

Model in 3D using plain text operations. Each `--op` transforms the scene and saves.
`--feedback` tells you where everything is in human spatial language.
Export to POV-Ray, PNG, SVG, OBJ, STL, glTF, and more.

## Installation

    pip install dwarvenmodeller

Or from source:

    git clone https://github.com/gitdwarf/DwarvenModeller.git
    cd DwarvenModeller
    pip install -e .

Requires Python 3.10+. POV-Ray is optional (for photorealistic renders).

## Quick start

    # Create a new scene
    dwarvenmodeller --new mysculpt

    # Add shapes
    dwarvenmodeller --file mysculpt.dms --op "add type=sphere id=head radius=10"
    dwarvenmodeller --file mysculpt.dms --op "add type=cube id=body width=6 height=8 depth=5 fill=coral"

    # Check what you have
    dwarvenmodeller --file mysculpt.dms --feedback

    # Move things
    dwarvenmodeller --file mysculpt.dms --op "move target=body down=5"

    # Export
    dwarvenmodeller --file mysculpt.dms --export "format=png out=mysculpt.png"

    # Load a sample scene
    dwarvenmodeller --file aldric --feedback

## Sample scenes

Installed to `~/.dwarvenmodeller/samples/` on first run:

- `aldric.dms` -- 30-object face sculpture, all primitive types demonstrated
- `bench.dms` -- calibration scene, all 6 cardinal directions labelled
- `box3.dms` -- DwarvenArchive icon: open box with documents
- `benchmark.dms` -- export regression testing scene

## Operations

    dwarvenmodeller --help-ops

## Shapes

    sphere  cube  cylinder  cone  capsule  torus  plane
    icosahedron  tetrahedron  octahedron  dodecahedron  text  null

## Exports

    png  png_native  povray  svg  obj  stl  glb  gltf  x3d  braille  spatial  txt

## Python API

```python
import dwarvenmodeller as dm

scene = dm.Scene.load('mysculpt.dms')
dm.op_add(scene, {'type': 'sphere', 'id': 'head', 'radius': '10'})
print(dm.generate_feedback(scene, tty=False))
dm.export_png_native(scene, 'preview.png', size=512)
scene.save('mysculpt.dms')
```

## Part of DwarvenSuite

All tools follow the same philosophy: small, fast, correct, as few dependencies as possible.

## Author

thedwarf -- gitdwarf

## Support / Tip Jar

If you find DwarvenModeller useful, you can support the project:

[![Donate via PayPal](https://img.shields.io/badge/Donate-PayPal-blue?logo=paypal)](https://www.paypal.com/paypalme/gitdwarf)

## Licence

**Individual use: free.** Use it, sell what you make with it, no payment needed.

**Business/entity use: USD $1,000 one-time fee.**
Any company, LLC, sole trader, or other legal entity must purchase a commercial licence.
Pay via PayPal: https://www.paypal.com/paypalme/gitdwarf

Questions: https://github.com/gitdwarf/DwarvenModeller/issues

Run `dwarvenmodeller --license` for full terms.
