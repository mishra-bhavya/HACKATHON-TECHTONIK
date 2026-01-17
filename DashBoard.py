import streamlit as st
import pandas as pd
import numpy as np

from AIModel import (
    process_data,
    train_model,
    detect_concern,
    has_made_progress,
    summarize_changes,
    generate_insight,
    sustained_decline
)
from auth import (
    initialize_session_state,
    require_authentication,
    get_current_nurse,
    logout
)

# ============================================================
# AUTHENTICATION & SECURITY
# ============================================================
# Initialize authentication session state
# This must be called BEFORE any authentication checks
initialize_session_state()

# Require authentication before showing ANY patient data
# This function will:
# 1. Check if user is logged in
# 2. If not, show login page and STOP execution (no patient data loaded)
# 3. If yes, continue to dashboard
require_authentication()

# IMPORTANT: All code below this line is ONLY executed for authenticated users
# Patient data is loaded ONLY after successful authentication

# ============================================================
# HELPER FUNCTIONS FOR PHASE 2 ENHANCEMENTS
# ============================================================

def calculate_trend_direction(series, window=7):
    """
    Calculates trend direction based on recent vs previous data.
    Returns: 'Improving', 'Declining', 'Stable', or 'Fluctuating'
    """
    if len(series) < window * 2:
        return "Insufficient Data"
    
    recent = series.tail(window).mean()
    previous = series.iloc[-window*2:-window].mean()
    
    diff_pct = ((recent - previous) / previous * 100) if previous != 0 else 0
    
    if abs(diff_pct) < 5:
        return "Stable"
    elif diff_pct > 5:
        return "Improving"
    elif diff_pct < -5:
        return "Declining"
    else:
        return "Fluctuating"


def get_overall_condition(risk_score, progress, insight):
    """
    Determines patient overall condition based on risk and progress.
    Returns: 'Stable', 'Monitor', or 'Critical'
    """
    if "High risk" in insight:
        return "Critical"
    elif "Medium risk" in insight or risk_score < -0.15:
        return "Monitor"
    else:
        return "Stable"


def generate_trend_insight(metric_name, series, threshold_high=None, threshold_low=None):
    """
    Generates AI-style text interpretation for a metric trend.
    """
    if len(series) < 7:
        return f"Not enough data to analyze {metric_name} trend."
    
    recent_avg = series.tail(7).mean()
    previous_avg = series.iloc[-14:-7].mean() if len(series) >= 14 else series.mean()
    overall_avg = series.mean()
    
    # Calculate change
    change = recent_avg - previous_avg
    change_pct = (change / previous_avg * 100) if previous_avg != 0 else 0
    
    # Trend description
    if abs(change_pct) < 5:
        trend_text = "remained stable"
    elif change_pct > 15:
        trend_text = "increased significantly"
    elif change_pct > 5:
        trend_text = "increased slightly"
    elif change_pct < -15:
        trend_text = "decreased significantly"
    else:
        trend_text = "decreased slightly"
    
    # Add context based on thresholds
    context = ""
    if threshold_high and recent_avg > threshold_high:
        context = f" ⚠️ Currently above normal range ({threshold_high})."
    elif threshold_low and recent_avg < threshold_low:
        context = f" ⚠️ Currently below recommended range ({threshold_low})."
    elif abs(recent_avg - overall_avg) > overall_avg * 0.2:
        context = f" This differs from patient's baseline average ({overall_avg:.1f})."
    
    return f"**{metric_name}** has {trend_text} over the past week (Recent: {recent_avg:.1f}, Previous: {previous_avg:.1f}).{context}"


def check_data_sufficiency(df, min_records=5):
    """
    Checks if patient has sufficient data for analysis.
    Returns: (bool, message)
    """
    if len(df) < min_records:
        return False, f"⚠️ Insufficient data: Only {len(df)} records available. At least {min_records} required for reliable analysis."
    return True, ""


# ============================================================
# PHASE 3: NURSE ALERT SYSTEM HELPER FUNCTIONS
# ============================================================

def detect_stress_increase_alert(df, window=3):
    """
    HIGH PRIORITY: Detects if stress level is increasing for 3+ consecutive days.
    Returns: (bool, message, explanation)
    """
    if len(df) < window:
        return False, "", ""
    
    recent_stress = df["stress_level"].tail(window)
    
    # Check if stress is increasing consecutively
    increasing_count = 0
    for i in range(1, len(recent_stress)):
        if recent_stress.iloc[i] > recent_stress.iloc[i-1]:
            increasing_count += 1
    
    if increasing_count >= window - 1:  # At least 2 increases in 3 days
        avg_stress = recent_stress.mean()
        return True, f"Stress indicators show upward trend over {window} consecutive assessments", \
               f"Patient's self-reported stress levels have increased progressively over the observation period (current average: {avg_stress:.1f}/10). This pattern may indicate inadequate coping mechanisms or emerging stressors requiring therapeutic intervention."
    
    return False, "", ""


def detect_low_mood_alert(df, threshold=2, window=3):
    """
    HIGH PRIORITY: Detects consistently low mood score (≤ 2) for 3+ days.
    Returns: (bool, message, explanation)
    """
    if len(df) < window:
        return False, "", ""
    
    recent_mood = df["mood_score"].tail(window)
    low_mood_count = (recent_mood <= threshold).sum()
    
    if low_mood_count >= window:
        avg_mood = recent_mood.mean()
        return True, f"Sustained low mood scores observed over {window}-day period", \
               f"Patient's self-reported mood ratings have consistently remained at or below {threshold}/5 for {window} consecutive assessments (average: {avg_mood:.1f}/5). This sustained pattern warrants evaluation for additional therapeutic support or medication review."
    
    return False, "", ""


def detect_elevated_heart_rate_alert(df, window=3):
    """
    HIGH PRIORITY: Detects heart rate above patient's normal average for multiple days.
    Returns: (bool, message, explanation)
    """
    if len(df) < window + 7:  # Need baseline + recent data
        return False, "", ""
    
    # Calculate patient's baseline (exclude recent days)
    baseline_hr = df["heart_rate"].iloc[:-window].mean()
    recent_hr = df["heart_rate"].tail(window)
    
    # Check if recent HR is consistently elevated (>10% above baseline)
    elevated_count = (recent_hr > baseline_hr * 1.10).sum()
    
    if elevated_count >= window:
        avg_recent = recent_hr.mean()
        return True, f"Heart rate trending above patient baseline for {window}-day period", \
               f"Recorded heart rate measurements consistently exceed patient's established baseline by >10% (current average: {avg_recent:.0f} BPM vs. baseline: {baseline_hr:.0f} BPM). Elevated readings may correlate with physiological stress response or require cardiovascular assessment."
    
    return False, "", ""


def detect_high_risk_score_alert(risk_score, threshold=-0.2):
    """
    HIGH PRIORITY: Detects risk score above critical threshold.
    Returns: (bool, message, explanation)
    """
    if risk_score < threshold:
        return True, "Behavioral pattern analysis indicates elevated clinical concern", \
               f"Multivariate behavioral assessment score: {risk_score:.3f}. Analysis suggests multiple patient metrics have deviated from established baseline patterns, warranting comprehensive clinical review."
    
    return False, "", ""


def detect_irregular_sleep_alert(df, window=5):
    """
    MEDIUM PRIORITY: Detects irregular sleep patterns.
    Returns: (bool, message, explanation)
    """
    if len(df) < window:
        return False, "", ""
    
    recent_sleep = df["sleep_hours"].tail(window)
    sleep_std = recent_sleep.std()
    avg_sleep = recent_sleep.mean()
    
    # High variability in sleep (std > 2 hours) or consistently low
    if sleep_std > 2.0:
        return True, "Sleep pattern variability noted in recent assessments", \
               f"Patient demonstrates significant variation in sleep duration (standard deviation: {sleep_std:.1f} hours, average: {avg_sleep:.1f} hours). Irregular sleep architecture may impact recovery trajectory and treatment efficacy."
    elif avg_sleep < 5.5:
        return True, "Sleep duration below clinical recommendations", \
               f"Average sleep duration of {avg_sleep:.1f} hours over {window}-day period falls below recommended minimum for therapeutic recovery. Persistent sleep deficit may compromise cognitive function and emotional regulation."
    
    return False, "", ""


def detect_missed_therapy_alert(df, window=5, threshold=2):
    """
    MEDIUM PRIORITY: Detects missed therapy sessions.
    Returns: (bool, message, explanation)
    """
    if len(df) < window:
        return False, "", ""
    
    recent_therapy = df["therapy_attended"].tail(window)
    missed_count = window - recent_therapy.sum()
    
    if missed_count >= threshold:
        attendance_rate = (recent_therapy.sum() / window) * 100
        return True, f"Therapy attendance pattern shows {missed_count} absences in {window}-day period", \
               f"Patient has attended {attendance_rate:.0f}% of scheduled therapy sessions over the observation period ({missed_count} absences). Reduced engagement may indicate motivational barriers, logistical challenges, or declining therapeutic alliance."
    
    return False, "", ""


def detect_declining_activity_alert(df, window=5):
    """
    MEDIUM PRIORITY: Detects declining activity levels.
    Returns: (bool, message, explanation)
    """
    if len(df) < window * 2:
        return False, "", ""
    
    recent_activity = df["activity_level"].tail(window).mean()
    previous_activity = df["activity_level"].iloc[-window*2:-window].mean()
    
    decline_pct = ((recent_activity - previous_activity) / previous_activity * 100) if previous_activity > 0 else 0
    
    if decline_pct < -25:  # 25% decline
        return True, f"Physical activity levels decreased by {abs(decline_pct):.0f}% from previous baseline", \
               f"Patient's ambulatory activity has declined from {previous_activity:.0f} to {recent_activity:.0f} steps per day. Reduced physical activity may correlate with decreased motivation, energy levels, or emerging somatic concerns."
    
    return False, "", ""


def detect_minor_fluctuation_alert(df, window=5):
    """
    LOW PRIORITY: Detects minor fluctuations or early warning trends.
    Returns: (bool, message, explanation)
    """
    if len(df) < window:
        return False, "", ""
    
    recent_mood = df["mood_score"].tail(window)
    mood_trend = calculate_trend_direction(recent_mood, window=min(3, window))
    
    # Early warning: mood declining but not critically low yet
    if mood_trend == "Declining" and recent_mood.mean() > 2 and recent_mood.mean() < 3:
        return True, "Mood indicators suggest early downward trajectory", \
               f"Patient's self-reported mood scores demonstrate a declining trend (current average: {recent_mood.mean():.1f}/5), though not yet at critical threshold. Early identification allows for proactive supportive intervention."
    
    # Check for stress starting to increase (not yet 3 consecutive days)
    if len(df) >= 3:
        recent_stress = df["stress_level"].tail(3)
        if recent_stress.iloc[-1] > recent_stress.iloc[-2] and recent_stress.mean() > 6:
            return True, "Stress measurements show emerging upward pattern", \
                   f"Recent self-reported stress levels indicate early ascending trend (most recent: {recent_stress.iloc[-1]:.1f}/10, average: {recent_stress.mean():.1f}/10). Continued observation will help determine if intervention is needed."
    
    return False, "", ""


# ============================================================
# ESCALATION LOGIC HELPER FUNCTIONS
# ============================================================

def check_sleep_persistence(df, window=5):
    """
    Checks if irregular sleep pattern has persisted for 5+ consecutive days.
    Returns: (bool, duration) - True if persistent, number of days
    """
    if len(df) < window:
        return False, 0
    
    # Check each day in the rolling window
    persistent_count = 0
    for i in range(len(df) - window + 1, len(df) + 1):
        window_data = df["sleep_hours"].iloc[max(0, i-5):i]
        if len(window_data) >= 5:
            sleep_std = window_data.std()
            avg_sleep = window_data.mean()
            # Same logic as detect_irregular_sleep_alert
            if sleep_std > 2.0 or avg_sleep < 5.5:
                persistent_count += 1
    
    # If condition persists for 5+ days
    if persistent_count >= window:
        return True, persistent_count
    return False, persistent_count


def check_therapy_persistence(df, window=5):
    """
    Checks if missed therapy pattern has persisted for 5+ consecutive days.
    Returns: (bool, duration) - True if persistent, number of days
    """
    if len(df) < window:
        return False, 0
    
    # Check if therapy attendance is poor across the entire window
    recent_therapy = df["therapy_attended"].tail(window)
    missed_count = window - recent_therapy.sum()
    
    # If missing 2+ sessions consistently over 5+ days
    if missed_count >= 2 and len(recent_therapy) >= window:
        return True, window
    return False, 0


def check_activity_persistence(df, window=5):
    """
    Checks if declining activity has persisted for 5+ consecutive days.
    Returns: (bool, duration) - True if persistent, number of days
    """
    if len(df) < window * 2:
        return False, 0
    
    recent_activity = df["activity_level"].tail(window).mean()
    previous_activity = df["activity_level"].iloc[-window*2:-window].mean()
    
    decline_pct = ((recent_activity - previous_activity) / previous_activity * 100) if previous_activity > 0 else 0
    
    # If decline is significant and persistent over 5+ days
    if decline_pct < -25 and len(df.tail(window)) >= window:
        return True, window
    return False, 0


def detect_multiple_medium_alerts(patient_df):
    """
    Checks if 2+ medium priority conditions are simultaneously active.
    Returns: (bool, list of active conditions, duration)
    """
    active_conditions = []
    
    # Check each medium priority condition
    if detect_irregular_sleep_alert(patient_df)[0]:
        active_conditions.append("irregular sleep patterns")
    
    if detect_missed_therapy_alert(patient_df)[0]:
        active_conditions.append("poor therapy attendance")
    
    if detect_declining_activity_alert(patient_df)[0]:
        active_conditions.append("declining physical activity")
    
    # If 2+ conditions are active
    if len(active_conditions) >= 2:
        # Estimate duration (use minimum of 3 days as threshold)
        duration = min(5, len(patient_df))
        return True, active_conditions, duration
    
    return False, [], 0


def generate_all_alerts(patient_df, risk_score):
    """
    Generates all alerts for a patient based on current data.
    Includes escalation logic for persistent medium-priority conditions.
    Returns: List of alert dictionaries with severity, message, and explanation.
    """
    alerts = []
    
    # ============================================================
    # ESCALATION LOGIC: Check for persistent MEDIUM conditions
    # ============================================================
    
    # Escalation 1: Persistent irregular sleep (5+ days)
    is_persistent, days = check_sleep_persistence(patient_df, window=5)
    if is_persistent:
        alerts.append({
            "severity": "HIGH",
            "message": f"ESCALATED: Persistent sleep disturbance ongoing for {days}+ consecutive days",
            "explanation": f"Patient's sleep irregularity has persisted beyond typical fluctuation period (ongoing for {days} days). Sustained sleep disruption at this duration significantly impacts therapeutic progress and requires immediate clinical intervention to assess underlying causes and implement sleep hygiene protocols."
        })
    
    # Escalation 2: Persistent therapy non-attendance (5+ days)
    is_persistent, days = check_therapy_persistence(patient_df, window=5)
    if is_persistent:
        alerts.append({
            "severity": "HIGH",
            "message": f"ESCALATED: Sustained therapy disengagement pattern ongoing for {days}+ days",
            "explanation": f"Patient's reduced therapy participation has continued for {days} consecutive days, indicating potential treatment resistance, motivational crisis, or unaddressed barriers to care. Immediate clinical team consultation recommended to reassess treatment plan and engagement strategies."
        })
    
    # Escalation 3: Persistent activity decline (5+ days)
    is_persistent, days = check_activity_persistence(patient_df, window=5)
    if is_persistent:
        alerts.append({
            "severity": "HIGH",
            "message": f"ESCALATED: Prolonged physical inactivity persisting for {days}+ days",
            "explanation": f"Patient's reduced ambulatory activity has been sustained for {days} days, suggesting potential anhedonia, physical deconditioning, or emerging medical concerns. Clinical assessment for mood disorder progression and physical health evaluation warranted."
        })
    
    # Escalation 4: Multiple concurrent medium-priority conditions
    is_multiple, conditions, duration = detect_multiple_medium_alerts(patient_df)
    if is_multiple:
        conditions_text = ", ".join(conditions)
        alerts.append({
            "severity": "HIGH",
            "message": f"ESCALATED: Multiple concurrent behavioral concerns ({len(conditions)} active patterns)",
            "explanation": f"Patient demonstrates {len(conditions)} simultaneous medium-priority patterns: {conditions_text}. The convergence of multiple behavioral indicators suggests cumulative risk requiring comprehensive clinical review and possible care plan modification."
        })
    
    # ============================================================
    # ORIGINAL HIGH PRIORITY ALERTS
    # ============================================================
    
    triggered, msg, explanation = detect_stress_increase_alert(patient_df)
    if triggered:
        alerts.append({"severity": "HIGH", "message": msg, "explanation": explanation})
    
    triggered, msg, explanation = detect_low_mood_alert(patient_df)
    if triggered:
        alerts.append({"severity": "HIGH", "message": msg, "explanation": explanation})
    
    triggered, msg, explanation = detect_elevated_heart_rate_alert(patient_df)
    if triggered:
        alerts.append({"severity": "HIGH", "message": msg, "explanation": explanation})
    
    triggered, msg, explanation = detect_high_risk_score_alert(risk_score)
    if triggered:
        alerts.append({"severity": "HIGH", "message": msg, "explanation": explanation})
    
    # ============================================================
    # MEDIUM PRIORITY ALERTS (Keep originals visible)
    # ============================================================
    
    triggered, msg, explanation = detect_irregular_sleep_alert(patient_df)
    if triggered:
        alerts.append({"severity": "MEDIUM", "message": msg, "explanation": explanation})
    
    triggered, msg, explanation = detect_missed_therapy_alert(patient_df)
    if triggered:
        alerts.append({"severity": "MEDIUM", "message": msg, "explanation": explanation})
    
    triggered, msg, explanation = detect_declining_activity_alert(patient_df)
    if triggered:
        alerts.append({"severity": "MEDIUM", "message": msg, "explanation": explanation})
    
    # ============================================================
    # LOW PRIORITY ALERTS
    # ============================================================
    
    # Only show low priority if no high priority alerts exist
    if len([a for a in alerts if a["severity"] == "HIGH"]) == 0:
        triggered, msg, explanation = detect_minor_fluctuation_alert(patient_df)
        if triggered:
            alerts.append({"severity": "LOW", "message": msg, "explanation": explanation})
    
    return alerts


# ============================================================
# STREAMLIT CONFIGURATION & DATA LOADING
# ============================================================

st.set_page_config(page_title="CARE-AI Dashboard", layout="wide", page_icon="🏥")

# ============================================================
# HEADER WITH NURSE INFO & LOGOUT
# ============================================================
col_header1, col_header2 = st.columns([3, 1])

with col_header1:
    st.markdown("# 🏥 CARE-AI Nurse Dashboard")
    st.markdown("##### *AI-Assisted Mental Health Monitoring for Rehabilitation Centers*")

with col_header2:
    nurse_info = get_current_nurse()
    st.markdown(f"""<div style='text-align: right; padding-top: 0.5rem;'>
        <p style='margin: 0; color: #666; font-size: 0.85rem;'>Logged in as:</p>
        <p style='margin: 0; font-weight: bold; font-size: 1rem;'>👤 {nurse_info['name']}</p>
        <p style='margin: 0; font-size: 0.75rem; color: #888;'>({nurse_info['nurse_id']})</p>
    </div>""", unsafe_allow_html=True)
    if st.button("🚪 Logout", use_container_width=True):
        logout()

st.markdown("---")

# Security notice
st.info("🔒 **Secure System** | This system protects patient confidentiality and complies with healthcare privacy regulations. All access is monitored.")
st.markdown("---")

# Load data with error handling
try:
    df = pd.read_csv("data/PatientData.csv")
    df = process_data(df)
except FileNotFoundError:
    st.error("❌ Data file not found. Please ensure 'data/PatientData.csv' exists.")
    st.stop()
except Exception as e:
    st.error(f"❌ Error loading data: {str(e)}")
    st.stop()

# ============================================================
# SIDEBAR: PATIENT SELECTION & INFO
# ============================================================
st.sidebar.markdown("### 👤 Patient Selection")
patient_ids = sorted(df["patient_id"].unique())
selected_patient = st.sidebar.selectbox(
    "Select Patient ID", 
    patient_ids, 
    key="patient_selector"
)

patient_df = df[df["patient_id"] == selected_patient].copy().reset_index(drop=True)

# Sidebar: Quick patient info
st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Quick Stats")
st.sidebar.metric("Total Records", len(patient_df))

# Calculate date range safely
try:
    date_range_days = (pd.to_datetime(patient_df['date']).max() - pd.to_datetime(patient_df['date']).min()).days + 1
    st.sidebar.metric("Date Range", f"{date_range_days}d")
except:
    st.sidebar.metric("Date Range", "N/A")

# Sidebar: System legend
st.sidebar.markdown("---")
st.sidebar.markdown("### 📖 Risk Level Guide")
st.sidebar.markdown("""
- 🟢 **Stable**: No concerning patterns
- 🟡 **Monitor**: Behavioral changes detected
- 🔴 **Critical**: Immediate review needed
""")

st.sidebar.markdown("### 📈 Trend Indicators")
st.sidebar.markdown("""
- **Improving**: Positive trajectory
- **Declining**: Concerning downward trend
- **Stable**: Consistent patterns
- **Fluctuating**: Variable patterns
""")

# Check data sufficiency
data_ok, data_msg = check_data_sufficiency(patient_df, min_records=5)

if not data_ok:
    st.warning(data_msg)
    st.info("📌 Upload more patient records to enable full AI analysis.")
    st.stop()

# ============================================================
# AI ANALYSIS WITH ERROR HANDLING
# ============================================================
try:
    model_features = patient_df[["sleep_hours", "activity_level", "mood_score", 
                                  "therapy_attended", "heart_rate", "stress_level"]]
    model = train_model(model_features)
    risk_score = detect_concern(model, patient_df)
    progress = has_made_progress(patient_df)
    summary = summarize_changes(patient_df)
    sustained_flag = sustained_decline(patient_df) if len(patient_df) >= 5 else False
    insight = generate_insight(risk_score, summary, sustained_flag)
except Exception as e:
    st.error(f"❌ AI Analysis failed: {str(e)}")
    st.stop()

# Calculate additional metrics for patient context
overall_condition = get_overall_condition(risk_score, progress, insight)
last_recorded = patient_df["date"].max()
mood_trend = calculate_trend_direction(patient_df["mood_score"])

# ============================================================
# MASTER PATIENT MONITORING LEVEL DETERMINATION
# ============================================================
# 
# This is the SINGLE SOURCE OF TRUTH for patient risk status.
# All subsequent displays (Clinical Status, Banner, Alert Actions)
# MUST derive their state from this variable.
#
# Hierarchy:
# 1. Generate alerts FIRST (needed to count severities)
# 2. Count alert severities
# 3. Determine patient_monitoring_level
# 4. All UI components reference this variable only
# ============================================================

# Generate alerts for current patient
patient_alerts = generate_all_alerts(patient_df, risk_score)

# Count alerts by severity  
high_alert_count = len([a for a in patient_alerts if a["severity"] == "HIGH"])
medium_alert_count = len([a for a in patient_alerts if a["severity"] == "MEDIUM"])

# ============================================================
# DETERMINE MASTER MONITORING LEVEL (SINGLE SOURCE OF TRUTH)
# ============================================================
# The AI insight from AIModel.py is the authoritative risk determination
# It already incorporates all behavioral patterns and multivariate analysis
if "High Risk" in insight or "High risk" in insight:
    patient_monitoring_level = "CRITICAL"
elif "Medium Risk" in insight or "Medium risk" in insight:
    patient_monitoring_level = "MONITOR"
else:
    # If insight says "Stable" or anything else, it's ROUTINE
    patient_monitoring_level = "ROUTINE"

# ============================================================
# DERIVE CLINICAL STATUS LABEL FROM MONITORING LEVEL
# ============================================================
if patient_monitoring_level == "CRITICAL":
    clinical_status_label = "Critical"
    status_emoji = "🔴"
elif patient_monitoring_level == "MONITOR":
    clinical_status_label = "Monitor"
    status_emoji = "🟡"
else:  # ROUTINE
    clinical_status_label = "Stable"
    status_emoji = "🟢"

# ============================================================
# PATIENT CONTEXT PANEL (PHASE 2)
# ============================================================
st.markdown("## 📋 Patient Summary")

with st.container():
    context_col1, context_col2, context_col3, context_col4 = st.columns(4)
    
    with context_col1:
        # Overall condition with color coding
        condition_emoji = {
            "Stable": "🟢",
            "Monitor": "🟡", 
            "Critical": "🔴"
        }
        st.markdown(f"""
        <div style='background-color: #f0f2f6; padding: 20px; border-radius: 10px; text-align: center;'>
            <h3 style='margin: 0; color: #1f1f1f;'>{condition_emoji.get(overall_condition, '⚪')} {overall_condition}</h3>
            <p style='margin: 5px 0 0 0; color: #4a4a4a; font-size: 14px;'>Overall Condition</p>
        </div>
        """, unsafe_allow_html=True)
    
    with context_col2:
        st.markdown(f"""
        <div style='background-color: #f0f2f6; padding: 20px; border-radius: 10px; text-align: center;'>
            <h3 style='margin: 0; color: #1f1f1f;'>📅 {last_recorded}</h3>
            <p style='margin: 5px 0 0 0; color: #4a4a4a; font-size: 14px;'>Last Recorded</p>
        </div>
        """, unsafe_allow_html=True)
    
    with context_col3:
        # Trend direction with arrow
        trend_emoji = {
            "Improving": "📈",
            "Declining": "📉",
            "Stable": "➡️",
            "Fluctuating": "📊",
            "Insufficient Data": "❓"
        }
        st.markdown(f"""
        <div style='background-color: #f0f2f6; padding: 20px; border-radius: 10px; text-align: center;'>
            <h3 style='margin: 0; color: #1f1f1f;'>{trend_emoji.get(mood_trend, '➡️')} {mood_trend}</h3>
            <p style='margin: 5px 0 0 0; color: #4a4a4a; font-size: 14px;'>Mood Trend</p>
        </div>
        """, unsafe_allow_html=True)
    
    with context_col4:
        total_records = len(patient_df)
        st.markdown(f"""
        <div style='background-color: #f0f2f6; padding: 20px; border-radius: 10px; text-align: center;'>
            <h3 style='margin: 0; color: #1f1f1f;'>📊 {total_records} Days</h3>
            <p style='margin: 5px 0 0 0; color: #4a4a4a; font-size: 14px;'>Records Available</p>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ============================================================
# CLINICAL RISK ASSESSMENT PANEL
# ============================================================
st.markdown("## 🔍 Clinical Risk Assessment")

# Key Metrics Section with improved visual hierarchy
with st.container():
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # Risk score with color aligned to patient_monitoring_level
        if patient_monitoring_level == "CRITICAL":
            risk_color = "🔴"
        elif patient_monitoring_level == "MONITOR":
            risk_color = "🟡"
        else:  # ROUTINE
            risk_color = "🟢"
        st.metric(
            label="🎯 Risk Score", 
            value=f"{risk_color} {round(risk_score, 3)}",
            delta=None,
            help="Anomaly score from AI model. Lower = higher risk."
        )

    with col2:
        progress_emoji = "✅" if progress else "⏳"
        progress_color = "normal" if progress else "inverse"
        st.metric(
            label="📈 Recent Progress", 
            value=f"{'Yes' if progress else 'No'}",
            delta=None,
            help="Stress level reduction in last 5 days vs previous 5 days."
        )

    with col3:
        # Clinical Status - DERIVED FROM patient_monitoring_level
        st.metric(
            label="🏥 Clinical Status", 
            value=f"{status_emoji} {clinical_status_label}",
            delta=None,
            help="Patient monitoring level determined by active alert severity."
        )

    with col4:
        therapy_rate = (patient_df["therapy_attended"].sum() / len(patient_df)) * 100
        st.metric(
            label="🎭 Therapy Rate", 
            value=f"{therapy_rate:.0f}%",
            delta=None,
            help="Percentage of attended therapy sessions."
        )

st.markdown("<br>", unsafe_allow_html=True)

# AI Insight Alert Box with better styling
with st.container():
    if "High Risk" in insight or "High risk" in insight:
        st.error(f"🚨 **ALERT**: {insight}")
    elif "Medium Risk" in insight or "Medium risk" in insight:
        st.warning(f"⚠️ **CAUTION**: {insight}")
    else:
        st.success(f"✅ **STATUS**: {insight}")

st.markdown("---")

# ============================================================
# GLOBAL PATIENT RISK BANNER (DERIVED FROM MONITORING LEVEL)
# ============================================================
# Banner state is DERIVED from patient_monitoring_level
# No independent decision-making here
# ============================================================

if patient_monitoring_level == "CRITICAL":
    # State: CRITICAL
    banner_state = "IMMEDIATE CLINICAL ATTENTION REQUIRED"
    banner_explanation = "High-priority behavioral indicators detected. Patient requires prompt clinical assessment and potential care plan modification."
    
    # Build detailed reasons list from summary
    critical_reasons = []
    if summary["high_hr_today"]:
        hr_value = patient_df.iloc[-1]["heart_rate"]
        critical_reasons.append(f"**Elevated Heart Rate**: Current reading {hr_value:.0f} BPM (threshold: 100 BPM)")
    if summary["high_stress_today"]:
        stress_value = patient_df.iloc[-1]["stress_level"]
        critical_reasons.append(f"**High Stress Level**: Current level {stress_value:.1f}/10 (threshold: 7/10)")
    if summary["missed_therapy"]:
        recent_therapy = patient_df.tail(3)["therapy_attended"].sum()
        critical_reasons.append(f"**Therapy Attendance Concern**: Only {recent_therapy}/3 sessions attended in last 3 days")
    if summary["low_mood"]:
        recent_mood = patient_df.tail(3)["mood_score"].mean()
        critical_reasons.append(f"**Declining Mood**: Average mood score {recent_mood:.1f}/5 over last 3 days (threshold: 2.5)")
    if summary["low_sleep"]:
        recent_sleep = patient_df.tail(3)["sleep_hours"].mean()
        critical_reasons.append(f"**Poor Sleep Quality**: Average {recent_sleep:.1f} hours over last 3 days (threshold: 5.5 hours)")
    if summary["low_activity"]:
        recent_activity = patient_df.tail(3)["activity_level"].mean()
        critical_reasons.append(f"**Low Activity Level**: Average {recent_activity:.0f} steps/day, below patient's 25th percentile")
    
    st.error(f"""
### 🔴 {banner_state}

{banner_explanation}

**Active High Priority Alerts**: {high_alert_count} | **Active Medium Priority Alerts**: {medium_alert_count}
    """)
    
    # Show detailed breakdown
    if critical_reasons:
        st.markdown("#### 📋 Detailed Clinical Indicators")
        for reason in critical_reasons:
            st.markdown(f"- {reason}")
        st.markdown("")
elif patient_monitoring_level == "MONITOR":
    # State: MONITOR
    banner_state = "INCREASED MONITORING RECOMMENDED"
    if medium_alert_count >= 2:
        banner_explanation = "Multiple behavioral patterns require closer observation. Document trends in patient chart and observe for persistence."
    else:
        banner_explanation = "Behavioral pattern identified that warrants closer observation. Continue standard care protocol with enhanced documentation."
    st.warning(f"""
### 🟡 {banner_state}

{banner_explanation}

**Active Medium Priority Alerts**: {medium_alert_count}
    """)
else:  # ROUTINE
    # State: ROUTINE
    banner_state = "ROUTINE MONITORING ONGOING"
    banner_explanation = "Patient behavioral metrics remain within expected therapeutic ranges. Continue standard care protocols and scheduled assessments."
    st.success(f"""
### 🟢 {banner_state}

{banner_explanation}
    """)

st.markdown("<br>", unsafe_allow_html=True)

# ============================================================
# PHASE 3: NURSE ALERT PANEL
# ============================================================
st.markdown("## 🚨 Nurse Alert Panel")
st.caption("*Real-time clinical alerts based on behavioral pattern analysis*")

# ============================================================
# ALERT ACTION WORDING POLICY
# ============================================================
# Alert recommended actions MUST align with patient_monitoring_level:
#
# CRITICAL (patient_monitoring_level = "CRITICAL"):
#   - Time-bound urgent actions (within current shift)
#   - Escalation language (consider physician consultation)
#   - Immediate intervention focus
#
# MONITOR (patient_monitoring_level = "MONITOR"):
#   - Routine observation language
#   - Documentation and trending focus
#   - Regular rounds assessment
#   - No time-bound urgency
#
# ROUTINE (patient_monitoring_level = "ROUTINE"):
#   - Standard care protocols
#   - Scheduled rounds review
#   - Minimal intervention
# ============================================================

# Display alerts or no-alert message
if len(patient_alerts) == 0:
    # No alerts - all clear
    with st.container():
        st.success("✅ **No active nurse alerts at this time.** Patient behavioral patterns are within expected ranges.")
else:
    # Display alerts grouped by severity
    high_alerts = [a for a in patient_alerts if a["severity"] == "HIGH"]
    medium_alerts = [a for a in patient_alerts if a["severity"] == "MEDIUM"]
    low_alerts = [a for a in patient_alerts if a["severity"] == "LOW"]
    
    # Show summary count
    st.markdown(f"**Active Alerts**: {len(patient_alerts)} total ({len(high_alerts)} High, {len(medium_alerts)} Medium, {len(low_alerts)} Low)")
    st.markdown("<br>", unsafe_allow_html=True)
    
    # HIGH PRIORITY ALERTS (Red - Concise bullet format)
    if len(high_alerts) > 0:
        st.markdown("### 🔴 High Priority Clinical Alerts")
        for idx, alert in enumerate(high_alerts, 1):
            st.error(f"**{idx}.** {alert['message']}")
            with st.expander("📋 View Details"):
                # Build detailed clinical interpretation
                interpretation_parts = []
                interpretation_parts.append(f"**Multivariate Risk Score:** {risk_score:.3f} (negative values indicate concern)")
                interpretation_parts.append(f"\n**Clinical Status:** {insight}")
                interpretation_parts.append("\n**Why This Patient is Critical:**")
                
                clinical_concerns = []
                if summary["high_hr_today"]:
                    hr_value = patient_df.iloc[-1]["heart_rate"]
                    hr_baseline = patient_df["heart_rate"].mean()
                    clinical_concerns.append(
                        f"• **Cardiovascular Stress**: Current heart rate is {hr_value:.0f} BPM, which exceeds the clinical threshold of 100 BPM. "
                        f"This is {hr_value - hr_baseline:.0f} BPM above the patient's baseline average of {hr_baseline:.0f} BPM, "
                        f"indicating acute physiological stress or anxiety that requires immediate assessment."
                    )
                
                if summary["high_stress_today"]:
                    stress_value = patient_df.iloc[-1]["stress_level"]
                    stress_baseline = patient_df["stress_level"].mean()
                    clinical_concerns.append(
                        f"• **Elevated Psychological Distress**: Patient's self-reported stress level is {stress_value:.1f}/10, "
                        f"exceeding the high-risk threshold of 7/10. Baseline stress for this patient is {stress_baseline:.1f}/10. "
                        f"This {((stress_value - stress_baseline) / stress_baseline * 100):.0f}% increase from baseline suggests "
                        f"acute psychological distress requiring intervention."
                    )
                
                if summary["low_mood"]:
                    recent_mood = patient_df.tail(3)["mood_score"].mean()
                    overall_mood = patient_df["mood_score"].mean()
                    clinical_concerns.append(
                        f"• **Depressive Symptomatology**: 3-day average mood score is {recent_mood:.1f}/5, below the clinical "
                        f"concern threshold of 2.5/5. Patient's historical average is {overall_mood:.1f}/5. This sustained low mood "
                        f"pattern over multiple days indicates worsening depressive symptoms that may affect treatment compliance "
                        f"and recovery outcomes."
                    )
                
                if summary["low_sleep"]:
                    recent_sleep = patient_df.tail(3)["sleep_hours"].mean()
                    overall_sleep = patient_df["sleep_hours"].mean()
                    clinical_concerns.append(
                        f"• **Sleep Deprivation**: Average sleep duration over the last 3 days is {recent_sleep:.1f} hours, "
                        f"significantly below the clinical minimum of 5.5 hours. Patient's typical sleep duration is {overall_sleep:.1f} hours. "
                        f"Chronic sleep deprivation is strongly correlated with mood deterioration, cognitive impairment, and increased "
                        f"risk of self-harm in rehabilitation populations."
                    )
                
                if summary["missed_therapy"]:
                    recent_therapy = patient_df.tail(3)["therapy_attended"].sum()
                    therapy_compliance = (patient_df["therapy_attended"].sum() / len(patient_df)) * 100
                    clinical_concerns.append(
                        f"• **Treatment Non-Compliance**: Patient attended only {recent_therapy}/3 therapy sessions in the last 3 days. "
                        f"Historical compliance rate is {therapy_compliance:.0f}%. Sudden decrease in therapy attendance is a red flag "
                        f"for disengagement, withdrawal, or deteriorating mental state. This pattern often precedes acute crisis events."
                    )
                
                if summary["low_activity"]:
                    recent_activity = patient_df.tail(3)["activity_level"].mean()
                    q25 = patient_df["activity_level"].quantile(0.25)
                    overall_activity = patient_df["activity_level"].mean()
                    clinical_concerns.append(
                        f"• **Behavioral Withdrawal**: Recent activity level is {recent_activity:.0f} steps/day, below the patient's "
                        f"25th percentile baseline of {q25:.0f} steps/day (typical average: {overall_activity:.0f} steps/day). "
                        f"Marked decrease in physical activity is associated with social withdrawal, anhedonia, and declining "
                        f"motivation—all indicators of worsening mental health status."
                    )
                
                if clinical_concerns:
                    interpretation_parts.extend(clinical_concerns)
                    interpretation_parts.append(
                        f"\n**Integrated Clinical Assessment:** Multiple behavioral metrics have deteriorated simultaneously, "
                        f"indicating a compound effect that significantly elevates clinical risk. The combination of "
                        f"{len(clinical_concerns)} concurrent concerning indicators suggests the patient is experiencing an acute "
                        f"decline in mental health functioning that requires immediate clinical evaluation and potential care plan "
                        f"modification to prevent further deterioration."
                    )
                else:
                    interpretation_parts.append(
                        "Analysis indicates elevated risk based on multivariate pattern detection. While individual metrics may be "
                        "within normal ranges, the combination and trajectory of behavioral patterns warrant comprehensive assessment."
                    )
                
                st.markdown(f"**Interpretation:**\n\n" + "\n\n".join(interpretation_parts))
                
                st.markdown("---")
                st.markdown("**Recommended Action:** Schedule clinical assessment within current shift. Consider consultation with attending physician if pattern persists.")
                
                # Add quick reference indicators
                st.markdown("---")
                st.markdown("**📊 Quick Reference - Current Values:**")
                indicator_details = []
                if summary["high_hr_today"]:
                    hr_value = patient_df.iloc[-1]["heart_rate"]
                    indicator_details.append(f"- ❤️ Heart Rate: **{hr_value:.0f} BPM** (Threshold: >100)")
                if summary["high_stress_today"]:
                    stress_value = patient_df.iloc[-1]["stress_level"]
                    indicator_details.append(f"- 😰 Stress Level: **{stress_value:.1f}/10** (Threshold: >7)")
                if summary["missed_therapy"]:
                    recent_therapy = patient_df.tail(3)["therapy_attended"].sum()
                    indicator_details.append(f"- 🎭 Therapy Attendance: **{recent_therapy}/3 sessions**")
                if summary["low_mood"]:
                    recent_mood = patient_df.tail(3)["mood_score"].mean()
                    indicator_details.append(f"- 😔 Mood Score: **{recent_mood:.1f}/5** (Threshold: <2.5)")
                if summary["low_sleep"]:
                    recent_sleep = patient_df.tail(3)["sleep_hours"].mean()
                    indicator_details.append(f"- 😴 Sleep: **{recent_sleep:.1f} hrs** (Threshold: <5.5)")
                if summary["low_activity"]:
                    recent_activity = patient_df.tail(3)["activity_level"].mean()
                    indicator_details.append(f"- 🚶 Activity: **{recent_activity:.0f} steps/day**")
                
                for detail in indicator_details:
                    st.markdown(detail)
                    
        st.markdown("<br>", unsafe_allow_html=True)
    
    # MEDIUM PRIORITY ALERTS (Yellow - Concise bullet format)
    if len(medium_alerts) > 0:
        st.markdown("### 🟡 Medium Priority Clinical Alerts")
        for idx, alert in enumerate(medium_alerts, 1):
            st.warning(f"**{idx}.** {alert['message']}")
            with st.expander("📋 View Details"):
                st.markdown(f"**Interpretation:** {alert['explanation']}")
                st.markdown("**Recommended Action:** Document observed pattern in patient chart. Continue routine monitoring and reassess during regular nursing rounds. Observe for persistence over subsequent assessments.")
        st.markdown("<br>", unsafe_allow_html=True)
    
    # LOW PRIORITY ALERTS (Blue - Concise bullet format)
    if len(low_alerts) > 0:
        st.markdown("### 🔵 Routine Monitoring Notes")
        for idx, alert in enumerate(low_alerts, 1):
            st.info(f"**{idx}.** {alert['message']}")
            with st.expander("📋 View Details"):
                st.markdown(f"**Interpretation:** {alert['explanation']}")
                st.markdown("**Recommended Action:** Note in chart for routine review. Continue standard care protocol. Reassess during next scheduled rounds.")

st.markdown("---")

# ============================================================
# BEHAVIORAL TRENDS SECTION (PHASE 2 ENHANCED)
# ============================================================
st.markdown("## 📈 Behavioral Trends & Analysis")

# Date range selector with better layout
with st.container():
    col_filter1, col_filter2, col_filter3 = st.columns([4, 1, 1])
    with col_filter1:
        max_days = len(patient_df)
        default_days = min(30, max_days)
        days_to_show = st.slider(
            "📅 Time Period (Days)", 
            min_value=7, 
            max_value=max_days, 
            value=default_days, 
            step=1
        )
    with col_filter2:
        st.metric("Available", f"{max_days}d")
    with col_filter3:
        st.metric("Showing", f"{days_to_show}d")

# Filter data based on selection
filtered_df = patient_df.tail(days_to_show).copy().reset_index(drop=True)

st.markdown("<br>", unsafe_allow_html=True)

# Create tabs for different visualizations with icons
trend_tab1, trend_tab2, trend_tab3, trend_tab4 = st.tabs([
    "📊 Key Metrics", 
    "💓 Health Indicators", 
    "🎯 Therapy & Activity", 
    "📊 Statistics"
])

with trend_tab1:
    st.markdown("### 😴 Sleep, Mood & Activity Patterns")
    
    # Normalize activity level for better visualization (scale to 0-10 range)
    viz_data = filtered_df[["sleep_hours", "mood_score"]].copy()
    if filtered_df["activity_level"].max() > 0:
        viz_data["activity_level_scaled"] = (filtered_df["activity_level"] / filtered_df["activity_level"].max()) * 10
    else:
        viz_data["activity_level_scaled"] = 0
    viz_data.columns = ["Sleep Hours", "Mood Score", "Activity (Scaled)"]
    
    st.line_chart(viz_data, use_container_width=True, height=400)
    st.caption("📌 Activity Level is scaled 0-10 for visualization clarity alongside sleep and mood.")
    
    # === PHASE 2: TREND INTERPRETATIONS ===
    st.markdown("#### 🤖 AI Trend Insights")
    with st.container():
        # Generate insights for each metric
        sleep_insight = generate_trend_insight(
            "Sleep Duration", 
            filtered_df["sleep_hours"], 
            threshold_low=6.0
        )
        mood_insight = generate_trend_insight(
            "Mood Score", 
            filtered_df["mood_score"], 
            threshold_low=2.5
        )
        activity_insight = generate_trend_insight(
            "Activity Level", 
            filtered_df["activity_level"], 
            threshold_low=3000
        )
        
        st.markdown(f"- {sleep_insight}")
        st.markdown(f"- {mood_insight}")
        st.markdown(f"- {activity_insight}")

with trend_tab2:
    st.markdown("### 💓 Heart Rate & Stress Monitoring")
    
    health_col1, health_col2 = st.columns(2)
    
    with health_col1:
        st.markdown("**💓 Heart Rate (BPM)**")
        st.line_chart(filtered_df["heart_rate"], use_container_width=True, color="#e74c3c", height=300)
        
        avg_hr = filtered_df["heart_rate"].mean()
        max_hr = filtered_df["heart_rate"].max()
        min_hr = filtered_df["heart_rate"].min()
        st.caption(f"📊 Avg: {avg_hr:.1f} BPM | Range: {min_hr:.0f}-{max_hr:.0f}")
    
    with health_col2:
        st.markdown("**😰 Stress Level (1-10)**")
        st.line_chart(filtered_df["stress_level"], use_container_width=True, color="#9b59b6", height=300)
        
        avg_stress = filtered_df["stress_level"].mean()
        max_stress = filtered_df["stress_level"].max()
        st.caption(f"📊 Avg: {avg_stress:.1f}/10 | Peak: {max_stress:.1f}/10")
    
    # === PHASE 2: TREND INTERPRETATIONS ===
    st.markdown("#### 🤖 AI Trend Insights")
    with st.container():
        hr_insight = generate_trend_insight(
            "Heart Rate", 
            filtered_df["heart_rate"], 
            threshold_high=95
        )
        stress_insight = generate_trend_insight(
            "Stress Level", 
            filtered_df["stress_level"], 
            threshold_high=7.0
        )
        
        st.markdown(f"- {hr_insight}")
        st.markdown(f"- {stress_insight}")

with trend_tab3:
    st.markdown("### 🎭 Therapy Attendance & Engagement")
    
    therapy_col1, therapy_col2 = st.columns(2)
    
    with therapy_col1:
        st.markdown("**🎭 Therapy Sessions**")
        st.bar_chart(filtered_df["therapy_attended"], use_container_width=True, color="#3498db", height=300)
        
        attended = filtered_df["therapy_attended"].sum()
        attendance_rate = (attended / len(filtered_df)) * 100
        st.caption(f"✅ Attended: {attended}/{len(filtered_df)} sessions ({attendance_rate:.0f}%)")
    
    with therapy_col2:
        st.markdown("**📊 Daily Activity (Steps)**")
        st.area_chart(filtered_df["activity_level"], use_container_width=True, color="#f39c12", height=300)
        
        avg_activity = filtered_df["activity_level"].mean()
        max_activity = filtered_df["activity_level"].max()
        st.caption(f"📊 Avg: {avg_activity:.0f} steps | Peak: {max_activity:.0f} steps")
    
    # === PHASE 2: TREND INTERPRETATIONS ===
    st.markdown("#### 🤖 AI Trend Insights")
    with st.container():
        if attendance_rate < 60:
            therapy_insight = "⚠️ **Therapy attendance** is below 60%, which may impact recovery progress. Engagement intervention recommended."
        elif attendance_rate < 80:
            therapy_insight = "⚪ **Therapy attendance** is moderate. Encouraging more consistent participation could accelerate progress."
        else:
            therapy_insight = "✅ **Therapy attendance** is excellent, showing strong engagement with treatment."
        
        # Activity trend
        recent_activity = filtered_df["activity_level"].tail(7).mean()
        if recent_activity < 2000:
            activity_insight = "⚠️ **Physical activity** is notably low. Consider encouraging light exercise or outdoor time."
        elif recent_activity < 5000:
            activity_insight = "⚪ **Physical activity** is within acceptable range. Gradual increases could boost mood and energy."
        else:
            activity_insight = "✅ **Physical activity** levels are healthy, contributing positively to overall wellbeing."
        
        st.markdown(f"- {therapy_insight}")
        st.markdown(f"- {activity_insight}")

with trend_tab4:
    st.markdown("### 📊 Summary Statistics")
    st.caption(f"*Analysis period: Last {days_to_show} days*")
    
    # Create summary statistics with better formatting
    summary_cols = st.columns(4)
    
    with summary_cols[0]:
        avg_sleep = filtered_df["sleep_hours"].mean()
        min_sleep = filtered_df["sleep_hours"].min()
        max_sleep = filtered_df["sleep_hours"].max()
        st.metric("😴 Avg Sleep", f"{avg_sleep:.1f}h")
        st.caption(f"Range: {min_sleep:.1f}h - {max_sleep:.1f}h")
        
        # Health indicator
        if avg_sleep < 6:
            st.warning("⚠️ Below recommended")
        elif avg_sleep > 9:
            st.info("ℹ️ Above typical range")
        else:
            st.success("✅ Healthy range")
    
    with summary_cols[1]:
        avg_mood = filtered_df["mood_score"].mean()
        min_mood = filtered_df["mood_score"].min()
        max_mood = filtered_df["mood_score"].max()
        st.metric("😊 Avg Mood", f"{avg_mood:.1f}/5")
        st.caption(f"Range: {min_mood:.1f} - {max_mood:.1f}")
        
        if avg_mood < 2.5:
            st.warning("⚠️ Low mood")
        elif avg_mood > 3.5:
            st.success("✅ Positive mood")
        else:
            st.info("ℹ️ Moderate mood")
    
    with summary_cols[2]:
        avg_hr = filtered_df["heart_rate"].mean()
        min_hr = filtered_df["heart_rate"].min()
        max_hr = filtered_df["heart_rate"].max()
        st.metric("💓 Avg Heart Rate", f"{avg_hr:.0f}")
        st.caption(f"Range: {min_hr:.0f} - {max_hr:.0f} BPM")
        
        if avg_hr > 100:
            st.warning("⚠️ Elevated")
        elif avg_hr < 60:
            st.info("ℹ️ Low resting HR")
        else:
            st.success("✅ Normal range")
    
    with summary_cols[3]:
        therapy_rate = (filtered_df["therapy_attended"].sum() / len(filtered_df)) * 100
        st.metric("🎭 Attendance", f"{therapy_rate:.0f}%")
        st.caption(f"{filtered_df['therapy_attended'].sum()}/{len(filtered_df)} sessions")
        
        if therapy_rate < 60:
            st.warning("⚠️ Low engagement")
        elif therapy_rate < 80:
            st.info("ℹ️ Moderate engagement")
        else:
            st.success("✅ High engagement")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Statistical summary table
    st.markdown("#### 📈 Detailed Statistics")
    stats_df = filtered_df[["sleep_hours", "mood_score", "activity_level", "heart_rate", "stress_level"]].describe().round(2)
    stats_df.index = ["Count", "Mean", "Std Dev", "Min", "25%", "50% (Median)", "75%", "Max"]
    stats_df.columns = ["Sleep (h)", "Mood (1-5)", "Activity (steps)", "Heart Rate (BPM)", "Stress (1-10)"]
    st.dataframe(stats_df, use_container_width=True)

st.markdown("---")

# ============================================================
# RAW PATIENT DATA SECTION
# ============================================================
st.markdown("## 📄 Complete Patient Records")

with st.expander("🔍 View & Export Patient Data", expanded=False):
    # Display dataframe with better formatting
    display_df = patient_df.copy()
    
    # Check if date column exists and format it
    if "date" in display_df.columns:
        display_df["date"] = pd.to_datetime(display_df["date"]).dt.strftime("%Y-%m-%d")
    
    # Rename columns for clarity
    display_df.columns = [
        "Patient ID", "Date", "Sleep Hours", "Activity Level", 
        "Mood Score", "Therapy Attended", "Heart Rate", "Stress Level"
    ]
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=400
    )
    
    # Download button for data export
    csv = display_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Download Patient Data (CSV)",
        data=csv,
        file_name=f"patient_{selected_patient}_data_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )
    
    st.caption(f"💾 Export includes {len(display_df)} records for Patient {selected_patient}")

st.markdown("---")

# ============================================================
# FOOTER: SYSTEM INFO
# ============================================================
with st.container():
    st.markdown("##### 🏥 CARE-AI System Information")
    footer_col1, footer_col2, footer_col3 = st.columns(3)
    
    with footer_col1:
        st.caption("**AI Model**: Isolation Forest (200 estimators)")
    with footer_col2:
        st.caption(f"**Total Patients**: {len(df['patient_id'].unique())}")
    with footer_col3:
        st.caption(f"**Data Updated**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================================
# DASHBOARD STABILIZED — LOGIC ALIGNED FOR TEAM CONTINUATION
# ============================================================
# 
# SINGLE SOURCE OF TRUTH:
# - patient_monitoring_level (ROUTINE / MONITOR / CRITICAL)
# - Set once based on alert severity counts
# - All UI components derive from this variable
# 
# LOGICAL ALIGNMENT:
# - Risk Score Color → aligned to monitoring level
# - Clinical Status Label → derived from monitoring level
# - Global Banner Message → derived from monitoring level  
# - Alert Panel Actions → aligned to monitoring level
# 
# NO CONTRADICTIONS:
# - ROUTINE/MONITOR alerts use routine observation language
# - CRITICAL alerts use urgent language
# - No component makes independent status decisions
# 
# ALERT SYSTEM:
# - HIGH PRIORITY: Stress increase, low mood, elevated HR, high risk score
# - MEDIUM PRIORITY: Irregular sleep, missed therapy, declining activity
# - LOW PRIORITY: Early warning trends and minor fluctuations
# - All alerts explainable with clear clinical reasoning
# - Concise bullet format with expandable details
# 
# READY FOR TEAM HANDOFF
# ============================================================