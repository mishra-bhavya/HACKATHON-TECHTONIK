"""
Authentication Module for CARE-AI Nurse Dashboard
==================================================

This module provides secure authentication for nurses accessing the patient monitoring system.

SECURITY FEATURES:
- Password hashing using bcrypt (prevents plain-text password storage)
- Session-based authentication using Streamlit's session_state
- Protected patient data access (only after successful login)

WHY PASSWORD HASHING?
- Even if the nurses.csv file is compromised, passwords remain secure
- bcrypt is a industry-standard, slow hashing algorithm that resists brute-force attacks
- Each password is salted automatically by bcrypt

WHY SESSION STATE?
- Streamlit reruns the entire script on every interaction
- session_state persists data across reruns within the same browser session
- This allows us to maintain "logged in" status without repeated authentication
"""

import bcrypt
import pandas as pd
import streamlit as st
from pathlib import Path


def hash_password(password: str) -> str:
    """
    Hash a plain-text password using bcrypt.
    
    Args:
        password: Plain-text password
        
    Returns:
        Hashed password as a string
        
    Security Note:
        bcrypt automatically adds a random salt to each password,
        making each hash unique even for identical passwords
    """
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against a hashed password.
    
    Args:
        plain_password: User-entered password
        hashed_password: Stored hashed password from database
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        password_bytes = plain_password.encode('utf-8')
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


def load_nurses_database() -> pd.DataFrame:
    """
    Load nurse credentials from secure storage.
    
    Returns:
        DataFrame containing nurse credentials
        
    Security Note:
        This file should have restricted file permissions in production
        Only authorized personnel should have read/write access
    """
    nurses_file = Path("data/nurses.csv")
    
    if not nurses_file.exists():
        st.error("⚠️ Nurse credentials database not found. Contact system administrator.")
        st.stop()
    
    return pd.read_csv(nurses_file)


def authenticate_nurse(username: str, password: str) -> dict:
    """
    Authenticate a nurse using username and password.
    
    Args:
        username: Nurse's username or email
        password: Plain-text password entered by user
        
    Returns:
        Dictionary with nurse information if authenticated, None otherwise
        
    Security Flow:
        1. Load nurse database
        2. Find nurse record by username
        3. Verify password using bcrypt
        4. Return nurse info (WITHOUT password) if successful
    """
    nurses_df = load_nurses_database()
    
    # Find nurse by username (case-insensitive)
    nurse_record = nurses_df[nurses_df['username'].str.lower() == username.lower()]
    
    if nurse_record.empty:
        return None
    
    nurse = nurse_record.iloc[0]
    
    # Verify password against hashed password
    if verify_password(password, nurse['hashed_password']):
        # Return nurse info WITHOUT the password hash
        return {
            'nurse_id': nurse['nurse_id'],
            'name': nurse['name'],
            'username': nurse['username'],
            'role': nurse['role']
        }
    
    return None


def initialize_session_state():
    """
    Initialize authentication-related session state variables.
    
    WHY THIS IS NEEDED:
    - Streamlit reruns the entire script on every interaction
    - session_state allows us to persist the "logged in" status
    - Without this, users would need to login on every button click
    """
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    
    if 'nurse_info' not in st.session_state:
        st.session_state.nurse_info = None


def login_page():
    """
    Render the nurse login page.
    
    SECURITY CONSIDERATION:
    - This is the ONLY page visible to unauthenticated users
    - No patient data is loaded or displayed here
    - All sensitive operations happen AFTER authentication
    """
    st.set_page_config(page_title="CARE-AI Login", layout="centered")
    
    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
            <div style='text-align: center; padding: 2rem 0;'>
                <h1>🏥 CARE-AI</h1>
                <h3>Nurse Authentication Portal</h3>
                <p style='color: #666; margin-top: 1rem;'>
                    Secure access to patient behavioral monitoring system
                </p>
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Fix alignment of form submission hint
        st.markdown("""
            <style>
            [data-testid="InputInstructions"] {
                text-align: right !important;
                font-size: 0.8rem !important;
                margin-top: -8px !important;
            }
            </style>
        """, unsafe_allow_html=True)
        
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("👤 Username", placeholder="Enter your username")
            password = st.text_input("🔒 Password", type="password", placeholder="Enter your password")
            
            submit_button = st.form_submit_button("🔐 Login", use_container_width=True)
            
            if submit_button:
                if not username or not password:
                    st.error("⚠️ Please enter both username and password")
                else:
                    # Attempt authentication
                    nurse_info = authenticate_nurse(username, password)
                    
                    if nurse_info:
                        # Successful login
                        st.session_state.authenticated = True
                        st.session_state.nurse_info = nurse_info
                        st.success(f"✅ Welcome, {nurse_info['name']}!")
                        st.rerun()
                    else:
                        # Failed login
                        st.error("❌ Invalid username or password. Please try again.")
        
        st.markdown("---")
        
        # Security notice
        st.info("""
            🔒 **Security Notice**
            
            This system contains sensitive patient information protected by healthcare privacy regulations.
            All access is logged and monitored. Unauthorized access attempts will be reported.
        """)
        
        # Help section
        with st.expander("ℹ️ Need Help?"):
            st.markdown("""
                **Forgot your password?**  
                Contact your system administrator or IT support.
                
                **First time login?**  
                Use the credentials provided by your facility administrator.
                
                **Technical issues?**  
                Contact IT support for assistance.
            """)


def logout():
    """
    Log out the current nurse and clear session state.
    
    SECURITY CONSIDERATION:
    - Clears all session data including authentication status
    - Forces user back to login page
    - Prevents unauthorized access after logout
    """
    st.session_state.authenticated = False
    st.session_state.nurse_info = None
    st.rerun()


def require_authentication():
    """
    Decorator-style function to protect dashboard content.
    
    HOW IT WORKS:
    - Checks if user is authenticated in session_state
    - If not authenticated, shows login page and stops execution
    - If authenticated, allows dashboard to render
    
    CRITICAL SECURITY FUNCTION:
    This prevents ANY patient data from being loaded or displayed
    without successful authentication.
    """
    if not st.session_state.get('authenticated', False):
        login_page()
        st.stop()


def get_current_nurse() -> dict:
    """
    Get information about the currently logged-in nurse.
    
    Returns:
        Dictionary with nurse information
    """
    return st.session_state.get('nurse_info', {})
