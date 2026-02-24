"""Graph and channel-reference UI components.

Contains channel/history plot widgets, custom axis items,
and the vector-drawn 5 GHz allocation dialog.
"""

from .core import *
from .theme import (
    BAND_SUBBAND_HEADERS,
    UNII6_CHAN_COLORS,
    UNII_CHAN_COLORS,
    UNII_NAME_COLORS,
)


def _channel_shape_unit(xs: np.ndarray, fc: float, bw: float) -> np.ndarray:
    """
    Returns a 0..1 flat-top shape with cosine rolloff shoulders.
    Multiply by (amplitude - floor) and shift by floor for dBm display.
    """
    half = bw / 2.0
    shoulder = max(half * 0.12, 5.0)  # 12 % of half-BW, min 5 MHz
    d = np.abs(xs - fc)
    in_flat = d <= (half - shoulder)
    in_roll = (~in_flat) & (d <= half)
    t = np.where(in_roll, (d - (half - shoulder)) / shoulder, 0.0)
    return np.where(
        in_flat, 1.0, np.where(in_roll, 0.5 * (1.0 + np.cos(np.pi * t)), 0.0)
    )


# ─── Color-coded dBm axis ────────────────────────────────────────────────────
class DbmAxisItem(pg.AxisItem):
    """
    Y-axis whose tick labels are colour-coded by signal-quality zone:
      green  ≥ -50 dBm  (excellent)
      lime   -50 … -60  (good)
      amber  -60 … -70  (fair)
      orange -70 … -80  (weak)
      red    < -80       (poor)
    """

    _BANDS = [
        (-50, 0, "#4caf50"),  # excellent — green
        (-60, -50, "#8bc34a"),  # good      — lime
        (-70, -60, "#ffc107"),  # fair      — amber
        (-80, -70, "#ff9800"),  # weak      — orange
        (-200, -80, "#f44336"),  # poor      — red
    ]

    def _dbm_color(self, text: str):
        try:
            v = float(text)
        except ValueError:
            pass
        else:
            for lo, hi, hex_c in self._BANDS:
                if lo <= v < hi:
                    return pg.mkColor(hex_c)
        is_dark = (
            QApplication.instance()
            .palette()
            .color(QPalette.ColorRole.Window)
            .lightness()
            < 128
        )
        return pg.mkColor("#8a96b0" if is_dark else "#445566")

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs):
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, False)
        p.setRenderHint(p.RenderHint.TextAntialiasing, True)
        pen, p1, p2 = axisSpec
        p.setPen(pen)
        p.drawLine(p1, p2)
        for pen, p1, p2 in tickSpecs:
            p.setPen(pen)
            p.drawLine(p1, p2)
        if self.style.get("tickFont") is not None:
            p.setFont(self.style["tickFont"])
        for rect, flags, text in textSpecs:
            p.setPen(self._dbm_color(text))
            p.drawText(rect, int(flags), text)
        p.restore()


_UNII_CHAN_COLORS = UNII_CHAN_COLORS
_UNII_NAME_COLORS = UNII_NAME_COLORS
_UNII6_CHAN_COLORS = UNII6_CHAN_COLORS
_BAND_SUBBAND_HEADERS = BAND_SUBBAND_HEADERS


class FiveGhzBottomAxisItem(pg.AxisItem):
    """X-axis for the 5 GHz panel — tick labels colour-coded by U-NII sub-band."""

    _CHAN_COLORS = _UNII_CHAN_COLORS
    _DRAW_DFS_SEGMENT = True
    _DFS_FREQ_RANGE = (5260.0, 5720.0)  # ch52 .. ch144 centers

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs):
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, False)
        p.setRenderHint(p.RenderHint.TextAntialiasing, True)
        pen, p1, p2 = axisSpec
        base_pen = pen
        if base_pen is None:
            c = QColor("#8a96b0")
            c.setAlpha(140)
            base_pen = pg.mkPen(c, width=1)
        p.setPen(base_pen)
        p.drawLine(p1, p2)
        if self._DRAW_DFS_SEGMENT and self.orientation == "bottom":
            dfs_lo, dfs_hi = self._DFS_FREQ_RANGE
            v1 = self.mapFromView(QPointF(dfs_lo, 0.0))
            v2 = self.mapFromView(QPointF(dfs_hi, 0.0))
            x_min = min(p1.x(), p2.x())
            x_max = max(p1.x(), p2.x())
            dfs_x1 = max(min(v1.x(), v2.x()), x_min)
            dfs_x2 = min(max(v1.x(), v2.x()), x_max)
            if dfs_x2 > dfs_x1:
                dfs_pen = QColor("#64b5f6")
                dfs_pen.setAlpha(255)
                p.setPen(pg.mkPen(dfs_pen, width=2))
                p.drawLine(QPointF(dfs_x1, p1.y()), QPointF(dfs_x2, p2.y()))
        for pen, p1, p2 in tickSpecs:
            p.setPen(pen)
            p.drawLine(p1, p2)
        if self.style.get("tickFont") is not None:
            p.setFont(self.style["tickFont"])
        default_pen = self.style.get("pen") or pg.mkPen("#8a96b0")
        for rect, flags, text in textSpecs:
            clean_text = text.strip()
            try:
                ch = int(clean_text)
                hex_c = self._CHAN_COLORS.get(ch)
            except ValueError:
                hex_c = _UNII_NAME_COLORS.get(clean_text)
            p.setPen(pg.mkPen(hex_c) if hex_c else default_pen)
            p.drawText(rect, int(flags), text)
        p.restore()


class SixGhzBottomAxisItem(FiveGhzBottomAxisItem):
    """X-axis for the 6 GHz panel — tick labels colour-coded by U-NII sub-band."""

    _CHAN_COLORS = _UNII6_CHAN_COLORS
    _DRAW_DFS_SEGMENT = False


# ─── Clickable label for channel graph ───────────────────────────────────────
class _ClickableLabel(pg.TextItem):
    """TextItem that fires a callback with the AP bssid when clicked."""

    def __init__(self, bssid: str, on_click, **kwargs):
        super().__init__(**kwargs)
        self._bssid = bssid
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._on_click(self._bssid)
            ev.accept()


class ChannelGraphWidget(QWidget):
    """Multi-panel channel view — one panel per WiFi band, dead spectrum removed."""

    ap_highlighted = pyqtSignal(object)  # str | None

    _BANDS_ORDER: List[str] = ["2.4 GHz", "5 GHz", "6 GHz"]
    _BAND_EXTENTS: Dict[str, Tuple[int, int]] = {
        "2.4 GHz": (2385, 2500),
        "5 GHz": (5080, 5920),
        # 6 GHz: band edges 5925–7125 MHz; ch1 center=5955, ch233 center=7115
        "6 GHz": (5930, 7130),
    }
    _BAND_TICKS: Dict[str, dict] = {
        "2.4 GHz": CH24,
        "5 GHz": CH5,
        "6 GHz": CH6,
    }
    # Visual panel width weights — proportional to MHz span
    # 2.4 GHz ~115 MHz, 5 GHz ~840 MHz, 6 GHz ~1200 MHz
    _BAND_STRETCH: Dict[str, int] = {
        "2.4 GHz": 2,
        "5 GHz": 5,
        "6 GHz": 8,  # wider: 1200 MHz span vs 840 for 5 GHz
    }
    # Tick stride per band — subsample dense channel grids for readability
    _BAND_TICK_STRIDE: Dict[str, int] = {
        "2.4 GHz": 1,  # 14 channels → show all
        "5 GHz": 1,  # ~36 channels → show all
        "6 GHz": 1,  # ch 1,5,9,…,233 (all 20 MHz primaries)
    }
    # For 6 GHz: show the 80/160/320 MHz anchor channels used by Wi-Fi 6E/7 APs
    # These are the standard 6 GHz preferred scanning channels (PSC) for 20 MHz:
    # every 4th primary, i.e. ch 5, 21, 37, 53, 69, 85, 101, 117, 133, 149, 165,
    # 181, 197, 213, 229 — plus ch 1 and 233 as band-edge anchors.
    _6GHZ_TICK_CHANS: List[int] = [
        1,
        5,
        21,
        37,
        53,
        69,
        85,
        101,
        117,
        133,
        149,
        165,
        181,
        197,
        213,
        229,
        233,
    ]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._panels_widget = QWidget()
        self._panels_layout = QHBoxLayout(self._panels_widget)
        self._panels_layout.setContentsMargins(0, 0, 0, 0)
        self._panels_layout.setSpacing(2)
        outer.addWidget(self._panels_widget)

        # band → PlotWidget (rebuilt whenever active band set changes)
        self._plots: Dict[str, PlotWidget] = {}
        self._active_bands: List[str] = []
        # bssid → {color, zero, fill, curve, label}
        self._items: Dict[str, dict] = {}
        self._aps: List[AccessPoint] = []
        self._ssid_colors: Dict[str, QColor] = {}
        self._band = "All"
        self._highlighted: Optional[str] = None
        self._theme_bg = "#0d1117"
        self._theme_fg = "#a9b4cc"
        self._band_channels: Dict[str, Dict[float, int]] = {}  # band → {freq_mhz: chan}
        self._view_ranges: Dict[
            str, Tuple[Tuple[float, float], Tuple[float, float]]
        ] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def set_theme(self, bg: str, fg: str):
        self._theme_bg = bg
        self._theme_fg = fg
        for i, (band, pw) in enumerate(self._plots.items()):
            pw.setBackground(bg)
            if i == 0:
                pw.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
            for ax in ("left", "bottom"):
                pw.getAxis(ax).setTextPen(fg)
                pw.getAxis(ax).setPen(fg)
        # Redraw so band-label TextItems inside the plot pick up the new fg
        self._redraw()

    def set_band(self, band: str):
        self._band = band
        self._redraw()

    def set_ssid_colors(self, colors: Dict[str, QColor]):
        self._ssid_colors = colors

    def update_aps(self, aps: List[AccessPoint], colors: Dict[str, QColor]):
        self._aps = aps
        self._ssid_colors = colors
        self._redraw()

    def highlight_bssid(self, bssid: Optional[str]):
        self._highlighted = bssid
        self._apply_highlight()

    # ── Internal ──────────────────────────────────────────────────────────

    def _make_plot(self, band: str, is_leftmost: bool) -> "PlotWidget":
        axis_items: dict = {}
        if is_leftmost:
            axis_items["left"] = DbmAxisItem(orientation="left")
        if band == "5 GHz":
            axis_items["bottom"] = FiveGhzBottomAxisItem(orientation="bottom")
        elif band == "6 GHz":
            axis_items["bottom"] = SixGhzBottomAxisItem(orientation="bottom")
        pw = PlotWidget(axisItems=axis_items)
        pw.setBackground(self._theme_bg)
        pw.showGrid(x=True, y=True, alpha=0.18)
        fg = self._theme_fg
        if is_leftmost:
            pw.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
        else:
            # Keep axis present (needed for y-grid lines) but invisible.
            # setWidth must be ≥1 — width=0 gives a zero bounding rect and
            # Qt skips painting the item entirely, suppressing grid lines.
            ax = pw.getAxis("left")
            ax.setWidth(1)
            ax.setStyle(showValues=False, tickLength=0)
            grid_pen = QColor(self._theme_fg)
            grid_pen.setAlpha(80)
            ax.setPen(pg.mkPen(grid_pen))
        # Bottom axis: two text rows (channels + sub-band labels)
        bottom_ax = pw.getAxis("bottom")
        bottom_ax.setTextPen(fg)
        axis_line_c = QColor(fg)
        axis_line_c.setAlpha(140)
        bottom_ax.setPen(pg.mkPen(axis_line_c, width=1))
        bottom_ax.setHeight(56)
        pw.setMenuEnabled(False)
        pw.getViewBox().setMouseEnabled(x=True, y=False)
        pw.scene().sigMouseClicked.connect(self._on_bg_click)
        pw.scene().sigMouseMoved.connect(
            lambda pos, b=band, p=pw: self._on_mouse_hover(b, p, pos)
        )
        return pw

    def _rebuild_panels(self, bands: List[str]):
        for pw in self._plots.values():
            self._panels_layout.removeWidget(pw)
            pw.setParent(None)
            pw.deleteLater()
        self._plots.clear()

        for i, band in enumerate(bands):
            pw = self._make_plot(band, i == 0)
            self._panels_layout.addWidget(pw, self._BAND_STRETCH.get(band, 3))
            self._plots[band] = pw

        self._active_bands = list(bands)

    # ── Sub-band header strips ────────────────────────────────────────────────

    def _draw_band_overlays(
        self, band: str, pw: "PlotWidget", xmin: float, xmax: float
    ):
        """Band name label in the top-right corner."""
        floor = float(CHAN_DBM_FLOOR)

        # 5 GHz DFS highlight (ch52..144): draw directly on the plot floor so it
        # is visible in the canvas, not only in the axis widget area.
        if band == "5 GHz":
            dfs_lo = max(5260.0, xmin)
            dfs_hi = min(5720.0, xmax)
            if dfs_hi > dfs_lo:
                dfs_color = QColor("#a952bd")
                dfs_color.setAlpha(235)
                dfs_line = pg.PlotCurveItem(
                    [dfs_lo, dfs_hi],
                    [floor + 0.15, floor + 0.15],
                    pen=pg.mkPen(dfs_color, width=2),
                )
                dfs_line.setZValue(20)
                pw.addItem(dfs_line)

                # Small label to explain the highlighted DFS range.
                dfs_lbl_color = QColor(dfs_color)
                dfs_lbl_color.setAlpha(240)
                dfs_lbl = pg.TextItem(
                    text="DFS (52–144)",
                    anchor=(0.5, 1.0),
                    color=dfs_lbl_color,
                )
                dfs_font = QFont()
                dfs_font.setPointSize(7)
                dfs_font.setBold(True)
                dfs_lbl.setFont(dfs_font)
                dfs_lbl.setPos((dfs_lo + dfs_hi) / 2.0, floor + 0.1)
                dfs_lbl.setZValue(21)
                pw.addItem(dfs_lbl)

        # -- band name label, just inside top-right corner --
        band_color = QColor(self._theme_fg)
        band_color.setAlpha(180)
        band_lbl = pg.TextItem(text=band, anchor=(1.0, 0.0), color=band_color)
        bfont = QFont()
        bfont.setPointSize(8)
        bfont.setBold(True)
        band_lbl.setFont(bfont)
        # anchor (1.0, 0.0) pins top-right of text to this point → text hangs downward
        band_lbl.setPos(xmax, float(CHAN_DBM_CEIL) - 1.0)
        band_lbl.setZValue(5)
        pw.addItem(band_lbl)

    def _on_label_click(self, bssid: str):
        self._highlighted = None if self._highlighted == bssid else bssid
        self._apply_highlight()
        self.ap_highlighted.emit(self._highlighted)

    def _on_bg_click(self, ev):
        if ev.isAccepted():
            return
        if self._highlighted is not None:
            self._highlighted = None
            self._apply_highlight()
            self.ap_highlighted.emit(None)

    def _apply_highlight(self):
        h = self._highlighted
        for bssid, items in self._items.items():
            if h is None or bssid == h:
                alpha_curve, alpha_fill, alpha_label = 255, 55, 255
            else:
                alpha_curve, alpha_fill, alpha_label = 28, 12, 40
            color: QColor = items["color"]
            c = QColor(color)
            c.setAlpha(alpha_curve)
            items["curve"].setPen(mkPen(color=c, width=2))
            fc = QColor(color)
            fc.setAlpha(alpha_fill)
            items["fill"].setBrush(mkBrush(fc))
            items["label"].setColor(
                QColor(color.red(), color.green(), color.blue(), alpha_label)
            )

    def _on_mouse_hover(self, band: str, pw: "PlotWidget", pos) -> None:
        if not pw.sceneBoundingRect().contains(pos):
            QToolTip.hideText()
            return
        view_pos = pw.plotItem.vb.mapSceneToView(pos)
        freq = view_pos.x()
        channels = self._band_channels.get(band, {})
        if not channels:
            return
        nearest_f = min(channels, key=lambda f: abs(f - freq))
        if abs(nearest_f - freq) < 25:
            QToolTip.showText(
                QCursor.pos(),
                f"Channel {channels[nearest_f]}  ·  {int(nearest_f)} MHz",
                pw,
            )
        else:
            QToolTip.hideText()

    def _needed_bands(self, visible: List[AccessPoint]) -> List[str]:
        if self._band != "All":
            return [self._band] if self._band in self._BAND_EXTENTS else []
        present = {a.band for a in visible if a.band in self._BAND_EXTENTS}
        return [b for b in self._BANDS_ORDER if b in present]

    def _redraw(self):
        self._items = {}
        visible = [a for a in self._aps if self._band == "All" or a.band == self._band]
        needed = self._needed_bands(visible)

        # Capture current per-band view ranges before any clear/rebuild so zoom/pan
        # persists across refreshes.
        for band, pw in self._plots.items():
            try:
                xr, yr = pw.getViewBox().viewRange()
                self._view_ranges[band] = (
                    (float(xr[0]), float(xr[1])),
                    (float(yr[0]), float(yr[1])),
                )
            except Exception:
                pass

        if needed != self._active_bands:
            self._rebuild_panels(needed)

        for pw in self._plots.values():
            pw.clear()

        # If no bands are needed at all (unknown band selected) bail out.
        # Do NOT bail when visible is empty — we still need correct axes.
        if not needed:
            return

        floor = CHAN_DBM_FLOOR
        y_ticks = [(v, str(v)) for v in range(floor, CHAN_DBM_CEIL + 1, 10)]

        for band, pw in self._plots.items():
            band_aps = [a for a in visible if a.band == band]
            xmin, xmax = self._BAND_EXTENTS[band]
            xs = np.linspace(xmin, xmax, 2000)
            floor_ys = np.full_like(xs, float(floor))
            tick_src = self._BAND_TICKS[band]

            for ap in band_aps:
                color = self._ssid_colors.get(ap.ssid, QColor("#888888"))
                # Use the bonded-block center for 5 GHz (not just primary channel)
                draw_center = get_ap_draw_center(ap)
                unit = _channel_shape_unit(xs, draw_center, max(ap.bandwidth_mhz, 20))
                active = unit > 1e-6
                if not np.any(active):
                    continue
                xs_act = xs[active]
                unit_act = unit[active]
                ys = floor + (ap.dbm - floor) * unit
                ys_act = floor + (ap.dbm - floor) * unit_act
                floor_ys_act = np.full_like(xs_act, float(floor))

                bc = QColor(color)
                bc.setAlpha(55)
                zero_item = pg.PlotCurveItem(xs_act, floor_ys_act, pen=pg.mkPen(None))
                curve_item = pg.PlotCurveItem(
                    xs_act, ys_act, pen=mkPen(color=color, width=2)
                )
                fill_item = pg.FillBetweenItem(zero_item, curve_item, brush=mkBrush(bc))
                pw.addItem(zero_item)
                pw.addItem(fill_item)
                pw.addItem(curve_item)

                label = _ClickableLabel(
                    bssid=ap.bssid,
                    on_click=self._on_label_click,
                    text=ap.display_ssid,
                    color=color,
                    anchor=(0.5, 1.1),
                )
                lf = QFont()
                lf.setPointSize(8)
                lf.setBold(True)
                label.setFont(lf)
                label.setPos(draw_center, ap.dbm)
                pw.addItem(label)

                self._items[ap.bssid] = {
                    "color": color,
                    "zero": zero_item,
                    "fill": fill_item,
                    "curve": curve_item,
                    "label": label,
                }

            pw.getAxis("left").setTicks([y_ticks])
            self._band_channels[band] = {
                float(f): c for c, f in tick_src.items() if xmin <= f <= xmax
            }
            # Build channel ticks
            stride = self._BAND_TICK_STRIDE.get(band, 1)
            sorted_chan = sorted(tick_src.items(), key=lambda x: x[1])
            ticks = [
                (f, str(c))
                for i, (c, f) in enumerate(sorted_chan)
                if xmin <= f <= xmax and i % stride == 0
            ]
            if ticks:
                subband_ticks = [
                    (((x0 + x1) / 2.0), "\n" + lbl)
                    for x0, x1, _c, lbl in _BAND_SUBBAND_HEADERS.get(band, [])
                    if xmin <= ((x0 + x1) / 2.0) <= xmax
                ]
                mixed_ticks = sorted(ticks + subband_ticks, key=lambda t: t[0])
                pw.getAxis("bottom").setTicks([mixed_ticks])

            # ── Band-specific spectrum annotations ─────────────────────────
            self._draw_band_overlays(band, pw, xmin, xmax)

            # Restore last user zoom/pan if available, otherwise use defaults.
            vr = self._view_ranges.get(band)
            if vr:
                (x0, x1), (y0, y1) = vr
                pw.setXRange(x0, x1, padding=0.0)
                pw.setYRange(y0, y1, padding=0.0)
            else:
                pw.setXRange(xmin, xmax, padding=0.01)
                pw.setYRange(floor, CHAN_DBM_CEIL, padding=0.0)

        self._apply_highlight()


# ─────────────────────────────────────────────────────────────────────────────
# Signal History Graph
# ─────────────────────────────────────────────────────────────────────────────


class SignalHistoryWidget(QWidget):
    """Time-series plot of signal strength per BSSID."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        layout.addWidget(self._splitter)

        self._ssid_list = QListWidget()
        self._ssid_list.setMinimumWidth(300)
        self._ssid_list.setMaximumWidth(420)
        self._ssid_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._ssid_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ssid_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._splitter.addWidget(self._ssid_list)

        self._plot = PlotWidget(axisItems={"left": DbmAxisItem(orientation="left")})
        self._plot.setBackground("#0d1117")
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "Signal (dBm)", color="#8a96b0", size="10pt")
        self._plot.setLabel("bottom", "Time (s ago)", color="#8a96b0", size="10pt")
        self._plot.getAxis("bottom").setTextPen("#8a96b0")
        self._plot.setMenuEnabled(True)
        self._plot.getViewBox().setMouseEnabled(x=True, y=True)
        self._plot.setYRange(CHAN_DBM_FLOOR, CHAN_DBM_CEIL, padding=0.02)
        self._plot.setXRange(-HISTORY_SECONDS, 0, padding=0.0)
        y_ticks = [(v, str(v)) for v in range(CHAN_DBM_FLOOR, CHAN_DBM_CEIL + 1, 10)]
        self._plot.getAxis("left").setTicks([y_ticks])
        self._splitter.addWidget(self._plot)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([320, 1200])
        self._plot.scene().sigMouseMoved.connect(self._on_mouse_hover)

        self._history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=HISTORY_SECONDS)
        )
        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._curve_data: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        self._ssid_colors: Dict[str, QColor] = {}
        self._ssid_map: Dict[str, str] = {}  # bssid → ssid
        self._t0 = time.time()
        self._filter_bssids: Optional[set] = None  # None = show all

    def set_theme(self, bg: str, fg: str):
        self._plot.setBackground(bg)
        self._plot.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
        self._plot.setLabel("bottom", "Time (s ago)", color=fg, size="10pt")
        for _ax in ("left", "bottom"):
            self._plot.getAxis(_ax).setTextPen(fg)
            self._plot.getAxis(_ax).setPen(fg)
        self._ssid_list.setStyleSheet(
            f"QListWidget {{ border: none; background: {bg}; color: {fg}; font-size: 10pt; }}"
            f"QListWidget::item {{ padding: 2px 4px; }}"
        )

    def set_ssid_colors(self, colors: Dict[str, QColor]):
        self._ssid_colors = colors

    def filter_bssids(self, bssids: Optional[set]):
        self._filter_bssids = bssids

    def push(self, aps: List[AccessPoint]):
        now = time.time()
        elapsed = now - self._t0
        for ap in aps:
            self._ssid_map[ap.bssid] = ap.display_ssid
            self._history[ap.bssid].append((elapsed, ap.dbm))  # store dBm
        self._redraw(elapsed)

    def _redraw(self, now_t: float):
        visible_bssids = set(self._history.keys())
        if self._filter_bssids is not None:
            visible_bssids &= self._filter_bssids

        # Remove stale curves
        for bssid in list(self._curves.keys()):
            if bssid not in visible_bssids:
                self._plot.removeItem(self._curves.pop(bssid))
                self._curve_data.pop(bssid, None)

        # Left legend/list (outside plot area)
        self._ssid_list.clear()
        sorted_bssids = sorted(
            visible_bssids,
            key=lambda b: (self._ssid_map.get(b, b).lower(), b),
        )
        for bssid in sorted_bssids:
            ssid = self._ssid_map.get(bssid, bssid)
            item = QListWidgetItem(f"{ssid} ({bssid[-5:]})")
            item.setToolTip(bssid)
            color = self._ssid_colors.get(ssid, QColor("#888888"))
            item.setForeground(QBrush(color))
            self._ssid_list.addItem(item)

        for bssid in visible_bssids:
            pts = list(self._history[bssid])
            if len(pts) < 2:
                continue
            ts = np.array([now_t - p[0] for p in pts])  # seconds ago (positive = older)
            ss = np.array([p[1] for p in pts])
            # Flip so most recent is on the right
            ts = -ts  # negative = past

            ssid = self._ssid_map.get(bssid, bssid)
            color = self._ssid_colors.get(ssid, QColor("#888888"))

            if bssid not in self._curves:
                pen = mkPen(color=color, width=2)
                curve = self._plot.plot(ts, ss, pen=pen)
                self._curves[bssid] = curve
            else:
                self._curves[bssid].setData(ts, ss)

            self._curve_data[bssid] = (ts, ss)

        self._plot.setXRange(-HISTORY_SECONDS, 0, padding=0.0)

    def _on_mouse_hover(self, pos) -> None:
        if not self._plot.sceneBoundingRect().contains(pos):
            QToolTip.hideText()
            return

        if not self._curve_data:
            QToolTip.hideText()
            return

        view_pos = self._plot.plotItem.vb.mapSceneToView(pos)
        x = float(view_pos.x())
        y = float(view_pos.y())

        best_bssid: Optional[str] = None
        best_dist = float("inf")
        best_y = None

        for bssid, (xs, ys) in self._curve_data.items():
            if len(xs) == 0:
                continue
            idx = int(np.argmin(np.abs(xs - x)))
            yv = float(ys[idx])
            dist = abs(yv - y)
            if dist < best_dist:
                best_dist = dist
                best_bssid = bssid
                best_y = yv

        if best_bssid is None or best_dist > 3.0:
            QToolTip.hideText()
            return

        ssid = self._ssid_map.get(best_bssid, best_bssid)
        QToolTip.showText(
            QCursor.pos(),
            f"{ssid}\n{best_bssid}\nSignal: {int(round(best_y))} dBm",
            self._plot,
        )


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Shared table-drawing infrastructure
# ─────────────────────────────────────────────────────────────────────────────


class _ChannelTableWidget(QWidget):
    """Zoomable, scrollable channel-allocation table rendered with QPainter.

    Subclasses define:
        _TITLE       str
        _SUBTITLE    str
        _COLS        List[Optional[int]]   — channel numbers, None = visual gap
        _UNII_BANDS  List[Tuple[str,str,List[int]]]
                     (band_label, hex_fill, [channel, …])
        _BW_ROWS     List[Tuple[str,str,List[Tuple[str,List[int]]]]]
                     (row_label, qty_str, [(cell_label, [channels…]), …])
        _EXTRA_ROWS  List[Tuple[str,float,List[Tuple[int,int,str,str]]]]
                     (row_label, row_height_px,
                      [(ch_start, ch_end, hex_fill, text), …])
    and override:
        _ch_freq(ch) -> int
    """

    _ZOOM_MIN = 0.25
    _ZOOM_MAX = 4.0
    _ZOOM_STEP = 1.15

    _TITLE = ""
    _SUBTITLE = ""
    _COLS: List = []
    _UNII_BANDS: List = []
    _BW_ROWS: List = []
    _EXTRA_ROWS: List = []
    # Channels in this set exist in _COLS for geometry purposes but are
    # rendered as invisible overflow slots (no label, no band colour).
    _PHANTOM_COLS: frozenset = frozenset()

    # Base dimensions at zoom = 1 (px)
    _BASE_LEFT_W = 132.0
    _BASE_COL_W = 28.0
    _BASE_GAP_W = 12.0
    _BASE_BAND_H = 28.0
    _BASE_FREQ_H = 54.0
    _BASE_BW_H = 28.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom = 1.0
        self._ch_idx: Dict[int, int] = {
            ch: i for i, ch in enumerate(self._COLS) if ch is not None
        }
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self._refresh_size()

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = ev.angleDelta().y()
            f = self._ZOOM_STEP if dy > 0 else 1.0 / self._ZOOM_STEP
            self._zoom = max(self._ZOOM_MIN, min(self._ZOOM_MAX, self._zoom * f))
            self._refresh_size()
            self.update()
            ev.accept()
        else:
            super().wheelEvent(ev)

    def sizeHint(self):
        w, h = self._content_size()
        return QSize(w, h)

    def _refresh_size(self):
        w, h = self._content_size()
        # Keep natural width as minimum so Ctrl+scroll zoom still triggers
        # horizontal scrollbars.  The parent QScrollArea (widgetResizable=True)
        # will expand the widget beyond this minimum when the viewport is wider,
        # and paintEvent stretches columns to fill whatever width we actually get.
        self.setMinimumSize(w, h)
        self.updateGeometry()

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _z(self, v: float) -> float:
        return v * self._zoom

    def _content_size(self) -> Tuple[int, int]:
        z = self._zoom
        cw = self._BASE_COL_W * z
        gw = self._BASE_GAP_W * z
        lw = self._BASE_LEFT_W * z
        tcw = sum(gw if c is None else cw for c in self._COLS)
        H = int(
            self._z(38)
            + self._z(self._BASE_BAND_H)
            + self._z(self._BASE_FREQ_H)
            + len(self._BW_ROWS) * self._z(self._BASE_BW_H)
            + sum(self._z(row[1]) for row in self._EXTRA_ROWS)
            + 4
        )
        return int(lw + tcw + 2), H

    def _col_xs(self) -> Tuple[List[float], List[float], float]:
        """Return (xs, widths, total_w) for all column slots."""
        cw = self._z(self._BASE_COL_W)
        gw = self._z(self._BASE_GAP_W)
        xs, ws = [], []
        x = 0.0
        for c in self._COLS:
            w = gw if c is None else cw
            xs.append(x)
            ws.append(w)
            x += w
        return xs, ws, x

    def _group_rect(
        self,
        chans: List[int],
        xs: List[float],
        ws: List[float],
        row_y: float,
        row_h: float,
        pad: float = 1.5,
    ) -> Optional[QRectF]:
        idxs = [self._ch_idx[c] for c in chans if c in self._ch_idx]
        if not idxs:
            return None
        i0, i1 = min(idxs), max(idxs)
        x0 = xs[i0] + pad
        x1 = xs[i1] + ws[i1] - pad
        return QRectF(x0, row_y + pad, max(1.0, x1 - x0), row_h - pad * 2.0)

    # ── Color helpers ─────────────────────────────────────────────────────────

    def _ch_band_hex(self, ch: int) -> Optional[str]:
        for _, hx, chans in self._UNII_BANDS:
            if ch in chans:
                return hx
        return None

    def _vivid(self, hex_c: str) -> QColor:
        return QColor(hex_c)

    def _cell_fill(self, hex_c: str) -> QColor:
        """Slightly translucent band colour for BW-row cells."""
        c = QColor(hex_c)
        c.setAlpha(220)
        return c

    # ── Subclass hook ─────────────────────────────────────────────────────────

    def _ch_freq(self, ch: int) -> int:
        raise NotImplementedError

    # ── Drawing helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _cell(
        p: QPainter,
        rect: QRectF,
        fill: QColor,
        border: QColor,
        bw: float,
        text: str,
        tc: QColor,
        font: QFont,
        align=Qt.AlignmentFlag.AlignCenter,
        wrap: bool = False,
    ):
        p.fillRect(rect, fill)
        if bw > 0:
            p.setPen(QPen(border, bw))
            p.drawRect(rect)
        if text:
            p.setPen(tc)
            p.setFont(font)
            flags = int(align)
            if wrap:
                flags |= int(Qt.TextFlag.TextWordWrap)
            p.drawText(rect.adjusted(5, 3, -5, -3), flags, text)

    @staticmethod
    def _vtxt(
        p: QPainter,
        cx: float,
        row_top: float,
        row_h: float,
        text: str,
        tc: QColor,
        font: QFont,
    ):
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        p.save()
        p.setPen(tc)
        p.setFont(font)
        p.translate(cx - th * 0.5 + th, row_top + (row_h + tw) * 0.5)
        p.rotate(-90)
        p.drawText(QRectF(0, 0, tw, th), Qt.AlignmentFlag.AlignLeft, text)
        p.restore()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        pal = self.palette()
        is_dark = pal.color(QPalette.ColorRole.Window).lightness() < 128

        BG = pal.color(
            QPalette.ColorRole.Base if is_dark else QPalette.ColorRole.Window
        )
        GRID = QColor("#3a4a5e" if is_dark else "#8a9ab8")
        CELL_BG = QColor("#18203a" if is_dark else "#edf1fb")
        LBL_BG = QColor("#232d40" if is_dark else "#d8dfee")
        TEXT_C = QColor("#dde8f8" if is_dark else "#1a2438")
        DIM_C = QColor("#6a7e9a" if is_dark else "#5a6a82")
        WHITE = QColor("#ffffff")
        BLACK = QColor("#0a0f1a")

        p.fillRect(self.rect(), BG)

        # fonts
        F = self.font()
        fbold = QFont(F)
        fbold.setBold(True)
        fsmall = QFont(F)
        fsmall.setPointSize(max(6, F.pointSize() - 1))
        fsmb = QFont(fsmall)
        fsmb.setBold(True)
        ftiny = QFont(F)
        ftiny.setPointSize(max(5, F.pointSize() - 2))
        ftinyb = QFont(ftiny)
        ftinyb.setBold(True)
        ftitle = QFont(F)
        ftitle.setPointSize(F.pointSize() + 1)
        ftitle.setBold(True)

        lw = self._z(self._BASE_LEFT_W)
        band_h = self._z(self._BASE_BAND_H)
        freq_h = self._z(self._BASE_FREQ_H)
        bw_h = self._z(self._BASE_BW_H)

        xs_nat, ws_nat, nat_cw = self._col_xs()
        # Stretch columns horizontally to fill the widget's actual width.
        # When the viewport is wider than the natural zoom size the columns
        # expand proportionally; when zoomed in the natural size is honoured
        # (the scroll area shows a horizontal scrollbar).
        avail_cw = max(nat_cw, float(self.width()) - lw)
        if nat_cw > 0:
            _hs = avail_cw / nat_cw
            xs = [x * _hs for x in xs_nat]
            ws = [w * _hs for w in ws_nat]
        else:
            xs, ws = xs_nat, ws_nat
        total_cw = avail_cw
        CX = lw  # x where chart columns begin

        # ── Title strip ────────────────────────────────────────────────────
        title_h = self._z(38)
        p.fillRect(QRectF(0, 0, lw + total_cw, title_h), LBL_BG)
        p.setPen(TEXT_C)
        p.setFont(ftitle)
        p.drawText(
            QRectF(10, 0, lw + total_cw - 20, title_h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._TITLE,
        )
        if self._SUBTITLE:
            p.setPen(DIM_C)
            p.setFont(ftiny)
            p.drawText(
                QRectF(10, 0, lw + total_cw - 12, title_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                self._SUBTITLE,
            )
        y = title_h

        # ── Row-label helper ───────────────────────────────────────────────
        def _lbl(ly, h, txt, bold=False):
            r = QRectF(0, ly, lw, h)
            p.fillRect(r, LBL_BG)
            p.setPen(QPen(GRID, 0.8))
            p.drawRect(r)
            p.setPen(TEXT_C)  # always readable, bold rows just get bigger font
            p.setFont(fbold if bold else fsmall)
            p.drawText(
                r.adjusted(8, 2, -4, -2),
                Qt.AlignmentFlag.AlignVCenter
                | Qt.AlignmentFlag.AlignLeft
                | Qt.TextFlag.TextWordWrap,
                txt,
            )

        # ── UNII band header row ───────────────────────────────────────────
        _lbl(y, band_h, "Band", bold=True)
        for band_lbl, band_hex, band_chans in self._UNII_BANDS:
            bc_set = set(band_chans)
            idxs = [self._ch_idx[c] for c in band_chans if c in self._ch_idx]
            if not idxs:
                continue
            i0, i1 = min(idxs), max(idxs)
            x0 = CX + xs[i0] + 1
            x1 = CX + xs[i1] + ws[i1] - 1
            r = QRectF(x0, y + 1, x1 - x0, band_h - 2)
            vivid = self._vivid(band_hex)
            p.fillRect(r, vivid)
            p.setPen(QPen(WHITE, 1.5))
            p.drawRect(r)
            p.setPen(WHITE)
            p.setFont(fbold)
            p.drawText(
                r,
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextDontClip,
                band_lbl,
            )
        y += band_h

        # ── Center-frequency row (vertical text per 20 MHz column) ────────
        _lbl(y, freq_h, "Center\nFrequency")
        p.fillRect(QRectF(CX, y, total_cw, freq_h), CELL_BG)
        p.setPen(QPen(GRID, 0.5))
        p.drawRect(QRectF(CX, y, total_cw, freq_h))
        for i, ch in enumerate(self._COLS):
            if ch is None or ch in self._PHANTOM_COLS:
                continue
            fv = self._ch_freq(ch)
            cx_c = CX + xs[i] + ws[i] / 2.0
            hx = self._ch_band_hex(ch)
            tc_f = self._vivid(hx) if hx else DIM_C
            # subtle tick at bottom
            p.setPen(QPen(QColor(tc_f.red(), tc_f.green(), tc_f.blue(), 80), 0.8))
            p.drawLine(QPointF(cx_c, y + freq_h - 4), QPointF(cx_c, y + freq_h))
            self._vtxt(p, cx_c, y + 2, freq_h - 6, str(fv), tc_f, ftinyb)
        y += freq_h

        # ── Bandwidth rows ─────────────────────────────────────────────────
        for row_lbl, qty_str, groups in self._BW_ROWS:
            lbl_txt = f"{row_lbl}\n({qty_str} ch)" if qty_str else row_lbl
            _lbl(y, bw_h, lbl_txt)
            p.fillRect(QRectF(CX, y, total_cw, bw_h), CELL_BG)
            for grp_lbl, chans in groups:
                if not chans:
                    continue
                hx = self._ch_band_hex(chans[0])
                fill = self._cell_fill(hx) if hx else CELL_BG
                rect = self._group_rect(chans, xs, ws, y, bw_h, pad=1.5)
                if rect is None:
                    continue
                rect.translate(CX, 0)
                use_font = ftinyb if (len(grp_lbl) > 4 or bw_h < 22) else fsmb
                self._cell(p, rect, fill, WHITE, 1.5, grp_lbl, WHITE, use_font)
            p.setPen(QPen(GRID, 0.8))
            p.drawRect(QRectF(CX, y, total_cw, bw_h))
            y += bw_h

        # ── Extra rows (FCC, DFS, notes) ───────────────────────────────────
        # Each _EXTRA_ROWS entry is (label, height, segments[, bold=True]).
        # A 4th bool element lets subclasses opt out of bold for short rows.
        for row_entry in self._EXTRA_ROWS:
            row_lbl, row_h_base, segments = row_entry[0], row_entry[1], row_entry[2]
            row_bold = row_entry[3] if len(row_entry) > 3 else True
            rh = self._z(row_h_base)
            _lbl(y, rh, row_lbl, bold=row_bold)
            p.fillRect(QRectF(CX, y, total_cw, rh), CELL_BG)
            for ch_s, ch_e, seg_hex, seg_text in segments:
                i0 = self._ch_idx.get(ch_s)
                i1 = self._ch_idx.get(ch_e)
                if i0 is None or i1 is None:
                    continue
                # Extend each bar by half a column on each side so that
                # bar edges land on column centres (±1.5-channel visual span).
                x0 = CX + xs[i0] - ws[i0] / 2 + 1
                x1 = CX + xs[i1] + ws[i1] + ws[i1] / 2 - 1
                r = QRectF(x0, y + 1, x1 - x0, rh - 2)
                sf = QColor(seg_hex)
                if is_dark:
                    sf = sf.darker(150)
                p.fillRect(r, sf)
                p.setPen(QPen(WHITE, 1.2))
                p.drawRect(r)
                if seg_text:
                    p.setPen(QColor("#f0f6ff") if is_dark else BLACK)
                    p.setFont(fsmb)
                    p.drawText(
                        r.adjusted(4, 2, -4, -2),
                        Qt.AlignmentFlag.AlignCenter,
                        seg_text,
                    )
            p.setPen(QPen(GRID, 0.8))
            p.drawRect(QRectF(CX, y, total_cw, rh))
            y += rh

        # ── Outer frame ────────────────────────────────────────────────────
        p.setPen(QPen(GRID, 1.5))
        p.drawRect(QRectF(0, 0, lw + total_cw, y))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# 2.4 GHz channel allocation table
# ─────────────────────────────────────────────────────────────────────────────

_24G_ISM = list(range(1, 14))  # ch 1..13 — universally permitted
_24G_JP = [14]  # ch 14  — Japan only (wider gap, 802.11b only)


# Japan ch 14 uses internal key 140 to avoid collision with the sequential
# slot-14 phantom column (2477 MHz) needed for ch-13 right-edge overflow.
_24G_JP_KEY = 140


class TwoGhzAllocationDiagram(_ChannelTableWidget):
    """Table-style 2.4 GHz channel allocation chart.

    Column grid: each real channel N has centre frequency 2407+N×5 MHz,
    so adjacent columns are 5 MHz apart.  Plan bars use 3 column-slots
    (±1.5 slots from centre) matching the user-visible overlap footprint.
    Columns -2, -1, 14, 15 are phantom (invisible overflow slots) so
    channels 1 and 13 can show their full bar without edge clipping.
    Japan's ch 14 (2484 MHz) is stored as key 140 to avoid conflict with
    sequential slot 14 (2477 MHz).
    """

    _TITLE = "2.4 GHz Channel Allocations"
    _SUBTITLE = "Ctrl+scroll to zoom  ·  scroll to pan"

    # Columns: phantom overflow (-2,-1), real ISM (1-13), sequential
    # overflow phantoms (14,15), spectral gap, Japan ch-14 (key=140).
    _COLS = [-2, -1] + list(range(1, 16)) + [None, 140]

    # Phantom cols exist only for geometry; no label/colour is drawn.
    _PHANTOM_COLS = frozenset({-2, -1, 14, 15})

    _UNII_BANDS = [
        ("2.4 GHz ISM  (ch 1–13, global)", "#1B5E20", _24G_ISM),
        ("ch 14  (JP only)", "#BF360C", [140]),
    ]

    _BW_ROWS = [
        (
            "Channels",
            "",
            [(str(c if c != 140 else 14), [c]) for c in list(range(1, 14)) + [140]],
        ),
    ]

    # Plan rows — each bar spans its actual RF footprint on the column grid.
    # Phantom cols (-2,-1,14,15) are used for left/right overflow so bars
    # for ch 1 and ch 13 show their full 20 MHz width.
    # 4th element: False → non-bold fsmall label (fits 36 px rows).
    _EXTRA_ROWS = [
        # ── 3-ch plan (US / global) ────────────────────────────────────────
        # Each 20 MHz bar: (N-1, N+1) = 3 cols wide = ±1.5 channels from centre
        # Ch  1: centre col 1,  bar (-1, 2)  — phantom -1 absorbs left overflow
        # Ch  6: centre col 6,  bar (5, 7)   — 3 cols ✓
        # Ch 11: centre col 11, bar (10, 12) — 3 cols ✓
        (
            "3-ch (1, 6, 11)\nUS/Global",
            36,
            [
                (-1, 2, "#1B5E20", "1"),
                (5, 7, "#1565C0", "6"),
                (10, 12, "#B71C1C", "11"),
            ],
            False,
        ),
        # ── 4-ch plan (Non-US: EU, APAC, Middle East) ─────────────────────
        # Each 20 MHz bar: (N-1, N+1) = 3 cols wide = ±1.5 channels from centre
        # Ch  1: (-1, 2)   — phantom -1 absorbs left overflow
        # Ch  5: (4, 6)    — 3 cols centred on ch 5 ✓
        # Ch  9: (8, 10)   — 3 cols centred on ch 9 ✓
        # Ch 13: (12, 14)  — phantom 14 absorbs right overflow ✓
        (
            "4-ch (1, 5, 9, 13)\nNon-US",
            36,
            [
                (-1, 2, "#1B5E20", "1"),
                (4, 6, "#E65100", "5"),
                (8, 10, "#1565C0", "9"),
                (12, 14, "#880E4F", "13"),
            ],
            False,
        ),
        # ── 802.11b — 22 MHz channel width ────────────────────────────────
        # 3-col bars (±1.5 channels) for visual consistency; label shows 22 MHz.
        # Ch  5 (2432): centre = col 5  → (4, 6)  ✓
        # Ch 10 (2457): centre = col 10 → (9, 11) ✓
        (
            "802.11b (22 MHz)\n(ch 5, 10)",
            36,
            [
                (4, 6, "#4527A0", "5  (22 MHz)"),
                (9, 11, "#00695C", "10  (22 MHz)"),
            ],
            False,
        ),
        # ── 802.11g/n/ax — Japan 14-channel domain ────────────────────────
        # 3-col bars (±1.5 channels) matching other 20 MHz plan rows.
        # Ch  4 (2427): centre = col 4  → (3, 5)  ✓
        # Ch  9 (2452): centre = col 9  → (8, 10) ✓
        # Ch 14 (2484): Japan-only DSSS — isolated gap column.
        (
            "802.11g/n/ax(20 MHz)\n(ch 4, 9, 14)(JP)",
            36,
            [
                (3, 5, "#1B5E20", "4"),
                (8, 10, "#1565C0", "9"),
                (140, 140, "#BF360C", "14"),
            ],
            False,
        ),
    ]

    # Wider columns — only 14 channels so we have room
    _BASE_COL_W = 42.0
    _BASE_GAP_W = 18.0
    _BASE_LEFT_W = 155.0  # wider than default (132) to fit "802.11g/n/ax" label

    def _ch_freq(self, ch: int) -> int:
        if ch == 140:
            return 2484  # Japan-only ch 14
        return 2407 + ch * 5


# ─────────────────────────────────────────────────────────────────────────────
# 5 GHz channel allocation table
# ─────────────────────────────────────────────────────────────────────────────

# pre-compute channel sets for UNII bands
_U1 = [36, 40, 44, 48]
_U2A = [52, 56, 60, 64]
_U2C = [100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144]
_U3 = [149, 153, 157, 161, 165]


class FiveGhzAllocationDiagram(_ChannelTableWidget):
    """Table-style 5 GHz channel allocation chart."""

    _TITLE = "5 GHz Channel Allocations"
    _SUBTITLE = "Ctrl+scroll to zoom"

    # Columns: real channel numbers + None for spectral gaps with no channels
    _COLS = [
        36,
        40,
        44,
        48,  # UNII-1   5150–5250 MHz
        None,  # gap  (5250–5260 MHz)
        52,
        56,
        60,
        64,  # UNII-2A  5250–5350 MHz
        None,  # gap  (5350–5470 MHz — no allocations)
        100,
        104,
        108,
        112,
        116,
        120,
        124,
        128,
        132,
        136,
        140,
        144,  # UNII-2C  5470–5725 MHz
        None,  # gap  (5720–5745 MHz)
        149,
        153,
        157,
        161,
        165,  # UNII-3   5725–5850 MHz
    ]

    _UNII_BANDS = [
        ("UNII-1", "#388E3C", _U1),
        ("UNII-2A", "#1976D2", _U2A),
        ("UNII-2C (Ext.)", "#0D47A1", _U2C),
        ("UNII-3", "#E64A19", _U3),
    ]

    _BW_ROWS = [
        (
            "20 MHz",
            "25",
            [
                ("36", [36]),
                ("40", [40]),
                ("44", [44]),
                ("48", [48]),
                ("52", [52]),
                ("56", [56]),
                ("60", [60]),
                ("64", [64]),
                ("100", [100]),
                ("104", [104]),
                ("108", [108]),
                ("112", [112]),
                ("116", [116]),
                ("120", [120]),
                ("124", [124]),
                ("128", [128]),
                ("132", [132]),
                ("136", [136]),
                ("140", [140]),
                ("144", [144]),
                ("149", [149]),
                ("153", [153]),
                ("157", [157]),
                ("161", [161]),
                ("165", [165]),
            ],
        ),
        (
            "40 MHz",
            "12",
            [
                ("38", [36, 40]),
                ("46", [44, 48]),
                ("54", [52, 56]),
                ("62", [60, 64]),
                ("102", [100, 104]),
                ("110", [108, 112]),
                ("118", [116, 120]),
                ("126", [124, 128]),
                ("134", [132, 136]),
                ("142", [140, 144]),
                ("151", [149, 153]),
                ("159", [157, 161]),
            ],
        ),
        (
            "80 MHz",
            "6",
            [
                ("42", [36, 40, 44, 48]),
                ("58", [52, 56, 60, 64]),
                ("106", [100, 104, 108, 112]),
                ("122", [116, 120, 124, 128]),
                ("138", [132, 136, 140, 144]),
                ("155", [149, 153, 157, 161]),
            ],
        ),
        (
            "160 MHz",
            "2",
            [
                ("50", [36, 40, 44, 48, 52, 56, 60, 64]),
                ("114", [100, 104, 108, 112, 116, 120, 124, 128]),
            ],
        ),
    ]

    _EXTRA_ROWS = [
        (
            "FCC (USA)",
            90,
            [
                (
                    36,
                    48,
                    "#81C784",
                    "1,000 mW Tx Power\nIndoor & Outdoor\nNo DFS needed",
                ),
                (52, 64, "#64B5F6", "250 mw w/6dBi\nIndoor & Outdoor\nDFS Required"),
                (
                    100,
                    116,
                    "#64B5F6",
                    "250mw w/6dBi\nIndoor & Outdoor\nDFS Required\n144 Now Allowed",
                ),
                (120, 128, "#FFD54F", "120, 124, 128\nDevices Now\nAllowed"),
                (132, 144, "#5C8BB0", ""),
                (
                    149,
                    165,
                    "#FF8A65",
                    "1,000 mW EIRP\nIndoor & Outdoor\nNo DFS needed\n165 was ISM,\nnow UNII-3",
                ),
            ],
        ),
        (
            "DFS",
            24,
            [
                (52, 144, "#546E7A", "DFS Channels — ch 52 through 144"),
            ],
        ),
    ]

    def _ch_freq(self, ch: int) -> int:
        return CH5.get(ch, 0)


class FiveGhzAllocationDialog(QDialog):
    """Popup for the 5 GHz channel-allocation table."""

    def __init__(self, is_dark: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🗺  5 GHz Channel Allocations")
        self.setModal(False)
        self.resize(1300, 580)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        title = QLabel("5 GHz Channel Allocation Reference")
        title.setObjectName("allocTitle")
        note = QLabel(
            "25 × 20 MHz  ·  12 × 40 MHz  ·  6 × 80 MHz  ·  2 × 160 MHz  "
            "·  Ctrl+scroll to zoom  ·  scroll to pan"
        )
        note.setObjectName("allocNote")
        lay.addWidget(title)
        lay.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._diagram = FiveGhzAllocationDiagram()
        scroll.setWidget(self._diagram)
        lay.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.close)
        lay.addWidget(btns)

        self._apply_theme(is_dark)

    def _apply_theme(self, is_dark: bool):
        bg, border = ("#0f1622", "#273248") if is_dark else ("#ffffff", "#c7d2e3")
        tc, nc = ("#dfe7f5", "#8ea0bf") if is_dark else ("#22314a", "#4a5a73")
        self.setStyleSheet(
            f"QDialog{{background:{bg};border:1px solid {border};border-radius:8px;}}"
            f"QLabel#allocTitle{{color:{tc};font-size:13pt;font-weight:700;}}"
            f"QLabel#allocNote{{color:{nc};font-size:9.5pt;}}"
            "QScrollArea{border:none;}"
        )

    def sync_theme(self, is_dark: bool):
        self._apply_theme(is_dark)
        self._diagram.update()


# ─────────────────────────────────────────────────────────────────────────────
# 6 GHz channel allocation table
# (keeping FiveGhzAllocationDialog / SixGhzAllocationDialog for compat)
# ─────────────────────────────────────────────────────────────────────────────

# pre-compute channel sets per UNII sub-band
_U5 = list(range(1, 94, 4))  # 24 channels: 1..93
_U6 = list(range(97, 114, 4))  # 5  channels: 97..113
_U7 = list(range(117, 182, 4))  # 17 channels: 117..181
_U8 = list(range(185, 234, 4))  # 13 channels: 185..233


class SixGhzAllocationDiagram(_ChannelTableWidget):
    """Table-style 6 GHz channel allocation chart — FCC Low Power Indoor."""

    _TITLE = "6 GHz Channel Allocations — FCC Low Power Indoor (LPI)"
    _SUBTITLE = "Ctrl+scroll to zoom · No DFS required"

    _COLS = _U5 + [None] + _U6 + [None] + _U7 + [None] + _U8

    _UNII_BANDS = [
        ("UNII-5", "#2E7D32", _U5),
        ("UNII-6", "#00695C", _U6),
        ("UNII-7", "#1565C0", _U7),
        ("UNII-8", "#6A1B9A", _U8),
    ]

    _BW_ROWS = [
        # 59 × 20 MHz
        ("20 MHz", "59", [(str(c), [c]) for c in _U5 + _U6 + _U7 + _U8]),
        # 29 × 40 MHz
        # UNII-5 (12): adjacent pairs (1,5)→3 … (89,93)→91
        # UNII-6 (2):  (97,101)→99, (105,109)→107
        # Cross-6/7 + UNII-7 (9): (113,117)→115, (121,125)→123 … (177,181)→179
        # UNII-8 (6):  (185,189)→187 … (225,229)→227   [ch 233 unpaired]
        (
            "40 MHz",
            "29",
            [
                ("3", [1, 5]),
                ("11", [9, 13]),
                ("19", [17, 21]),
                ("27", [25, 29]),
                ("35", [33, 37]),
                ("43", [41, 45]),
                ("51", [49, 53]),
                ("59", [57, 61]),
                ("67", [65, 69]),
                ("75", [73, 77]),
                ("83", [81, 85]),
                ("91", [89, 93]),
                ("99", [97, 101]),
                ("107", [105, 109]),
                ("115", [113, 117]),
                ("123", [121, 125]),
                ("131", [129, 133]),
                ("139", [137, 141]),
                ("147", [145, 149]),
                ("155", [153, 157]),
                ("163", [161, 165]),
                ("171", [169, 173]),
                ("179", [177, 181]),
                ("187", [185, 189]),
                ("195", [193, 197]),
                ("203", [201, 205]),
                ("211", [209, 213]),
                ("219", [217, 221]),
                ("227", [225, 229]),
            ],
        ),
        # 14 × 80 MHz
        # UNII-5 (6): (1..13)→7 … (81..93)→87
        # UNII-6 (1): (97..109)→103
        # Cross-6/7 (1): (113..125)→119
        # UNII-7 (4): (129..141)→135 … (161..173)→167,  cross-7/8: (177..189)→183
        # UNII-8 (2): (193..205)→199, (209..221)→215
        (
            "80 MHz",
            "14",
            [
                ("7", [1, 5, 9, 13]),
                ("23", [17, 21, 25, 29]),
                ("39", [33, 37, 41, 45]),
                ("55", [49, 53, 57, 61]),
                ("71", [65, 69, 73, 77]),
                ("87", [81, 85, 89, 93]),
                ("103", [97, 101, 105, 109]),
                ("119", [113, 117, 121, 125]),
                ("135", [129, 133, 137, 141]),
                ("151", [145, 149, 153, 157]),
                ("167", [161, 165, 169, 173]),
                ("183", [177, 181, 185, 189]),
                ("199", [193, 197, 201, 205]),
                ("215", [209, 213, 217, 221]),
            ],
        ),
        # 7 × 160 MHz
        # UNII-5 (3): (1..29)→15, (33..61)→47, (65..93)→79
        # Cross-6/7 (1): (97..125)→111
        # UNII-7 (1): (129..157)→143
        # Cross-7/8 (1): (161..189)→175 (spans UNII-7 and start of UNII-8)
        # UNII-8 (1): (193..221)→207
        (
            "160 MHz",
            "7",
            [
                ("15", [1, 5, 9, 13, 17, 21, 25, 29]),
                ("47", [33, 37, 41, 45, 49, 53, 57, 61]),
                ("79", [65, 69, 73, 77, 81, 85, 89, 93]),
                ("111", [97, 101, 105, 109, 113, 117, 121, 125]),
                ("143", [129, 133, 137, 141, 145, 149, 153, 157]),
                ("175", [161, 165, 169, 173, 177, 181, 185, 189]),
                ("207", [193, 197, 201, 205, 209, 213, 217, 221]),
            ],
        ),
    ]

    _EXTRA_ROWS = []

    # Narrower base column so 59 channels fit comfortably at default zoom
    _BASE_COL_W = 22.0
    _BASE_GAP_W = 10.0

    def _ch_freq(self, ch: int) -> int:
        return 5950 + ch * 5


class SixGhzAllocationDialog(QDialog):
    """Popup for the 6 GHz channel-allocation table."""

    def __init__(self, is_dark: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🗺  6 GHz Channel Allocations")
        self.setModal(False)
        self.resize(1500, 500)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        title = QLabel("6 GHz Channel Allocation Reference")
        title.setObjectName("allocTitle")
        note = QLabel(
            "FCC Low Power Indoor (LPI)  ·  UNII-5/6/7/8  ·  No DFS Required  "
            "·  59 × 20 MHz  ·  29 × 40 MHz  ·  14 × 80 MHz  ·  7 × 160 MHz  "
            "·  Ctrl+scroll to zoom"
        )
        note.setObjectName("allocNote")
        lay.addWidget(title)
        lay.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._diagram = SixGhzAllocationDiagram()
        scroll.setWidget(self._diagram)
        lay.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.close)
        lay.addWidget(btns)

        self._apply_theme(is_dark)

    def _apply_theme(self, is_dark: bool):
        bg, border = ("#0f1622", "#273248") if is_dark else ("#ffffff", "#c7d2e3")
        tc, nc = ("#dfe7f5", "#8ea0bf") if is_dark else ("#22314a", "#4a5a73")
        self.setStyleSheet(
            f"QDialog{{background:{bg};border:1px solid {border};border-radius:8px;}}"
            f"QLabel#allocTitle{{color:{tc};font-size:13pt;font-weight:700;}}"
            f"QLabel#allocNote{{color:{nc};font-size:9.5pt;}}"
            "QScrollArea{border:none;}"
        )

    def sync_theme(self, is_dark: bool):
        self._apply_theme(is_dark)
        self._diagram.update()


# ─────────────────────────────────────────────────────────────────────────────
# Combined Channel Allocations dialog (5 GHz + 6 GHz on one page)
# ─────────────────────────────────────────────────────────────────────────────


class ChannelAllocationsDialog(QDialog):
    """Single popup showing the 5 GHz and 6 GHz allocation tables stacked."""

    def __init__(self, is_dark: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001f5fa\ufe0f  Channel Allocations")
        self.setModal(False)
        self.resize(1400, 760)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        title = QLabel("Channel Allocation Reference")
        title.setObjectName("allocTitle")
        note = QLabel(
            "2.4 GHz: 3-ch plan (1,6,11) \u00b7 4-ch plan (1,5,9,13) \u00b7 802.11b 22 MHz \u00b7 802.11g/n/ax JP  \u00b7  "
            "5 GHz: 25\u00d720 \u00b7 12\u00d740 \u00b7 6\u00d780 \u00b7 2\u00d7160 MHz  \u00b7  "
            "6 GHz (FCC LPI): 59\u00d720 \u00b7 29\u00d740 \u00b7 14\u00d780 \u00b7 7\u00d7160 MHz  \u00b7  "
            "Ctrl+scroll to zoom  \u00b7  scroll to pan"
        )
        note.setObjectName("allocNote")
        lay.addWidget(title)
        lay.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(40)

        self._2g = TwoGhzAllocationDiagram()
        self._5g = FiveGhzAllocationDiagram()
        self._6g = SixGhzAllocationDiagram()
        vl.addWidget(self._2g)
        vl.addWidget(self._5g)
        vl.addWidget(self._6g)
        vl.addStretch()

        scroll.setWidget(container)
        lay.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.close)
        lay.addWidget(btns)

        self._apply_theme(is_dark)

    def _apply_theme(self, is_dark: bool):
        bg, border = ("#0f1622", "#273248") if is_dark else ("#ffffff", "#c7d2e3")
        tc, nc = ("#dfe7f5", "#8ea0bf") if is_dark else ("#22314a", "#4a5a73")
        self.setStyleSheet(
            f"QDialog{{background:{bg};border:1px solid {border};border-radius:8px;}}"
            f"QLabel#allocTitle{{color:{tc};font-size:13pt;font-weight:700;}}"
            f"QLabel#allocNote{{color:{nc};font-size:9.5pt;}}"
            "QScrollArea{border:none;}"
        )

    def sync_theme(self, is_dark: bool):
        self._apply_theme(is_dark)
        self._2g.update()
        self._5g.update()
        self._6g.update()


# Monitor Mode — Packet Capture
# ─────────────────────────────────────────────────────────────────────────────
