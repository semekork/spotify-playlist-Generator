import sys
import threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLineEdit, QPushButton, QLabel, QTextEdit, QFileDialog, QTabWidget
)
from PySide6.QtCore import Qt, QThreadPool, Slot
from spotify_backend import SpotifyBot, WorkerSignals, CreateWorker, DedupeWorker
import os 

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Spotify Studio Pro (PySide6)")
        self.setGeometry(100, 100, 800, 600)

        # Threading setup
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(1) # Only run one operation at a time

        # Signals setup
        self.worker_signals = WorkerSignals()
        self.worker_signals.log_message.connect(self.update_log)
        self.worker_signals.finished.connect(self.enable_controls)

        # --- FIX #2: LOG BOX SETUP MOVED HERE ---
        # Initialize central widget and main layout first
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        # Shared Log Box must be initialized BEFORE the bot, as the bot logs immediately.
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(150)
        # Temporarily append log box to main layout. It will be moved to the bottom later.

        # Initialize Bot (must be done in the main thread)
        try:
            # The bot will immediately use self.log_box via self.worker_signals
            self.bot = SpotifyBot(signals=self.worker_signals)
        except Exception as e:
            self.update_log(f"FATAL AUTH ERROR: {str(e)}\nEnsure .env is correct and token is fresh.")
            self.bot = None

        # --- UI SETUP CONTINUES ---
        
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        # Tabs
        self.create_tab = QWidget()
        # --- FIX #1: Corrected typo from QQWidget to QWidget ---
        self.dedupe_tab = QWidget()
        
        self.tabs.addTab(self.create_tab, "Create Playlist")
        self.tabs.addTab(self.dedupe_tab, "De-Duplicator")

        self.setup_create_tab()
        self.setup_dedupe_tab()
        
        # Re-add Log Box and Label at the end of the layout
        self.layout.addWidget(QLabel("--- Application Log ---"))
        self.layout.addWidget(self.log_box)
        
        self.update_log("Welcome to Spotify Studio Pro.")
        if self.bot and not self.bot.sp:
            self.disable_controls() # Disable if auth failed during startup


    def setup_create_tab(self):
        layout = QVBoxLayout(self.create_tab)
        
        # Input Source Group
        input_group = QWidget()
        input_layout = QGridLayout(input_group)
        
        # File Input
        self.btn_file = QPushButton("Select File (CSV/TXT)")
        self.btn_file.clicked.connect(self.select_file)
        self.lbl_file = QLabel("No file selected")
        input_layout.addWidget(self.btn_file, 0, 0)
        input_layout.addWidget(self.lbl_file, 0, 1)

        # YouTube Input
        self.entry_yt = QLineEdit()
        self.entry_yt.setPlaceholderText("OR Paste YouTube Playlist/Video URL")
        input_layout.addWidget(self.entry_yt, 1, 0, 1, 2)
        
        layout.addWidget(input_group)

        # Playlist Name Input
        self.entry_name = QLineEdit()
        self.entry_name.setPlaceholderText("Enter New Playlist Name")
        layout.addWidget(QLabel("Playlist Name:"))
        layout.addWidget(self.entry_name)

        # Run Button
        self.btn_run_create = QPushButton("GENERATE PLAYLIST")
        self.btn_run_create.setStyleSheet("background-color: green; color: white;")
        self.btn_run_create.clicked.connect(self.run_creator)
        layout.addWidget(self.btn_run_create)
        
        layout.addStretch() # Push everything to the top

    def setup_dedupe_tab(self):
        layout = QVBoxLayout(self.dedupe_tab)
        
        layout.addWidget(QLabel("Playlist Link:"))
        self.entry_pl_link = QLineEdit()
        self.entry_pl_link.setPlaceholderText("Paste Spotify Playlist URL to Clean")
        layout.addWidget(self.entry_pl_link)

        self.btn_run_dedupe = QPushButton("SCAN AND REMOVE DUPLICATES")
        self.btn_run_dedupe.setStyleSheet("background-color: red; color: white;")
        self.btn_run_dedupe.clicked.connect(self.run_dedupe)
        layout.addWidget(self.btn_run_dedupe)
        
        layout.addStretch()

    # --- SLOTS (Receivers of Signals) ---
    @Slot(str)
    def update_log(self, message):
        """Updates the log box safely from any thread."""
        self.log_box.insertPlainText(message)
        self.log_box.ensureCursorVisible()

    @Slot()
    def enable_controls(self):
        """Re-enables buttons after a worker thread finishes."""
        self.btn_run_create.setEnabled(True)
        self.btn_run_dedupe.setEnabled(True)
        self.update_log("Process finished.\n")

    # --- UI HANDLERS ---
    def select_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select CSV or Text File", "", "Data Files (*.csv *.txt);;All Files (*)"
        )
        if filename:
            self.lbl_file.setText(filename)
            self.entry_yt.clear() # Clear YT field if file selected

    def disable_controls(self):
        self.btn_run_create.setEnabled(False)
        self.btn_run_dedupe.setEnabled(False)
        self.log_box.clear()

    # --- THREADING HANDLERS ---
    def run_creator(self):
        if not self.bot or not self.bot.sp: 
            self.update_log("❌ Error: Spotify not authenticated. Cannot run.\n")
            return

        pl_name = self.entry_name.text().strip()
        file_path = self.lbl_file.text().strip()
        yt_url = self.entry_yt.text().strip()

        if not pl_name:
            self.update_log("❌ Error: Enter a playlist name.\n")
            return
        
        # Determine input source
        source = None
        if file_path not in ("No file selected", "") and os.path.exists(file_path):
            source = file_path
        elif yt_url and yt_url.startswith(("http", "https")):
            source = yt_url
        
        if not source:
            self.update_log("❌ Error: Select a file or enter a YouTube URL.\n")
            return

        self.disable_controls()
        self.update_log(f"Starting playlist generation for: {pl_name}\n")
        
        # Create and start the worker thread
        worker = CreateWorker(self.bot, source, pl_name)
        self.threadpool.start(worker)

    def run_dedupe(self):
        if not self.bot or not self.bot.sp: 
            self.update_log("❌ Error: Spotify not authenticated. Cannot run.\n")
            return
        
        url = self.entry_pl_link.text().strip()
        if not url or "spotify" not in url:
            self.update_log("❌ Error: Enter a valid Spotify playlist URL.\n")
            return

        self.disable_controls()
        self.update_log(f"Starting deduplication for: {url}\n")
        
        # Create and start the worker thread
        worker = DedupeWorker(self.bot, url)
        self.threadpool.start(worker)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())