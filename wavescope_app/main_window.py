"""Main application window composition.

Composes UI and behavior mixins into the MainWindow class.
"""

from .core import *
from .main_window_ui import MainWindowUIMixin
from .main_window_logic import MainWindowLogicMixin
from .known_ssids import KnownSSIDStore


class MainWindow(MainWindowLogicMixin, MainWindowUIMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1400, 850)

        self._aps: List[AccessPoint] = []
        # Cache for iw-enriched fields, kept while NetworkManager still lists
        # the BSS (up to IW_CACHE_MAX_AGE_S) — see _on_data.
        self._iw_cache: Dict[str, dict] = {}  # bssid.lower() → field snapshot
        self._iw_seen_at: Dict[str, float] = {}  # bssid.lower() → monotonic time iw last decoded it
        # Cache for fields that must never regress to 0 / "" / None once known
        self._sticky_cache: Dict[str, dict] = {}  # bssid.lower() → {field: last_good}
        self._conn_counter_prev: Dict[str, Dict[str, int]] = {}
        # Scanner threads that were asked to stop but have not finished yet;
        # kept referenced so Qt never destroys a running QThread.
        self._retired_scanners: List[WiFiScanner] = []
        self._scanner: Optional[WiFiScanner] = None
        # Latest cross-AP analysis (congestion / BSS color / roaming)
        self._channel_stats: Dict[Tuple[str, int], ChannelStats] = {}
        self._color_collisions: Dict[str, List[AccessPoint]] = {}
        self._settings = QSettings("wavescope", "WaveScope")

        self._known_store = KnownSSIDStore()

        self._model = APTableModel()
        self._proxy = APFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.set_known_ssids(self._known_store.as_frozenset())

        self._setup_ui()
        # Apply initial theme styling to the details/connection cards so the
        # first-launch appearance matches what the user sees after any theme switch.
        self._apply_details_theme(True)
        self._apply_tb_theme(True)
        self._ap_sidebar.apply_theme(True)
        # Filter changes reach the proxy as rows inserted/removed (Qt 6
        # invalidateFilter) or layoutChanged (re-sort); coalesce them into one
        # graph refresh per event-loop pass.
        self._filter_refresh_timer = QTimer(self)
        self._filter_refresh_timer.setSingleShot(True)
        self._filter_refresh_timer.setInterval(0)
        self._filter_refresh_timer.timeout.connect(self._on_filter_changed)
        for sig in (
            self._proxy.layoutChanged,
            self._proxy.rowsInserted,
            self._proxy.rowsRemoved,
            self._proxy.modelReset,
        ):
            sig.connect(lambda *_: self._filter_refresh_timer.start())
        # Re-fit column widths only when the set of rows changes.
        self._model.rows_changed.connect(self._auto_size_table_columns)

        self._restore_settings()
        self._start_scanner()
        self._status("Scanning…")
        # First-run OUI prompt (only if IEEE JSON not yet downloaded)
        if not OUI_JSON_PATH.exists():
            QTimer.singleShot(800, self._prompt_oui_download)
