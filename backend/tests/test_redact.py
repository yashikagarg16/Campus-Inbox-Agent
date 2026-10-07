from tools.redact import redact


def test_redacts_emails_phones_and_names():
    text = "Contact Riya Sharma at riya.s@college.edu or +91 98765 43210 / 9876543210."
    out = redact(text, names=["Riya Sharma"])
    assert out == "Contact [NAME] at [EMAIL] or [PHONE] / [PHONE]."


def test_keeps_years_and_cgpa():
    text = "Batch 2027, CGPA 8.5, deadline 20/10/2026"
    assert redact(text) == text
