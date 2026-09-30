"""Every new invoice and every recorded payment is emailed with its PDF (config/invoice.yaml `email`)."""
import dataclasses
import smtplib

import pytest
from fastapi.testclient import TestClient

from app.invoice import mailer
from app.main import create_app
from app.settings import get_settings

from .test_invoice_api import PASSCODE, invoice_body, k1_line


class FakeSMTP:
    sent: list = []
    logins: list = []
    fail = False

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port

    def __enter__(self):
        if FakeSMTP.fail:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        FakeSMTP.logins.append((user, password))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.fail = [], [], False
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)


def make_client(tmp_path, **settings_changes):
    settings = dataclasses.replace(
        get_settings(), staff_passcode=PASSCODE, secret_key="test-secret",
        database_url=f"sqlite:///{(tmp_path / 'invoices.db').as_posix()}", **settings_changes,
    )
    client = TestClient(create_app(settings))
    token = client.post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_new_invoice_and_payment_are_emailed(tmp_path):
    client, auth = make_client(tmp_path, smtp_password="abcdefghijklmnop")
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    assert r.status_code == 201
    [msg] = FakeSMTP.sent
    assert msg["To"] == msg["From"] == "printevrdesk@gmail.com"
    assert msg["Subject"] == "Invoice 19 · Sogat Jutti Store · Unpaid"
    [pdf] = list(msg.iter_attachments())
    assert pdf.get_filename() == "Invoice_19_Sogat-Jutti-Store_Unpaid.pdf" and pdf.get_content() == r.content
    assert FakeSMTP.logins == [("printevrdesk@gmail.com", "abcdefghijklmnop")]

    r = client.post("/api/invoices/19/payments", json={"amount": "10000", "date": "2026-10-01", "mode": "upi"}, headers=auth)
    assert r.status_code == 200
    msg = FakeSMTP.sent[1]
    assert msg["Subject"] == "Payment recorded · Invoice 19 · Sogat Jutti Store · Part-paid"
    assert next(msg.iter_attachments()).get_content() == r.content


def test_a_mail_failure_never_stops_the_invoice(tmp_path):
    client, auth = make_client(tmp_path, smtp_password="wrong")
    FakeSMTP.fail = True
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    assert r.status_code == 201 and r.content.startswith(b"%PDF")
    assert client.get("/api/invoices/19", headers=auth).status_code == 200


def test_no_password_no_email(tmp_path):
    client, auth = make_client(tmp_path, smtp_password=None)
    assert client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth).status_code == 201
    assert FakeSMTP.sent == []
