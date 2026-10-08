# Face section properties for Alibre Design

Select one or more planar faces in Alibre Design, run
`alibre_section_properties.py`, and get area, centroid, Ixx/Iyy/Ixy, principal moments, section moduli,
plastic moduli, torsion constant J, warping constant and shear centre —
every value shown with its unit (mm, mm², mm³, mm⁴, mm⁶) in a results
window that stays on top of Alibre and has a Copy button (tab-separated,
pastes into Excel).
Next to the table the window shows a plot of the section (made with
matplotlib, saved as `work\face_plot.png`): centroid,
centroidal x/y axes in global coordinates, principal axes 1 and 2 with the
angle phi from +x, and the shear centre.

Tested on Alibre Design Expert 29.1 (AlibreScript, IronPython 2.7.10) on
2026-10-07: a rail-like profile with lines and arcs gave A = 7439.13 mm²
against 7438.75 mm² in Alibre's status bar (0.005 %).

## How it works

Alibre Script (IronPython) cannot load NumPy/`sectionproperties`, so:

- **`alibre_section_properties.py`** (inside Alibre) reads the selected face
  through the full AlibreX API (`face._Face.Loops` → coedges →
  `edge.Geometry`), samples every edge curve (lines, arcs, full circles,
  ellipses, splines) into 2D points, writes `face_geometry.json`, runs the
  analysis and shows the results.
- **`section_analysis.py`** (normal CPython with `sectionproperties`)
  computes the properties and writes `face_results.json`.
- **`results_window.py`** is the WinForms results window (loaded with
  `execfile`, so edits take effect on the next run).

## Multiple faces

Select several faces (Ctrl+click) to analyse them as one section. They must
lie in one plane (`COPLANAR_TOL`, default 0.01 mm). Faces are unioned: faces
that touch merge into one section; separate faces form a compound section.
For a section made of separate parts, torsion/warping (J, Iw, shear centre)
is not computed, because it isn't meaningful for unconnected parts.

2D axes: the face is shown as seen from outside, like Alibre's standard views:
y = global Y (up), or -Z for faces normal to Y, and x completes a right-handed
system with the outward face normal (a face facing -X gets x = Z, y = Y). The
origin is the global origin, so the centroid is in model coordinates.
Ixx/Iyy etc. are about the centroid. If a face comes out mirrored compared to
the screen, set `VIEW_FROM_BEHIND = True`.

## Setup

1. Clone or copy this folder somewhere under
   `Documents\Alibre Script Library\`, so it shows up in the Alibre Script
   Library. The script finds its own folder there.
2. Install Python 3.10+ (python.org) and, in this folder, create the
   environment:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

All paths are relative to this folder: `.venv\` for Python, `work\` for the
geometry, results, plot and log (both are git-ignored). If your Script
Library lives elsewhere, set `SCRIPT_DIR` (and optionally `PYTHON_EXE`) at the
top of `alibre_section_properties.py`.

## Usage

1. Select one or more coplanar faces in the 3D view.
2. In the Alibre Script panel, double-click `alibre_section_properties` under
   Library → AreaPropsForAlibre, then click **Run**.
3. Wait for the analysis to finish (about 20–30 s, mostly the torsion/warping
   FEM). The results window appears on top. Full results:
   `work\face_results.json`, log: `work\face_log.txt`.

If you edited the script while its tab was open in the Alibre editor, close
the tab and reopen it. Run executes the editor's copy, not the file on disk.

## Model units (important)

AlibreScript and AlibreX ignore a document's **ModelUnits**. A part whose
model units are meters (e.g. a STEP imported in m) comes back 100× too small.
The script reads `ModelUnits` and corrects for it with `MODEL_UNIT_FACTOR`:

| ModelUnits | factor | status |
|---|---|---|
| AD_METERS | 100 | verified against the status-bar area |
| AD_MILLIMETERS | 1 | assumed (normal case) |
| other | — | script stops and asks you to verify |

For another unit, compare the script's area with Alibre's status bar
(click the face) and set `MODEL_UNIT_OVERRIDE`, or add the unit to the table.

## Notes / limitations

- AlibreScript's `Face.GetArea()` is a polygon calculation on the vertices,
  and `Edge.Length` returns roughly the chord for arcs. Neither is used as a
  check for that reason.
- For a closed curve split by two vertices (a circle edge between two
  points), the sweep is chosen by comparing with `Edge.Length`. An arc
  sweeping more than 180° on such a curve could pick the wrong side. This
  hasn't been seen in practice.
- `MESH_SIZE = None` sets the maximum element area to area/3000. Use a
  smaller value for thin-walled sections.
