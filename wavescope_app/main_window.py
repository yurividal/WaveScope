"""Main application window composition.

Composes UI and behavior mixins into the MainWindow class.
"""

from .core import *
from .main_window_ui import MainWindowUIMixin
from .main_window_logic import MainWindowLogicMixin


class MainWindow(MainWindowLogicMixin, MainWindowUIMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1400, 850)

        self._aps: List[AccessPoint] = []
        # Cache for iw-enriched fields — persisted across up to 5 missed cycles
        self._iw_cache: Dict[str, dict] = {}  # bssid.lower() → field snapshot
        self._iw_miss: Dict[str, int] = {}  # bssid.lower() → consecutive-miss count
        # Cache for fields that must never regress to 0 / "" / None once known
        self._sticky_cache: Dict[str, dict] = {}  # bssid.lower() → {field: last_good}
        self._conn_counter_prev: Dict[str, Dict[str, int]] = {}
        self._scanner = WiFiScanner(interval_sec=2, linger_secs=60.0)
        self._scanner.data_ready.connect(self._on_data)
        self._scanner.scan_error.connect(self._on_error)

        self._model = APTableModel()
        self._proxy = APFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._setup_ui()
        # Whenever any filter changes (text, band, column include/exclude) the
        # proxy emits layoutChanged — refresh the graph to show only visible APs.
        self._proxy.layoutChanged.connect(self._on_filter_changed)
        self._scanner.start()
        self._status("Scanning…")

        # First-run OUI prompt (only if IEEE JSON not yet downloaded)
        if not OUI_JSON_PATH.exists():
            QTimer.singleShot(800, self._prompt_oui_download)
