# 🎵 Spotify Studio Pro (PySide6)

Spotify Studio Pro is a desktop application built with Python and
PySide6 that simplifies Spotify tasks like playlist creation and
duplicate removal while keeping the UI responsive.

## ✨ Features

-   **Playlist Generation** from CSV, TXT, or YouTube links.
-   **De-Duplicator** for cleaning Spotify playlists.
-   **Responsive UI** using QThreadPool threads.
-   **Logging** for real-time updates.
-   **Smart Search** with similarity checking.
-   **Auto Extend** playlists using Spotify recommendations.

## 🛠️ Installation and Setup

### 1. Prerequisites

1.  Create a Spotify Developer App.
2.  Set redirect URI: `http://localhost:8888/callback`.
3.  Install Python 3.8+.

### 2. Environment Variables (.env)

    SPOTIPY_CLIENT_ID="YOUR_CLIENT_ID_HERE"
    SPOTIPY_CLIENT_SECRET="YOUR_CLIENT_SECRET_HERE"
    SPOTIPY_REDIRECT_URI="http://127.0.0:8888/callback"

### 3. Install Dependencies

    pip install -r requirements.txt

`requirements.txt`:

    spotipy
    python-dotenv
    Pillow
    requests
    yt-dlp
    PySide6

## 🚀 Usage

Run:

    python app_pyside.py

### Tab 1: Create Playlist

1.  Enter a name.
2.  Select file or paste YouTube link.
3.  Click Generate.

### Tab 2: De-Duplicator

1.  Paste playlist URL.
2.  Click Scan and Remove.

## ⚙️ Architecture Overview

  Component            Tech              Purpose
  -------------------- ----------------- -----------------------
  app_pyside.py        PySide6           GUI
  spotify_backend.py   spotipy, QtCore   API logic, workers
  Threading            QThreadPool       Background processing
