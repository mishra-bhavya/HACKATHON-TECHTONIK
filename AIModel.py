import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


# ----------------------------------
# Data Loading & Processing
# ----------------------------------

def load_data(path="data/PatientData.csv"):
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()

    if "date" not in df.columns:
        raise ValueError("Dataset must contain a 'date' column")

    df["date"] = pd.to_datetime(df["date"])
    return df


def process_data(df):
    df = df.sort_values("date")
    df = df.fillna(df.mean(numeric_only=True))
    return df


# ----------------------------------
# Model Training (Baseline Learning)
# ----------------------------------

def train_model(df):
    features = df[
        [
            "sleep_hours",
            "activity_level",
            "mood_score",
            "therapy_attended",
            "heart_rate",
            "stress_level",
        ]
    ]

    model = IsolationForest(
        n_estimators=250,
        contamination=0.10,
        random_state=42,
    )
    model.fit(features)
    return model


# ----------------------------------
# Risk Detection (IMMEDIATE DAILY ALERTS)
# ----------------------------------

def detect_concern(model, df):
    features = df[
        [
            "sleep_hours",
            "activity_level",
            "mood_score",
            "therapy_attended",
            "heart_rate",
            "stress_level",
        ]
    ]

    base_score = np.mean(model.decision_function(features))
    risk_score = base_score

    latest_hr = df.iloc[-1]["heart_rate"]
    latest_stress = df.iloc[-1]["stress_level"]

    baseline_hr = df["heart_rate"].mean()
    baseline_stress = df["stress_level"].mean()

    if latest_hr > 100:
        risk_score -= 1.0

    if latest_stress > 7:
        risk_score -= 1.0

    if latest_hr - baseline_hr > 8:
        risk_score -= 0.3

    if latest_stress - baseline_stress > 1.5:
        risk_score -= 0.3

    return risk_score


# ----------------------------------
# Sustained Behavioral Decline (5 Days)
# ----------------------------------

def sustained_decline(df, days=5):
    if len(df) < days:
        return False

    recent = df.tail(days)

    low_mood = recent["mood_score"].mean() < 2.5
    low_activity = recent["activity_level"].mean() < df["activity_level"].quantile(0.25)
    low_sleep = recent["sleep_hours"].mean() < 5.5

    return low_mood and low_activity and low_sleep


# ----------------------------------
# Progress Tracking (TREND ONLY)
# ----------------------------------

def has_made_progress(df):
    if len(df) < 10:
        return False

    recent = df.tail(5)["mood_score"].mean()
    previous = df.iloc[-10:-5]["mood_score"].mean()

    return recent > previous


# ----------------------------------
# Explainable Change Summary
# ----------------------------------

def summarize_changes(df):
    recent = df.tail(3)

    return {
        "high_hr_today": df.iloc[-1]["heart_rate"] > 100,
        "high_stress_today": df.iloc[-1]["stress_level"] > 7,
        "missed_therapy": recent["therapy_attended"].sum() < 2,
        "low_sleep": recent["sleep_hours"].mean() < 5.5,
        "low_activity": recent["activity_level"].mean()
        < df["activity_level"].quantile(0.25),
        "low_mood": recent["mood_score"].mean() < 2.5,
    }


# ----------------------------------
# Insight Generation
# ----------------------------------

def generate_insight(risk_score, summary, sustained_flag):
    reasons = []

    if summary["high_hr_today"]:
        reasons.append("HR↑")
    if summary["high_stress_today"]:
        reasons.append("Stress↑")
    if summary["missed_therapy"]:
        reasons.append("Therapy Missed")
    if summary["low_sleep"]:
        reasons.append("Sleep↓")
    if summary["low_activity"]:
        reasons.append("Activity↓")
    if summary["low_mood"]:
        reasons.append("Mood↓")

    reason_text = ", ".join(reasons) if reasons else "No issues"

    if sustained_flag:
        return "High Risk | 5-day behavioral decline"

    if summary["high_hr_today"] or summary["high_stress_today"]:
        return f"High Risk | {reason_text}"

    if risk_score < -0.2:
        return f"Medium Risk | {reason_text}"

    return "Stable"


# ----------------------------------
# All Patients Analysis (FIX APPLIED)
# ----------------------------------

def analyze_all_patients(df):
    results = []

    for patient_id in df["patient_id"].unique():
        patient_df = df[df["patient_id"] == patient_id]

        if len(patient_df) < 30:
            continue

        model = train_model(patient_df)
        risk = detect_concern(model, patient_df)
        summary = summarize_changes(patient_df)
        sustained_flag = sustained_decline(patient_df)

        insight = generate_insight(risk, summary, sustained_flag)

        # 🔴 FIX: No progress allowed during High Risk
        if insight.startswith("High Risk"):
            progress = False
        else:
            progress = has_made_progress(patient_df)

        results.append(
            {
                "patient_id": patient_id,
                "risk_score": round(risk, 3),
                "progress": progress,
                "insight": insight,
            }
        )

    return pd.DataFrame(results)


# ----------------------------------
# Standalone Run
# ----------------------------------

if __name__ == "__main__":
    pd.set_option("display.max_colwidth", 40)

    df = load_data()
    df = process_data(df)

    results_df = analyze_all_patients(df)

    high_risk_df = results_df[
        results_df["insight"].str.startswith("High Risk")
    ].sort_values("risk_score")

    print("\n=== HIGH-RISK PATIENTS (IMMEDIATE ATTENTION REQUIRED) ===\n")
    print(high_risk_df.to_string(index=False))
    print(f"\nTotal High-Risk Patients: {len(high_risk_df)}")
