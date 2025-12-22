import os
import spotipy
import random
import csv
import re
from difflib import SequenceMatcher
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import requests

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
    def __init__(self, log_callback=None):
        """
        :param log_callback: A function that accepts a string message (e.g., st.write or print)
        """
        self.log_callback = log_callback
        self.sp = self.authenticate()
        if self.sp:
            try:
                self.user_id = self.sp.current_user()['id']
                self.log("✅ Spotify authenticated.")
            except Exception as e:
                self.log(f"❌ Auth Error: {e}")
                self.sp = None

    def log(self, message):
        """Sends message to the callback if it exists."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def authenticate(self):
        session = requests.Session()
        session.trust_env = False
        
        try:
            # open_browser=False is crucial for Streamlit Cloud to prevent hanging
            return spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uri=REDIRECT_URI,
                scope=SCOPE,
                cache_path=".spotify_cache",
                open_browser=False 
            ), requests_session=session)
        except Exception as e:
            self.log(f"FATAL AUTH ERROR: {str(e)}")
            return None 

    def parse_csv(self, file_object):
        """
        Parses an uploaded file object (Streamlit UploadedFile) or local path.
        """
        songs = []
        try:
            # Check if it's a Streamlit UploadedFile (has 'read' attribute) or string path
            if hasattr(file_object, 'read'):
                # Reset pointer and decode
                file_object.seek(0)
                content = file_object.read().decode('utf-8')
                name = getattr(file_object, 'name', 'Uploaded File')
            else:
                with open(file_object, 'r', encoding='utf-8') as f:
                    content = f.read()
                name = file_object

            self.log(f"Loading songs from: {name}")

            # Heuristic: if comma in first line, treat as CSV
            if ',' in content and len(content.split('\n')[0].split(',')) > 1:
                reader = csv.reader(content.splitlines())
                for row in reader:
                    if row:
                        songs.append(row[0].strip())
            else:
                # Treat as line-by-line list
                songs = [line.strip() for line in content.splitlines() if line.strip()]

            self.log(f"Successfully loaded {len(songs)} items.")
            return songs
        except Exception as e:
            self.log(f"❌ Error parsing file: {e}")
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

            entries = info_dict.get('entries', [info_dict] if 'title' in info_dict else [])
            
            if 'entries' in info_dict:
                 self.log(f"Found YouTube Playlist: {info_dict.get('title', 'Untitled')}")

            for entry in entries:
                if entry and 'title' in entry:
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

    def deduplicate_playlist(self, playlist_url):
        try:
            if not self.sp:
                self.log("❌ Cannot run deduplication: Spotify not authenticated.")
                return

            # Extract ID more robustly
            if "playlist/" in playlist_url:
                playlist_id = playlist_url.split("playlist/")[1].split("?")[0]
            else:
                playlist_id = playlist_url

            self.log(f"🔎 Scanning playlist ID: {playlist_id}...")
            
            results = self.sp.playlist_items(playlist_id)
            tracks = results['items']
            while results['next']:
                results = self.sp.next(results)
                tracks.extend(results['items'])

            seen_ids = set()
            to_remove = []
            
            for i, item in enumerate(tracks):
                if item.get('track') and item['track'].get('id'):
                    tid = item['track']['id']
                    if tid in seen_ids:
                        to_remove.append({
                            "uri": item['track']['uri'],
                            "positions": [i] 
                        })
                        self.log(f"   -> Found duplicate: {item['track']['artists'][0]['name']} - {item['track']['name']}")
                    else:
                        seen_ids.add(tid)

            if to_remove:
                self.log(f"🧹 Found {len(to_remove)} duplicates. Removing...")
                for i in range(0, len(to_remove), 100):
                    batch = to_remove[i:i+100]
                    self.sp.playlist_remove_specific_occurrences_of_items(playlist_id, batch)
                self.log("✅ Playlist cleaned!")
            else:
                self.log("✨ No duplicates found.")
                
        except Exception as e:
            self.log(f"❌ Error during deduplication: {str(e)}")

    def validate_match(self, query, track_obj):
        found_str = f"{track_obj['artists'][0]['name']} {track_obj['name']}".lower()
        clean_query = query.lower().replace("track:", "").replace("artist:", "")
        ratio = SequenceMatcher(None, clean_query, found_str).ratio()
        return (True, found_str) if ratio >= MATCH_THRESHOLD else (False, f"{found_str} ({ratio:.2f})")

    def create_playlist_from_list(self, song_list, playlist_name):
        if not self.sp:
            self.log("❌ Cannot create playlist: Spotify not authenticated.")
            return

        valid_ids = []
        missing = []
        
        self.log(f"🔎 Processing {len(song_list)} songs...")
        
        # Streamlit progress bar handling could go here, but logging is safer
        for query in song_list:
            try:
                # Simple sleep or check to avoid rate limits could be added here
                res = self.sp.search(q=query, limit=1, type='track')
                if res['tracks']['items']:
                    track = res['tracks']['items'][0]
                    is_valid, found_name = self.validate_match(query, track)
                    if is_valid:
                        valid_ids.append(track['id'])
                        self.log(f"   -> Found: {found_name}")
                    else:
                        self.log(f"   -> Weak Match (Skipped): {query} vs {found_name}")
                        missing.append(query)
                else:
                    self.log(f"   -> Not found: {query}")
                    missing.append(query)
            except Exception as e:
                self.log(f"Error searching {query}: {e}")
                missing.append(query)

        if not valid_ids:
            self.log("❌ No valid tracks found.")
            return

        if 0 < len(valid_ids) < 10:
            valid_ids = self.extend_playlist(valid_ids, target_size=20)

        try:
            desc = f"Generated by Spotify Studio Pro 🐍 | {len(valid_ids)} Tracks"
            pl = self.sp.user_playlist_create(self.user_id, playlist_name, public=False, description=desc)
            
            uris = [f"spotify:track:{tid}" for tid in valid_ids]
            for i in range(0, len(uris), 100):
                self.sp.playlist_add_items(pl['id'], uris[i:i+100])
            
            self.log(f"🚀 Success! Created '{playlist_name}' with {len(uris)} songs.")
            self.log(f"🔗 Link: {pl['external_urls']['spotify']}")
        except Exception as e:
            self.log(f"❌ Error creating playlist: {e}")
        
        if missing:
            self.log(f"⚠️ {len(missing)} missing songs.")
            # We can return this list or handle it in the UI
            return missing

    def extend_playlist(self, track_ids, target_size=20):
        if len(track_ids) >= target_size: return track_ids
        self.log(f"✨ Extending playlist from {len(track_ids)} to {target_size} songs...")
        needed = target_size - len(track_ids)
        seeds = random.sample(track_ids, min(5, len(track_ids)))
        try:
            recs = self.sp.recommendations(seed_tracks=seeds, limit=needed)
            new_ids = [t['id'] for t in recs['tracks']]
            self.log(f"   -> Added {len(new_ids)} recommended tracks.")
            return track_ids + new_ids
        except Exception as e:
            self.log(f"Error extending playlist: {e}")
            return track_ids