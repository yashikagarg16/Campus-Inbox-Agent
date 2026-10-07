from datetime import datetime

from app.parsing import clean_text, html_to_text, parse_eml


def test_clean_text_strips_quoted_replies_and_extra_blank_lines():
    raw = "Hello\r\n\r\n\r\n\r\nBatch 2027\r\n> old reply line\r\nThanks  ​"
    assert clean_text(raw) == "Hello\n\nBatch 2027\nThanks"


def test_html_keeps_hidden_link_targets():
    text = html_to_text('<p>Register <a href="https://forms.gle/x1">here</a></p><style>p{}</style>')
    assert "https://forms.gle/x1" in text
    assert "p{}" not in text


def test_parse_eml_plain():
    data = (
        b"From: Placement Cell <tpo@example.edu>\r\n"
        b"Subject: Acme hiring 2027 batch\r\n"
        b"Date: Wed, 07 Oct 2026 04:30:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Batch 2027 only. Minimum CGPA 8.0.\r\n"
    )
    parsed = parse_eml(data)
    assert parsed.subject == "Acme hiring 2027 batch"
    assert parsed.body == "Batch 2027 only. Minimum CGPA 8.0."
    assert parsed.received_at == datetime(2026, 10, 7, 10, 0)  # converted to IST


def test_parse_eml_html_only():
    data = (
        b"Subject: x\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<div>Last date: 20 Oct</div><div><a href='https://forms.gle/y'>Apply</a></div>"
    )
    parsed = parse_eml(data)
    assert "Last date: 20 Oct" in parsed.body
    assert "https://forms.gle/y" in parsed.body
