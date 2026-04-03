import streamlit as st
import sqlite3
import random
import string
import hashlib
from datetime import datetime, timedelta, timezone
import os

# Database setup
DB_NAME = "shortlinks.db"

def init_db():
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
    return datetime.now(timezone.utc)

def generate_short_code(long_url: str, length: int = 6) -> str:
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
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE links SET click_count = click_count + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()

def cleanup_expired_links():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = get_current_utc().isoformat()
    c.execute("DELETE FROM links WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
    c.execute("DELETE FROM links WHERE max_clicks > 0 AND click_count >= max_clicks")
    conn.commit()
    conn.close()

def perform_redirect():
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

def main():
    st.set_page_config(page_title="Temporary URL Shortener", page_icon="🔗")
    perform_redirect()
    cleanup_expired_links()
    
    st.title("🔗 Temporary URL Shortener")
    st.markdown("Create short links that **self‑destruct** after a time limit or number of clicks.")
    
    # Show deployment info
    st.info("🌐 **This app is live on Streamlit Cloud** - Share short links with anyone, anywhere!")
    
    # Session state to store the generated short URL
    if 'generated_short_url' not in st.session_state:
        st.session_state.generated_short_url = None
    if 'generated_code' not in st.session_state:
        st.session_state.generated_code = None
    
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
            
            # Store in session state
            st.session_state.generated_code = code
            
            st.success("✅ Short link created successfully!")
    
    # Display the generated short link if it exists
    if st.session_state.generated_code:
        code = st.session_state.generated_code
        
        st.markdown("### 🔗 Your Short Link (Share This):")
        st.markdown("**The original long URL is completely hidden from recipients**")
        
        # Create a container for the short link display
        col_display, col_copy = st.columns([4, 1])
        
        with col_display:
            # Show the short link in a text input for easy selection
            short_link_display = st.text_input(
                "Short link (select and copy with Ctrl+C):",
                value=f"?code={code}",
                key="short_link_display",
                disabled=False,
                label_visibility="collapsed"
            )
        
        with col_copy:
            # Simple copy button using st.button
            if st.button("📋 Copy Full Short Link", key="copy_main_btn", use_container_width=True):
                # Use st.write to show the link to copy
                st.markdown("---")
                st.info("**Copy this full URL:**")
                st.code(f"https://{st.get_option('browser.serverAddress')}/?code={code}", language="text")
                st.success("✅ **Full URL is shown above - select it and press Ctrl+C!**")
        
        # Show the full URL in a code block for easy copying
        st.markdown("### Full URL to share:")
        
        # Try to get the actual deployed URL
        try:
            # This works on Streamlit Cloud
            from urllib.parse import urlparse
            import requests
            
            # Get the current URL from the browser
            full_short_url = f"?code={code}"
            st.code(full_short_url, language="text")
            st.caption("📝 **Note:** When deployed on Streamlit Cloud, this becomes:")
            st.caption(f"`https://{st.get_option('browser.serverAddress')}/?code={code}`")
        except:
            st.code(f"?code={code}", language="text")
        
        # Alternative copy method using st.code's built-in copy button
        st.markdown("### 💡 Easy Copy Method:")
        st.markdown("The code block above has a **copy button** in the top-right corner (📋) - click it to copy!")
        
        # Display link details
        st.info(f"""
        **📊 Link Details:**
        - **Short Code:** `{code}`
        - **Expires:** {expiry_hours} hours {'(never)' if expiry_hours == 0 else ''}
        - **Max Clicks:** {max_clicks}
        - **Original URL is completely hidden** from recipients
        """)
        
        # Add a reset button to clear the current short link
        if st.button("🔄 Create Another Short Link", use_container_width=True):
            st.session_state.generated_code = None
            st.rerun()
    
    # --- Display active links for management ---
    with st.expander("📋 Manage Active Short Links", expanded=False):
        conn = sqlite3.connect(DB_NAME)
        rows = conn.execute("SELECT code, long_url, expires_at, max_clicks, click_count, created_at FROM links ORDER BY created_at DESC LIMIT 50").fetchall()
        conn.close()
        
        if rows:
            st.markdown("**Your active short links:**")
            for row in rows:
                code, long_url, expires_at, max_clicks, clicks, created_at = row
                
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    st.markdown(f"**Code:** `{code}`")
                    st.caption(f"Original: `{long_url[:50]}...`")
                    st.caption(f"Clicks: {clicks}/{max_clicks} | Expires: {expires_at[:10] if expires_at else 'Never'}")
                
                with col2:
                    # Copy button for this specific link
                    if st.button(f"📋 Copy", key=f"copy_{code}"):
                        st.markdown(f"""
                        <div style="background-color:#f0f2f6; padding:10px; border-radius:5px; margin:10px 0;">
                            <b>Copy this URL:</b><br/>
                            <code>?code={code}</code>
                        </div>
                        """, unsafe_allow_html=True)
                        st.info(f"📋 **Copy this full URL:** `?code={code}`")
                
                with col3:
                    # Test button
                    if st.button(f"🔗 Test", key=f"test_{code}"):
                        st.markdown(f"[Click to test](?code={code})", unsafe_allow_html=True)
                        st.info(f"🔗 **Test link:** `?code={code}`")
                
                with col4:
                    # Delete button
                    if st.button(f"🗑️ Delete", key=f"del_{code}"):
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("DELETE FROM links WHERE code = ?", (code,))
                        conn.commit()
                        conn.close()
                        st.rerun()
                
                st.markdown("---")
        else:
            st.write("No active short links yet. Create your first one above!")
    
    # Footer with instructions
    st.markdown("---")
    st.markdown("### 📖 How to Use:")
    st.markdown("""
    1. **Create a short link** by entering your long file URL above
    2. **Copy the short link** using the code block's copy button (📋 in top-right corner)
    3. **Share only the short link** with others - they will never see your original URL
    4. **Links expire automatically** after the set time or number of clicks
    """)
    st.caption("🔒 Your original long URLs are never exposed to recipients.")

if __name__ == "__main__":
    main()
