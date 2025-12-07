import os
import spotipy
import datetime
import random
import base64
import requests
import io
import csv
import re # Added for YouTube title cleanup
from PIL import Image
from difflib import SequenceMatcher
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

# PySide6 components for safe threading communication
from PySide6.QtCore import QObject, Signal, QRunnable

# Try importing yt_dlp
try:
    import yt_dlp
    YT_SUPPORT = True
except ImportError:
    YT_SUPPORT = False

# Load environment variables
load_dotenv()

# Configuration (Constants)
CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SCOPE = "playlist-modify-private playlist-modify-public playlist-read-private ugc-image-upload"
MATCH_THRESHOLD = 0.4

class SpotifyBot:
    # Constructor updated to only expect signals, as this file is now PySide6-exclusive
    def __init__(self, signals):
        self.signals = signals
        self.sp = self.authenticate()
        # Only proceed if authentication was successful
        if self.sp:
            self.user_id = self.sp.current_user()['id']
            self.log("✅ Spotify authenticated.")

    def log(self, message):
        """Emits message to the GUI via the log signal."""
        # Use .emit() for the PySide6 Signal object
        self.signals.log_message.emit(message + "\n")

    def authenticate(self):
        # PROXY FIX: Ignore system proxies
        session = requests.Session()
        session.trust_env = False
        
        try:
            return spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uri=REDIRECT_URI,
                scope=SCOPE,
                cache_path=".spotify_cache"
            ), requests_session=session)
        except Exception as e:
            self.log(f"FATAL AUTH ERROR: {str(e)}")
            return None # Return None if authentication fails

    # --- NEW: PARSING METHODS (Moved from CreateWorker and added) ---
    def parse_csv(self, file_path):
        songs = []
        try:
            self.log(f"Loading songs from file: {file_path}")
            
            # Read content to check format
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Simple heuristic for CSV/TXT
            if ',' in content and len(content.split('\n')[0].split(',')) > 1:
                # Treat as CSV, assume song name is in the first column
                with open(file_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if row:
                            songs.append(row[0].strip())
            else:
                # Treat as a simple list, one song per line
                songs = [line.strip() for line in content.splitlines() if line.strip()]

            self.log(f"Successfully loaded {len(songs)} items.")
            return songs
        except Exception as e:
            self.log(f"❌ Error parsing file {file_path}: {e}")
            return []

    def parse_youtube(self, url):
        songs = []
        if not YT_SUPPORT:
            self.log("❌ Error: 'yt-dlp' is not installed. YouTube parsing disabled.")
            return []
            
        self.log(f"Fetching titles from YouTube URL: {url}...")
        try:
            ydl_opts = {
                'format': 'bestaudio',
                'dump_single_json': True,
                'extract_flat': True,
                'force_generic_extractor': True,
                'logger': None, 
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)

            # Handle playlists and single videos
            entries = info_dict.get('entries', [info_dict] if 'title' in info_dict else [])
            
            if 'entries' in info_dict:
                 self.log(f"Found YouTube Playlist: {info_dict.get('title', 'Untitled')}")

            for entry in entries:
                if entry and 'title' in entry:
                    # Clean the title: remove content in parentheses/brackets (e.g., [Official Video])
                    title = entry['title']
                    title = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', title).strip()
                    songs.append(title)
            
            if songs:
                self.log(f"Successfully retrieved {len(songs)} song titles.")
            else:
                self.log("❌ Error: Could not find any titles in the YouTube URL.")

            return songs

        except Exception as e:
            self.log(f"❌ Error fetching YouTube data: {e}")
            return []


    # --- DE-DUPLICATOR ---
    def deduplicate_playlist(self, playlist_url):
        try:
            # Check if authentication failed before fetching
            if not self.sp:
                self.log("❌ Cannot run deduplication: Spotify not authenticated.")
                return

            playlist_id = playlist_url.split("/")[-1].split("?")[0]
            self.log(f"🔎 Scanning playlist: {playlist_id}...")
            
            # Fetch all tracks
            results = self.sp.playlist_items(playlist_id)
            tracks = results['items']
            while results['next']:
                results = self.sp.next(results)
                tracks.extend(results['items'])

            seen_ids = set()
            to_remove = []
            
            for i, item in enumerate(tracks):
                if item['track'] and item['track']['id']:
                    tid = item['track']['id']
                    if tid in seen_ids:
                        # Found duplicate! Append the specific occurrence (position i)
                        to_remove.append({
                            "uri": item['track']['uri'],
                            "positions": [i] 
                        })
                        self.log(f"   -> Found duplicate: {item['track']['artists'][0]['name']} - {item['track']['name']}")
                    else:
                        seen_ids.add(tid)

            if to_remove:
                self.log(f"🧹 Found {len(to_remove)} duplicates. Removing...")
                # Remove in batches of 100
                for i in range(0, len(to_remove), 100):
                    batch = to_remove[i:i+100]
                    self.sp.playlist_remove_specific_occurrences_of_items(playlist_id, batch)
                self.log("✅ Playlist cleaned!")
            else:
                self.log("✨ No duplicates found.")
                
        except Exception as e:
            self.log(f"❌ Error during deduplication: {str(e)}")
        finally:
            self.signals.finished.emit()


    # --- CREATOR LOGIC ---
    def validate_match(self, query, track_obj):
        found_str = f"{track_obj['artists'][0]['name']} {track_obj['name']}".lower()
        clean_query = query.lower().replace("track:", "").replace("artist:", "")
        ratio = SequenceMatcher(None, clean_query, found_str).ratio()
        return (True, found_str) if ratio >= MATCH_THRESHOLD else (False, f"{found_str} ({ratio:.2f})")

    def create_playlist_from_list(self, song_list, playlist_name):
        # Check if authentication failed before running search
        if not self.sp:
            self.log("❌ Cannot create playlist: Spotify not authenticated.")
            self.signals.finished.emit()
            return

        valid_ids = []
        missing = []
        
        self.log(f"🔎 Processing {len(song_list)} songs...")
        
        for query in song_list:
            try:
                self.log(f"Searching: {query}...")
                res = self.sp.search(q=query, limit=1, type='track')
                if res['tracks']['items']:
                    track = res['tracks']['items'][0]
                    is_valid, found_name = self.validate_match(query, track)
                    if is_valid:
                        valid_ids.append(track['id'])
                        self.log(f"   -> Found: {found_name}")
                    else:
                        missing.append(query)
                else:
                    missing.append(query)
            except Exception as e:
                self.log(f"Error searching {query}: {e}")
                missing.append(query)

        if not valid_ids:
            self.log("❌ No valid tracks found.")
            self.signals.finished.emit()
            return

        # Apply recommender if list is short
        if len(valid_ids) < 10 and len(valid_ids) > 0:
            valid_ids = self.extend_playlist(valid_ids, target_size=20)

        # Create Playlist
        desc = f"Generated by Spotify Studio Pro 🐍 | {len(valid_ids)} Tracks"
        pl = self.sp.user_playlist_create(self.user_id, playlist_name, public=False, description=desc)
        
        # Add Tracks
        uris = [f"spotify:track:{tid}" for tid in valid_ids]
        for i in range(0, len(uris), 100):
            self.sp.playlist_add_items(pl['id'], uris[i:i+100])
        
        self.log(f"🚀 Success! Created '{playlist_name}' with {len(uris)} songs. URL: {pl['external_urls']['spotify']}")
        
        # Handle Missing
        if missing:
            try:
                with open("missing_songs.txt", "w", encoding='utf-8') as f:
                    f.write("\n".join(missing))
                self.log(f"⚠️ {len(missing)} missing songs saved to missing_songs.txt")
            except Exception as e:
                 self.log(f"⚠️ Could not save missing songs file: {e}")
        
        self.signals.finished.emit()

    def extend_playlist(self, track_ids, target_size=20):
        if len(track_ids) >= target_size: return track_ids
        self.log(f"✨ Extending playlist from {len(track_ids)} to {target_size} songs...")
        needed = target_size - len(track_ids)
        # Use random sample up to 5 tracks as seeds
        seeds = random.sample(track_ids, min(5, len(track_ids)))
        recs = self.sp.recommendations(seed_tracks=seeds, limit=needed)
        new_ids = [t['id'] for t in recs['tracks']]
        self.log(f"   -> Added {len(new_ids)} recommended tracks.")
        return track_ids + new_ids


    # --- WORKER CLASSES (for threading) ---

class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    finished = Signal()
    log_message = Signal(str)

class CreateWorker(QRunnable):
    """Worker for the playlist creation process."""
    def __init__(self, bot, source, playlist_name):
        super().__init__()
        self.bot = bot
        self.source = source # Stores the file path or URL
        self.playlist_name = playlist_name

    def run(self):
        # Determine input source and call the new parsing methods on the bot
        if self.source.startswith(("http", "https")):
            songs = self.bot.parse_youtube(self.source)
        elif self.source.endswith(('.csv', '.txt')) or os.path.exists(self.source):
            songs = self.bot.parse_csv(self.source)
        else:
            self.bot.log(f"❌ Error: Invalid input source or file not found: {self.source}")
            self.bot.signals.finished.emit()
            return
            
        self.bot.create_playlist_from_list(songs, self.playlist_name)

class DedupeWorker(QRunnable):
    """Worker for the deduplication process."""
    def __init__(self, bot, playlist_url):
        super().__init__()
        self.bot = bot
        self.playlist_url = playlist_url

    def run(self):
        self.bot.deduplicate_playlist(self.playlist_url)