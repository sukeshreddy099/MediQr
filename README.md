# MediQR – AI-Enabled Smart Medical History & QR System

Flask web application with Patient Profiles, Consultation Timelines, Doctor Handover Snapshots, ReportLab PDF Exports, Medical Document Uploads, and System Admin Control Center.
Data is stored securely in CSV files in `data/` and medical files in `uploads/`.

## Run
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 (on a phone on the same Wi-Fi: `http://<your-PC-IP>:5000`)

## Demo Credentials

### System Admin Login (Full Access)
| User ID | Password | Role |
|---------|----------|------|
| `ADMIN` | `Admin@1234` | System Administrator (Full CRUD Access, Audit Trail, Patient & Consultation Control) |

### Demo Patient Logins
| Patient ID | Password      | Condition |
|------------|---------------|-----------|
| P-001      | Arjun@4521    | Elevated Blood Glucose |
| P-002      | Priya@7788    | Mild Asthma |
| P-003      | Karthik@3342  | Migraine |
| P-004      | Divya@6154    | Vitamin D Deficiency |
| P-006      | Suresh@1234   | Essential Hypertension |
| P-007      | Ananya@5678   | Allergic Rhinitis & Sinusitis |

**P-005 (Rohan) & P-008 (Vikram) are not registered yet** – use the *Register* tab to test sign-up:
- Patient ID `P-005`, DOB `28-02-1988`, Mobile `9876509021`, then choose a password.
- Patient ID `P-008`, DOB `18-08-1975`, Mobile `9876508910`, then choose a password.

---

## Key System Endpoints

- `/admin` – Admin Dashboard (Patient CRUD, Consultation Entry, System Metrics, Global Audit Log)
- `/scanner` – Web QR Camera Scanner & Manual Patient/Token Search
- `/emergency/<pid>` – One-Tap First-Responder Emergency Card
- `/handover/<pid>` – Doctor-to-Doctor Clinical Handover Snapshot
- `/prep` – Patient Visit Preparation Checklist
- `/audit` – System Access Audit Log Stream
- `/pdf/patient/<pid>` – Downloadable Patient Summary PDF Report
- `/pdf/consultation/<pid>/<visit_no>` – Downloadable Consultation Visit PDF Report

---

## Project Structure
- `app.py` – All application routes, QR engine, ReportLab PDF generators, and Admin CRUD functions
- `templates/` – Jinja2 UI templates (`admin.html`, `scanner.html`, `consultation_report.html`, `audit.html`, `emergency.html`, `handover.html`, `prep.html`, `profile.html`, `main.html`, `base.html`, `register.html`)
- `static/` – `style.css`, scan images
- `uploads/` – Secure medical document storage
- `data/` – `patients.csv`, `consultations.csv`, `users.csv`, `qr_tokens.csv`, `documents.csv`, `audit_logs.csv`
