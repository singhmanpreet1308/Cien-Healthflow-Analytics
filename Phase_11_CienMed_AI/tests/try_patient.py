"""Manual check for Step 5."""
from cienmed.tools import patient_tool as pt

rec = pt.get_patient(12224)
print("=== FACTS TEXT (what the LLM will read)\n")
print(rec.facts_text())

print("\n=== Cardiac history")
print(pt.cardiac_history(rec)[["diagnosis_date", "diagnosis_description", "severity"]])

print("\n=== Typical medication classes (NOT prescriptions)")
print(pt.medication_classes(12224))

print("\n=== Name search: 'Aryan Sanchez'")
print(pt.find_patients("Aryan Sanchez"))

print("\n=== Name search: 'Aryan' (expect several matches)")
print(pt.find_patients("Aryan"))

print("\n=== Missing patient")
print(pt.get_patient(999999))

print("\n=== Injection attempt (should return nothing, not every patient)")
print(pt.find_patients("x' OR 1=1 --"))