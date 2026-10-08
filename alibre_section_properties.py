# -*- coding: utf-8 -*-
"""
alibre_section_properties.py
Runs INSIDE Alibre Design as an Alibre Script (IronPython 2.7.x).

Select exactly one planar face in the 3D view, then run this script. It:
  1. Reads the face's boundary loops through the full AlibreX API
     (face._Face.Loops -> coedges -> edge.Geometry) and samples every edge
     curve (lines, arcs, full circles, ellipses, splines) into 2D points.
  2. Writes that geometry to a JSON file.
  3. Launches an external CPython process running section_analysis.py
     (uses `sectionproperties`) and shows the results in a dialog.

See README.md for the one-time setup of the external Python environment.
"""
import codecs
import json
import math
import os

import clr
clr.AddReference("System")
from System.Diagnostics import Process, ProcessStartInfo

# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------
PYTHON_EXE = r"C:\AlibreTools\sectionprops_env\Scripts\python.exe"
SCRIPT_DIR = r"C:\Users\kunde\Documents\Alibre Script Library\AreaProps"
ANALYSIS_SCRIPT = os.path.join(SCRIPT_DIR, "section_analysis.py")
WINDOW_SCRIPT = os.path.join(SCRIPT_DIR, "results_window.py")
WORK_DIR = r"C:\AlibreTools\work"
GEOMETRY_PATH = os.path.join(WORK_DIR, "face_geometry.json")
RESULTS_PATH = os.path.join(WORK_DIR, "face_results.json")
PLOT_PATH = os.path.join(WORK_DIR, "face_plot.png")
LOG_PATH = os.path.join(WORK_DIR, "face_log.txt")

VIEW_FROM_BEHIND = False    # True: mirror the 2D axes (view the face from the back)
COPLANAR_TOL = 0.01         # output units; max plane offset between selected faces
MESH_SIZE = None            # None -> section_analysis.py picks a size (max element area)
SEGMENTS_PER_CIRCLE = 96    # sampling density for curved edges
# Extra length factor per document ModelUnits. AlibreScript/AlibreX ignore a
# document's model units: a part whose ModelUnits are meters (e.g. a STEP
# imported in m) comes back 100x too small. Verified: meters -> 100 (status
# bar area matched). Millimeters -> 1 is the normal case. Others unverified.
MODEL_UNIT_FACTOR = {"AD_METERS": 100.0, "AD_MILLIMETERS": 1.0}
MODEL_UNIT_OVERRIDE = None  # set a number to force the factor

win = Windows()
log_lines = []


def log(msg):
    log_lines.append(msg if isinstance(msg, basestring) else str(msg))


def write_log():
    try:
        if not os.path.isdir(WORK_DIR):
            os.makedirs(WORK_DIR)
        with codecs.open(LOG_PATH, "w", "utf-8") as f:
            f.write(u"\n".join(log_lines))
    except Exception:
        pass


def fail(message):
    log("FAIL: " + message)
    write_log()
    win.ErrorDialog(message, "Section Properties")
    raise SystemExit


# ---------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------
def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_norm(a):
    length = vec_dot(a, a) ** 0.5
    if length < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / length, a[1] / length, a[2] / length)


def dist(a, b):
    d = vec_sub(a, b)
    return vec_dot(d, d) ** 0.5


def polyline_length(pts):
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def pt3(p):
    return (p.X, p.Y, p.Z)


def com_items(coll):
    """AlibreX COM collections are not iterable from IronPython."""
    n = coll.Count
    try:
        return [coll.Item(i) for i in range(n)]
    except Exception:
        return [coll.Item(i) for i in range(1, n + 1)]


# ---------------------------------------------------------------------
# Edge sampling via AlibreX (coordinates in AlibreX internal units, cm)
# ---------------------------------------------------------------------
def param_extents(curve):
    try:
        lo, hi = curve.GetParameterExtents()
    except TypeError:
        lo_ref, hi_ref = clr.Reference[float](), clr.Reference[float]()
        curve.GetParameterExtents(lo_ref, hi_ref)
        lo, hi = lo_ref.Value, hi_ref.Value
    return lo, hi


def sample_curve(curve, t0, t1, n):
    return [pt3(curve.PointAtParam(t0 + (t1 - t0) * float(k) / n)) for k in range(n + 1)]


def edge_polyline(ad_edge, script_length, scale):
    """Sample one AlibreX edge. script_length is Alibre's own edge length in
    script units, used to choose between the two possible sweeps of a closed
    curve (e.g. minor vs major arc of a circle)."""
    curve = ad_edge.Geometry
    ctype = str(curve.CurveType)
    sv, ev = ad_edge.StartVertex, ad_edge.EndVertex
    if "AD_LINE" in ctype:
        return [pt3(sv.Point), pt3(ev.Point)], ctype

    lo, hi = param_extents(curve)
    period = hi - lo
    closed_edge = sv is None or ev is None or dist(pt3(sv.Point), pt3(ev.Point)) < 1e-9
    if closed_edge:
        return sample_curve(curve, lo, hi, SEGMENTS_PER_CIRCLE), ctype

    ts = curve.ParamAtPoint(sv.Point)
    te = curve.ParamAtPoint(ev.Point)
    if not curve.IsClosed:
        n = max(8, SEGMENTS_PER_CIRCLE // 2)
        return sample_curve(curve, ts, te, n), ctype

    # Periodic curve with two distinct vertices: two candidate sweeps.
    def wrap(a, b):
        while b <= a:
            b += period
        return b

    candidates = []
    for a, b in ((ts, wrap(ts, te)), (te, wrap(te, ts))):
        n = max(4, int(math.ceil(SEGMENTS_PER_CIRCLE * (b - a) / period)))
        pts = sample_curve(curve, a, b, n)
        err = abs(polyline_length(pts) * scale - script_length)
        candidates.append((err, pts))
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1], ctype


def chain_loop(polylines, tol):
    """Order/orient the edge polylines of one loop into a closed point list."""
    if len(polylines) == 1:
        pts = list(polylines[0])
        if dist(pts[0], pts[-1]) < tol:
            pts = pts[:-1]
        return pts
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
        if best_d > tol:
            fail("Could not chain the face's edges into a closed loop "
                 "(gap of %.6g). Is the face valid?" % best_d)
        q = remaining.pop(best_i)
        if best_rev:
            q = list(reversed(q))
        chain.extend(q[1:])
    if dist(chain[0], chain[-1]) < tol:
        chain = chain[:-1]
    return chain


def shoelace_area(points):
    a = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def axis_name(vec):
    """'X', '-X', ... for a global axis direction, else a short description."""
    for i, name in enumerate("XYZ"):
        if abs(vec[i]) > 0.9999:
            return name if vec[i] > 0 else u"\u2212" + name
    return u"schuin (%.2f; %.2f; %.2f)" % vec


def plane_axes(n_out):
    """2D axes as seen looking at the face from outside: y = global Y projected
    onto the plane ("up", as in Alibre's standard views), or -Z when looking
    along Y; x = y cross n so that x, y, n form a right-handed system."""
    if abs(n_out[1]) > 0.999:
        up = (0.0, 0.0, -1.0 if n_out[1] > 0 else 1.0)
    else:
        up = (0.0, 1.0, 0.0)
    d = vec_dot(up, n_out)
    v = vec_norm((up[0] - d * n_out[0], up[1] - d * n_out[1], up[2] - d * n_out[2]))
    u = vec_norm(vec_cross(v, n_out))
    if VIEW_FROM_BEHIND:
        u = (-u[0], -u[1], -u[2])
    return u, v, axis_name(u), axis_name(v)


# ---------------------------------------------------------------------
# Alibre integration
# ---------------------------------------------------------------------
part = CurrentPart()
if part is None:
    fail("No part is currently open. Open a part, select one or more faces, and try again.")

selection = list(part.Selections or [])
faces = [s for s in selection if hasattr(s, "_Face")]
if not faces:
    fail("Please select one or more planar faces (found %d selected item(s), "
         "none of them faces)." % len(selection))


def face_loops_3d(face, scale, out_scale, U):
    """Closed 3D point loops (AlibreX units) of one face."""
    script_len_by_key = {}
    for e in face.GetEdges():
        script_len_by_key[tuple(e._Edge.Key)] = e.Length
    loops = []
    for loop in com_items(face._Face.Loops):
        polylines = []
        for coedge in com_items(loop.Coedges):
            ad_edge = coedge.Edge
            s_len = script_len_by_key.get(tuple(ad_edge.Key))
            pts, ctype = edge_polyline(ad_edge, s_len if s_len is not None else 0.0, scale)
            log("  edge %s: %d pts, sampled len %.6g %s"
                % (ctype, len(pts), polyline_length(pts) * out_scale, U))
            polylines.append(pts)
        loops.append(chain_loop(polylines, 1e-4))  # AlibreX units
    if not loops:
        fail("No boundary loops found on %s." % face.Name)
    return loops


try:
    units = "script units"
    try:
        units = str(Units.Current)
    except Exception:
        pass
    U = {"Millimeters": "mm", "Centimeters": "cm", "Meters": "m",
         "Inches": "in", "Feet": "ft"}.get(units, units)
    face_names = [f.Name for f in faces]
    log("Faces: %s, units: %s" % (", ".join(face_names), units))
    if len(faces) != len(selection):
        log("Ignored %d non-face selection item(s)" % (len(selection) - len(faces)))

    for f in faces:
        surf_type = str(f._Face.Geometry.SurfaceType)
        if "AD_PLANE" not in surf_type:
            fail("%s is not planar (%s). Section properties require flat faces." % (f.Name, surf_type))

    # Scale factor AlibreX units -> script units (AlibreX works in cm).
    scale = None
    for f in faces:
        for v in f.GetVertices():
            p = pt3(v._Vertex.Point)
            n_ad = vec_dot(p, p) ** 0.5
            n_sc = (v.X ** 2 + v.Y ** 2 + v.Z ** 2) ** 0.5
            if n_ad > 1e-9:
                scale = n_sc / n_ad
                break
        if scale is not None:
            break
    if scale is None:
        scale = 10.0  # AlibreX cm -> script mm
    log("scale AlibreX->script: %.9g" % scale)
    model_units = "?"
    try:
        model_units = str(faces[0]._Face.Part.DesignProperties.ModelUnits)
    except Exception as exc:
        log("DesignProperties unavailable: %s" % exc)
    if MODEL_UNIT_OVERRIDE is not None:
        model_factor = float(MODEL_UNIT_OVERRIDE)
    elif model_units in MODEL_UNIT_FACTOR:
        model_factor = MODEL_UNIT_FACTOR[model_units]
    else:
        fail("Document ModelUnits = %s: the length factor for this unit has not "
             "been verified. Measure an edge in Alibre, compare with this script, "
             "and set MODEL_UNIT_OVERRIDE (or add it to MODEL_UNIT_FACTOR)." % model_units)
    out_scale = scale * model_factor
    log("ModelUnits=%s, model factor %.6g, AlibreX->output %.6g" % (model_units, model_factor, out_scale))

    # All faces must lie in one plane (that of the first face).
    g0 = faces[0]._Face.Geometry
    normal = vec_norm((g0.Normal.X, g0.Normal.Y, g0.Normal.Z))
    if faces[0]._Face.IsSenseReversed:
        normal = (-normal[0], -normal[1], -normal[2])  # outward face normal
    log("outward normal: (%.4f, %.4f, %.4f)" % normal)
    plane_d = vec_dot(pt3(g0.RootPoint), normal)
    for f in faces[1:]:
        gi = f._Face.Geometry
        ni = vec_norm((gi.Normal.X, gi.Normal.Y, gi.Normal.Z))
        if abs(vec_dot(normal, ni)) < 1.0 - 1e-6:
            fail("%s is not parallel to %s. All selected faces must lie in one plane."
                 % (f.Name, faces[0].Name))
        gap = abs(vec_dot(pt3(gi.RootPoint), normal) - plane_d) * out_scale
        if gap > COPLANAR_TOL:
            fail("%s lies %.6g %s out of the plane of %s. All selected faces must "
                 "lie in one plane." % (f.Name, gap, U, faces[0].Name))
    u_axis, v_axis, u_name, v_name = plane_axes(normal)
    plane_offset = plane_d * out_scale

    regions = []
    for f in faces:
        log("%s:" % f.Name)
        loops_2d = [[(vec_dot(p, u_axis) * out_scale, vec_dot(p, v_axis) * out_scale) for p in lp]
                    for lp in face_loops_3d(f, scale, out_scale, U)]
        areas = [abs(shoelace_area(lp)) for lp in loops_2d]
        outer_idx = areas.index(max(areas))
        regions.append({"outer": loops_2d[outer_idx],
                        "holes": [lp for i, lp in enumerate(loops_2d) if i != outer_idx]})
        log("  loops: %d, polygon area %.6g" % (len(loops_2d), 2 * areas[outer_idx] - sum(areas)))

    if not os.path.isdir(WORK_DIR):
        os.makedirs(WORK_DIR)
    with open(GEOMETRY_PATH, "w") as f:
        json.dump({"units": U, "mesh_size": MESH_SIZE, "regions": regions,
                   "axis_names": [u_name, v_name], "plot_path": PLOT_PATH}, f)

    # ----------------------- run the external analysis -----------------------
    if not os.path.isfile(PYTHON_EXE):
        fail("Configured PYTHON_EXE not found:\n%s\nSee README." % PYTHON_EXE)
    if not os.path.isfile(ANALYSIS_SCRIPT):
        fail("Configured ANALYSIS_SCRIPT not found:\n%s\nSee README." % ANALYSIS_SCRIPT)
    for old in (RESULTS_PATH, PLOT_PATH):
        if os.path.isfile(old):
            os.remove(old)

    psi = ProcessStartInfo(PYTHON_EXE, '"%s" "%s" "%s"' % (ANALYSIS_SCRIPT, GEOMETRY_PATH, RESULTS_PATH))
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    psi.RedirectStandardError = True
    proc = Process.Start(psi)
    stderr = proc.StandardError.ReadToEnd()
    proc.WaitForExit()

    if not os.path.isfile(RESULTS_PATH):
        fail("The external analysis did not produce a results file.\nstderr:\n%s" % stderr[-2000:])
    with open(RESULTS_PATH, "r") as f:
        results = json.load(f)
    if not results.get("success", False):
        fail("sectionproperties analysis failed:\n%s" % results.get("error", "unknown error"))

    # ------------------------------ show results ------------------------------
    r = results
    u1, u2, u3, u4, u6 = U, U + u"²", U + u"³", U + u"⁴", U + u"⁶"
    cx, cy = r["centroid"]
    c3 = tuple(cx * u_axis[i] + cy * v_axis[i] + plane_offset * normal[i] for i in range(3))
    sections = [
        (u"Geometrie", [
            (u"Oppervlakte A", r["area"], u2),
            (u"Omtrek (buitenrand)", r["perimeter"], u1),
            (u"Zwaartepunt (x; y)", (cx, cy), u1),
            (u"Zwaartepunt globaal (X; Y; Z)", c3, u1),
        ]),
        (u"Traagheid t.o.v. zwaartepunt", [
            (u"Ixx", r["ixx_c"], u4),
            (u"Iyy", r["iyy_c"], u4),
            (u"Ixy", r["ixy_c"], u4),
            (u"I11 (hoofdas)", r["i11_c"], u4),
            (u"I22 (hoofdas)", r["i22_c"], u4),
            (u"Hoek hoofdas φ", r["principal_angle_deg"], u"°"),
            (u"Traagheidsstraal rx", r["rc"][0], u1),
            (u"Traagheidsstraal ry", r["rc"][1], u1),
        ]),
        (u"Weerstandsmomenten", [
            (u"Wx boven (+y)", r["zxx_plus"], u3),
            (u"Wx onder (−y)", r["zxx_minus"], u3),
            (u"Wy rechts (+x)", r["zyy_plus"], u3),
            (u"Wy links (−x)", r["zyy_minus"], u3),
        ]),
    ]
    if r.get("plastic_properties_computed"):
        sections[2][1].extend([
            (u"Wpl,x (plastisch)", r["sxx"], u3),
            (u"Wpl,y (plastisch)", r["syy"], u3),
        ])
    notes = []
    if r.get("warping_properties_computed"):
        sections.append((u"Torsie en welving", [
            (u"Torsieconstante J", r["j"], u4),
            (u"Welvingsconstante Iw", r["gamma"], u6),
            (u"Dwarskrachtcentrum (x; y)", tuple(r["shear_centre"]), u1),
        ]))
    else:
        notes.append(u"Torsie/welving niet berekend: %s" % (r.get("warping_note") or u"onbekende fout"))
    n_parts = r.get("n_parts", 1)
    if len(faces) > 1:
        notes.append(u"%d vlakken samengevoegd tot %d los(se) deel/delen." % (len(faces), n_parts))
    notes.append(u"Assen: x = globaal %s, y = globaal %s (gezien van buiten op het vlak)"
                 % (u_name, v_name))
    notes.append(u"Volledige resultaten: %s" % RESULTS_PATH)

    if len(face_names) <= 4:
        faces_txt = u", ".join(face_names)
    else:
        faces_txt = u"%d vlakken" % len(face_names)
    subtitle = u"%s  ·  eenheden: %s" % (faces_txt, U)

    text_lines = []
    for title, rows in sections:
        text_lines.append(title)
        for label, value, unit in rows:
            if isinstance(value, tuple):
                value = u"(" + u"; ".join("%.6g" % v for v in value) + u")"
            else:
                value = "%.6g" % value
            text_lines.append(u"  %s = %s %s" % (label, value, unit))
    log(subtitle)
    log(u"\n".join(text_lines + notes))
    write_log()

    try:
        ns = {}
        execfile(WINDOW_SCRIPT, ns)
        plot = PLOT_PATH if os.path.isfile(PLOT_PATH) else None
        if plot is None and r.get("plot_error"):
            notes.append(u"Plot niet gemaakt: %s" % r["plot_error"])
        ns["show_results"](u"Section Properties", subtitle, sections, notes, image_path=plot)
    except SystemExit:
        raise
    except Exception as exc:
        log("Results window failed: %s" % exc)
        write_log()
        win.InfoDialog(u"\n".join([subtitle, u""] + text_lines + [u""] + notes), "Section Properties")

except SystemExit:
    raise
except Exception as exc:
    import traceback
    fail("Unexpected error:\n%s\n\n%s" % (str(exc), traceback.format_exc()))
