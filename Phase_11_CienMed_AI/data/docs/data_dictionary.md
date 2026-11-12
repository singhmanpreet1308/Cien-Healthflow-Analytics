# Cien HealthFlow — Data Dictionary

## Claims
A claim is a bill submitted to an insurer for a service. `billed_amount` is what the provider charged; `approved_amount` is what the insurer agreed to pay; `patient_copay` is the patient's share. Revenue leakage is defined as billed minus approved.

Claim status values: Approved, Denied, Pending, Under Review. Claim denial rate = denied claims divided by all claims for the period, expressed as a percentage. Pending and Under Review claims are counted in the denominator.

Denial reasons recorded: Not Covered Under Plan, Pre-authorization Required, Documentation Missing, Out of Network Provider, Duplicate Claim.

## Patients
Patient master data contains PHI (name, date of birth, phone, email). Patients with no insurer on file are labelled "Uninsured" in the warehouse. Phone numbers were exported with a leading minus sign; this is corrected during loading.

## Diagnoses
Each row is a diagnosis episode coded in ICD-10 with severity (Mild, Moderate, Severe, Critical), a chronic flag, a treatment plan and a follow-up date. Cardiac codes in the data: I10 Essential Hypertension, I25.10 Coronary Artery Disease, I48.91 Atrial Fibrillation.

## Readmission (proxy definition)
The source systems do not contain admission/discharge records. Readmission is therefore approximated as a new diagnosis episode for the same patient within 30 days of a previous episode (`v_readmission_proxy.readmit_30d`). Report this as a proxy, not as a true hospital readmission rate.

## Medications
`medications` is a reference catalogue (name, generic name, category, form, manufacturer, unit price). There is no patient prescription table. The `dx_medication_class` mapping links diagnosis codes to typical medication categories and must be presented as "typical classes for the recorded diagnoses", never as the patient's actual medication list.

## Facility metrics
Monthly KPIs per facility from 2023-01 to 2024-12: patients seen, claims filed, revenue, average wait time (minutes), patient satisfaction (1–5), bed occupancy rate (%), staff count and emergency visits.
