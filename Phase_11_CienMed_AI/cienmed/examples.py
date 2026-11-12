"""Example questions shown as buttons in the app.

These are pre-answered into data/demo_cache.json by build_demo_cache.py,
so demo/guest accounts can click them at zero token cost.
"""
EXAMPLES = {
    "clinician": [
        "Summarise patient 3's medical history",
        "What medications is patient 3 taking?",
        "Does patient 1904 have any allergies?",
        "Which patients are allergic to peanuts?",
        "What is patient 12224's readmission risk?",
        "How many patients have both CKD stage 3 and pneumonia?",
    ],
    "admin": [
        "Which insurers have the highest claim denial rate?",
        "Show the monthly claim denial rate for 2024",
        "What are the top 5 service types by total billed amount?",
        "Which facilities have the longest average wait time?",
        "Which open claims are most likely to be denied?",
        "How is the readmission rate defined?",
    ],
}

# Reports pre-generated for the demo (kind, start, end, facility)
DEMO_REPORTS = [(kind, "2024-01-01", "2024-12-31", None) for kind in (
    "Executive overview", "Claims & denials", "Facility performance", "Readmission (proxy)")]