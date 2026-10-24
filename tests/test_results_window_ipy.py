# -*- coding: utf-8 -*-
"""
Offscreen test of results_window.py in IronPython 2.7 (no Alibre needed):
accuracy dropdown, settings file, Recalculate (busy -> done, and an error),
language switch. Runs the window on an MTA thread, like Alibre Script.

    ipy tests\\test_results_window_ipy.py [png_output_dir]

Any IronPython 2.7 works, e.g. Mecway's via run_ipy.ps1 (see README, Tests).
PNG snapshots of each state are written to png_output_dir (default: a temp dir).
"""
import json
import os
import shutil
import sys
import tempfile
import time

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Drawing import Bitmap, Rectangle
from System.Drawing.Imaging import ImageFormat
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import Application

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="areaprops_win_")
if not os.path.isdir(OUT):
    os.makedirs(OUT)

ns = {}
execfile(os.path.join(ROOT, "results_window.py"), ns)


def T(nl, en):
    return {"nl": nl, "en": en}


def sections_for(area):
    return [(T(u"Geometrie", u"Geometry"), [
        (T(u"Oppervlakte A", u"Area A"), area, u"mm²"),
        (T(u"Zwaartepunt (x; y)", u"Centroid (x; y)"), (50.0, 10.0), u"mm"),
    ]), (T(u"Traagheid t.o.v. zwaartepunt", u"Second moments about centroid"), [
        (u"Ixx", 66666.6667, u"mm⁴"), (u"Iyy", 1666666.667, u"mm⁴"), (u"Ixy", 0.0, u"mm⁴"),
    ])]


def notes_for(n_el, n):
    return [T(u"Mesh: %d elementen (doel ~%d)" % (n_el, n), u"Mesh: %d elements (target ~%d)" % (n_el, n)),
            T(u"Volledige resultaten: C:\\x\\face_results.json", u"Full results: C:\\x\\face_results.json")]


def pump(form, until, timeout=15.0):
    t0 = time.time()
    while not until():
        Application.DoEvents()
        Thread.Sleep(20)
        if time.time() - t0 > timeout:
            raise AssertionError("timeout waiting for the window")
    Application.DoEvents()


def find(form, name):
    found = form.Controls.Find(name, True)
    assert found.Length == 1, (name, found.Length)
    return found[0]


def snap(form, name):
    Application.DoEvents()
    bmp = Bitmap(form.Width, form.Height)
    form.DrawToBitmap(bmp, Rectangle(0, 0, bmp.Width, bmp.Height))
    path = os.path.join(OUT, name)
    bmp.Save(path, ImageFormat.Png)
    print("  snapshot %s" % path)


def all_texts(form):
    out = []

    def walk(c):
        for ch in c.Controls:
            out.append(ch.Text)
            walk(ch)
    walk(form)
    return out


def main():
    work = tempfile.mkdtemp(prefix="areaprops_settings_")
    try:
        settings = os.path.join(work, "window_settings.json")
        lang_txt = os.path.join(work, "window_lang.txt")
        with open(lang_txt, "w") as f:
            f.write("en")   # old language file: must still be honoured

        plots = dict((k, os.path.join(ROOT, "work", "face_plot_%s.png" % k)) for k in ("nl", "en"))
        plots = dict((k, p) for k, p in plots.items() if os.path.isfile(p)) or None
        print("plot images: %s" % ("yes" if plots else "no (work\\face_plot_*.png missing)"))

        # 1. snapshot through the public entry point (no settings file yet -> EN from lang txt)
        ns["show_results"](None, T(u"Face<1>  ·  eenheden: mm", u"Face<1>  ·  units: mm"),
                           sections_for(2000.0), notes_for(4758, 3000),
                           snapshot_path=os.path.join(OUT, "win_1_initial.png"),
                           image_path=plots, lang_path=lang_txt, settings_path=settings,
                           n_target=3000, recalc=lambda n: {})
        print("  snapshot %s" % os.path.join(OUT, "win_1_initial.png"))

        calls = []

        def recalc(n):
            calls.append(n)
            Thread.Sleep(1200)  # the external analysis
            if n == 30000:
                raise ValueError("sectionproperties analysis failed:\nTraceback (most recent call last):\n"
                                 "  File x\nMemoryError: mesh too fine (test)")
            n_el = {1000: 1567, 3000: 4758, 10000: 15896}[n]
            return {"sections": sections_for(2000.0 + n / 1e6), "notes": notes_for(n_el, n),
                    "image_path": plots, "n_target": n}

        form = ns["build_form"](None, T(u"Face<1>  ·  eenheden: mm", u"Face<1>  ·  units: mm"),
                                sections_for(2000.0), notes_for(4758, 3000), plots, lang_txt,
                                None, settings, 3000, recalc)
        form.Show()
        pump(form, lambda: True)
        assert form.Text == u"Section properties", form.Text   # EN from window_lang.txt
        cmb = find(form, "cmbMesh")
        assert cmb.SelectedIndex == 1 and cmb.Text == u"Normal (~3000)", cmb.Text
        assert [cmb.Items[i] for i in range(cmb.Items.Count)] == \
            [u"Coarse (~1000 elements)", u"Normal (~3000)", u"Fine (~10000)", u"Very fine (~30000)"]
        assert find(form, "lblMeshStatus").Text == u""

        # 2. choose Fine: remembered, "click Recalculate" hint
        cmb.SelectedIndex = 2
        Application.DoEvents()
        with open(settings) as f:
            assert json.load(f)["n_target"] == 10000
        assert find(form, "lblMeshStatus").Text == u"Click Recalculate to apply"
        snap(form, "win_2_pending.png")

        # 3. Recalculate: busy state, then the new results in place
        find(form, "btnRecalc").PerformClick()
        pump(form, lambda: find(form, "lblMeshStatus").Text == u"Calculating...")
        assert not find(form, "btnRecalc").Enabled and not find(form, "cmbMesh").Enabled
        snap(form, "win_3_busy.png")
        pump(form, lambda: find(form, "lblMeshStatus").Text.startswith(u"Recalculated in"))
        assert calls == [10000], calls
        texts = all_texts(form)
        assert u"Mesh: 15896 elements (target ~10000)" in texts, texts
        assert u"2000.01" in texts, texts   # area of the recalculated sections
        assert find(form, "btnRecalc").Enabled
        snap(form, "win_4_done.png")

        # 4. a failing recalculation: message in the window, old results stay
        find(form, "cmbMesh").SelectedIndex = 3
        Application.DoEvents()
        find(form, "btnRecalc").PerformClick()
        pump(form, lambda: find(form, "lblMeshStatus").Text.startswith(u"Recalculation failed"))
        msg = find(form, "lblMeshStatus").Text
        assert msg == u"Recalculation failed: MemoryError: mesh too fine (test)", msg
        assert u"Mesh: 15896 elements (target ~10000)" in all_texts(form)
        snap(form, "win_5_error.png")

        # 5. switch to NL: texts, dropdown labels and settings follow
        rbs = [c for c in form.Controls[0].Controls if c.GetType().Name == "RadioButton"]
        nl_rb = [c for c in rbs if c.Tag == "nl"][0]
        nl_rb.Checked = True
        pump(form, lambda: form.Text == u"Doorsnede-eigenschappen")
        cmb = find(form, "cmbMesh")
        assert cmb.Text == u"Zeer fijn (~30000)", cmb.Text
        assert find(form, "btnRecalc").Text == u"Opnieuw berekenen"
        assert find(form, "lblMeshStatus").Text.startswith(u"Herberekenen mislukt: MemoryError")
        with open(settings) as f:
            s = json.load(f)
        assert s == {"lang": "nl", "n_target": 30000}, s
        snap(form, "win_6_nl_error.png")

        # 6. back to Coarse and recalculate in NL
        cmb.SelectedIndex = 0
        Application.DoEvents()
        find(form, "btnRecalc").PerformClick()
        pump(form, lambda: find(form, "lblMeshStatus").Text == u"Bezig...")
        pump(form, lambda: find(form, "lblMeshStatus").Text.startswith(u"Herberekend in"))
        assert u"Mesh: 1567 elementen (doel ~1000)" in all_texts(form)
        snap(form, "win_7_nl_done.png")
        form.Close()

        # 7. settings are read back; an invalid value falls back to Normal
        assert ns["read_settings"](settings) == {"lang": "nl", "n_target": 1000}
        with open(settings, "w") as f:
            f.write("{broken")
        assert ns["read_settings"](settings, lang_txt) == {"lang": "en", "n_target": 3000}

        # 8. without a recalc callback there is no mesh bar (old behaviour)
        form = ns["build_form"](None, u"x", sections_for(2000.0), [], None, None, "en")
        assert form.Controls.Find("cmbMesh", True).Length == 0
        form.Dispose()
    finally:
        shutil.rmtree(work, ignore_errors=True)


errors = []


def run():
    try:
        main()
    except BaseException:
        import traceback
        errors.append(traceback.format_exc())


th = Thread(ThreadStart(run))
th.SetApartmentState(ApartmentState.MTA)   # like Alibre Script
th.Start()
th.Join()
if errors:
    print(errors[0])
    sys.exit(1)
print("results window test passed (PNGs in %s)" % OUT)
