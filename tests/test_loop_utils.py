# -*- coding: utf-8 -*-
"""
Tests for loop_utils.py (chain_loop, shoelace_area). Plain asserts, no pytest:

    .venv\\Scripts\\python.exe tests\\test_loop_utils.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from loop_utils import GAP_TOL_REL, LoopGapError, bbox_size, chain_loop, shoelace_area  # noqa: E402

TOL = 1e-6


def square_edges(size=100.0):
    """Four edges of a size x size square, counter-clockwise, as 3D points."""
    a, b, c, d = (0.0, 0.0, 0.0), (size, 0.0, 0.0), (size, size, 0.0), (0.0, size, 0.0)
    return [[a, b], [b, c], [c, d], [d, a]]


def area(pts):
    return abs(shoelace_area(pts))


def max_gap_for(edges):
    return GAP_TOL_REL * bbox_size(edges)


def test_exact_loop():
    pts, gaps = chain_loop(square_edges(), TOL, max_gap_for(square_edges()))
    assert len(pts) == 4, pts
    assert gaps == []
    assert abs(area(pts) - 1e4) < 1e-9


def test_reversed_and_shuffled_edges():
    e = square_edges()
    edges = [e[0], list(reversed(e[2])), list(reversed(e[1])), e[3]]
    pts, gaps = chain_loop(edges, TOL, max_gap_for(edges))
    assert len(pts) == 4 and gaps == []
    assert abs(area(pts) - 1e4) < 1e-9


def test_single_closed_edge():
    circle = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0)]
    pts, gaps = chain_loop([circle], TOL)
    assert len(pts) == 4 and gaps == []


def gap_case(gap):
    """Square with the end of edge 2 pulled back by `gap` (edge 3 unchanged)."""
    e = square_edges()
    e[1] = [(100.0, 0.0, 0.0), (100.0, 100.0 - gap, 0.0)]
    return e


def test_small_gap_closed():
    edges = gap_case(0.01)
    pts, gaps = chain_loop(edges, TOL, max_gap_for(edges))
    assert len(gaps) == 1, gaps
    assert abs(gaps[0][0] - 0.01) < 1e-9
    mid = gaps[0][1]
    assert abs(mid[0] - 100.0) < 1e-9 and abs(mid[1] - 99.995) < 1e-9
    assert abs(area(pts) - 1e4) < 1e-6


def test_half_mm_gap_closed():
    edges = gap_case(0.5)
    pts, gaps = chain_loop(edges, TOL, max_gap_for(edges))
    assert len(gaps) == 1 and abs(gaps[0][0] - 0.5) < 1e-9
    assert abs(area(pts) - 1e4) < 1e-6   # straight bridge along the same line


def test_final_gap_closed():
    e = square_edges()
    e[3] = [(0.0, 100.0, 0.0), (0.0, 0.3, 0.0)]   # last edge stops short of the start
    pts, gaps = chain_loop(e, TOL, max_gap_for(e))
    assert len(gaps) == 1 and abs(gaps[0][0] - 0.3) < 1e-9, gaps
    assert abs(area(pts) - 1e4) < 1e-6


def test_two_gaps_and_reversed():
    e = square_edges()
    e[1] = [(100.0, 100.0 - 0.02, 0.0), (100.0, 0.05, 0.0)]   # reversed, short at both ends
    pts, gaps = chain_loop(e, TOL, max_gap_for(e))
    assert sorted(round(g[0], 9) for g in gaps) == [0.02, 0.05], gaps


def test_gap_above_tolerance_fails():
    edges = gap_case(5.0)   # 5 mm in a 100 mm loop > 2 %
    try:
        chain_loop(edges, TOL, max_gap_for(edges))
    except LoopGapError as exc:
        assert abs(exc.gap - 5.0) < 1e-9
        assert abs(exc.at[1] - 97.5) < 1e-9
        assert "gap of 5" in str(exc)
        print("    message: %s" % exc)
    else:
        raise AssertionError("expected LoopGapError")


def test_no_bridging_without_max_gap():
    try:
        chain_loop(gap_case(0.01), TOL)
    except LoopGapError:
        pass
    else:
        raise AssertionError("expected LoopGapError without max_gap")


if __name__ == "__main__":
    names = sorted(n for n in globals() if n.startswith("test_"))
    for n in names:
        globals()[n]()
        print("OK  %s" % n)
    print("%d tests passed" % len(names))
