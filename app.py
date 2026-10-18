"""MediQR - Patient Medical History App (simple Flask + CSV, no database)."""
import csv
import io
import os
import re
import uuid
from datetime import datetime, date

import qrcode
from PIL import Image
from flask import Flask, flash, redirect, render_template, request, session, url_for, send_file, Response
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data") if os.path.exists(os.path.join(BASE, "data")) else BASE
UPLOADS_DIR = os.path.join(BASE, "uploads")
if not os.path.exists(UPLOADS_DIR):
    os.makedirs(UPLOADS_DIR)

template_folder = os.path.join(BASE, "templates") if os.path.exists(os.path.join(BASE, "templates")) else BASE
static_folder = os.path.join(BASE, "static") if os.path.exists(os.path.join(BASE, "static")) else BASE

app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
app.secret_key = "mediqr-academic-demo-key"  # change for real use


# ---------------------------------------------------------------- data helpers
def read_csv(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_patients():
    return read_csv("patients.csv")


def get_patient(pid):
    return next((p for p in get_patients() if p["Patient_ID"] == pid), None)


def get_consultations(pid=None):
    rows = read_csv("consultations.csv")
    for r in rows:
        r["_date"] = datetime.strptime(r["Date"], "%d-%m-%Y")
    if pid:
        rows = [r for r in rows if r["Patient_ID"] == pid]
    return sorted(rows, key=lambda row: row["_date"])


def get_users():
    return {r["Patient_ID"]: r["Password_Hash"] for r in read_csv("users.csv")}


def save_user(pid, password):
    new_file = not os.path.exists(os.path.join(DATA, "users.csv"))
    with open(os.path.join(DATA, "users.csv"), "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["Patient_ID", "Password_Hash"])
        w.writerow([pid, generate_password_hash(password)])


def normalise_id(text):
    """'p1', 'P-001', 'P 001', 'p-1' -> 'P-001'"""
    t = text.strip().upper().replace(" ", "").replace("-", "")
    if t == "ADMIN":
        return "ADMIN"
    digits = t[1:] if t.startswith("P") else t
    if digits.isdigit():
        return f"P-{int(digits):03d}"
    return text.strip().upper()


def normalise_dob(text):
    s = text.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%m-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d-%m-%Y")
        except ValueError:
            pass
    return s


def normalise_mobile(text):
    digits = re.sub(r"\D", "", text)
    return digits[-10:] if len(digits) >= 10 else digits


def is_admin_session():
    return session.get("is_admin", False) or session.get("pid") == "ADMIN"


def current_patient():
    pid = session.get("pid")
    return get_patient(pid) if pid else None


def age_from(dob):
    b = datetime.strptime(dob, "%d-%m-%Y").date()
    t = date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


# ------------------------------------------------------------- Admin CRUD Helpers
def save_patient_record(p_data):
    patients = get_patients()
    file_path = os.path.join(DATA, "patients.csv")
    pid = p_data["Patient_ID"]
    updated = False
    for i, p in enumerate(patients):
        if p["Patient_ID"] == pid:
            patients[i] = p_data
            updated = True
            break
    if not updated:
        patients.append(p_data)

    fieldnames = [
        "Patient_ID", "Name", "DOB", "Gender", "Aadhaar_No", "Blood_Group",
        "Mobile_No", "Address", "Emergency_Contact_Name", "Emergency_Contact_No",
        "Patient_Status", "Heart_Rate_bpm", "Temperature_C", "Blood_Pressure_mmHg",
        "Oxygen_Saturation_%", "Latest_Diagnosis", "Latest_Doctor",
        "Latest_Consultation_Date", "Current_Treatment_Plan", "Next_Follow_up"
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for p in patients:
            w.writerow(p)


def delete_patient_record(patient_id):
    patients = [p for p in get_patients() if p["Patient_ID"] != patient_id]
    file_path = os.path.join(DATA, "patients.csv")
    fieldnames = [
        "Patient_ID", "Name", "DOB", "Gender", "Aadhaar_No", "Blood_Group",
        "Mobile_No", "Address", "Emergency_Contact_Name", "Emergency_Contact_No",
        "Patient_Status", "Heart_Rate_bpm", "Temperature_C", "Blood_Pressure_mmHg",
        "Oxygen_Saturation_%", "Latest_Diagnosis", "Latest_Doctor",
        "Latest_Consultation_Date", "Current_Treatment_Plan", "Next_Follow_up"
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for p in patients:
            w.writerow(p)


def save_consultation_record(c_data):
    consults = get_consultations()
    file_path = os.path.join(DATA, "consultations.csv")
    fieldnames = [
        "Patient_ID", "Visit_No", "Date", "Doctor", "Specialist",
        "Symptom_1", "Symptom_2", "Symptom_3", "Diagnosis",
        "Treatment_1", "Treatment_2", "Treatment_3", "Severity",
        "Scan_Type", "Scan_Body_Part", "Scan_Findings", "Scan_Reporting_Doctor",
        "Scan_File", "Handover_Notes"
    ]
    updated = False
    for i, c in enumerate(consults):
        if c["Patient_ID"] == c_data["Patient_ID"] and str(c["Visit_No"]) == str(c_data["Visit_No"]):
            consults[i] = {k: c_data.get(k, "") for k in fieldnames}
            updated = True
            break
    if not updated:
        consults.append({k: c_data.get(k, "") for k in fieldnames})

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for c in consults:
            w.writerow({k: c.get(k, "") for k in fieldnames})


def delete_consultation_record(patient_id, visit_no):
    consults = [c for c in get_consultations() if not (c["Patient_ID"] == patient_id and str(c["Visit_No"]) == str(visit_no))]
    file_path = os.path.join(DATA, "consultations.csv")
    fieldnames = [
        "Patient_ID", "Visit_No", "Date", "Doctor", "Specialist",
        "Symptom_1", "Symptom_2", "Symptom_3", "Diagnosis",
        "Treatment_1", "Treatment_2", "Treatment_3", "Severity",
        "Scan_Type", "Scan_Body_Part", "Scan_Findings", "Scan_Reporting_Doctor",
        "Scan_File", "Handover_Notes"
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for c in consults:
            w.writerow({k: c.get(k, "") for k in fieldnames})


# ------------------------------------------------------------- QR & Token Helpers
def get_qr_tokens():
    return read_csv("qr_tokens.csv")


def save_qr_token(token_data):
    file_path = os.path.join(DATA, "qr_tokens.csv")
    exists = os.path.exists(file_path)
    with open(file_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists or os.path.getsize(file_path) == 0:
            w.writerow(["Token_ID", "Patient_ID", "Visit_No", "Type", "Created_At", "Status", "Revoked_At"])
        w.writerow([
            token_data["Token_ID"], token_data["Patient_ID"], token_data.get("Visit_No", ""),
            token_data["Type"], token_data["Created_At"], token_data["Status"], token_data.get("Revoked_At", "")
        ])


def get_token_by_id(token_id):
    tokens = get_qr_tokens()
    for t in tokens:
        if t["Token_ID"] == token_id:
            return t
    return None


def get_or_create_patient_qr_token(patient_id):
    tokens = get_qr_tokens()
    for t in tokens:
        if t["Patient_ID"] == patient_id and t["Type"] == "patient" and t["Status"] == "Active":
            return t["Token_ID"]
    new_id = f"PAT-QR-{uuid.uuid4().hex[:12].upper()}"
    save_qr_token({
        "Token_ID": new_id,
        "Patient_ID": patient_id,
        "Visit_No": "",
        "Type": "patient",
        "Created_At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Status": "Active",
        "Revoked_At": ""
    })
    return new_id


def get_or_create_consultation_qr_token(patient_id, visit_no):
    tokens = get_qr_tokens()
    v_str = str(visit_no)
    for t in tokens:
        if t["Patient_ID"] == patient_id and str(t.get("Visit_No", "")) == v_str and t["Type"] == "consultation" and t["Status"] == "Active":
            return t["Token_ID"]
    new_id = f"CON-QR-{uuid.uuid4().hex[:12].upper()}"
    save_qr_token({
        "Token_ID": new_id,
        "Patient_ID": patient_id,
        "Visit_No": v_str,
        "Type": "consultation",
        "Created_At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Status": "Active",
        "Revoked_At": ""
    })
    return new_id


def revoke_qr_token(token_id):
    tokens = get_qr_tokens()
    file_path = os.path.join(DATA, "qr_tokens.csv")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = False
    for t in tokens:
        if t["Token_ID"] == token_id and t["Status"] == "Active":
            t["Status"] = "Revoked"
            t["Revoked_At"] = now_str
            updated = True
    if updated:
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Token_ID", "Patient_ID", "Visit_No", "Type", "Created_At", "Status", "Revoked_At"])
            for t in tokens:
                w.writerow([t["Token_ID"], t["Patient_ID"], t.get("Visit_No",""), t["Type"], t["Created_At"], t["Status"], t.get("Revoked_At","")])
    return updated


# ------------------------------------------------------------- Audit Logging Helpers
def log_audit_event(user_id, action, resource, ip_addr, status="Success"):
    file_path = os.path.join(DATA, "audit_logs.csv")
    exists = os.path.exists(file_path)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_id = f"LOG-{uuid.uuid4().hex[:8].upper()}"
    with open(file_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists or os.path.getsize(file_path) == 0:
            w.writerow(["Log_ID", "Timestamp", "User_ID", "Action", "Resource", "IP_Address", "Status"])
        w.writerow([log_id, now_str, user_id, action, resource, ip_addr, status])


def get_audit_logs():
    return list(reversed(read_csv("audit_logs.csv")))


# ------------------------------------------------------------- Document Helpers
def get_documents(patient_id=None):
    docs = read_csv("documents.csv")
    if patient_id:
        return [d for d in docs if d["Patient_ID"] == patient_id]
    return docs


def save_document(doc_data):
    file_path = os.path.join(DATA, "documents.csv")
    exists = os.path.exists(file_path)
    with open(file_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists or os.path.getsize(file_path) == 0:
            w.writerow(["Doc_ID", "Patient_ID", "Visit_No", "Doc_Type", "File_Name", "Original_Name", "Upload_Date", "Notes"])
        w.writerow([
            doc_data["Doc_ID"], doc_data["Patient_ID"], doc_data.get("Visit_No", ""),
            doc_data["Doc_Type"], doc_data["File_Name"], doc_data["Original_Name"],
            doc_data["Upload_Date"], doc_data.get("Notes", "")
        ])


def generate_qr_png_io(data_url):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(data_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f766e", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ------------------------------------------------------------- health analysis
def vitals_status(p):
    hr, temp, spo2 = int(p["Heart_Rate_bpm"]), float(p["Temperature_C"]), int(p["Oxygen_Saturation_%"])
    sys_, dia = (int(x) for x in p["Blood_Pressure_mmHg"].split("/"))

    bp = "ok" if sys_ < 120 and dia < 80 else "watch" if sys_ < 140 and dia < 90 else "high"
    return [
        {"label": "Heart rate", "value": hr, "unit": "bpm", "state": "ok" if 60 <= hr <= 100 else "watch"},
        {"label": "Blood pressure", "value": p["Blood_Pressure_mmHg"], "unit": "mmHg", "state": bp},
        {"label": "Temperature", "value": temp, "unit": "°C", "state": "ok" if 36.1 <= temp <= 37.5 else "watch"},
        {"label": "Oxygen (SpO₂)", "value": spo2, "unit": "%",
         "state": "ok" if spo2 >= 95 else "watch" if spo2 >= 92 else "high"},
    ]


GLOSSARY = {
    "hypertension": "High blood pressure - pressure against arterial walls is elevated.",
    "glucose": "Blood sugar concentration requiring monitoring and dietary balance.",
    "asthma": "Airway swelling causing occasional shortness of breath or chest tightness.",
    "migraine": "Recurrent neurological headache accompanied by sensitivity to light or dizziness.",
    "gastritis": "Irritation or acidity in the stomach lining.",
    "spondylosis": "Age-related natural wear and tear in spinal discs and joints.",
    "bronchial thickening": "Mild irritation or inflammation in airway wall lining.",
    "sinus rhythm": "Normal, healthy regular heartbeat pattern.",
    "acl sprain": "Stretched ligament in the knee joint without a complete tear.",
    "otitis": "Infection or irritation of the ear canal.",
    "rhinitis": "Nasal lining allergy causing sneezing, congestion or runny nose.",
    "sinusitis": "Swelling or inflammation of the sinuses around nasal passages.",
    "spo2": "Blood oxygen saturation percentage level.",
}


def explain_medical_term(term):
    t_lower = term.lower()
    for key, val in GLOSSARY.items():
        if key in t_lower:
            return val
    return "Clinical diagnostic term recorded during consultation."


def profile_completeness(p):
    if not p:
        return {"score": 0, "missing": []}
    fields = [
        ("Aadhaar_No", "Aadhaar Identity Number"),
        ("Blood_Group", "Blood Group"),
        ("Mobile_No", "Mobile Number"),
        ("Address", "Home Address"),
        ("Emergency_Contact_Name", "Emergency Contact Person"),
        ("Emergency_Contact_No", "Emergency Phone Number"),
        ("DOB", "Date of Birth"),
        ("Latest_Diagnosis", "Primary Diagnosis"),
        ("Current_Treatment_Plan", "Treatment Plan"),
    ]
    completed = 0
    missing = []
    for k, label in fields:
        val = p.get(k, "").strip()
        if val and not val.startswith("XXXX XXXX 0000"):
            completed += 1
        else:
            missing.append(label)

    score = int((completed / len(fields)) * 100)
    return {"score": score, "missing": missing, "count": completed, "total": len(fields)}


def treatment_response_status(consults):
    if not consults:
        return {"status": "Stable", "badge": "stable", "icon": "🟡", "text": "Awaiting initial follow-up evaluation."}
    severities = [c.get("Severity", "Mild").lower() for c in consults]
    first_sev = severities[0]
    last_sev = severities[-1]

    if (first_sev == "moderate" and last_sev == "mild") or (first_sev == "severe" and last_sev in ("moderate", "mild")):
        return {"status": "Improving", "badge": "improving", "icon": "🟢", "text": "Condition shows positive progress from earlier visits."}
    elif first_sev == "mild" and last_sev in ("moderate", "severe"):
        return {"status": "Needs Attention", "badge": "attention", "icon": "🔴", "text": "Symptoms require updated clinical review."}
    else:
        return {"status": "Stable", "badge": "stable", "icon": "🟡", "text": "Condition is steady under current management."}


def missing_info_alerts(p, consults):
    alerts = []
    if not p.get("Emergency_Contact_No"):
        alerts.append("Emergency contact phone number is missing.")
    for c in consults:
        if c.get("Scan_Type") and not c.get("Scan_File"):
            alerts.append(f"Visit {c['Visit_No']} lists {c['Scan_Type']} but image attachment is missing.")
    return alerts


RULES = [
    ("glucose", ("Nutrition", "Control blood sugar",
                 "Cut sugary drinks and refined carbs, add fibre and protein, walk 30 minutes daily, and check fasting sugar monthly.")),
    ("diabet", ("Nutrition", "Control blood sugar",
                "Cut sugary drinks and refined carbs, add fibre and protein, walk 30 minutes daily, and check fasting sugar monthly.")),
    ("asthma", ("Lungs", "Protect your lungs",
                "Keep the inhaler with you, avoid dust, smoke and cold air, and note what triggers an attack.")),
    ("migraine", ("Lifestyle", "Reduce migraine triggers",
                  "Sleep at fixed times, stay hydrated, limit screen glare and caffeine, and keep a headache diary.")),
    ("vitamin d", ("Nutrition", "Boost vitamin D",
                   "Get 15-20 minutes of morning sunlight, eat eggs, fortified milk and fish, and take supplements as prescribed.")),
    ("gastritis", ("Nutrition", "Soothe your stomach",
                   "Eat small regular meals, avoid spicy, oily food and late dinners, drink enough water, limit tea/coffee.")),
    ("hypertension", ("Heart", "Keep blood pressure down",
                      "Use less salt, take medicines on time, exercise regularly and check your BP weekly.")),
    ("lumbar", ("Activity", "Look after your back",
                "Do the physiotherapy exercises, avoid heavy lifting, and keep a good sitting posture.")),
    ("ligament", ("Activity", "Protect your knee",
                  "Strengthen the thigh muscles gently, avoid sudden twisting, and wear supportive footwear.")),
    ("infection", ("Recovery", "Support recovery",
                   "Rest well, drink warm fluids, finish any prescribed course, and see a doctor if symptoms return.")),
    ("fever", ("Recovery", "Support recovery",
               "Rest well, drink warm fluids, finish any prescribed course, and see a doctor if symptoms return.")),
]


def suggestions(p, consults):
    out, seen = [], set()
    text = " ".join(c["Diagnosis"].lower() for c in consults) + " " + p["Latest_Diagnosis"].lower()
    for key, (cat, title, advice) in RULES:
        if key in text and title not in seen:
            seen.add(title)
            out.append({"cat": cat, "title": title, "text": advice})

    states = {v["label"]: v["state"] for v in vitals_status(p)}
    if states["Blood pressure"] != "ok":
        out.append({"cat": "Heart", "title": "Blood pressure is slightly above ideal",
                    "text": f"Your last reading was {p['Blood_Pressure_mmHg']} mmHg. Reduce salt, manage stress and recheck regularly."})
    if states["Oxygen (SpO₂)"] != "ok":
        out.append({"cat": "Lungs", "title": "Oxygen level needs attention",
                    "text": "Practise deep-breathing exercises and consult your doctor if it stays low."})
    if p["Next_Follow_up"].lower() != "as needed":
        out.append({"cat": "Follow-up", "title": f"Follow-up in {p['Next_Follow_up']}",
                    "text": f"Book your visit with {p['Latest_Doctor']} and carry this history with you."})
    out.append({"cat": "General", "title": "Daily basics",
                "text": "Sleep 7-8 hours, drink 2-3 litres of water and stay active every day."})
    return out


# ------------------------------------------------------------------ timeline SVG
def timeline_svg(consults, patient_ids):
    """Scatter timeline drawn in plain Python: Y = patient, X = consultation date (month)."""
    if not consults:
        return ""
    first = min(c["_date"] for c in consults).replace(day=1)
    last = max(c["_date"] for c in consults)
    end = datetime(last.year + (last.month == 12), last.month % 12 + 1, 1)
    span = (end - first).total_seconds()

    w, l, r, t, row = 960, 90, 30, 30, 62
    h = t + row * len(patient_ids) + 55
    pw = w - l - r
    x_of = lambda d: l + (d - first).total_seconds() / span * pw
    s = [f'<svg viewBox="0 0 {w} {h}" class="tl" role="img" aria-label="Consultation timeline">']

    m = first
    while m <= end:  # month gridlines + labels
        x = x_of(m)
        s.append(f'<line x1="{x:.1f}" y1="{t-10}" x2="{x:.1f}" y2="{h-45}" class="grid"/>')
        s.append(f'<text x="{x:.1f}" y="{h-24}" class="tick" text-anchor="middle">{m:%b}</text>')
        if m.month == 1 or m == first:
            s.append(f'<text x="{x:.1f}" y="{h-8}" class="tick yr" text-anchor="middle">{m:%Y}</text>')
        m = datetime(m.year + (m.month == 12), m.month % 12 + 1, 1)

    for i, pid in enumerate(patient_ids):
        y = t + row * i + row / 2
        s.append(f'<line x1="{l}" y1="{y}" x2="{w-r}" y2="{y}" class="lane"/>')
        s.append(f'<text x="{l-14}" y="{y+4}" class="ylab" text-anchor="end">{pid}</text>')
        mine = [c for c in consults if c["Patient_ID"] == pid]
        if len(mine) > 1:
            s.append(f'<polyline fill="none" class="link" points="{" ".join(f"{x_of(c["_date"]):.1f},{y}" for c in mine)}"/>')
        for c in mine:
            cls = "dot " + c["Severity"].lower()
            s.append(f'<circle cx="{x_of(c["_date"]):.1f}" cy="{y}" r="9" class="{cls}">'
                     f'<title>{pid} · Visit {c["Visit_No"]} · {c["Date"]} · {c["Severity"]}</title></circle>')
    s.append("</svg>")
    return "".join(s)


# ------------------------------------------------------------- ReportLab PDF Engine
def generate_patient_pdf_bytes(patient, consults, vitals, qr_token_url):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()

    normal_style = styles['Normal']
    heading_style = ParagraphStyle('SectionHeading', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0f766e'), spaceBefore=8, spaceAfter=4)

    story = []

    # Header with Patient QR Code placed Top Right
    qr_img_bytes = generate_qr_png_io(qr_token_url)
    qr_rl_img = RLImage(qr_img_bytes, width=70, height=70)

    header_text = Paragraph(
        f"<b>MediQR Smart Medical Summary Report</b><br/>"
        f"<font size=14 color='#115e59'><b>Patient: {patient['Name']}</b></font><br/>"
        f"Patient ID: <b>{patient['Patient_ID']}</b> | DOB: {patient['DOB']} ({age_from(patient['DOB'])} yrs)<br/>"
        f"Blood Group: <b>{patient['Blood_Group']}</b> | Gender: {patient['Gender']} | Mobile: {patient['Mobile_No']}",
        normal_style
    )

    header_table = Table([[header_text, qr_rl_img]], colWidths=[450, 90])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0f766e'), spaceAfter=10))

    # Vitals Section
    story.append(Paragraph("<b>Recorded Vital Signs Baseline</b>", heading_style))
    vitals_data = [["Vital Parameter", "Value Reading", "Unit", "Clinical State"]]
    for v in vitals:
        vitals_data.append([v["label"], str(v["value"]), v["unit"], "Normal" if v["state"]=="ok" else "Watch"])
    v_table = Table(vitals_data, colWidths=[150, 120, 100, 170])
    v_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0fdfa')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#0f766e')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    story.append(v_table)
    story.append(Spacer(1, 10))

    # Consultations Section
    story.append(Paragraph("<b>Chronological Medical History & Consultations</b>", heading_style))
    consult_data = [["Date", "Visit", "Doctor & Specialty", "Diagnosis & Treatment", "Severity"]]
    for c in reversed(consults):
        diag_text = f"<b>{c['Diagnosis']}</b><br/>Regimen: {c.get('Treatment_1','')}"
        doc_text = f"{c['Doctor']}<br/><font color='#64748b'>{c['Specialist']}</font>"
        consult_data.append([c['Date'], f"Visit {c['Visit_No']}", Paragraph(doc_text, normal_style), Paragraph(diag_text, normal_style), c['Severity']])

    c_table = Table(consult_data, colWidths=[65, 50, 140, 215, 70])
    c_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0fdfa')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#0f766e')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    story.append(c_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<font size=8 color='#64748b'>Report Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} via MediQR System. Confidential Document.</font>", normal_style))

    doc.build(story)
    buf.seek(0)
    return buf


def generate_consultation_pdf_bytes(patient, consult, qr_token_url):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()

    normal_style = styles['Normal']
    heading_style = ParagraphStyle('SectionHeading', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0f766e'), spaceBefore=8, spaceAfter=4)

    story = []

    # Consultation Header with Consultation QR
    qr_img_bytes = generate_qr_png_io(qr_token_url)
    qr_rl_img = RLImage(qr_img_bytes, width=70, height=70)

    header_text = Paragraph(
        f"<b>MediQR Consultation Report</b><br/>"
        f"<font size=14 color='#115e59'><b>Visit No. {consult['Visit_No']} — {consult['Date']}</b></font><br/>"
        f"Patient: <b>{patient['Name']}</b> ({patient['Patient_ID']}) | Age: {age_from(patient['DOB'])} yrs<br/>"
        f"Physician: <b>{consult['Doctor']}</b> ({consult['Specialist']})",
        normal_style
    )

    header_table = Table([[header_text, qr_rl_img]], colWidths=[450, 90])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0f766e'), spaceAfter=10))

    # Details Table
    details_data = [
        ["Reported Symptoms:", f"{consult.get('Symptom_1','')} {consult.get('Symptom_2','')} {consult.get('Symptom_3','')}"],
        ["Primary Diagnosis:", consult.get('Diagnosis','Not recorded')],
        ["Prescribed Treatments:", f"1. {consult.get('Treatment_1','')}  2. {consult.get('Treatment_2','')}  3. {consult.get('Treatment_3','')}"],
        ["Visit Severity:", consult.get('Severity','Mild')],
        ["Clinical Handover Note:", consult.get('Handover_Notes','Standard consultation completed.')]
    ]
    d_table = Table(details_data, colWidths=[150, 390])
    d_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#0f766e')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    story.append(d_table)
    story.append(Spacer(1, 12))

    if consult.get("Scan_Type"):
        story.append(Paragraph("<b>Attached Investigation / Scan Report</b>", heading_style))
        scan_data = [
            ["Scan Type:", consult.get('Scan_Type','')],
            ["Body Area:", consult.get('Scan_Body_Part','')],
            ["Findings:", consult.get('Scan_Findings','')],
            ["Reporting Radiologist:", consult.get('Scan_Reporting_Doctor','')]
        ]
        s_table = Table(scan_data, colWidths=[150, 390])
        s_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(s_table)
        story.append(Spacer(1, 12))

    story.append(Paragraph(f"<font size=8 color='#64748b'>Official Consultation Record generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} via MediQR System.</font>", normal_style))

    doc.build(story)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------- routes
@app.context_processor
def inject_user():
    return {
        "me": current_patient(),
        "is_admin": is_admin_session()
    }


@app.route("/")
def main():
    patients = get_patients()
    consults = get_consultations()
    stats = {
        "patients": len(patients),
        "visits": len(consults),
        "scans": sum(1 for c in consults if c.get("Scan_File")),
        "doctors": len({c["Doctor"] for c in consults if c.get("Doctor")}),
    }
    chart = timeline_svg(consults, [p["Patient_ID"] for p in patients])
    return render_template("main.html", stats=stats, chart=chart)


@app.route("/register")
def register():
    if current_patient() or is_admin_session():
        return redirect(url_for("profile") if not is_admin_session() else url_for("admin_dashboard"))
    return render_template("register.html", tab=request.args.get("tab", "login"))


@app.route("/login", methods=["POST"])
def login():
    raw_pid = request.form.get("pid", "")
    pid = normalise_id(raw_pid)
    password = request.form.get("password", "")

    if raw_pid.strip().upper() == "ADMIN" or pid == "ADMIN":
        users_dict = get_users()
        stored = users_dict.get("ADMIN")
        if not stored:
            save_user("ADMIN", "Admin@1234")
            stored = get_users().get("ADMIN")

        if stored and check_password_hash(stored, password):
            session.clear()
            session["pid"] = "ADMIN"
            session["is_admin"] = True
            log_audit_event("ADMIN", "ADMIN_LOGIN", "System/Admin", request.remote_addr, "Success")
            flash("Welcome to Admin Control Center!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            log_audit_event("ADMIN", "ADMIN_LOGIN_FAILED", "Auth", request.remote_addr, "Failed")
            flash("Incorrect Admin password. (Default is Admin@1234)", "error")
            return redirect(url_for("register", tab="login"))

    stored = get_users().get(pid)
    if stored and check_password_hash(stored, password):
        session.clear()
        session["pid"] = pid
        session["is_admin"] = False
        log_audit_event(pid, "USER_LOGIN", f"Patient/{pid}", request.remote_addr, "Success")
        return redirect(url_for("profile"))

    log_audit_event(pid or "UNKNOWN", "USER_LOGIN_FAILED", "Auth", request.remote_addr, "Failed")
    flash("Incorrect Patient ID or password. Please try again.", "error")
    return redirect(url_for("register", tab="login"))


@app.route("/signup", methods=["POST"])
def signup():
    f = request.form
    pid = normalise_id(f.get("pid", ""))
    patient = get_patient(pid)
    back = lambda msg: (flash(msg, "error"), redirect(url_for("register", tab="signup")))[1]

    if not patient:
        return back("We could not verify these details against our patient records.")

    dob_match = normalise_dob(patient["DOB"]) == normalise_dob(f.get("dob", ""))
    mobile_match = normalise_mobile(patient["Mobile_No"]) == normalise_mobile(f.get("mobile", ""))

    if not (dob_match and mobile_match):
        return back("We could not verify these details against our patient records.")
    if pid in get_users():
        flash("This patient is already registered. Please sign in.", "error")
        return redirect(url_for("register", tab="login"))
    if len(f.get("password", "")) < 6:
        return back("Password must be at least 6 characters.")
    if f.get("password") != f.get("confirm"):
        return back("Passwords do not match.")

    save_user(pid, f["password"])
    get_or_create_patient_qr_token(pid)
    log_audit_event(pid, "USER_SIGNUP", f"Patient/{pid}", request.remote_addr, "Success")
    flash("Registration successful! Sign in with your new password.", "success")
    return redirect(url_for("register", tab="login"))


@app.route("/profile")
def profile():
    if is_admin_session():
        return redirect(url_for("admin_dashboard"))

    p = current_patient()
    if not p:
        flash("Please sign in to view your profile.", "error")
        return redirect(url_for("register"))
    consults = get_consultations(p["Patient_ID"])
    completeness = profile_completeness(p)
    response = treatment_response_status(consults)
    alerts = missing_info_alerts(p, consults)
    docs = get_documents(p["Patient_ID"])

    patient_qr_token = get_or_create_patient_qr_token(p["Patient_ID"])

    # attach consultation tokens
    for c in consults:
        c["qr_token"] = get_or_create_consultation_qr_token(p["Patient_ID"], c["Visit_No"])

    return render_template(
        "profile.html", p=p, age=age_from(p["DOB"]), vitals=vitals_status(p),
        consults=list(reversed(consults)), scans=[c for c in reversed(consults) if c.get("Scan_File")],
        tips=suggestions(p, consults), completeness=completeness, response=response,
        alerts=alerts, explain=explain_medical_term, docs=docs,
        patient_qr_token=patient_qr_token
    )


# ------------------------------------------------------------- Admin Routes
@app.route("/admin")
def admin_dashboard():
    if not is_admin_session():
        flash("Admin privileges required.", "error")
        return redirect(url_for("register"))

    patients = get_patients()
    consults = get_consultations()
    tokens = get_qr_tokens()
    logs = get_audit_logs()
    docs = get_documents()

    stats = {
        "patients": len(patients),
        "visits": len(consults),
        "active_qrs": sum(1 for t in tokens if t.get("Status") == "Active"),
        "revoked_qrs": sum(1 for t in tokens if t.get("Status") == "Revoked"),
        "docs": len(docs),
        "logs": len(logs)
    }

    return render_template("admin.html", patients=patients, consults=list(reversed(consults)), stats=stats, tokens=tokens, logs=logs[:20], docs=docs)


@app.route("/admin/patient/add", methods=["POST"])
def admin_add_patient():
    if not is_admin_session():
        flash("Admin privileges required.", "error")
        return redirect(url_for("register"))

    f = request.form
    pid = normalise_id(f.get("pid", ""))
    if not pid:
        flash("Valid Patient ID required.", "error")
        return redirect(url_for("admin_dashboard"))

    p_data = {
        "Patient_ID": pid,
        "Name": f.get("name", "").strip(),
        "DOB": f.get("dob", "").strip(),
        "Gender": f.get("gender", "Male").strip(),
        "Aadhaar_No": f.get("aadhaar", "XXXX XXXX 0000").strip(),
        "Blood_Group": f.get("blood_group", "O+").strip(),
        "Mobile_No": f.get("mobile", "").strip(),
        "Address": f.get("address", "").strip(),
        "Emergency_Contact_Name": f.get("emergency_name", "").strip(),
        "Emergency_Contact_No": f.get("emergency_no", "").strip(),
        "Patient_Status": f.get("status", "Active").strip(),
        "Heart_Rate_bpm": f.get("hr", "75").strip(),
        "Temperature_C": f.get("temp", "36.8").strip(),
        "Blood_Pressure_mmHg": f.get("bp", "120/80").strip(),
        "Oxygen_Saturation_%": f.get("spo2", "98").strip(),
        "Latest_Diagnosis": f.get("diagnosis", "General Evaluation").strip(),
        "Latest_Doctor": f.get("doctor", "Dr. Arun Kumar").strip(),
        "Latest_Consultation_Date": datetime.now().strftime("%d-%m-%Y"),
        "Current_Treatment_Plan": f.get("plan", "General Health Observation").strip(),
        "Next_Follow_up": f.get("follow_up", "1 month").strip()
    }

    save_patient_record(p_data)
    get_or_create_patient_qr_token(pid)
    log_audit_event("ADMIN", "ADMIN_ADD_PATIENT", f"Patient/{pid}", request.remote_addr, "Success")
    flash(f"Patient record {pid} ({p_data['Name']}) created successfully!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/patient/delete/<pid>", methods=["POST"])
def admin_delete_patient(pid):
    if not is_admin_session():
        flash("Admin privileges required.", "error")
        return redirect(url_for("register"))

    delete_patient_record(pid)
    log_audit_event("ADMIN", "ADMIN_DELETE_PATIENT", f"Patient/{pid}", request.remote_addr, "Success")
    flash(f"Patient record {pid} has been removed from system.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/consultation/add", methods=["POST"])
def admin_add_consultation():
    if not is_admin_session():
        flash("Admin privileges required.", "error")
        return redirect(url_for("register"))

    f = request.form
    pid = normalise_id(f.get("pid", ""))
    patient = get_patient(pid)
    if not patient:
        flash("Specified Patient ID does not exist.", "error")
        return redirect(url_for("admin_dashboard"))

    patient_consults = get_consultations(pid)
    next_visit = len(patient_consults) + 1

    c_data = {
        "Patient_ID": pid,
        "Visit_No": str(next_visit),
        "Date": f.get("date", datetime.now().strftime("%d-%m-%Y")).strip(),
        "Doctor": f.get("doctor", "Dr. Arun Kumar").strip(),
        "Specialist": f.get("specialist", "General Physician").strip(),
        "Symptom_1": f.get("symptom_1", "").strip(),
        "Symptom_2": f.get("symptom_2", "").strip(),
        "Symptom_3": f.get("symptom_3", "").strip(),
        "Diagnosis": f.get("diagnosis", "").strip(),
        "Treatment_1": f.get("treatment_1", "").strip(),
        "Treatment_2": f.get("treatment_2", "").strip(),
        "Treatment_3": f.get("treatment_3", "").strip(),
        "Severity": f.get("severity", "Moderate").strip(),
        "Scan_Type": f.get("scan_type", "").strip(),
        "Scan_Body_Part": f.get("scan_part", "").strip(),
        "Scan_Findings": f.get("scan_findings", "").strip(),
        "Scan_Reporting_Doctor": f.get("scan_doctor", "").strip(),
        "Scan_File": f.get("scan_file", "").strip(),
        "Handover_Notes": f.get("notes", "").strip()
    }

    save_consultation_record(c_data)
    get_or_create_consultation_qr_token(pid, next_visit)
    log_audit_event("ADMIN", "ADMIN_ADD_CONSULTATION", f"Consultation/{pid}/{next_visit}", request.remote_addr, "Success")
    flash(f"New consultation Visit #{next_visit} added for {pid}!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/consultation/delete/<pid>/<visit_no>", methods=["POST"])
def admin_delete_consultation(pid, visit_no):
    if not is_admin_session():
        flash("Admin privileges required.", "error")
        return redirect(url_for("register"))

    delete_consultation_record(pid, visit_no)
    log_audit_event("ADMIN", "ADMIN_DELETE_CONSULTATION", f"Consultation/{pid}/{visit_no}", request.remote_addr, "Success")
    flash(f"Consultation Visit #{visit_no} for {pid} has been deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/qr/image/<token_id>")
def qr_image(token_id):
    target_url = url_for("qr_scan", token_id=token_id, _external=True)
    buf = generate_qr_png_io(target_url)
    return send_file(buf, mimetype="image/png")


@app.route("/qr/scan/<token_id>")
def qr_scan(token_id):
    token = get_token_by_id(token_id)
    ip_addr = request.remote_addr
    user_id = session.get("pid", "ANONYMOUS")

    if not token:
        log_audit_event(user_id, "QR_SCAN_UNKNOWN", f"Token/{token_id}", ip_addr, "Failed")
        flash("Invalid or unknown QR code scanned.", "error")
        return redirect(url_for("scanner"))

    if token["Status"] == "Revoked":
        log_audit_event(user_id, "QR_SCAN_REVOKED", f"Token/{token_id}", ip_addr, "Denied")
        flash("This QR code has been revoked and is no longer active.", "error")
        return redirect(url_for("scanner"))

    log_audit_event(user_id, "QR_SCAN_SUCCESS", f"Token/{token_id}", ip_addr, "Success")

    if token["Type"] == "patient":
        return redirect(url_for("emergency_view", pid=token["Patient_ID"]))
    elif token["Type"] == "consultation":
        return redirect(url_for("consultation_report", pid=token["Patient_ID"], visit_no=token["Visit_No"]))

    return redirect(url_for("main"))


@app.route("/qr/revoke/<token_id>", methods=["POST"])
def revoke_qr(token_id):
    token = get_token_by_id(token_id)
    p = current_patient()

    if not is_admin_session() and (not p or p["Patient_ID"] != token.get("Patient_ID")):
        flash("Unauthorized action.", "error")
        return redirect(url_for("register"))

    if token:
        revoke_qr_token(token_id)
        new_token = get_or_create_patient_qr_token(token["Patient_ID"])
        actor = "ADMIN" if is_admin_session() else p["Patient_ID"]
        log_audit_event(actor, "QR_REVOKED_REPLACED", f"Token/{token_id}->{new_token}", request.remote_addr, "Success")
        flash("Compromised QR code has been revoked and a fresh QR code generated.", "success")

    return redirect(url_for("admin_dashboard") if is_admin_session() else url_for("profile"))


@app.route("/scanner")
def scanner():
    return render_template("scanner.html")


@app.route("/consultation/<pid>/<visit_no>")
def consultation_report(pid, visit_no):
    p = get_patient(normalise_id(pid))
    if not p:
        flash("Patient record not found.", "error")
        return redirect(url_for("main"))
    consults = get_consultations(p["Patient_ID"])
    consult = next((c for c in consults if str(c["Visit_No"]) == str(visit_no)), None)
    if not consult:
        flash("Consultation visit record not found.", "error")
        return redirect(url_for("profile"))

    qr_token = get_or_create_consultation_qr_token(p["Patient_ID"], visit_no)
    docs = [d for d in get_documents(p["Patient_ID"]) if str(d.get("Visit_No","")) == str(visit_no)]

    return render_template("consultation_report.html", p=p, age=age_from(p["DOB"]), consult=consult, qr_token=qr_token, docs=docs)


@app.route("/pdf/patient/<pid>")
def download_patient_pdf(pid):
    p = get_patient(normalise_id(pid))
    if not p:
        flash("Patient record not found.", "error")
        return redirect(url_for("main"))

    user_pid = session.get("pid")
    if not is_admin_session() and user_pid != p["Patient_ID"]:
        log_audit_event(user_pid or "ANONYMOUS", "PDF_ACCESS_DENIED", f"Patient/{pid}", request.remote_addr, "Denied")

    consults = get_consultations(p["Patient_ID"])
    token_id = get_or_create_patient_qr_token(p["Patient_ID"])
    qr_url = url_for("qr_scan", token_id=token_id, _external=True)

    pdf_buf = generate_patient_pdf_bytes(p, consults, vitals_status(p), qr_url)
    log_audit_event(user_pid or "GUEST", "PDF_DOWNLOAD_PATIENT", f"Patient/{pid}", request.remote_addr, "Success")
    return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name=f"MediQR_Summary_{p['Patient_ID']}.pdf")


@app.route("/pdf/consultation/<pid>/<visit_no>")
def download_consultation_pdf(pid, visit_no):
    p = get_patient(normalise_id(pid))
    if not p:
        flash("Patient record not found.", "error")
        return redirect(url_for("main"))

    consults = get_consultations(p["Patient_ID"])
    consult = next((c for c in consults if str(c["Visit_No"]) == str(visit_no)), None)
    if not consult:
        flash("Consultation record not found.", "error")
        return redirect(url_for("profile"))

    token_id = get_or_create_consultation_qr_token(p["Patient_ID"], visit_no)
    qr_url = url_for("qr_scan", token_id=token_id, _external=True)

    pdf_buf = generate_consultation_pdf_bytes(p, consult, qr_url)
    log_audit_event(session.get("pid","GUEST"), "PDF_DOWNLOAD_CONSULT", f"Consultation/{pid}/{visit_no}", request.remote_addr, "Success")
    return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name=f"MediQR_Consultation_{p['Patient_ID']}_V{visit_no}.pdf")


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/upload", methods=["POST"])
def upload_file():
    p = current_patient()
    if not p and not is_admin_session():
        flash("Please sign in to upload medical documents.", "error")
        return redirect(url_for("register"))

    target_pid = request.form.get("patient_id", p["Patient_ID"] if p else "")
    file = request.files.get("file")
    doc_type = request.form.get("doc_type", "General")
    visit_no = request.form.get("visit_no", "")
    notes = request.form.get("notes", "")

    if not file or file.filename == "":
        flash("No file selected for upload.", "error")
        return redirect(url_for("admin_dashboard") if is_admin_session() else url_for("profile"))

    if not allowed_file(file.filename):
        flash("Invalid file format. Allowed formats: PNG, JPG, JPEG, PDF.", "error")
        return redirect(url_for("admin_dashboard") if is_admin_session() else url_for("profile"))

    orig_name = secure_filename(file.filename)
    ext = orig_name.rsplit(".", 1)[1].lower()
    doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
    saved_filename = f"{target_pid}_{doc_id}.{ext}"

    file.save(os.path.join(UPLOADS_DIR, saved_filename))

    save_document({
        "Doc_ID": doc_id,
        "Patient_ID": target_pid,
        "Visit_No": visit_no,
        "Doc_Type": doc_type,
        "File_Name": saved_filename,
        "Original_Name": orig_name,
        "Upload_Date": datetime.now().strftime("%Y-%m-%d"),
        "Notes": notes
    })

    actor = "ADMIN" if is_admin_session() else target_pid
    log_audit_event(actor, "DOCUMENT_UPLOAD", f"Doc/{doc_id}", request.remote_addr, "Success")
    flash("Medical document uploaded successfully!", "success")
    return redirect(url_for("admin_dashboard") if is_admin_session() else url_for("profile"))


@app.route("/document/<doc_id>")
def serve_document(doc_id):
    docs = read_csv("documents.csv")
    doc = next((d for d in docs if d["Doc_ID"] == doc_id), None)
    if not doc:
        flash("Document not found.", "error")
        return redirect(url_for("profile"))

    me = current_patient()
    if not is_admin_session() and (not me or me["Patient_ID"] != doc["Patient_ID"]):
        log_audit_event(me["Patient_ID"] if me else "ANONYMOUS", "DOCUMENT_ACCESS_DENIED", f"Doc/{doc_id}", request.remote_addr, "Denied")
        flash("Access denied. Authorized authentication required.", "error")
        return redirect(url_for("main"))

    file_path = os.path.join(UPLOADS_DIR, doc["File_Name"])
    if not os.path.exists(file_path):
        static_path = os.path.join(BASE, "static", doc["File_Name"])
        if os.path.exists(static_path):
            file_path = static_path
        else:
            flash("Document file not found on disk.", "error")
            return redirect(url_for("profile"))

    actor = "ADMIN" if is_admin_session() else (me["Patient_ID"] if me else "GUEST")
    log_audit_event(actor, "DOCUMENT_VIEW", f"Doc/{doc_id}", request.remote_addr, "Success")
    return send_file(file_path)


@app.route("/audit")
def audit_view():
    if is_admin_session():
        logs = get_audit_logs()
        return render_template("audit.html", p={"Patient_ID": "ADMIN", "Name": "System Administrator"}, logs=logs)

    p = current_patient()
    if not p:
        flash("Please sign in to view audit logs.", "error")
        return redirect(url_for("register"))

    logs = get_audit_logs()
    patient_logs = [l for l in logs if l.get("User_ID") == p["Patient_ID"] or p["Patient_ID"] in l.get("Resource","")]
    return render_template("audit.html", p=p, logs=patient_logs)


@app.route("/emergency/<pid>")
def emergency_view(pid):
    p = get_patient(normalise_id(pid))
    if not p:
        flash("Patient record not found.", "error")
        return redirect(url_for("main"))
    consults = get_consultations(p["Patient_ID"])
    qr_token = get_or_create_patient_qr_token(p["Patient_ID"])
    return render_template("emergency.html", p=p, age=age_from(p["DOB"]), consults=consults, qr_token=qr_token)


@app.route("/handover/<pid>")
def handover_view(pid):
    p = get_patient(normalise_id(pid))
    if not p:
        flash("Patient record not found.", "error")
        return redirect(url_for("main"))
    consults = get_consultations(p["Patient_ID"])
    response = treatment_response_status(consults)
    completeness = profile_completeness(p)
    alerts = missing_info_alerts(p, consults)
    return render_template(
        "handover.html", p=p, age=age_from(p["DOB"]), consults=list(reversed(consults)),
        response=response, completeness=completeness, alerts=alerts,
        vitals=vitals_status(p), explain=explain_medical_term
    )


@app.route("/prep")
def prep_view():
    p = current_patient()
    consults = get_consultations(p["Patient_ID"]) if p else []
    return render_template("prep.html", p=p, consults=consults)


@app.route("/logout")
def logout():
    actor = "ADMIN" if is_admin_session() else (session.get("pid") or "USER")
    log_audit_event(actor, "USER_LOGOUT", f"User/{actor}", request.remote_addr, "Success")
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("main"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
