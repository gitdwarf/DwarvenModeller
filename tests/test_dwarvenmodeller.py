"""DwarvenModeller -- basic test suite."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import dwarvenmodeller as dm

SAMPLES = os.path.join(os.path.dirname(__file__), '..', 'assets')


def load_sample(name):
    path = os.path.join(SAMPLES, name)
    if not path.endswith('.dms'): path += '.dms'
    return dm.Scene.load(path)


def test_import():
    assert hasattr(dm, 'Scene')
    assert hasattr(dm, 'op_add')
    assert hasattr(dm, 'generate_feedback')
    assert hasattr(dm, 'export_png_native')
    assert hasattr(dm, 'export_povray')
    assert hasattr(dm, 'ansi_render')
    assert dm.__version__


def test_new_scene():
    scene = dm.Scene.new()
    assert len(scene.all_objects()) == 0
    vp = scene.active_viewpoint()
    assert vp.az == 180.0  # faces user by default


def test_add_primitives():
    scene = dm.Scene.new()
    for ptype in ['sphere', 'cube', 'cylinder', 'cone', 'capsule']:
        r = dm.op_add(scene, {'type': ptype, 'id': ptype, 'radius': '5'})
        assert ptype in r
    assert len(scene.all_objects()) == 5


def test_colour_names():
    assert dm._norm_colour('red') == '#ff0000'
    assert dm._norm_colour('navy') == '#000080'
    assert dm._norm_colour('#c1a377') == '#c1a377'


def test_feedback_box3():
    scene = load_sample('box3')
    fb = dm.generate_feedback(scene, tty=False)
    assert 'Scene:' in fb
    assert 'yaw=' in fb
    assert 'Attached to' in fb


def test_feedback_aldric():
    scene = load_sample('aldric-test')
    fb = dm.generate_feedback(scene, tty=False)
    assert 'Scene:' in fb
    assert len(scene.all_objects()) == 30


def test_png_native():
    scene = load_sample('box3')
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        path = f.name
    try:
        result = dm.export_png_native(scene, path, size=256)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000
        assert '256x256' in result
    finally:
        os.unlink(path)


def test_pov_export():
    scene = load_sample('box3')
    with tempfile.NamedTemporaryFile(suffix='.pov', delete=False, mode='w') as f:
        path = f.name
    try:
        dm.export_povray(scene, path)
        with open(path) as f:
            pov = f.read()
        assert 'camera' in pov
        assert 'mesh2' in pov
        assert 'colors.inc' not in pov  # was causing brightness bug
    finally:
        os.unlink(path)


def test_ansi_render():
    scene = load_sample('box3')
    result = dm.ansi_render(scene)
    assert '▀' in result
    assert len(result.splitlines()) == 33


def test_op_move():
    scene = load_sample('box3')
    vp = scene.active_viewpoint()
    old_y = vp.look_at.y if vp.look_at else 0
    dm.op_move(scene, {'up': '3'})
    # look_at should have shifted
    new_y = vp.look_at.y if vp.look_at else 0
    assert abs(new_y - old_y) > 0


def test_op_colour():
    scene = load_sample('box3')
    dm.op_color(scene, {'target': 'panel_front', 'fill': 'red'})
    for obj in scene.all_objects():
        if obj.id == 'panel_front':
            assert obj.material.fill == '#ff0000'


def test_viewpoint_aliases():
    scene = load_sample('box3')
    dm.op_viewpoint(scene, {'yaw': '90', 'pitch': '15', 'zoom': '1.0'})
    vp = scene.active_viewpoint()
    assert vp.az == 90.0
    assert vp.el == 15.0


def test_obj_export():
    scene = load_sample('box3')
    with tempfile.NamedTemporaryFile(suffix='.obj', delete=False) as f:
        path = f.name
    try:
        dm.export_obj(scene, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 100
    finally:
        os.unlink(path)


def test_dms_save_load_roundtrip():
    scene = dm.Scene.new()
    dm.op_add(scene, {'type': 'sphere', 'id': 'head', 'radius': '10', 'fill': 'coral'})
    dm.op_add(scene, {'type': 'cube', 'id': 'body', 'width': '6', 'height': '8', 'depth': '5'})
    with tempfile.NamedTemporaryFile(suffix='.dms', delete=False) as f:
        path = f.name
    try:
        scene.save(path)
        scene2 = dm.Scene.load(path)
        assert len(scene2.all_objects()) == 2
        for obj in scene2.all_objects():
            if obj.id == 'head':
                assert obj.material.fill == '#ff7f50'  # coral
    finally:
        os.unlink(path)


if __name__ == '__main__':
    tests = [v for k,v in sorted(globals().items()) if k.startswith('test_')]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  OK  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ERR {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
