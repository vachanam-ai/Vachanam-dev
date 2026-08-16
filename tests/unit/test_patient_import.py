import io

import pytest
from openpyxl import Workbook

from backend.services.patient_import import PatientImportError, parse_patient_file


def test_csv_reads_only_required_patient_fields_and_reports_bad_rows():
    content = (
        "Patient Name,Mobile Number,Age,Sex,Diagnosis,Outstanding Balance\n"
        "Lakshmi,9876543210,42,Female,private note,500\n"
        "No Phone,123,30,Male,ignore,0\n"
        "Child,9876543210,8,M,ignore,0\n"
    ).encode()

    rows, errors = parse_patient_file("patients.csv", content)

    assert [(row.name, row.phone, row.age, row.gender) for row in rows] == [
        ("Lakshmi", "+919876543210", 42, "female"),
        ("Child", "+919876543210", 8, "male"),
    ]
    assert errors == [{"row": 3, "error": "mobile number is invalid"}]
    assert not hasattr(rows[0], "diagnosis")


def test_xlsx_normalizes_patient_name_and_numeric_mobile():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Phone", "Age", "Gender"])
    sheet.append(["శ్రీదేవి", 9876543211, 35, "F"])
    payload = io.BytesIO()
    workbook.save(payload)

    rows, errors = parse_patient_file("patients.xlsx", payload.getvalue())

    assert errors == []
    assert rows[0].name == "Shridevi"
    assert rows[0].phone == "+919876543211"


def test_missing_name_or_phone_header_is_rejected():
    with pytest.raises(PatientImportError, match="Name and Mobile/Phone"):
        parse_patient_file("patients.csv", b"Name,Age\nRavi,30\n")


def test_csv_transliterates_name_and_unicode_age_digits():
    rows, errors = parse_patient_file(
        "patients.csv",
        "Name,Phone,Age\nవినయ్,9876543210,౨౪\n".encode("utf-8"),
    )

    assert errors == []
    assert (rows[0].name, rows[0].age) == ("Vinay", 24)
