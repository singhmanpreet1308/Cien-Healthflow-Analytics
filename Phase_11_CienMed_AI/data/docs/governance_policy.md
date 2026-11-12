# CienMed AI — Governance, Access and Responsible-AI Policy

## Role-based access
Two roles exist. Clinicians (patient care, clinical review) may view individual patient records, diagnosis history, typical medication classes and risk scores for patients in their care. Administrators and business analysts (operations, finance, claims) see aggregated operational and financial data; patient identifiers in their results are masked.

## PHI handling
Names, phone numbers, email addresses and dates of birth are protected health information. For the admin role these fields are masked in every tool result before they reach the language model or the screen. Only the minimum necessary PHI is sent to the language model for clinician requests.

## Audit logging
Every question, the role and user who asked it, the tool selected, generated SQL and row counts are written to an append-only audit log.

## Responsible AI
CienMed AI is decision support, not a diagnostic device. Risk scores come from models trained on historical data and must be reviewed by a clinician. Answers must be grounded in retrieved records; when data is missing the assistant must say so rather than guess. Model performance (AUC) is shown alongside every prediction.

## Claim denial management
Common preventable denial causes are missing pre-authorisation, missing documentation and duplicate submission. Claims flagged as high denial risk should be reviewed for pre-authorisation and documentation before submission.
