import streamlit as st
import os
from spotify_backend import SpotifyBot

# Page Config
st.set_page_config(page_title="Spotify Studio Pro", page_icon="🎵", layout="wide")

st.title("🎵 Spotify Studio Pro")

# --- Initialize Bot and State ---
if 'logs' not in st.session_state:
    st.session_state.logs = []

def log_to_ui(message):
    st.session_state.logs.append(message)

# Initialize bot only once
if 'bot' not in st.session_state:
    try:
        st.session_state.bot = SpotifyBot(log_callback=log_to_ui)
    except Exception as e:
        st.error(f"Failed to initialize: {e}")
        st.session_state.bot = None

# Display Logs (Sidebar or Bottom)
with st.sidebar:
    st.header("Log Output")
    log_area = st.empty()
    # Function to render logs
    def render_logs():
        log_text = "\n".join(st.session_state.logs)
        log_area.text_area("Logs", log_text, height=400)
    
    render_logs()
    if st.button("Clear Logs"):
        st.session_state.logs = []
        render_logs()

# --- Main UI Tabs ---
tab1, tab2 = st.tabs(["Create Playlist", "De-Duplicator"])

# --- Tab 1: Create Playlist ---
with tab1:
    st.header("Create New Playlist")
    
    # Inputs
    source_file = st.file_uploader("Upload CSV or Text File", type=["csv", "txt"])
    yt_url = st.text_input("OR Paste YouTube Playlist/Video URL")
    playlist_name = st.text_input("New Playlist Name", "My Awesome Playlist")
    
    if st.button("GENERATE PLAYLIST", type="primary"):
        st.session_state.logs = [] # Clear previous logs
        render_logs()
        
        if not st.session_state.bot or not st.session_state.bot.sp:
            st.error("Spotify not authenticated. Check logs/credentials.")
        elif not playlist_name:
            st.warning("Please enter a playlist name.")
        elif not source_file and not yt_url:
            st.warning("Please upload a file or enter a YouTube URL.")
        else:
            with st.spinner("Processing... Check sidebar for details."):
                # Determine Source
                songs = []
                if source_file:
                    songs = st.session_state.bot.parse_csv(source_file)
                elif yt_url:
                    songs = st.session_state.bot.parse_youtube(yt_url)
                
                if songs:
                    st.session_state.bot.create_playlist_from_list(songs, playlist_name)
                    st.success("Task Complete!")
                else:
                    st.error("No songs found to process.")
        render_logs()


# --- Tab 2: De-Duplicator ---
with tab2:
    st.header("Playlist De-Duplicator")
    
    playlist_link = st.text_input("Paste Spotify Playlist URL to Clean")
    
    if st.button("SCAN AND REMOVE DUPLICATES", type="primary"):
        st.session_state.logs = []
        render_logs()
        
        if not st.session_state.bot or not st.session_state.bot.sp:
            st.error("Spotify not authenticated.")
        elif not playlist_link or "spotify" not in playlist_link:
            st.warning("Please enter a valid Spotify URL.")
        else:
            with st.spinner("Scanning playlist..."):
                st.session_state.bot.deduplicate_playlist(playlist_link)
                st.success("Task Complete!")
        render_logs()