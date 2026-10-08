# -*- coding: utf-8 -*-
"""
results_window.py  (IronPython 2.7 / WinForms)

Results window for alibre_section_properties.py. Loaded with execfile() so
edits take effect without restarting Alibre. Entry point:

    show_results(title, subtitle, sections, notes, snapshot_path=None)

sections: [(section_title, [(label, value_or_None, unit), ...]), ...]
notes:    list of short strings shown under the table
snapshot_path: if given, render the window to a PNG instead of showing it
"""
import math

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System.Drawing import Bitmap, Color, ContentAlignment, Font, FontStyle, Point, Rectangle, Size, SizeF
from System.Drawing.Imaging import ImageFormat
from System.Drawing import Image
from System.Globalization import CultureInfo
from System.IO import File, MemoryStream
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import (AnchorStyles, AutoScaleMode, Button, Clipboard, Cursors,
                                  FlatStyle, Form, FormBorderStyle, PictureBox,
                                  PictureBoxSizeMode, Screen, CheckBox,
                                  FormStartPosition, Label, Panel)

DEC = CultureInfo.CurrentCulture.NumberFormat.NumberDecimalSeparator

C_HEADER = Color.FromArgb(32, 41, 54)
C_HEADER_SUB = Color.FromArgb(170, 182, 196)
C_ACCENT = Color.FromArgb(0, 120, 212)
C_TEXT = Color.FromArgb(30, 30, 30)
C_MUTED = Color.FromArgb(105, 112, 120)
C_LINE = Color.FromArgb(225, 229, 234)
C_BAND = Color.FromArgb(247, 249, 251)
C_BG = Color.White

SUP = {"-": u"⁻", "0": u"⁰", "1": u"¹", "2": u"²", "3": u"³",
       "4": u"⁴", "5": u"⁵", "6": u"⁶", "7": u"⁷", "8": u"⁸",
       "9": u"⁹"}

WIDTH = 560             # table column
IMG_W = 520             # plot column (PNG is 520 x 660 px)
PAD = 22
COL_VALUE_RIGHT = 440   # right edge of the value column
ROW_H = 22


def fmt(v):
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
            ip = u" ".join(groups)
        return sign + ip + (DEC + fp if fp else u"")
    e = int(math.floor(math.log10(a)))
    m = v / 10.0 ** e
    ms = ("%.4f" % m).rstrip("0").rstrip(".").replace(".", DEC)
    return u"%s × 10%s" % (ms, u"".join(SUP[c] for c in str(e)))


def raw(v):
    return u"" if v is None else ("%.10g" % v).replace(".", DEC)


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


def _button(parent, text, x, y, primary):
    b = Button()
    b.Text = text
    b.Location = Point(x, y)
    b.Size = Size(110, 32)
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
    b.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
    parent.Controls.Add(b)
    return b


def build_form(title, subtitle, sections, notes, image_path=None):
    form = Form()
    form.AutoScaleDimensions = SizeF(96.0, 96.0)
    form.AutoScaleMode = AutoScaleMode.Dpi
    form.Text = title
    form.BackColor = C_BG
    form.FormBorderStyle = FormBorderStyle.FixedSingle
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.ShowInTaskbar = True
    form.StartPosition = FormStartPosition.CenterScreen
    form.TopMost = True
    form.Font = Font("Segoe UI", 9.75)

    image = None
    if image_path:
        try:
            # load via a stream so the PNG file is not locked for the next run
            image = Image.FromStream(MemoryStream(File.ReadAllBytes(image_path)))
        except Exception:
            image = None
    TW = WIDTH + (IMG_W + PAD if image is not None else 0)

    # Header
    header = Panel()
    header.BackColor = C_HEADER
    header.Location = Point(0, 0)
    header.Size = Size(TW, 70)
    form.Controls.Add(header)
    _label(header, title, PAD, 10, TW - 2 * PAD, 30, 15, FontStyle.Bold, Color.White)
    _label(header, subtitle, PAD, 40, TW - 2 * PAD, 20, 9, FontStyle.Regular, C_HEADER_SUB)

    # Body
    y = 70 + 10
    copy_lines = [title, subtitle, u""]
    for sec_title, rows in sections:
        y += 8
        _label(form, sec_title.upper(), PAD, y, WIDTH - 2 * PAD, 22, 8.5, FontStyle.Bold, C_ACCENT)
        y += 24
        line = Panel()
        line.BackColor = C_LINE
        line.Location = Point(PAD, y - 2)
        line.Size = Size(WIDTH - 2 * PAD, 1)
        form.Controls.Add(line)
        copy_lines.append(sec_title)
        for i, (label, value, unit) in enumerate(rows):
            band = C_BAND if i % 2 == 1 else C_BG
            row = Panel()
            row.BackColor = band
            row.Location = Point(PAD, y)
            row.Size = Size(WIDTH - 2 * PAD, ROW_H)
            form.Controls.Add(row)
            _label(row, label, 8, 0, 200, ROW_H, 9.75, FontStyle.Regular, C_MUTED, back=band)
            if isinstance(value, tuple):
                text = u"(" + u";  ".join(fmt(v) for v in value) + u")"
                copy_val = u"\t".join(raw(v) for v in value)
            elif isinstance(value, basestring):
                text, copy_val = value, value
            else:
                text, copy_val = fmt(value), raw(value)
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
            _label(form, n, PAD, y, WIDTH - 2 * PAD, 18, 8.5, FontStyle.Regular, C_MUTED)
            y += 18
            copy_lines.append(n)

    if image is not None:
        pic = PictureBox()
        pic.Image = image
        pic.SizeMode = PictureBoxSizeMode.Zoom
        pic.Location = Point(WIDTH, 80)
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
    btn_close = _button(footer, u"Sluiten", TW - PAD - 110, 12, True)
    btn_copy = _button(footer, u"Kopiëren", TW - PAD - 230, 12, False)
    status = _label(footer, u"", PAD, 12, 250, 32, 9, FontStyle.Regular, C_MUTED, back=C_BAND)
    chk_img = None
    if image is not None:
        chk_img = CheckBox()
        chk_img.Text = u"Afbeelding kopi\u00ebren"
        chk_img.Font = Font("Segoe UI", 9.5)
        chk_img.ForeColor = C_TEXT
        chk_img.BackColor = C_BAND
        chk_img.AutoSize = True
        chk_img.Location = Point(TW - PAD - 230 - 175, 18)
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
            status.Text = u"Kopiëren mislukt: %s" % errors[0]
        else:
            status.Text = (u"Afbeelding gekopieerd" if as_image
                           else u"Gegevens gekopieerd (plakbaar in Excel)")

    def on_close(sender, e):
        form.Close()

    btn_copy.Click += on_copy
    btn_close.Click += on_close
    form.AcceptButton = btn_close
    form.CancelButton = btn_close

    def on_shown(sender, e):
        wa = Screen.FromControl(form).WorkingArea
        if form.Height > wa.Height:
            form.AutoScroll = True
            form.Height = wa.Height
            form.Width += 18
            form.Top = wa.Top
        form.Activate()
        form.BringToFront()

    form.Shown += on_shown
    form.ClientSize = Size(TW, y + 56)
    return form


def show_results(title, subtitle, sections, notes, snapshot_path=None, image_path=None):
    form = build_form(title, subtitle, sections, notes, image_path)
    if snapshot_path:
        form.Show()
        bmp = Bitmap(form.Width, form.Height)
        form.DrawToBitmap(bmp, Rectangle(0, 0, bmp.Width, bmp.Height))
        bmp.Save(snapshot_path, ImageFormat.Png)
        form.Close()
        return
    form.ShowDialog()
