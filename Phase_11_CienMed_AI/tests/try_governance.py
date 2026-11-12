"""Manual check for Step 8 — zero tokens."""
import pandas as pd

from cienmed import governance as g

print("=== 1. Login")
print("correct password  :", g.authenticate("dr.demo", "Clinician@123"))
print("wrong password    :", g.authenticate("dr.demo", "wrong"))
print("unknown user      :", g.authenticate("nobody", "x"))
print("username is case-insensitive:", g.authenticate("DR.DEMO", "Clinician@123") is not None)

print("\n=== 2. Passwords are stored as hashes, never plain text")
print(g.load_users()["dr.demo"]["password_hash"][:30], "...")

print("\n=== 3. PHI masking — same rows, two roles")
rows = pd.DataFrame({
    "patient_id": [1, 2],
    "first_name": ["Aryan", "Harsh"],
    "last_name": ["Sanchez", "Sami"],
    "date_of_birth": ["1999-07-07", "1977-09-20"],
    "phone": ["8269829317", "7001743408"],
    "email": ["aryan@gmail.com", "harsh@gmail.com"],
    "insurance_provider": ["Max Bupa", "ICICI Lombard"],
})
print("ADMIN sees:\n", g.mask_df(rows, "admin").to_string(index=False))
print("\nCLINICIAN sees:\n", g.mask_df(rows, "clinician").to_string(index=False))

print("\n=== 4. Free-text masking (LLM answers)")
print(g.mask_text("Contact aryan.sanchez568@gmail.com or 8269829317 for follow-up.", "admin"))

print("\n=== 5. Audit log")
g.audit({"username": "dr.demo", "role": "clinician"}, "Summarise patient 1", "patient_summary", rows=2)
print(g.read_audit(3).to_string(index=False))