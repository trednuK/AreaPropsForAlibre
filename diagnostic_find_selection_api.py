# -*- coding: utf-8 -*-
"""
diagnostic_find_selection_api.py

Run this INSIDE Alibre Design (Alibre Script), with a face selected, if
`alibre_section_properties.py` fails at the "part.Selections" line.

None of the Windows / Vertex / Parameter / Axis / Edge / CSharp / Plane /
Face class references cover the Application/Document/Selection object, so
the exact call for "get me the currently selected face(s)" could not be
confirmed in advance. This script uses IronPython's own introspection
(dir/type) to list what's actually available on `part`, so you can find
the right name in under a minute instead of guessing.

Select a face first, then run this, then read the InfoDialog it pops up.
"""
win = Windows()

part = CurrentPart()
if part is None:
    win.ErrorDialog("No part is currently open.", "Diagnostic")
    raise SystemExit

members = [m for m in dir(part) if not m.startswith("_")]
# Members whose name suggests they're relevant to selection
likely = [m for m in members if "select" in m.lower() or "current" in m.lower() or "pick" in m.lower()]

lines = []
lines.append("Members of `part` that look selection-related:")
lines.append(", ".join(likely) if likely else "(none found by name match)")
lines.append("")
lines.append("Full member list of `part` (%d members):" % len(members))
lines.append(", ".join(members))

win.InfoDialog("\n".join(lines), "Diagnostic: part members")

# If you find the right member above (e.g. it might be `part.Selections`,
# `part.SelectedFaces`, `Application.ActiveDocument.Selections`, etc.),
# try calling/printing it directly to see its type and contents, e.g.:
#
#   val = part.WhateverItsCalled
#   win.InfoDialog(str(type(val)) + "\n" + str(val), "Diagnostic: value")
#
# Then update the one line in alibre_section_properties.py that reads:
#   selection = part.Selections
# to match what you found here.
