# -*- coding: utf-8 -*-
"""
Tests for snapping nearly touching faces in section_analysis.py. Needs the
venv with sectionproperties (takes a minute: every case runs the analysis):

    .venv\\Scripts\\python.exe tests\\test_section_healing.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from section_analysis import run_analysis  # noqa: E402


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def run(regions, gaps_closed=None):
    data = {"units": "mm", "mesh_size": None, "regions": regions}
    if gaps_closed is not None:
        data["gaps_closed"] = gaps_closed
    return run_analysis(data)


def test_exactly_touching_faces():
    r = run([{"outer": rect(0, 0, 50, 20)}, {"outer": rect(50, 0, 100, 20)}])
    assert r["n_parts"] == 1 and r["warping_properties_computed"]
    assert not r["healing"]["snapped_faces"], r["healing"]
    assert abs(r["area"] - 2000.0) < 1e-6
    return r


def test_gap_001_between_faces_merged():
    r = run([{"outer": rect(0, 0, 50, 20)}, {"outer": rect(50.01, 0, 100, 20)}])
    h = r["healing"]
    assert r["n_parts"] == 1, r["n_parts"]
    assert r["warping_properties_computed"] and r["j"] > 0
    assert h["snapped_faces"] and h["parts_before_snap"] == 2 and h["parts_after_snap"] == 1, h
    assert abs(h["max_snap"] - 0.01) < 1e-6, h
    assert abs(r["area"] - 2000.0) < 0.5
    return r


def test_gap_with_different_heights_merged():
    # second face is taller: the corners of the first snap onto its edge
    r = run([{"outer": rect(0, 0, 50, 20)}, {"outer": rect(50.02, -5, 100, 25)}])
    assert r["n_parts"] == 1 and r["warping_properties_computed"], r["healing"]
    return r


def test_overlap_between_faces():
    r = run([{"outer": rect(0, 0, 50.01, 20)}, {"outer": rect(50, 0, 100, 20)}])
    assert r["n_parts"] == 1 and r["warping_properties_computed"]
    assert abs(r["area"] - 2000.0) < 0.5
    return r


def slot_face():
    # 100 x 20 plate with a real 0.5 mm wide, 10 mm deep slot from the top
    return {"outer": [[0, 0], [100, 0], [100, 20], [50.25, 20], [50.25, 10],
                      [49.75, 10], [49.75, 20], [0, 20]]}


def test_slot_in_one_face_stays():
    r = run([slot_face()])
    assert abs(r["area"] - (2000.0 - 5.0)) < 1e-6, r["area"]
    assert not r["healing"]["snapped_faces"]
    return r


def test_slot_stays_next_to_snapped_face():
    # slot face plus a second face with a 0.01 mm gap on the right
    r = run([slot_face(), {"outer": rect(100.01, 0, 120, 20)}])
    assert r["n_parts"] == 1 and r["healing"]["snapped_faces"]
    assert abs(r["area"] - (2400.0 - 5.0)) < 0.5, r["area"]
    return r


def test_separate_faces_stay_separate():
    r = run([{"outer": rect(0, 0, 50, 20)}, {"outer": rect(60, 0, 100, 20)}])
    assert r["n_parts"] == 2 and not r["warping_properties_computed"]
    assert not r["healing"]["snapped_faces"]
    return r


def test_gaps_closed_passed_through():
    g = [{"face": "Face<1>", "length": 0.012, "at": [1.0, 2.0]}]
    r = run([{"outer": rect(0, 0, 50, 20)}], gaps_closed=g)
    assert r["healing"]["gaps_closed"] == g
    return r


if __name__ == "__main__":
    names = sorted(n for n in globals() if n.startswith("test_"))
    for n in names:
        r = globals()[n]()
        h = r["healing"]
        print("OK  %-40s parts=%d A=%.4f J=%s snapped=%s max_snap=%.3g"
              % (n, r["n_parts"], r["area"], ("%.6g" % r["j"]) if "j" in r else "-",
                 h["snapped_faces"], h["max_snap"]))
    print("%d tests passed" % len(names))
