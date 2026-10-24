# -*- coding: utf-8 -*-
"""
Tests for the mesh accuracy setting ("n_target") in section_analysis.py.
Needs the venv with sectionproperties:

    .venv\\Scripts\\python.exe tests\\test_mesh_target.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
from section_analysis import DEFAULT_N_TARGET, run_analysis  # noqa: E402

RECT = [[0, 0], [100, 0], [100, 20], [0, 20]]


def run(**extra):
    data = {"units": "mm", "mesh_size": None, "regions": [{"outer": RECT}]}
    data.update(extra)
    return run_analysis(data)


def test_default_is_3000():
    r = run()
    assert DEFAULT_N_TARGET == 3000
    assert r["n_target"] == 3000, r["n_target"]
    assert abs(r["mesh_size"] - 2000.0 / 3000) < 1e-12
    assert r["n_elements"] > 0
    return r


def test_more_elements_for_finer_target():
    counts = []
    for n in (1000, 3000, 10000):
        r = run(n_target=n)
        assert r["n_target"] == n
        assert abs(r["mesh_size"] - 2000.0 / n) < 1e-12
        # mesh_size is a maximum element area, so at least ~n elements
        assert r["n_elements"] >= n, (n, r["n_elements"])
        assert abs(r["area"] - 2000.0) < 1e-6
        counts.append(r["n_elements"])
    assert counts[0] < counts[1] < counts[2], counts
    return r


def test_explicit_mesh_size_wins():
    r = run(mesh_size=20.0, n_target=30000)
    assert r["n_target"] is None, r["n_target"]
    assert r["mesh_size"] == 20.0
    assert r["n_elements"] < 1000, r["n_elements"]
    return r


def test_command_line_writes_counts():
    # the route used by Alibre: python section_analysis.py geometry.json results.json
    d = tempfile.mkdtemp()
    g, res = os.path.join(d, "g.json"), os.path.join(d, "r.json")
    with open(g, "w") as f:
        json.dump({"units": "mm", "mesh_size": None, "n_target": 1000,
                   "regions": [{"outer": RECT}]}, f)
    subprocess.check_call([sys.executable, os.path.join(ROOT, "section_analysis.py"), g, res])
    with open(res) as f:
        r = json.load(f)
    assert r["success"] and r["n_target"] == 1000 and r["n_elements"] >= 1000, r
    return r


if __name__ == "__main__":
    names = sorted(n for n in globals() if n.startswith("test_"))
    for n in names:
        r = globals()[n]()
        print("OK  %-40s n_target=%s n_elements=%d mesh_size=%.4g"
              % (n, r["n_target"], r["n_elements"], r["mesh_size"]))
    print("%d tests passed" % len(names))
