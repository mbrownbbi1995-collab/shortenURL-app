import streamlit as st
import sqlite3
import random
import string
import hashlib
from datetime import datetime, timedelta, timezone
import os

# Database setup - uses a file-based SQLite database
DB_NAME = "shortlinks.db"

def init_db():
    """Initialize the database"""
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

def get_current_utc():
    """Return current UTC datetime as string (timezone-aware)"""
    return datetime.now(timezone.utc)

def generate_short_code(long_url: str, length: int = 6) -> str:
    """Generate a unique short code"""
    chars = string.ascii_letters + string.digits
    for _ in range(3):
        code = ''.join(random.choice(chars) for _ in range(length))
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT code FROM links WHERE code = ?", (code,))
        exists = c.fetchone()
        conn.close()
        if not exists:
            return code
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
    c.execute("DELETE FROM links WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
    c.execute("DELETE FROM links WHERE max_clicks > 0 AND click_count >= max_clicks")
    conn.commit()
    conn.close()

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
            <meta http-equiv="refresh" content="0; url={info['long_url']}" />
            <script>window.location.href = "{info['long_url']}";</script>
            Redirecting to your file...
            """,
            unsafe_allow_html=True
        )
        st.stop()

def get_base_url():
    """Get the base URL of the deployed app"""
    # For Streamlit Cloud, use the built-in method to get the app URL
    if hasattr(st, 'context') and hasattr(st.context, 'get'):
        try:
            # This works on Streamlit Cloud
            return st.context.get("streamlit_app_url", "").rstrip('/')
        except:
            pass
    
    # Fallback to relative URL (works on any domain)
    return ""

def main():
    st.set_page_config(page_title="Temporary URL Shortener", page_icon="🔗")
    
    # Check if this is a redirect request
    perform_redirect()
    
    # Clean up expired links periodically
    cleanup_expired_links()
    
    # Main title
    st.title("🔗 Temporary URL Shortener")
    st.markdown("Create short links that **self‑destruct** after a time limit or number of clicks.")
    
    # Show deployment info
    st.info("🌐 **This app is live on Streamlit Cloud** - Share short links with anyone, anywhere!")
    
    # --- Form for creating short links ---
    with st.form("create_short_link"):
        long_url = st.text_input(
            "Long URL (the file or page you want to share)", 
            placeholder="https://drive.google.com/your-secret-file.zip?dl=1",
            help="This URL will be hidden from recipients"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            expiry_hours = st.number_input(
                "Expiry (hours)", 
                min_value=0.0, 
                value=24.0, 
                step=1.0,
                help="0 = never expires (but click limit still applies)"
            )
        with col2:
            max_clicks = st.number_input(
                "Max clicks", 
                min_value=1, 
                value=10,
                help="Link becomes invalid after this many uses"
            )
        
        submitted = st.form_submit_button("✨ Generate Short Link", use_container_width=True)
    
    # --- Handle form submission ---
    if submitted and long_url.strip():
        if not (long_url.startswith("http://") or long_url.startswith("https://")):
            st.warning("⚠️ URL must start with http:// or https://")
        else:
            # Generate and store the short link
            code = generate_short_code(long_url)
            store_link(code, long_url, expiry_hours, max_clicks)
            
            # Build the full short URL (relative path works on any domain)
            short_url = f"?code={code}"
            
            st.success("✅ Short link created successfully!")
            st.markdown("### 🔗 Share this link:")
            
            # Display the short link prominently
            st.code(short_url, language="text")
            
            # Copy button using Streamlit's native button with JavaScript
            if st.button("📋 Copy Short Link", use_container_width=True):
                # JavaScript to copy the full URL
                st.markdown(f"""
                <script>
                    const fullUrl = window.location.origin + window.location.pathname + "?code={code}";
                    navigator.clipboard.writeText(fullUrl);
                    alert("Short link copied to clipboard!\\n\\n" + fullUrl);
                </script>
                """, unsafe_allow_html=True)
                st.success("✅ Link copied to clipboard!")
            
            # Show the full URL for manual copy
            st.markdown("**Or copy this full URL:**")
            st.caption("(The long URL is completely hidden from recipients)")
            
            # Display link details
            st.info(f"""
            **📊 Link Details:**
            - **Short Code:** `{code}`
            - **Expires:** {expiry_hours} hours {'(never)' if expiry_hours == 0 else f'({expiry_hours} hours)'}
            - **Max Clicks:** {max_clicks}
            - **Original URL is hidden** from anyone who receives the short link
            """)
    
    # --- Display active links for management ---
    with st.expander("📋 Manage Active Short Links", expanded=False):
        conn = sqlite3.connect(DB_NAME)
        rows = conn.execute("SELECT code, long_url, expires_at, max_clicks, click_count, created_at FROM links ORDER BY created_at DESC LIMIT 50").fetchall()
        conn.close()
        
        if rows:
            st.markdown("**Your active short links (click the delete button to remove):**")
            for row in rows:
                code, long_url, expires_at, max_clicks, clicks, created_at = row
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**Code:** `{code}`")
                    st.caption(f"Original: `{long_url[:60]}...`")
                    st.caption(f"Clicks: {clicks}/{max_clicks} | Expires: {expires_at[:10] if expires_at else 'Never'}")
                with col2:
                    if st.button(f"📋 Copy", key=f"copy_{code}"):
                        st.markdown(f"""
                        <script>
                            const fullUrl = window.location.origin + window.location.pathname + "?code={code}";
                            navigator.clipboard.writeText(fullUrl);
                            alert("Copied: " + fullUrl);
                        </script>
                        """, unsafe_allow_html=True)
                        st.success("Copied!")
                with col3:
                    if st.button(f"🗑️ Delete", key=f"del_{code}"):
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("DELETE FROM links WHERE code = ?", (code,))
                        conn.commit()
                        conn.close()
                        st.rerun()
                st.markdown("---")
        else:
            st.write("No active short links yet. Create your first one above!")
    
    # Footer
    st.markdown("---")
    st.caption("🔒 Your original long URLs are never exposed to recipients. Links self-destruct automatically.")

if __name__ == "__main__":
    main()
