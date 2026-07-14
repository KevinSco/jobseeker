"""Tests for credential storage."""

from job_automation.browser.credentials import CredentialStore, PortalCredential


def test_credential_store_roundtrip(tmp_path):
    path = tmp_path / "credentials.enc"
    store = CredentialStore(path=path)
    store.save(
        "hiringcafe",
        PortalCredential(username="user@example.com", password="secret-pass"),
    )
    loaded = store.get("hiringcafe")
    assert loaded is not None
    assert loaded.username == "user@example.com"
    assert loaded.password == "secret-pass"

    statuses = store.list_status()
    hc = next(item for item in statuses if item.portal == "hiringcafe")
    assert hc.configured is True
    assert hc.username == "user@example.com"

    store.delete("hiringcafe")
    assert store.get("hiringcafe") is None
