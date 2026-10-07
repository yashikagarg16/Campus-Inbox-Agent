from __future__ import annotations

import json

from app.schemas import Extraction


def ev(value, evidence=None):
    return {"value": value, "evidence": evidence}


def make_extraction(**fields) -> Extraction:
    return Extraction.model_validate(fields)


class FakeLLM:
    """Returns canned responses in order and records the prompts it received."""

    def __init__(self, *responses):
        self.responses = [r if isinstance(r, str) else json.dumps(r) for r in responses]
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeLLM ran out of responses")
        return self.responses.pop(0)


SAMPLE_EMAIL = """Dear Students,

Acme Analytics is hiring for the role of Software Engineer Intern.

Eligibility:
Batch 2027 and 2028 only.
Minimum CGPA 8.0 required.
Branches: CSE, IT, ECE

Last date: 20 Oct, 5 PM.
Register here: https://forms.gle/abc123XYZ

Regards,
Training & Placement Cell
"""

SAMPLE_RESPONSE = {
    "is_opportunity": True,
    "company": ev("Acme Analytics", "Acme Analytics is hiring for the role of Software Engineer Intern."),
    "role": ev("Software Engineer Intern", "Acme Analytics is hiring for the role of Software Engineer Intern."),
    "deadline": ev("2026-10-20T17:00", "Last date: 20 Oct, 5 PM."),
    "form_link": ev("https://forms.gle/abc123XYZ", "Register here: https://forms.gle/abc123XYZ"),
    "batches": ev([2027, 2028], "Batch 2027 and 2028 only."),
    "min_cgpa": ev(8.0, "Minimum CGPA 8.0 required."),
    "cgpa_scale": 10,
    "branches": ev(["CSE", "IT", "ECE"], "Branches: CSE, IT, ECE"),
    "min_10th_percent": ev(None),
    "min_12th_percent": ev(None),
    "max_active_backlogs": ev(None),
    "required_skills": ev(None),
    "other_criteria": [],
}
