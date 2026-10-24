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
     (uses `sectionproperties`) and shows the results in a dialog. The
     dialog's Recalculate button reruns step 3 with another mesh accuracy.

See README.md for the one-time setup of the external Python environment.
"""
import codecs
import json
import math
import os

import clr
clr.AddReference("System")
from System.Diagnostics import Process, ProcessStartInfo
from System import Environment
from System.IO import Path

# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------
# Folder holding this script, section_analysis.py, results_window.py and loop_utils.py.
# None -> found automatically under Documents\Alibre Script Library (Alibre
# Script runs scripts from a string, so the script can't see its own path).
SCRIPT_DIR = None
# Python with sectionproperties. None -> <SCRIPT_DIR>\.venv (see README).
PYTHON_EXE = None


def find_script_dir():
    def ok(d):
        return d and os.path.isfile(os.path.join(d, "section_analysis.py")) \
            and os.path.isfile(os.path.join(d, "results_window.py")) \
            and os.path.isfile(os.path.join(d, "loop_utils.py"))
    if ok(SCRIPT_DIR):
        return SCRIPT_DIR
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        if ok(d):
            return d
    except NameError:
        pass
    docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)
    root = os.path.join(docs, "Alibre Script Library")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [n for n in dirnames if n not in (".git", ".venv", "work", "__pycache__")]
        if ok(dirpath) and "alibre_section_properties.py" in filenames:
            return dirpath
    return None


SCRIPT_DIR = find_script_dir()
BASE_DIR = SCRIPT_DIR or os.path.join(Path.GetTempPath(), "AreaPropsForAlibre")
if not PYTHON_EXE:
    PYTHON_EXE = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
ANALYSIS_SCRIPT = os.path.join(BASE_DIR, "section_analysis.py")
WINDOW_SCRIPT = os.path.join(BASE_DIR, "results_window.py")
LOOP_SCRIPT = os.path.join(BASE_DIR, "loop_utils.py")
WORK_DIR = os.path.join(BASE_DIR, "work")
GEOMETRY_PATH = os.path.join(WORK_DIR, "face_geometry.json")
RESULTS_PATH = os.path.join(WORK_DIR, "face_results.json")
PLOT_PATHS = {"nl": os.path.join(WORK_DIR, "face_plot_nl.png"),
              "en": os.path.join(WORK_DIR, "face_plot_en.png")}
LANG_PATH = os.path.join(WORK_DIR, "window_lang.txt")   # old NL/EN file, still read
SETTINGS_PATH = os.path.join(WORK_DIR, "window_settings.json")  # language + accuracy choice
LOG_PATH = os.path.join(WORK_DIR, "face_log.txt")

VIEW_FROM_BEHIND = False    # True: mirror the 2D axes (view the face from the back)
COPLANAR_TOL = 0.01         # output units; max plane offset between selected faces
MESH_SIZE = None            # max element area; None -> area / target element count, with
                            # the target from the accuracy dropdown in the results window
                            # (remembered in work\window_settings.json). A number overrides it.
DEFAULT_N_TARGET = 3000     # target element count when nothing was chosen yet ("Normal")
SEGMENTS_PER_CIRCLE = 96    # sampling density for curved edges
# Gaps between edge ends (edges that don't quite connect) up to this fraction
# of the face's bounding-box size are closed with a straight segment and
# reported. None -> default from loop_utils.py (0.02 = 2 %).
GAP_TOL_REL = None
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
# External analysis (first run and Recalculate in the results window)
# ---------------------------------------------------------------------
class AnalysisError(Exception):
    pass


def saved_n_target():
    """Target element count chosen in the results window (accuracy dropdown)."""
    try:
        with open(SETTINGS_PATH) as f:
            n = json.load(f).get("n_target")
        if isinstance(n, int) and n > 0:
            return n
    except Exception:
        pass
    return DEFAULT_N_TARGET


def run_external_analysis(n_target):
    """Run section_analysis.py on the saved face_geometry.json with the given
    target element count and return the results dict. Raises AnalysisError;
    shows no dialogs, so it can run on the results window's background thread."""
    with open(GEOMETRY_PATH, "r") as f:
        geometry = json.load(f)
    geometry["n_target"] = n_target
    with open(GEOMETRY_PATH, "w") as f:
        json.dump(geometry, f)
    for old in [RESULTS_PATH] + list(PLOT_PATHS.values()):
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
        raise AnalysisError("The external analysis did not produce a results file.\nstderr:\n%s"
                            % stderr[-2000:])
    with open(RESULTS_PATH, "r") as f:
        results = json.load(f)
    if not results.get("success", False):
        raise AnalysisError("sectionproperties analysis failed:\n%s"
                            % results.get("error", "unknown error"))
    return results


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


def axis_name(vec):
    """'X', '-X', ... for a global axis direction, else a short description."""
    for i, name in enumerate("XYZ"):
        if abs(vec[i]) > 0.9999:
            return name if vec[i] > 0 else u"\u2212" + name
    return u"(%.2f; %.2f; %.2f)" % vec


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
if SCRIPT_DIR is None:
    fail("Could not find the AreaProps script folder (with section_analysis.py, "
         "results_window.py and loop_utils.py) under Documents\\Alibre Script Library. Set SCRIPT_DIR "
         "at the top of alibre_section_properties.py.")

# Pure geometry helpers (chain_loop, shoelace_area, ...), shared with the tests.
_loop_ns = {}
execfile(LOOP_SCRIPT, _loop_ns)
chain_loop = _loop_ns["chain_loop"]
shoelace_area = _loop_ns["shoelace_area"]
bbox_size = _loop_ns["bbox_size"]
LoopGapError = _loop_ns["LoopGapError"]
gap_tol_rel = GAP_TOL_REL if GAP_TOL_REL is not None else _loop_ns["GAP_TOL_REL"]

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
    loop_polylines = []
    for loop in com_items(face._Face.Loops):
        polylines = []
        for coedge in com_items(loop.Coedges):
            ad_edge = coedge.Edge
            s_len = script_len_by_key.get(tuple(ad_edge.Key))
            pts, ctype = edge_polyline(ad_edge, s_len if s_len is not None else 0.0, scale)
            log("  edge %s: %d pts, sampled len %.6g %s"
                % (ctype, len(pts), polyline_length(pts) * out_scale, U))
            polylines.append(pts)
        loop_polylines.append(polylines)
    if not loop_polylines:
        fail("No boundary loops found on %s." % face.Name)
    # Edge ends closer than 1e-4 AlibreX units are connected; larger gaps up
    # to GAP_TOL_REL x the face size are bridged with a straight segment.
    size = bbox_size([pl for pls in loop_polylines for pl in pls])
    max_gap = gap_tol_rel * size
    loops, gaps = [], []
    for polylines in loop_polylines:
        try:
            pts, loop_gaps = chain_loop(polylines, 1e-4, max_gap)  # AlibreX units
        except LoopGapError as exc:
            at = tuple(c * out_scale for c in exc.at)
            fail("The edges of %s do not form a closed boundary: there is a gap of "
                 "%.4g %s near (%.6g; %.6g; %.6g) %s (global). Gaps up to %.4g %s "
                 "(GAP_TOL_REL = %.3g of the face size) are closed automatically. "
                 "Repair the face in Alibre."
                 % (face.Name, exc.gap * out_scale, U, at[0], at[1], at[2], U,
                    max_gap * out_scale, U, gap_tol_rel))
        loops.append(pts)
        for g, mid in loop_gaps:
            at = tuple(c * out_scale for c in mid)
            log("  gap closed: %.6g %s near (%.6g; %.6g; %.6g) %s (global)"
                % (g * out_scale, U, at[0], at[1], at[2], U))
            gaps.append((g * out_scale, mid))
    return loops, gaps


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
    gaps_closed = []   # bridged gaps between edge ends, in output units
    for f in faces:
        log("%s:" % f.Name)
        loops_3d, face_gaps = face_loops_3d(f, scale, out_scale, U)
        loops_2d = [[(vec_dot(p, u_axis) * out_scale, vec_dot(p, v_axis) * out_scale) for p in lp]
                    for lp in loops_3d]
        for g, mid in face_gaps:
            gaps_closed.append({"face": f.Name, "length": g,
                                "at": [vec_dot(mid, u_axis) * out_scale,
                                       vec_dot(mid, v_axis) * out_scale]})
        areas = [abs(shoelace_area(lp)) for lp in loops_2d]
        outer_idx = areas.index(max(areas))
        regions.append({"outer": loops_2d[outer_idx],
                        "holes": [lp for i, lp in enumerate(loops_2d) if i != outer_idx]})
        log("  loops: %d, polygon area %.6g" % (len(loops_2d), 2 * areas[outer_idx] - sum(areas)))

    if not os.path.isdir(WORK_DIR):
        os.makedirs(WORK_DIR)
    n_target = saved_n_target()
    with open(GEOMETRY_PATH, "w") as f:
        json.dump({"units": U, "mesh_size": MESH_SIZE, "n_target": n_target, "regions": regions,
                   "gaps_closed": gaps_closed,
                   "axis_names": [u_name, v_name], "plot_paths": PLOT_PATHS}, f)

    # ----------------------- run the external analysis -----------------------
    if not os.path.isfile(PYTHON_EXE):
        fail("Python environment not found:\n%s\nCreate it with the two commands in README (Setup)." % PYTHON_EXE)
    if not os.path.isfile(ANALYSIS_SCRIPT):
        fail("Configured ANALYSIS_SCRIPT not found:\n%s\nSee README." % ANALYSIS_SCRIPT)
    log("Mesh target: %s elements%s" % (n_target, " (MESH_SIZE = %s wins)" % MESH_SIZE if MESH_SIZE else ""))
    try:
        results = run_external_analysis(n_target)
    except AnalysisError as exc:
        fail(str(exc))

    # ------------------------------ show results ------------------------------
    # Texts as {"nl": ..., "en": ...}; the results window switches language live.
    def T(nl, en):
        return {"nl": nl, "en": en}

    def num(v, lang):
        s = u"%.3g" % v
        return s.replace(u".", u",") if lang == "nl" else s

    def build_display(r):
        """(subtitle, sections, notes, plots) for the results window from one
        results dict; used for the first run and for Recalculate."""
        u1, u2, u3, u4, u6 = U, U + u"²", U + u"³", U + u"⁴", U + u"⁶"
        cx, cy = r["centroid"]
        c3 = tuple(cx * u_axis[i] + cy * v_axis[i] + plane_offset * normal[i] for i in range(3))
        sections = [
            (T(u"Geometrie", u"Geometry"), [
                (T(u"Oppervlakte A", u"Area A"), r["area"], u2),
                (T(u"Omtrek (buitenrand)", u"Perimeter (outer)"), r["perimeter"], u1),
                (T(u"Zwaartepunt (x; y)", u"Centroid (x; y)"), (cx, cy), u1),
                (T(u"Zwaartepunt globaal (X; Y; Z)", u"Centroid global (X; Y; Z)"), c3, u1),
            ]),
            (T(u"Traagheid t.o.v. zwaartepunt", u"Second moments about centroid"), [
                (u"Ixx", r["ixx_c"], u4),
                (u"Iyy", r["iyy_c"], u4),
                (u"Ixy", r["ixy_c"], u4),
                (T(u"I11 (hoofdas)", u"I11 (principal)"), r["i11_c"], u4),
                (T(u"I22 (hoofdas)", u"I22 (principal)"), r["i22_c"], u4),
                (T(u"Hoek hoofdas φ", u"Principal angle φ"), r["principal_angle_deg"], u"°"),
                (T(u"Traagheidsstraal rx", u"Radius of gyration rx"), r["rc"][0], u1),
                (T(u"Traagheidsstraal ry", u"Radius of gyration ry"), r["rc"][1], u1),
            ]),
            (T(u"Weerstandsmomenten", u"Section moduli"), [
                (T(u"Wx boven (+y)", u"Wx top (+y)"), r["zxx_plus"], u3),
                (T(u"Wx onder (−y)", u"Wx bottom (−y)"), r["zxx_minus"], u3),
                (T(u"Wy rechts (+x)", u"Wy right (+x)"), r["zyy_plus"], u3),
                (T(u"Wy links (−x)", u"Wy left (−x)"), r["zyy_minus"], u3),
            ]),
        ]
        if r.get("plastic_properties_computed"):
            sections[2][1].extend([
                (T(u"Wpl,x (plastisch)", u"Wpl,x (plastic)"), r["sxx"], u3),
                (T(u"Wpl,y (plastisch)", u"Wpl,y (plastic)"), r["syy"], u3),
            ])
        notes = []
        n_parts = r.get("n_parts", 1)
        if r.get("warping_properties_computed"):
            sections.append((T(u"Torsie en welving", u"Torsion and warping"), [
                (T(u"Torsieconstante J", u"Torsion constant J"), r["j"], u4),
                (T(u"Welvingsconstante Iw", u"Warping constant Iw"), r["gamma"], u6),
                (T(u"Dwarskrachtcentrum (x; y)", u"Shear centre (x; y)"), tuple(r["shear_centre"]), u1),
            ]))
        elif n_parts > 1:
            notes.append(T(u"Torsie/welving niet berekend: doorsnede bestaat uit %d losse delen." % n_parts,
                           u"Torsion/warping not computed: section consists of %d separate parts." % n_parts))
        else:
            reason = r.get("warping_note") or u"?"
            notes.append(T(u"Torsie/welving niet berekend: %s" % reason,
                           u"Torsion/warping not computed: %s" % reason))
        if len(faces) > 1:
            notes.append(T(u"%d vlakken samengevoegd tot %d los(se) deel/delen." % (len(faces), n_parts),
                           u"%d faces merged into %d separate part(s)." % (len(faces), n_parts)))

        # Repairs are always reported, never silent.
        if gaps_closed:
            n_gaps = len(gaps_closed)
            g_max = max(g["length"] for g in gaps_closed)
            notes.append(T(u"%d kleine opening(en) in de rand gesloten (grootste %s %s)."
                           % (n_gaps, num(g_max, "nl"), U),
                           u"%d small gap(s) in the boundary closed (largest %s %s)."
                           % (n_gaps, num(g_max, "en"), U)))
        healing = r.get("healing") or {}
        if healing.get("snapped_faces"):
            s_max = healing.get("max_snap", 0.0)
            before, after = healing.get("parts_before_snap"), healing.get("parts_after_snap")
            if before is not None and after is not None and before != after:
                extra = (u" (%d -> %d delen)" % (before, after), u" (%d -> %d parts)" % (before, after))
            else:
                extra = (u"", u"")
            notes.append(T(u"Vlakken samengevoegd over een opening van max. %s %s%s."
                           % (num(s_max, "nl"), U, extra[0]),
                           u"Faces merged across a gap of at most %s %s%s."
                           % (num(s_max, "en"), U, extra[1])))
        n_el = r.get("n_elements")
        if n_el is not None:
            if r.get("n_target"):
                notes.append(T(u"Mesh: %d elementen (doel ~%d)" % (n_el, r["n_target"]),
                               u"Mesh: %d elements (target ~%d)" % (n_el, r["n_target"])))
            else:
                notes.append(T(u"Mesh: %d elementen (MESH_SIZE = %s, keuze nauwkeurigheid niet gebruikt)"
                               % (n_el, MESH_SIZE),
                               u"Mesh: %d elements (MESH_SIZE = %s, accuracy choice not used)"
                               % (n_el, MESH_SIZE)))
        notes.append(T(u"Assen: x = globaal %s, y = globaal %s (gezien van buiten op het vlak)" % (u_name, v_name),
                       u"Axes: x = global %s, y = global %s (face seen from outside)" % (u_name, v_name)))
        notes.append(T(u"Volledige resultaten: %s" % RESULTS_PATH, u"Full results: %s" % RESULTS_PATH))
        plots = dict((k, p) for k, p in PLOT_PATHS.items() if os.path.isfile(p)) or None
        if plots is None and r.get("plot_error"):
            notes.append(T(u"Plot niet gemaakt: %s" % r["plot_error"],
                           u"Plot not created: %s" % r["plot_error"]))
        return subtitle, sections, notes, plots

    if len(face_names) <= 4:
        faces_txt = T(u", ".join(face_names), u", ".join(face_names))
    else:
        faces_txt = T(u"%d vlakken" % len(face_names), u"%d faces" % len(face_names))
    subtitle = T(u"%s  ·  eenheden: %s" % (faces_txt["nl"], U),
                 u"%s  ·  units: %s" % (faces_txt["en"], U))

    def nl(t):
        return t["nl"] if isinstance(t, dict) else t

    def display_text(sections, notes):
        """Plain (Dutch) text of the results, for the log and the fallback dialog."""
        text_lines = []
        for title, rows in sections:
            text_lines.append(nl(title))
            for label, value, unit in rows:
                if isinstance(value, tuple):
                    value = u"(" + u"; ".join("%.6g" % v for v in value) + u")"
                else:
                    value = "%.6g" % value
                text_lines.append(u"  %s = %s %s" % (nl(label), value, unit))
        return text_lines, [nl(n) for n in notes]

    subtitle, sections, notes, plots = build_display(results)
    text_lines, note_lines = display_text(sections, notes)
    log(nl(subtitle))
    log(u"\n".join(text_lines + note_lines))
    write_log()

    def recalc(n):
        """Recalculate from the results window (background thread): rerun
        section_analysis.py on the saved face_geometry.json with mesh target n.
        Raises AnalysisError (shown in the window) instead of calling fail()."""
        log(u"")
        log(u"Recalculate: mesh target %s elements" % n)
        try:
            r = run_external_analysis(n)
            subtitle_r, sections_r, notes_r, plots_r = build_display(r)
            tl, nlines = display_text(sections_r, notes_r)
            log(u"\n".join(tl + nlines))
        except Exception as exc:
            log(u"Recalculate failed: %s" % exc)
            write_log()
            raise
        write_log()
        return {"subtitle": subtitle_r, "sections": sections_r, "notes": notes_r,
                "image_path": plots_r, "n_target": r.get("n_target")}

    try:
        ns = {}
        execfile(WINDOW_SCRIPT, ns)
        ns["show_results"](None, subtitle, sections, notes, image_path=plots, lang_path=LANG_PATH,
                           settings_path=SETTINGS_PATH, n_target=results.get("n_target"),
                           recalc=recalc)
    except SystemExit:
        raise
    except Exception as exc:
        log("Results window failed: %s" % exc)
        write_log()
        win.InfoDialog(u"\n".join([nl(subtitle), u""] + text_lines + [u""] + note_lines),
                       "Section Properties")

except SystemExit:
    raise
except Exception as exc:
    import traceback
    fail("Unexpected error:\n%s\n\n%s" % (str(exc), traceback.format_exc()))
