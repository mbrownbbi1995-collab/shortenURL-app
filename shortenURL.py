import streamlit as st
import sqlite3
import random
import string
import hashlib
from datetime import datetime, timedelta, timezone
import os
import re

# ==================== DATABASE SETUP ====================
DB_NAME = "shortlinks.db"

def init_db():
    """Initialize the SQLite database with the links table"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS links (
            code TEXT PRIMARY KEY,
            long_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            max_clicks INTEGER,
            click_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==================== HELPER FUNCTIONS ====================
def get_current_utc():
    """Return current UTC datetime as timezone-aware object"""
    return datetime.now(timezone.utc)

def generate_short_code(long_url: str, length: int = 6) -> str:
    """Generate a unique short code for the URL"""
    chars = string.ascii_letters + string.digits
    # Try up to 3 times to generate a unique code
    for _ in range(3):
        code = ''.join(random.choice(chars) for _ in range(length))
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT code FROM links WHERE code = ?", (code,))
        exists = c.fetchone()
        conn.close()
        if not exists:
            return code
    # Fallback to hash-based code if random generation fails
    return hashlib.blake2b(long_url.encode(), digest_size=length//2).hexdigest()[:length]

def store_link(code: str, long_url: str, expiry_hours: float, max_clicks: int):
    """Store a new short link in the database"""
    expires_at = None
    if expiry_hours > 0:
        expires_at = (get_current_utc() + timedelta(hours=expiry_hours)).isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO links (code, long_url, created_at, expires_at, max_clicks, click_count)
        VALUES (?, ?, ?, ?, ?, 0)
    ''', (code, long_url, get_current_utc().isoformat(), expires_at, max_clicks))
    conn.commit()
    conn.close()

def get_link_info(code: str):
    """Retrieve information about a short link"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT long_url, expires_at, max_clicks, click_count FROM links WHERE code = ?", (code,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "long_url": row[0],
            "expires_at": datetime.fromisoformat(row[1]) if row[1] else None,
            "max_clicks": row[2],
            "click_count": row[3]
        }
    return None

def increment_click_count(code: str):
    """Increment the click counter for a short link"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE links SET click_count = click_count + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()

def cleanup_expired_links():
    """Remove expired links from the database"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = get_current_utc().isoformat()
    # Remove time-expired links
    c.execute("DELETE FROM links WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
    # Remove click-limit expired links
    c.execute("DELETE FROM links WHERE max_clicks > 0 AND click_count >= max_clicks")
    conn.commit()
    conn.close()

def is_valid_url(url: str) -> bool:
    """Validate if the URL has a proper format"""
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return url_pattern.match(url) is not None

def perform_redirect():
    """Handle redirection when someone visits a short link"""
    query_params = st.query_params
    if "code" in query_params:
        code = query_params["code"]
        info = get_link_info(code)
        
        if info is None:
            st.error("❌ Invalid, expired, or used‑up short link.")
            st.stop()
        
        if info["expires_at"] and datetime.now(timezone.utc) > info["expires_at"]:
            st.error("⏰ This short link has expired.")
            conn = sqlite3.connect(DB_NAME)
            conn.execute("DELETE FROM links WHERE code = ?", (code,))
            conn.commit()
            conn.close()
            st.stop()
        
        if info["max_clicks"] > 0 and info["click_count"] >= info["max_clicks"]:
            st.error("🔁 This short link has reached its click limit.")
            st.stop()
        
        # Increment click count and redirect
        increment_click_count(code)
        st.markdown(
            f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta http-equiv="refresh" content="0; url={info['long_url']}">
                <script>window.location.href = "{info['long_url']}";</script>
            </head>
            <body>
                <p>Redirecting to your file... <a href="{info['long_url']}">Click here if not redirected.</a></p>
            </body>
            </html>
            """,
            unsafe_allow_html=True
        )
        st.stop()

# ==================== MAIN APP ====================
def main():
    # Page configuration
    st.set_page_config(
        page_title="Temporary URL Shortener",
        page_icon="🔗",
        layout="centered",
        initial_sidebar_state="collapsed"
    )
    
    # Handle redirects first
    perform_redirect()
    
    # Clean up expired links
    cleanup_expired_links()
    
    # ==================== HEADER SECTION ====================
    st.title("🔗 Temporary URL Shortener")
    st.markdown("Create short links that **self‑destruct** after a time limit or number of clicks.")
    st.markdown("---")
    
    # ==================== SESSION STATE ====================
    if 'generated_short_code' not in st.session_state:
        st.session_state.generated_short_code = None
    if 'generated_expiry' not in st.session_state:
        st.session_state.generated_expiry = None
    if 'generated_clicks' not in st.session_state:
        st.session_state.generated_clicks = None
    if 'generated_long_url' not in st.session_state:
        st.session_state.generated_long_url = None
    
    # ==================== CREATE SHORT LINK FORM ====================
    with st.container():
        st.subheader("📝 Create New Short Link")
        
        with st.form("create_short_link_form"):
            long_url = st.text_input(
                "**Long URL** (the file or page you want to share)", 
                placeholder="https://drive.google.com/your-secret-file.zip?dl=1",
                help="This URL will be completely hidden from recipients"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                expiry_hours = st.number_input(
                    "**Expiry Time**", 
                    min_value=0.0, 
                    value=24.0, 
                    step=1.0,
                    format="%.0f",
                    help="0 = never expires (but click limit still applies)"
                )
                expiry_text = "Never" if expiry_hours == 0 else f"{expiry_hours:.0f} hours"
                st.caption(f"⏰ Expires: {expiry_text}")
            
            with col2:
                max_clicks = st.number_input(
                    "**Max Clicks**", 
                    min_value=1, 
                    value=10, 
                    step=1,
                    help="Link becomes invalid after this many uses"
                )
                st.caption(f"🖱️ Will expire after {max_clicks} click(s)")
            
            submitted = st.form_submit_button("✨ Generate Short Link", use_container_width=True, type="primary")
        
        if submitted and long_url.strip():
            if not is_valid_url(long_url):
                st.error("⚠️ Please enter a valid URL starting with http:// or https://")
            else:
                # Generate and store the short link
                code = generate_short_code(long_url)
                store_link(code, long_url, expiry_hours, max_clicks)
                
                # Store in session state
                st.session_state.generated_short_code = code
                st.session_state.generated_expiry = expiry_hours
                st.session_state.generated_clicks = max_clicks
                st.session_state.generated_long_url = long_url
                
                st.success("✅ Short link created successfully!")
                st.rerun()
    
    # ==================== DISPLAY GENERATED SHORT LINK ====================
    if st.session_state.generated_short_code:
        code = st.session_state.generated_short_code
        
        st.markdown("---")
        st.markdown("## 🎉 Your Short Link Is Ready!")
        
        # Success message with info
        st.info("🔒 **The original long URL is completely hidden from recipients**")
        
        # Display short code prominently
        st.markdown("### 📋 Short Code:")
        st.markdown(f"# `{code}`")
        
        # Create columns for different copy methods
        st.markdown("### 📌 Copy Your Short Link:")
        
        # Method 1: st.code with built-in copy button (BEST METHOD)
        short_url_partial = f"?code={code}"
        st.markdown("**Option 1: Click the copy icon in the box below**")
        st.code(short_url_partial, language="text")
        st.caption("💡 **Click the 📋 icon in the top-right corner of the box above**")
        
        # Method 2: Text input for manual selection
        st.markdown("**Option 2: Select and copy manually**")
        st.text_input(
            "Select all text below and press Ctrl+C (or Cmd+C on Mac):",
            value=short_url_partial,
            key="manual_copy_url",
            disabled=False,
            label_visibility="collapsed"
        )
        
        # Method 3: Display what the full URL will look like
        st.markdown("### 📍 Full URL Preview:")
        st.info(f"`https://maapnext-url-shortener.streamlit.app/?code={code}`")
        #st.caption("This is your live short link URL when deployed")
                
        # Link details
        st.markdown("### 📊 Link Details:")
        details_col1, details_col2, details_col3 = st.columns(3)
        with details_col1:
            st.metric("Short Code", code)
        with details_col2:
            expiry_display = "Never" if st.session_state.generated_expiry == 0 else f"{st.session_state.generated_expiry:.0f} hours"
            st.metric("Expires", expiry_display)
        with details_col3:
            st.metric("Max Clicks", st.session_state.generated_clicks)
        
        # Hidden original URL (for your reference only)
        with st.expander("🔒 Original URL (hidden from recipients)"):
            st.code(st.session_state.generated_long_url, language="text")
            st.caption("This URL is never shown to people who receive the short link")
        
        # Reset button
        st.markdown("---")
        col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
        with col_btn2:
            if st.button("🔄 Create Another Short Link", use_container_width=True):
                st.session_state.generated_short_code = None
                st.rerun()
    
    # ==================== MANAGE ACTIVE LINKS ====================
    st.markdown("---")
    with st.expander("📋 Manage Active Short Links", expanded=False):
        conn = sqlite3.connect(DB_NAME)
        rows = conn.execute("SELECT code, long_url, expires_at, max_clicks, click_count, created_at FROM links ORDER BY created_at DESC LIMIT 50").fetchall()
        conn.close()
        
        if rows:
            st.markdown("**Your active short links:**")
            
            for row in rows:
                code, long_url, expires_at, max_clicks, clicks, created_at = row
                
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    
                    with col1:
                        st.markdown(f"**Code:** `{code}`")
                        st.caption(f"Original: `{long_url[:60]}...`" if len(long_url) > 60 else f"Original: `{long_url}`")
                        st.caption(f"Clicks: {clicks}/{max_clicks}")
                        if expires_at:
                            exp_date = datetime.fromisoformat(expires_at)
                            st.caption(f"Expires: {exp_date.strftime('%Y-%m-%d %H:%M')}")
                        else:
                            st.caption("Expires: Never")
                    
                    with col2:
                        if st.button(f"📋 Copy Link", key=f"copy_btn_{code}"):
                            st.code(f"?code={code}", language="text")
                            st.info(f"Copy the URL above (click the 📋 icon)")
                    
                    with col3:
                        # Test link button
                        if st.button(f"🔗 Test", key=f"test_btn_{code}"):
                            st.markdown(f"[Click to test the short link](?code={code})")
                            st.success(f"Test link: `?code={code}`")
                    
                    with col4:
                        if st.button(f"🗑️ Delete", key=f"delete_btn_{code}"):
                            conn = sqlite3.connect(DB_NAME)
                            conn.execute("DELETE FROM links WHERE code = ?", (code,))
                            conn.commit()
                            conn.close()
                            st.success(f"Deleted short link: {code}")
                            st.rerun()
                    
                    st.markdown("---")
        else:
            st.info("📭 No active short links yet. Create your first one above!")
    
    # ==================== STATISTICS SECTION ====================
    with st.expander("📊 Statistics", expanded=False):
        conn = sqlite3.connect(DB_NAME)
        total_links = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        total_clicks = conn.execute("SELECT SUM(click_count) FROM links").fetchone()[0]
        expired_links = conn.execute("SELECT COUNT(*) FROM links WHERE expires_at IS NOT NULL AND expires_at < ?", 
                                      (get_current_utc().isoformat(),)).fetchone()[0]
        conn.close()
        
        col_stat1, col_stat2, col_stat3 = st.columns(3)
        with col_stat1:
            st.metric("Total Active Links", total_links)
        with col_stat2:
            st.metric("Total Clicks", total_clicks or 0)
        with col_stat3:
            st.metric("Expired Links", expired_links)
    
    # ==================== FOOTER ====================
    st.markdown("---")
    st.markdown("### 📖 How It Works:")
    
    col_guide1, col_guide2, col_guide3 = st.columns(3)
    with col_guide1:
        st.markdown("**1️⃣ Create**")
        st.markdown("Enter your long file URL and set expiry time or click limit")
    with col_guide2:
        st.markdown("**2️⃣ Copy**")
        st.markdown("Click the 📋 icon in the code box to copy the short link")
    with col_guide3:
        st.markdown("**3️⃣ Share**")
        st.markdown("Send the short link to others - the original URL stays hidden")
    
    st.markdown("---")
    st.caption("🔒 **Privacy Guarantee:** Your original long URLs are never exposed to recipients. Links self-destruct automatically based on your settings.")
    st.caption(f"🕐 Current server time (UTC): {get_current_utc().strftime('%Y-%m-%d %H:%M:%S')}")

# ==================== RUN THE APP ====================
if __name__ == "__main__":
    main()
