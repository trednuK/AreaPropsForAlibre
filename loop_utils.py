# -*- coding: utf-8 -*-
"""
loop_utils.py  (pure Python, runs in IronPython 2.7 and CPython 3)

Geometry helpers for alibre_section_properties.py that don't need Alibre:
chaining a face's edge polylines into one closed loop (bridging small gaps
between edge ends) and the shoelace area. Loaded by the Alibre script with
execfile(), like results_window.py; tests/test_loop_utils.py tests it with
CPython.
"""

# Gaps between edge ends up to this fraction of the face's bounding-box size
# are bridged with a straight segment (and reported); larger gaps fail.
GAP_TOL_REL = 0.02


class LoopGapError(Exception):
    """An edge loop has a gap larger than the allowed maximum.
    gap: the gap length, at: its midpoint (input units)."""

    def __init__(self, gap, at):
        Exception.__init__(self, "gap of %.6g at %s" % (gap, fmt_point(at)))
        self.gap = gap
        self.at = at


def fmt_point(p):
    return "(" + "; ".join("%.6g" % c for c in p) + ")"


def dist(a, b):
    """Distance between two points of the same dimension (2D or 3D)."""
    return sum((a[i] - b[i]) ** 2 for i in range(len(a))) ** 0.5


def midpoint(a, b):
    return tuple((a[i] + b[i]) / 2.0 for i in range(len(a)))


def bbox_size(polylines):
    """Largest bounding-box extent of all points in a list of polylines."""
    pts = [p for pl in polylines for p in pl]
    if not pts:
        return 0.0
    return max(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(len(pts[0])))


def chain_loop(polylines, tol, max_gap=None):
    """Order/orient the edge polylines of one loop into a closed point list.

    Edge ends closer than tol count as connected. A larger gap, up to max_gap
    (default: tol, i.e. no bridging), is bridged with a straight segment;
    this includes the gap between the loop's last and first point.
    Returns (points, gaps), gaps = [(length, midpoint), ...] of the bridged
    gaps. Raises LoopGapError when a gap exceeds max_gap.
    """
    if max_gap is None or max_gap < tol:
        max_gap = tol
    gaps = []

    def close(chain):
        d = dist(chain[0], chain[-1])
        if d < tol:
            return chain[:-1]
        if d > max_gap:
            raise LoopGapError(d, midpoint(chain[-1], chain[0]))
        gaps.append((d, midpoint(chain[-1], chain[0])))
        return chain   # the polygon closes itself with a straight segment

    if len(polylines) == 1:
        return close(list(polylines[0])), gaps
    remaining = list(polylines)
    first = remaining.pop(0)

    # Orient the first edge so its end connects to one of the others.
    def min_end_dist(p):
        return min(min(dist(p, q[0]), dist(p, q[-1])) for q in remaining)
    if min_end_dist(first[0]) < min_end_dist(first[-1]):
        first = list(reversed(first))
    chain = list(first)
    while remaining:
        end = chain[-1]
        best_i, best_rev, best_d = None, False, None
        for i, q in enumerate(remaining):
            for rev, p in ((False, q[0]), (True, q[-1])):
                d = dist(end, p)
                if best_d is None or d < best_d:
                    best_i, best_rev, best_d = i, rev, d
        q = remaining.pop(best_i)
        if best_rev:
            q = list(reversed(q))
        if best_d < tol:
            chain.extend(q[1:])
        elif best_d <= max_gap:
            gaps.append((best_d, midpoint(end, q[0])))
            chain.extend(q)    # straight segment from end to q[0]
        else:
            raise LoopGapError(best_d, midpoint(end, q[0]))
    return close(chain), gaps


def shoelace_area(points):
    a = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        a += x1 * y2 - x2 * y1
    return a / 2.0
