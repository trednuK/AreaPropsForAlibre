# -*- coding: utf-8 -*-
"""
results_window.py  (IronPython 2.7 / WinForms)

Results window for alibre_section_properties.py. Loaded with execfile() so
edits take effect without restarting Alibre. Entry point:

    show_results(title, subtitle, sections, notes, snapshot_path=None,
                 image_path=None, lang_path=None, lang=None,
                 settings_path=None, n_target=None, recalc=None)

Every text may be a plain string or a {"nl": ..., "en": ...} dict; the NL/EN
radio buttons in the header rebuild the window in the other language.

sections:   [(section_title, [(label, value_or_None, unit), ...]), ...]
notes:      list of short texts shown under the table
image_path: plot PNG, or {"nl": path, "en": path}
lang_path:  old file with the last chosen language (read when settings_path
            has no language yet; written only without settings_path)
settings_path: JSON file that remembers the language and the mesh choice
            ({"lang": "nl", "n_target": 3000})
n_target:   mesh target (element count) the shown results were computed with
recalc:     callback recalc(n_target) -> {"subtitle", "sections", "notes",
            "image_path", "n_target"} (all optional); raises on failure. With
            a callback the window shows the accuracy dropdown and the
            Recalculate button. recalc runs on a background thread so the
            window stays responsive; it must not touch the window.
snapshot_path: if given, render the window to a PNG instead of showing it
"""
import json
import math
import os
import time

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System.Drawing import (Bitmap, Color, ContentAlignment, Font, FontStyle, Image, Point,
                            Rectangle, Size, SizeF)
from System.Drawing.Imaging import ImageFormat
from System.Globalization import CultureInfo
from System.IO import File, MemoryStream
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import (AnchorStyles, AutoScaleMode, Button, CheckBox, Clipboard,
                                  ComboBox, ComboBoxStyle, Cursors, FlatStyle, Form,
                                  FormBorderStyle, FormStartPosition, Label, MethodInvoker, Panel,
                                  PictureBox, PictureBoxSizeMode, RadioButton, Screen, ToolTip)

CULTURE_DEC = CultureInfo.CurrentCulture.NumberFormat.NumberDecimalSeparator  # for Copy/Excel

C_HEADER = Color.FromArgb(32, 41, 54)
C_HEADER_SUB = Color.FromArgb(170, 182, 196)
C_ACCENT = Color.FromArgb(0, 120, 212)
C_TEXT = Color.FromArgb(30, 30, 30)
C_MUTED = Color.FromArgb(105, 112, 120)
C_LINE = Color.FromArgb(225, 229, 234)
C_BAND = Color.FromArgb(247, 249, 251)
C_BG = Color.White
C_ERROR = Color.FromArgb(196, 43, 28)

SUP = {"-": u"⁻", "0": u"⁰", "1": u"¹", "2": u"²", "3": u"³",
       "4": u"⁴", "5": u"⁵", "6": u"⁶", "7": u"⁷", "8": u"⁸",
       "9": u"⁹"}

UI = {
    "nl": {"title": u"Doorsnede-eigenschappen", "copy": u"Kopiëren", "close": u"Sluiten",
           "copy_img": u"Afbeelding kopiëren", "copied": u"Gegevens gekopieerd (plakbaar in Excel)",
           "copied_img": u"Afbeelding gekopieerd", "copy_fail": u"Kopiëren mislukt: %s",
           "dec": u",", "mesh": u"Nauwkeurigheid (mesh):", "recalc": u"Opnieuw berekenen",
           "busy": u"Bezig...", "done": u"Herberekend in %d s",
           "pending": u"Klik op Opnieuw berekenen om toe te passen",
           "fail": u"Herberekenen mislukt: %s"},
    "en": {"title": u"Section properties", "copy": u"Copy", "close": u"Close",
           "copy_img": u"Copy image", "copied": u"Data copied (pastes into Excel)",
           "copied_img": u"Image copied", "copy_fail": u"Copy failed: %s",
           "dec": u".", "mesh": u"Accuracy (mesh):", "recalc": u"Recalculate",
           "busy": u"Calculating...", "done": u"Recalculated in %d s",
           "pending": u"Click Recalculate to apply",
           "fail": u"Recalculation failed: %s"},
}
LANGS = ("nl", "en")

# Accuracy presets: target number of mesh elements (max element area = area / n).
# Same presets and labels as the Mecway section-properties tool.
MESH_PRESETS = [
    (1000, {"nl": u"Grof (~1000 elementen)", "en": u"Coarse (~1000 elements)"}),
    (3000, {"nl": u"Normaal (~3000)", "en": u"Normal (~3000)"}),
    (10000, {"nl": u"Fijn (~10000)", "en": u"Fine (~10000)"}),
    (30000, {"nl": u"Zeer fijn (~30000)", "en": u"Very fine (~30000)"}),
]
DEFAULT_N_TARGET = 3000

WIDTH = 560             # table column
IMG_W = 520             # plot column (PNG aspect 520 x 660)
PAD = 22
COL_VALUE_RIGHT = 440   # right edge of the value column
ROW_H = 22
HEADER_H = 70


def tr(text, lang):
    if isinstance(text, dict):
        return text.get(lang) or text.get("en") or text.values()[0]
    return text


def fmt(v, dec):
    """Readable number: grouped digits, x10^n for very large/small values."""
    if v is None:
        return u"–"
    if v == 0:
        return u"0"
    a = abs(v)
    if 1e-3 <= a < 1e6:
        s = "%.6g" % v
        if "e" in s:
            s = "%.6f" % v
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        sign = ""
        if s.startswith("-"):
            sign, s = "-", s[1:]
        ip, _, fp = s.partition(".")
        if len(ip) > 4:
            groups = []
            while len(ip) > 3:
                groups.insert(0, ip[-3:])
                ip = ip[:-3]
            groups.insert(0, ip)
            ip = u" ".join(groups)
        return sign + ip + (dec + fp if fp else u"")
    e = int(math.floor(math.log10(a)))
    m = v / 10.0 ** e
    ms = ("%.4f" % m).rstrip("0").rstrip(".").replace(".", dec)
    return u"%s × 10%s" % (ms, u"".join(SUP[c] for c in str(e)))


def raw(v):
    return u"" if v is None else ("%.10g" % v).replace(".", CULTURE_DEC)


def _label(parent, text, x, y, w, h, size=9.75, style=FontStyle.Regular, color=C_TEXT,
           align=ContentAlignment.MiddleLeft, back=None):
    lb = Label()
    lb.Text = text
    lb.Location = Point(x, y)
    lb.Size = Size(w, h)
    lb.Font = Font("Segoe UI", size, style)
    lb.ForeColor = color
    lb.TextAlign = align
    lb.BackColor = back if back is not None else Color.Transparent
    lb.AutoEllipsis = True
    parent.Controls.Add(lb)
    return lb


def _button(parent, text, x, y, primary, w=110, h=32, anchor=True):
    b = Button()
    b.Text = text
    b.Location = Point(x, y)
    b.Size = Size(w, h)
    b.FlatStyle = FlatStyle.Flat
    b.Font = Font("Segoe UI", 9.5)
    b.Cursor = Cursors.Hand
    if primary:
        b.BackColor = C_ACCENT
        b.ForeColor = Color.White
        b.FlatAppearance.BorderSize = 0
    else:
        b.BackColor = C_BG
        b.ForeColor = C_TEXT
        b.FlatAppearance.BorderColor = Color.FromArgb(200, 205, 212)
    if anchor:
        b.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
    parent.Controls.Add(b)
    return b


def _load_image(path):
    try:
        # via a stream so the PNG file is not locked for the next run
        return Image.FromStream(MemoryStream(File.ReadAllBytes(path)))
    except Exception:
        return None


def _load_images(image_path):
    if isinstance(image_path, dict):
        return dict((k, _load_image(p)) for k, p in image_path.items() if p)
    if image_path:
        img = _load_image(image_path)
        return dict((k, img) for k in LANGS)
    return {}


def _read_lang(lang_path):
    try:
        with open(lang_path) as f:
            v = f.read().strip()
        return v if v in LANGS else None
    except Exception:
        return None


def _write_lang(lang_path, lang):
    try:
        with open(lang_path, "w") as f:
            f.write(lang)
    except Exception:
        pass


def read_settings(settings_path, lang_path=None):
    """{"lang": "nl"/"en"/None, "n_target": one of MESH_PRESETS}. The language
    falls back to the old window_lang.txt; unknown values give the defaults."""
    s = {}
    try:
        with open(settings_path) as f:
            s = json.load(f)
        if not isinstance(s, dict):
            s = {}
    except Exception:
        pass
    lang = s.get("lang")
    if lang not in LANGS:
        lang = _read_lang(lang_path) if lang_path else None
    n = s.get("n_target")
    if n not in [p[0] for p in MESH_PRESETS]:
        n = DEFAULT_N_TARGET
    return {"lang": lang, "n_target": n}


def write_settings(settings_path, lang_path=None, **values):
    try:
        s = read_settings(settings_path, lang_path)
        s.update(values)
        d = os.path.dirname(settings_path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(settings_path, "w") as f:
            json.dump(s, f)
    except Exception:
        pass


def _last_line(text, n=160):
    """Last non-empty line of an error text (the actual message of a traceback)."""
    lines = [ln.strip() for ln in (u"%s" % text).splitlines() if ln.strip()]
    t = lines[-1] if lines else u""
    return t if len(t) <= n else t[:n - 3] + u"..."


def build_form(title, subtitle, sections, notes, image_path=None, lang_path=None, lang=None,
               settings_path=None, n_target=None, recalc=None):
    if settings_path:
        settings = read_settings(settings_path, lang_path)
    else:
        settings = {"lang": lang_path and _read_lang(lang_path), "n_target": DEFAULT_N_TARGET}
    lang = lang or settings["lang"] or "nl"
    preset_values = [p[0] for p in MESH_PRESETS]

    form = Form()
    form.AutoScaleDimensions = SizeF(96.0, 96.0)
    form.AutoScaleMode = AutoScaleMode.Dpi
    form.BackColor = C_BG
    form.FormBorderStyle = FormBorderStyle.FixedSingle
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.ShowInTaskbar = True
    form.StartPosition = FormStartPosition.CenterScreen
    form.TopMost = True
    form.Font = Font("Segoe UI", 9.75)

    def render(lang):
        U = UI[lang]
        dec = U["dec"]
        subtitle, sections, notes = state["subtitle"], state["sections"], state["notes"]
        images = state["images"]
        image = images.get(lang) or images.get("nl") or images.get("en")
        form.SuspendLayout()
        for c in list(form.Controls):
            c.Dispose()
        form.Controls.Clear()
        for tip in state["tooltips"]:
            tip.Dispose()
        state["tooltips"] = []
        form.AutoScroll = False
        form.Text = tr(title, lang) if title else U["title"]
        TW = WIDTH + (IMG_W + PAD if image is not None else 0)

        # Header with NL / EN switch
        header = Panel()
        header.BackColor = C_HEADER
        header.Location = Point(0, 0)
        header.Size = Size(TW, HEADER_H)
        form.Controls.Add(header)
        _label(header, form.Text, PAD, 10, TW - 2 * PAD - 120, 30, 15, FontStyle.Bold, Color.White)
        _label(header, tr(subtitle, lang), PAD, 40, TW - 2 * PAD - 120, 20, 9,
               FontStyle.Regular, C_HEADER_SUB)
        for i, code in enumerate(LANGS):
            rb = RadioButton()
            rb.Text = code.upper()
            rb.Font = Font("Segoe UI", 9.5, FontStyle.Bold)
            rb.ForeColor = Color.White
            rb.BackColor = C_HEADER
            rb.AutoSize = True
            rb.Location = Point(TW - PAD - 110 + i * 56, 24)
            rb.Checked = (code == lang)
            rb.Cursor = Cursors.Hand
            rb.Tag = code
            rb.CheckedChanged += on_lang
            header.Controls.Add(rb)

        # Accuracy (mesh) bar: dropdown + Recalculate + busy/error text
        top = HEADER_H
        if recalc is not None:
            top = build_mesh_bar(U, lang, TW)

        # Table
        y = top + 10
        copy_lines = [form.Text, tr(subtitle, lang), u""]
        for sec_title, rows in sections:
            st = tr(sec_title, lang)
            y += 8
            _label(form, st.upper(), PAD, y, WIDTH - 2 * PAD, 22, 8.5, FontStyle.Bold, C_ACCENT)
            y += 24
            line = Panel()
            line.BackColor = C_LINE
            line.Location = Point(PAD, y - 2)
            line.Size = Size(WIDTH - 2 * PAD, 1)
            form.Controls.Add(line)
            copy_lines.append(st)
            for i, (label, value, unit) in enumerate(rows):
                label = tr(label, lang)
                band = C_BAND if i % 2 == 1 else C_BG
                row = Panel()
                row.BackColor = band
                row.Location = Point(PAD, y)
                row.Size = Size(WIDTH - 2 * PAD, ROW_H)
                form.Controls.Add(row)
                _label(row, label, 8, 0, 200, ROW_H, 9.75, FontStyle.Regular, C_MUTED, back=band)
                if isinstance(value, tuple):
                    text = u"(" + u";  ".join(fmt(v, dec) for v in value) + u")"
                    copy_val = u"\t".join(raw(v) for v in value)
                elif isinstance(value, (basestring, dict)):
                    text = copy_val = tr(value, lang)
                else:
                    text, copy_val = fmt(value, dec), raw(value)
                _label(row, text, 205, 0, COL_VALUE_RIGHT - PAD - 205, ROW_H, 10, FontStyle.Bold,
                       C_TEXT, ContentAlignment.MiddleRight, back=band)
                _label(row, unit, COL_VALUE_RIGHT - PAD + 8, 0, WIDTH - COL_VALUE_RIGHT - PAD, ROW_H,
                       9.75, FontStyle.Regular, C_MUTED, back=band)
                copy_lines.append(u"%s\t%s\t%s" % (label, copy_val, unit))
                y += ROW_H
            copy_lines.append(u"")
            y += 4

        # Notes
        if notes:
            y += 6
            for n in notes:
                n = tr(n, lang)
                _label(form, n, PAD, y, WIDTH - 2 * PAD, 18, 8.5, FontStyle.Regular, C_MUTED)
                y += 18
                copy_lines.append(n)

        # Plot
        if image is not None:
            pic = PictureBox()
            pic.Image = image
            pic.SizeMode = PictureBoxSizeMode.Zoom
            pic.Location = Point(WIDTH, top + 10)
            pic.Size = Size(IMG_W, int(IMG_W * image.Height / float(image.Width)))
            form.Controls.Add(pic)
            y = max(y, pic.Bottom)

        # Footer
        y += 14
        footer = Panel()
        footer.BackColor = C_BAND
        footer.Location = Point(0, y)
        footer.Size = Size(TW, 56)
        form.Controls.Add(footer)
        sep = Panel()
        sep.BackColor = C_LINE
        sep.Location = Point(0, 0)
        sep.Size = Size(TW, 1)
        footer.Controls.Add(sep)
        btn_close = _button(footer, U["close"], TW - PAD - 110, 12, True)
        btn_copy = _button(footer, U["copy"], TW - PAD - 230, 12, False)
        btn_copy.Enabled = not state["busy"]
        status = _label(footer, u"", PAD, 12, 300, 32, 9, FontStyle.Regular, C_MUTED, back=C_BAND)
        chk_img = None
        if image is not None:
            chk_img = CheckBox()
            chk_img.Text = U["copy_img"]
            chk_img.Font = Font("Segoe UI", 9.5)
            chk_img.ForeColor = C_TEXT
            chk_img.BackColor = C_BAND
            chk_img.AutoSize = True
            chk_img.Checked = state.get("copy_img", False)
            chk_img.Location = Point(TW - PAD - 230 - 175, 18)

            def on_chk(sender, e):
                state["copy_img"] = sender.Checked

            chk_img.CheckedChanged += on_chk
            footer.Controls.Add(chk_img)

        copy_text = u"\r\n".join(copy_lines)

        def on_copy(sender, e):
            # AlibreScript runs scripts on an MTA thread; the clipboard needs STA.
            errors = []
            as_image = chk_img is not None and chk_img.Checked

            def worker():
                try:
                    if as_image:
                        Clipboard.SetImage(image)
                    else:
                        Clipboard.SetText(copy_text)
                except Exception as exc:
                    errors.append(exc)

            t = Thread(ThreadStart(worker))
            t.SetApartmentState(ApartmentState.STA)
            t.Start()
            t.Join()
            if errors:
                status.Text = U["copy_fail"] % errors[0]
            else:
                status.Text = U["copied_img"] if as_image else U["copied"]

        def on_close(sender, e):
            form.Close()

        btn_copy.Click += on_copy
        btn_close.Click += on_close
        form.AcceptButton = btn_close
        form.CancelButton = btn_close
        form.ClientSize = Size(TW, y + 56)
        form.UseWaitCursor = state["busy"]
        form.ResumeLayout()
        fit_screen()

    def build_mesh_bar(U, lang, TW):
        """Dropdown with the accuracy presets, Recalculate button and a status
        text (busy / pending / done / error). Returns the bottom y."""
        busy = state["busy"]
        bar = Panel()
        bar.BackColor = C_BAND
        bar.Location = Point(0, HEADER_H)
        form.Controls.Add(bar)
        _label(bar, U["mesh"], PAD, 10, 165, 26, 9.75, FontStyle.Regular, C_TEXT, back=C_BAND)
        cmb = ComboBox()
        cmb.Name = "cmbMesh"
        cmb.DropDownStyle = ComboBoxStyle.DropDownList
        cmb.Font = Font("Segoe UI", 9.75)
        cmb.Location = Point(PAD + 168, 11)
        cmb.Size = Size(190, 26)
        for n, label in MESH_PRESETS:
            cmb.Items.Add(tr(label, lang))
        if state["n_target"] in preset_values:
            cmb.SelectedIndex = preset_values.index(state["n_target"])
        cmb.Enabled = not busy
        bar.Controls.Add(cmb)
        btn = _button(bar, U["recalc"], PAD + 368, 8, False, 150, 30, anchor=False)
        btn.Name = "btnRecalc"
        btn.Enabled = not busy

        # status text next to the button, or on a second row when there is no room
        x, h, ty = PAD + 530, 46, 10
        if TW - PAD - x < 200:
            x, h, ty = PAD, 76, 44
        msg, color = mesh_message(U)
        lbl = _label(bar, msg, x, ty, TW - PAD - x, 26, 9.5,
                     FontStyle.Bold if busy else FontStyle.Regular, color, back=C_BAND)
        lbl.Name = "lblMeshStatus"
        if state["error"]:
            tip = ToolTip()
            tip.SetToolTip(lbl, u"%s" % state["error"])
            state["tooltips"].append(tip)
        bar.Size = Size(TW, h)
        line = Panel()
        line.BackColor = C_LINE
        line.Location = Point(0, h - 1)
        line.Size = Size(TW, 1)
        bar.Controls.Add(line)

        def on_mesh(sender, e):
            i = sender.SelectedIndex
            if i < 0 or state["busy"]:
                return
            state["n_target"] = preset_values[i]
            state["error"] = None
            state["message"] = None
            if settings_path:
                write_settings(settings_path, lang_path, n_target=preset_values[i])
            m, c = mesh_message(UI[state["lang"]])
            lbl.Text = m
            lbl.ForeColor = c

        cmb.SelectedIndexChanged += on_mesh
        btn.Click += on_recalc
        return HEADER_H + h

    def mesh_message(U):
        if state["busy"]:
            return U["busy"], C_ACCENT
        if state["error"]:
            return U["fail"] % _last_line(state["error"]), C_ERROR
        if state["n_used"] is not None and state["n_target"] != state["n_used"]:
            return U["pending"], C_ACCENT
        if state["message"]:
            key, arg = state["message"]
            return U[key] % arg, C_MUTED
        return u"", C_MUTED

    def on_recalc(sender, e):
        if state["busy"]:
            return
        state["busy"] = True
        state["error"] = None
        state["message"] = None
        n = state["n_target"]
        t0 = time.time()

        def worker():
            # Background thread: never touch controls here, and never let an
            # exception escape (an unhandled one would take Alibre down).
            out, err = None, None
            try:
                out = recalc(n) or {}
            except BaseException as exc:
                err = (u"%s" % exc) or exc.__class__.__name__
            try:
                if not form.IsDisposed:
                    form.BeginInvoke(MethodInvoker(lambda: finish(out, err, n, t0)))
            except BaseException:
                pass

        # show the busy state first (render rebuilds the clicked button, so
        # not from inside its own Click event)
        form.BeginInvoke(MethodInvoker(lambda: render(state["lang"])))
        t = Thread(ThreadStart(worker))
        t.IsBackground = True
        t.Start()

    def finish(out, err, n, t0):
        try:
            state["busy"] = False
            if err is not None:
                state["error"] = err
            else:
                for key in ("subtitle", "sections", "notes"):
                    if key in out:
                        state[key] = out[key]
                if "image_path" in out:
                    state["images"] = _load_images(out["image_path"])
                state["n_used"] = out.get("n_target", n)
                state["message"] = ("done", int(round(time.time() - t0)))
            if not form.IsDisposed:
                render(state["lang"])
        except BaseException as exc:
            state["busy"] = False
            state["error"] = u"%s" % exc
            try:
                render(state["lang"])
            except BaseException:
                pass

    def fit_screen():
        if not form.IsHandleCreated:
            return
        wa = Screen.FromControl(form).WorkingArea
        if form.Height > wa.Height:
            form.AutoScroll = True
            form.Height = wa.Height
            form.Width += 18
            form.Top = wa.Top

    def on_lang(sender, e):
        if not sender.Checked or sender.Tag == state["lang"]:
            return
        state["lang"] = sender.Tag
        if settings_path:
            write_settings(settings_path, lang_path, lang=sender.Tag)
        elif lang_path:
            _write_lang(lang_path, sender.Tag)
        # rebuild after this event returns (the radio button itself is disposed)
        form.BeginInvoke(MethodInvoker(lambda: render(state["lang"])))

    def on_shown(sender, e):
        fit_screen()
        form.Activate()
        form.BringToFront()

    state = {"lang": lang, "copy_img": False, "subtitle": subtitle, "sections": sections,
             "notes": notes, "images": _load_images(image_path),
             "n_target": settings["n_target"], "n_used": n_target, "busy": False,
             "error": None, "message": None, "tooltips": []}
    if n_target in preset_values:
        state["n_target"] = n_target   # show what the shown results were computed with
    form.Shown += on_shown
    render(lang)
    return form


def show_results(title, subtitle, sections, notes, snapshot_path=None, image_path=None,
                 lang_path=None, lang=None, settings_path=None, n_target=None, recalc=None):
    form = build_form(title, subtitle, sections, notes, image_path, lang_path, lang,
                      settings_path, n_target, recalc)
    if snapshot_path:
        form.Show()
        bmp = Bitmap(form.Width, form.Height)
        form.DrawToBitmap(bmp, Rectangle(0, 0, bmp.Width, bmp.Height))
        bmp.Save(snapshot_path, ImageFormat.Png)
        form.Close()
        return
    form.ShowDialog()
