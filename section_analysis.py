"""
section_analysis.py  (CPython 3.x - runs OUTSIDE Alibre Design)

Reads a face boundary (outer loop + optional hole loops, as flat 2D point
lists) from a JSON file, builds the cross-section with `sectionproperties`,
runs the analysis, and writes the results back to a JSON file.

Usage:
    python section_analysis.py <input_geometry.json> <output_results.json>

Input JSON schema (written by the Alibre-side script):
{
    "units": "mm",
    "mesh_size": null,
    "regions": [                      # one per selected face
        {"outer": [[x, y], ...], "holes": [[[x, y], ...], ...]},
        ...
    ]
}
The older single-face form {"outer": ..., "holes": ...} is also accepted.
Regions are unioned: faces that touch merge into one section, separate
faces form a compound section.
"""
import sys
import json
import traceback

from shapely.geometry import MultiPolygon, Polygon
from shapely import set_precision, unary_union
from sectionproperties.pre import Geometry
from sectionproperties.pre.geometry import CompoundGeometry
from sectionproperties.analysis import Section


def region_polygon(region):
    outer = [tuple(p) for p in region["outer"]]
    holes = [[tuple(p) for p in h] for h in region.get("holes", [])]
    poly = Polygon(outer, holes=holes if holes else None)
    if not poly.is_valid:
        # e.g. a self-intersecting loop or a hole touching the outer boundary
        poly = poly.buffer(0)
    if poly.is_empty:
        raise ValueError("A face boundary produced an empty polygon.")
    return poly


def build_geometry(data):
    regions = data.get("regions")
    if regions is None:
        regions = [{"outer": data["outer"], "holes": data.get("holes", [])}]
    polys = [region_polygon(r) for r in regions]
    # Snap to a fine grid so faces that share an edge (but whose vertices
    # differ by ~1e-11 from tessellation/round-off) really merge, and no
    # near-duplicate points reach the mesher ("ran out of precision").
    minx = min(p.bounds[0] for p in polys)
    miny = min(p.bounds[1] for p in polys)
    maxx = max(p.bounds[2] for p in polys)
    maxy = max(p.bounds[3] for p in polys)
    grid = max(maxx - minx, maxy - miny) * 1e-6
    polys = [set_precision(p, grid) for p in polys]
    merged = unary_union(polys, grid_size=grid).buffer(0)
    if merged.is_empty or not merged.is_valid:
        raise ValueError("Combined faces give an invalid or empty section.")
    if isinstance(merged, Polygon):
        return Geometry(geom=merged), [merged]
    if isinstance(merged, MultiPolygon):
        parts = list(merged.geoms)
        return CompoundGeometry([Geometry(geom=p) for p in parts]), parts
    raise ValueError("Unexpected geometry type after union: %s" % merged.geom_type)


def run_analysis(data):
    geom, shapes = build_geometry(data)
    n_parts = len(shapes)

    mesh_size = data.get("mesh_size", None)
    if not mesh_size:
        # mesh_sizes is a maximum element AREA: aim for ~3000 elements
        mesh_size = geom.calculate_area() / 3000.0

    geom.create_mesh(mesh_sizes=mesh_size)
    sec = Section(geometry=geom)

    sec.calculate_geometric_properties()
    warping_ok = True
    warping_note = ""
    try:
        if n_parts > 1:
            # J/Iw of separate, unconnected parts is not meaningful as one section
            raise ValueError("section consists of %d separate parts" % n_parts)
        sec.calculate_warping_properties()
    except Exception as exc:
        warping_note = str(exc)
        # Warping/torsion analysis can fail or be extremely slow on
        # very thin/degenerate or multi-region sections. Geometric
        # properties are still valid and returned regardless.
        warping_ok = False

    plastic_ok = True
    try:
        sec.calculate_plastic_properties()
    except Exception:
        plastic_ok = False

    ixx_c, iyy_c, ixy_c = sec.get_ic()
    iuu, ivv = sec.get_ip()
    zxx_plus, zxx_minus, zyy_plus, zyy_minus = sec.get_z()

    results = {
        "units_note": "length units as supplied in input JSON ('{}'); "
                       "area/inertia units are that unit to the 2nd/4th power".format(
                           data.get("units", "unspecified")
                       ),
        "area": sec.get_area(),
        "perimeter": sec.get_perimeter(),
        "centroid": list(sec.get_c()),
        "ixx_c": ixx_c,
        "iyy_c": iyy_c,
        "ixy_c": ixy_c,
        "i11_c": iuu,
        "i22_c": ivv,
        "principal_angle_deg": sec.get_phi(),
        "zxx_plus": zxx_plus,
        "zxx_minus": zxx_minus,
        "zyy_plus": zyy_plus,
        "zyy_minus": zyy_minus,
        "rc": list(sec.get_rc()),
        "n_parts": n_parts,
        "warping_properties_computed": warping_ok,
        "warping_note": warping_note,
        "plastic_properties_computed": plastic_ok,
    }

    if warping_ok:
        results["j"] = sec.get_j()
        results["gamma"] = sec.get_gamma()
        results["shear_centre"] = list(sec.get_sc())

    if plastic_ok:
        results["sxx"] = sec.get_s()[0]
        results["syy"] = sec.get_s()[1]

    # one PNG per language: {"nl": path, "en": path}; older form: "plot_path"
    plot_paths = data.get("plot_paths") or (
        {"nl": data["plot_path"]} if data.get("plot_path") else {})
    if plot_paths:
        try:
            for lang, path in plot_paths.items():
                plot_section(shapes, results, data, lang, path)
            results["plot_paths"] = plot_paths
        except Exception as exc:
            results["plot_error"] = str(exc)

    return results


PLOT_TEXT = {
    "nl": {"centroid": u"zwaartepunt", "axes": u"x, y: assen door zwaartepunt (Ixx, Iyy)",
           "principal": u"hoofdas", "phi": u"van +x naar as 1", "sc": u"dwarskrachtcentrum",
           "global": u"globaal", "dec": u","},
    "en": {"centroid": u"centroid", "axes": u"x, y: centroidal axes (Ixx, Iyy)",
           "principal": u"principal axis", "phi": u"from +x to axis 1", "sc": u"shear centre",
           "global": u"global", "dec": u"."},
}


def plot_section(shapes, r, data, lang, path):
    """PNG of the section with centroid, centroidal x/y axes and principal axes."""
    T = PLOT_TEXT.get(lang, PLOT_TEXT["en"])
    import math
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Arc, PathPatch
    from matplotlib.path import Path

    u = data.get("units", "")
    ax_names = data.get("axis_names", ["x", "y"])
    cx, cy = r["centroid"]
    minx = min(p.bounds[0] for p in shapes)
    miny = min(p.bounds[1] for p in shapes)
    maxx = max(p.bounds[2] for p in shapes)
    maxy = max(p.bounds[3] for p in shapes)
    size = max(maxx - minx, maxy - miny)
    L = 0.62 * size  # half-length of the axis arrows

    fig, ax = plt.subplots(figsize=(5.2, 6.6), dpi=100)
    for poly in shapes:
        rings = [poly.exterior] + list(poly.interiors)
        verts, codes = [], []
        for ring in rings:
            pts = list(ring.coords)
            verts += pts
            codes += [Path.MOVETO] + [Path.LINETO] * (len(pts) - 2) + [Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes), facecolor="#cfe3f7", edgecolor="#1f3b57",
                               lw=1.2, zorder=1))

    def arrow(angle_deg, color, label, ls, lw):
        a = math.radians(angle_deg)
        dx, dy = L * math.cos(a), L * math.sin(a)
        ax.plot([cx - dx, cx], [cy - dy, cy], color=color, ls=ls, lw=lw, zorder=3)
        ax.annotate("", xy=(cx + dx, cy + dy), xytext=(cx, cy), zorder=3,
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, ls=ls,
                                    mutation_scale=14))
        ax.text(cx + 1.08 * dx, cy + 1.08 * dy, label, color=color, fontsize=11,
                fontweight="bold", ha="center", va="center", zorder=4)

    arrow(0.0, "#555555", "x", "--", 1.0)
    arrow(90.0, "#555555", "y", "--", 1.0)
    phi = r["principal_angle_deg"]
    arrow(phi, "#d1342f", "1", "-", 1.6)
    arrow(phi + 90.0, "#2e8b57", "2", "-", 1.6)

    # angle arc from +x to axis 1, in the sense of the reported phi
    rad = 0.22 * size
    t1, t2 = (0.0, phi) if phi >= 0 else (phi, 0.0)
    ax.add_patch(Arc((cx, cy), 2 * rad, 2 * rad, theta1=t1, theta2=t2,
                     color="#d1342f", lw=1.0, zorder=3))
    def nl(v, fmt="%.4g"):
        if v != 0 and not (1e-3 <= abs(v) < 1e6) and fmt == "%.4g":
            e = int(math.floor(math.log10(abs(v))))
            sup = str(e).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))
            return ("%.4g" % (v / 10.0 ** e)).replace(".", T["dec"]) + " × 10" + sup
        if fmt == "%.4g" and abs(v) >= 1e4:
            return "{:,.0f}".format(v).replace(",", " ")
        return (fmt % v).replace(".", T["dec"])

    from matplotlib.lines import Line2D
    handles = [
        Line2D([], [], marker="o", ls="", ms=8, mfc="white", mec="black", mew=1.5,
               label=u"%s (%s; %s)" % (T["centroid"], nl(cx), nl(cy))),
        Line2D([], [], color="#555555", ls="--", lw=1.0,
               label=T["axes"]),
        Line2D([], [], color="#d1342f", lw=1.6,
               label=u"1: %s, I11 = %s %s⁴" % (T["principal"], nl(r["i11_c"]), u)),
        Line2D([], [], color="#2e8b57", lw=1.6,
               label=u"2: %s, I22 = %s %s⁴" % (T["principal"], nl(r["i22_c"]), u)),
        Line2D([], [], color="#d1342f", lw=1.0,
               label=u"φ = %s° (%s)" % (nl(phi, "%.1f"), T["phi"])),
    ]
    ax.plot(cx, cy, marker="o", ms=9, mfc="white", mec="black", mew=1.5, zorder=5)
    ax.plot(cx, cy, marker="+", ms=9, color="black", mew=1.5, zorder=6)
    if r.get("shear_centre"):
        sx, sy = r["shear_centre"]
        if math.hypot(sx - cx, sy - cy) > 1e-3 * size:
            ax.plot(sx, sy, marker="D", ms=6, mfc="#f2a33a", mec="black", zorder=5)
            handles.append(Line2D([], [], marker="D", ls="", ms=6, mfc="#f2a33a", mec="black",
                                  label=u"%s (%s; %s)" % (T["sc"], nl(sx), nl(sy))))

    pad = 0.75 * size
    ax.set_xlim(cx - pad, cx + pad)
    ax.set_ylim(cy - pad, cy + pad)
    ax.set_aspect("equal")
    ax.grid(True, color="#e6e6e6", lw=0.6, zorder=0)
    ax.set_xlabel(u"x = %s %s  [%s]" % (T["global"], ax_names[0], u))
    ax.set_ylabel(u"y = %s %s  [%s]" % (T["global"], ax_names[1], u))
    for sp in ax.spines.values():
        sp.set_color("#bbbbbb")
    fig.legend(handles=handles, loc="lower center", ncol=1, fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, 0.0))
    fig.tight_layout(rect=(0, 0.032 * len(handles), 1, 1))
    fig.savefig(path, dpi=200)  # sharp when copied; window scales it down
    plt.close(fig)


def main():
    if len(sys.argv) != 3:
        print("Usage: python section_analysis.py <input_geometry.json> <output_results.json>")
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]

    try:
        with open(in_path, "r") as f:
            data = json.load(f)
        results = run_analysis(data)
        results["success"] = True
    except Exception as exc:
        results = {
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }

    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    if not results["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
