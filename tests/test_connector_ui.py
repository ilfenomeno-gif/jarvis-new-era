from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication, QCheckBox, QPushButton, QWidget

import ui

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _connector(
    *,
    status="disconnected",
    oauth_configured=True,
    oauth_setup=None,
    oauth_setup_url="",
    transport_configured=True,
):
    return {
        "id": "test-provider",
        "name": "Test Provider",
        "type": "remote-mcp",
        "status": status,
        "oauth_configured": oauth_configured,
        "oauth_setup": oauth_setup or [],
        "oauth_setup_url": oauth_setup_url,
        "oauth_redirect_uri": "http://127.0.0.1:8765/oauth/test-provider/callback",
        "oauth_requires_client_secret": True,
        "transport_configured": transport_configured,
        "scopes_declared": ["read"],
        "scopes_granted": ["read"] if status == "connected" else [],
    }


def _click_connector_button(
    monkeypatch, item, button_text, *, begin=None, revoke=None, save_credentials=None
):
    _app()
    parent = QWidget()
    messages = []
    opened = []
    parent.get_connectors = lambda: [item]
    parent.begin_connector_oauth = begin or (lambda _connector_id: "")
    parent.save_connector_oauth_credentials = save_credentials
    parent._configure_connector_oauth = lambda connector: (
        ui.MainWindow._configure_connector_oauth(parent, connector)
    )
    parent._prompt_connector_oauth_setup = lambda connector, _dialog: (
        parent._configure_connector_oauth(connector)
    )
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None

    def disconnect(connector_id):
        assert connector_id == item["id"]
        if revoke:
            revoke()
        item["status"] = "disconnected"
        item["scopes_granted"] = []

    parent.revoke_connector = disconnect
    monkeypatch.setattr(
        ui.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append((title, text)),
    )
    monkeypatch.setattr(
        ui.QMessageBox,
        "warning",
        lambda _parent, title, text: messages.append((title, text)),
    )
    monkeypatch.setattr(ui.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    def execute_dialog(dialog):
        if dialog.windowTitle().startswith("Configura OAuth"):
            fields = dialog.findChildren(ui.QLineEdit)
            fields[0].setText("test-client-id")
            fields[1].setText("test-client-secret")
            assert fields[1].echoMode() == ui.QLineEdit.EchoMode.Password
            assert any(
                "pagina per creare l'app OAuth" in label.text()
                and item["oauth_setup_url"] in label.text()
                for label in dialog.findChildren(ui.QLabel)
            )
            assert any(
                field.text() == item["oauth_redirect_uri"]
                for field in dialog.findChildren(ui.QLineEdit)
            )
            next(
                button
                for button in dialog.findChildren(QPushButton)
                if button.text() == "Salva"
            ).click()
            return int(ui.QDialog.DialogCode.Accepted)
        check = dialog.findChild(QCheckBox)
        assert check is not None
        check.setChecked(True)
        button = next(
            candidate
            for candidate in dialog.findChildren(QPushButton)
            if candidate.text() == button_text
        )
        assert button.isEnabled()
        button.click()
        dialog.accept()
        return 0

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    ui.MainWindow._show_connections_dialog(parent)
    parent.deleteLater()
    _app().processEvents()
    return messages, opened


def test_dependency_install_confirmation_defaults_to_no_and_completes(monkeypatch):
    _app()
    prompts = []
    monkeypatch.setattr(
        ui.QMessageBox,
        "question",
        lambda _parent, title, text, buttons, default: (
            prompts.append((title, text, buttons, default))
            or ui.QMessageBox.StandardButton.No
        ),
    )
    signal = SimpleNamespace(emit=lambda message: None)
    window = SimpleNamespace(_log_sig=signal)
    window._confirm_dependency_install_direct = lambda package: (
        ui.MainWindow._confirm_dependency_install_direct(window, package)
    )
    response = {"event": threading.Event()}

    ui.MainWindow._confirm_dependency_install_on_ui_thread(
        window, "beautifulsoup4", response
    )

    assert response["event"].is_set()
    assert response["confirmed"] is False
    assert "beautifulsoup4" in prompts[0][1]
    assert prompts[0][3] == ui.QMessageBox.StandardButton.No


def test_connector_card_shows_oauth_waiting_then_green_connected(monkeypatch):
    _app()
    parent = QWidget()
    item = _connector(status="disconnected")
    item["oauth_pending"] = True
    parent.get_connectors = lambda: [item]
    parent.get_plugins = lambda: []
    parent.begin_connector_oauth = lambda _connector_id: ""
    parent.save_connector_oauth_credentials = None
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None
    parent.revoke_connector = lambda _connector_id: None
    observed = []

    def refresh_twice(timer, _interval):
        timer.timeout.emit()
        state = next(
            label
            for label in timer.parent().findChildren(ui.QLabel)
            if label.text().startswith("Stato:")
        )
        observed.append((state.text(), state.styleSheet()))
        item["status"] = "connected"
        item["oauth_pending"] = False
        item["scopes_granted"] = ["read"]
        timer.timeout.emit()
        state = next(
            label
            for label in timer.parent().findChildren(ui.QLabel)
            if label.text().startswith("Stato:")
        )
        observed.append((state.text(), state.styleSheet()))

    monkeypatch.setattr(ui.QTimer, "start", refresh_twice)
    monkeypatch.setattr(ui.QDialog, "exec", lambda _dialog: 0)
    ui.MainWindow._show_connections_dialog(parent)
    parent.deleteLater()
    _app().processEvents()

    assert "In attesa di autorizzazione…" in observed[0][0]
    assert observed[0][1] == "color: #f0b84b;"
    assert "Stato: connected" in observed[1][0]
    assert observed[1][1] == "color: #35d07f;"


def test_connector_scope_checkboxes_persist_changes_immediately(monkeypatch):
    _app()
    parent = QWidget()
    item = _connector(status="connected")
    item["scopes_declared"] = ["read", "write"]
    item["scopes_granted"] = ["read"]
    saved = []

    def set_scopes(connector_id, scopes):
        saved.append((connector_id, scopes))
        item["scopes_granted"] = list(scopes)

    parent.get_connectors = lambda: [item]
    parent.get_plugins = lambda: []
    parent.set_connector_scopes = set_scopes
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None
    parent.revoke_connector = lambda _connector_id: None

    def execute_dialog(dialog):
        checks = dialog.findChildren(QCheckBox)
        read_check = next(check for check in checks if check.text() == "read")
        write_check = next(check for check in checks if check.text() == "write")
        assert read_check.isChecked()
        assert not write_check.isChecked()
        read_check.setChecked(False)
        write_check.setChecked(True)
        dialog.accept()
        return int(ui.QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    ui.MainWindow._show_connections_dialog(parent)

    assert saved == [
        ("test-provider", []),
        ("test-provider", ["write"]),
    ]
    assert item["scopes_granted"] == ["write"]


def test_connect_button_saves_missing_credentials_then_starts_oauth(monkeypatch):
    item = _connector(
        oauth_configured=False,
        oauth_setup=["JARVIS_TEST_CLIENT_ID", "JARVIS_TEST_CLIENT_SECRET"],
        oauth_setup_url="https://provider.test/create-app",
    )
    saved = []

    def save_credentials(connector_id, client_id, client_secret):
        saved.append((connector_id, client_id, client_secret))
        item["oauth_configured"] = True
        item["oauth_setup"] = []

    messages, opened = _click_connector_button(
        monkeypatch,
        item,
        "Connetti",
        begin=lambda _connector_id: "https://provider.test/authorize",
        save_credentials=save_credentials,
    )

    assert saved == [("test-provider", "test-client-id", "test-client-secret")]
    assert opened == ["https://provider.test/authorize"]
    assert not messages


def test_google_workspace_setup_enables_connection_and_starts_oauth(monkeypatch):
    _app()
    parent = QWidget()
    item = _connector(
        oauth_configured=False,
        transport_configured=False,
    )
    item.update(
        id="google-workspace",
        name="Google Workspace",
        auth="oauth2",
        oauth_setup=["JARVIS_GOOGLE_CLIENT_ID", "JARVIS_GOOGLE_CLIENT_SECRET"],
    )
    saved = []
    opened = []
    parent.get_connectors = lambda: [item.copy()]

    def save_credentials(connector_id, client_id, client_secret):
        saved.append((connector_id, client_id, client_secret))
        item["oauth_configured"] = True
        item["oauth_setup"] = []
        item["oauth_client_id"] = client_id

    def begin_oauth(connector_id):
        assert connector_id == "google-workspace"
        item["oauth_pending"] = True
        return "https://accounts.google.com/o/oauth2/v2/auth"

    parent.save_connector_oauth_credentials = save_credentials
    parent._configure_connector_oauth = lambda connector: (
        ui.MainWindow._configure_connector_oauth(parent, connector)
    )
    parent.begin_connector_oauth = begin_oauth
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None
    parent.revoke_connector = lambda _connector_id: None
    monkeypatch.setattr(ui.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    def execute_dialog(dialog):
        if dialog.windowTitle().startswith("Configura OAuth"):
            fields = dialog.findChildren(ui.QLineEdit)
            client_id = next(field for field in fields if field.placeholderText() == "Client ID")
            client_secret = next(
                field for field in fields if field.placeholderText() == "Client Secret"
            )
            assert client_secret.echoMode() == ui.QLineEdit.EchoMode.Password
            client_id.setText("google-client-id.apps.googleusercontent.com")
            client_secret.setText("google-client-secret")
            return int(ui.QDialog.DialogCode.Accepted)
        connect = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Connetti"
        )
        assert not connect.isEnabled()
        assert any(
            "Credenziali OAuth mancanti: usa Configura ora" in label.text()
            for label in dialog.findChildren(ui.QLabel)
        )
        assert any(
            "Client ID Google mancante o non valido. Controlla il file .env."
            in label.text()
            for label in dialog.findChildren(ui.QLabel)
        )
        assert any(
            "Endpoint MCP non configurato" in label.text()
            for label in dialog.findChildren(ui.QLabel)
        )
        configure = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Configura ora"
        )
        configure.click()
        assert connect.isEnabled()
        assert not configure.isHidden()
        assert not any(
            "Client ID Google mancante o non valido" in label.text()
            for label in dialog.findChildren(ui.QLabel)
        )
        dialog.findChild(QCheckBox).setChecked(True)
        connect.click()
        assert not connect.isEnabled()
        assert connect.text() == "In attesa…"
        dialog.accept()
        return 0

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    ui.MainWindow._show_connections_dialog(parent)
    assert saved == [(
        "google-workspace", "google-client-id.apps.googleusercontent.com",
        "google-client-secret"
    )]
    assert opened == ["https://accounts.google.com/o/oauth2/v2/auth"]


def test_google_invalid_client_id_shows_ui_error_without_opening_browser(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from core.audit_log import AuditLog
    from core.connectors import ConnectorRegistry
    from core.secret_store import SecretStore

    class FakeBackend:
        def protect(self, data):
            return data

        def unprotect(self, data):
            return data

    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_ID", "invalid-google-id")
    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_SECRET", "test-secret")
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        SecretStore(tmp_path / "secrets.json", FakeBackend()),
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    item = next(item for item in registry.view() if item["id"] == "google-workspace")

    messages, opened = _click_connector_button(
        monkeypatch, item, "Connetti", begin=registry.begin_oauth
    )

    assert not opened
    assert any(
        "Client ID Google mancante o non valido. Controlla il file .env." in message
        for _title, message in messages
    )


def test_google_env_credentials_enable_connect_and_preserve_configure_on_invalid(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from core.audit_log import AuditLog
    from core.connectors import ConnectorRegistry
    from core.env_config import load_env_file
    from core.secret_store import SecretStore

    class FakeBackend:
        def protect(self, data):
            return data

        def unprotect(self, data):
            return data

    _app()
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_SECRET", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'JARVIS_GOOGLE_CLIENT_ID="  valid.apps.googleusercontent.com  "\n'
        "JARVIS_GOOGLE_CLIENT_SECRET=test-secret\n",
        encoding="utf-8",
    )
    load_env_file(env_file)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    secrets.set("connector:google-workspace:client_id", "")
    registry = ConnectorRegistry(
        tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl")
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    google = next(item for item in registry.view() if item["id"] == "google-workspace")
    assert ui.is_google_client_id_valid(google["oauth_client_id"])
    parent = QWidget()
    parent.get_connectors = lambda: [
        item for item in registry.view() if item["id"] == "google-workspace"
    ]
    saved = []
    parent.save_connector_oauth_credentials = lambda *args: saved.append(args)
    parent._configure_connector_oauth = lambda connector: (
        ui.MainWindow._configure_connector_oauth(parent, connector)
    )
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None
    parent.revoke_connector = lambda _connector_id: None

    def execute_dialog(dialog):
        if dialog.windowTitle().startswith("Configura OAuth"):
            client_id = next(
                field for field in dialog.findChildren(ui.QLineEdit)
                if field.placeholderText() == "Client ID"
            )
            secret = next(
                field for field in dialog.findChildren(ui.QLineEdit)
                if field.placeholderText() == "Client Secret"
            )
            assert client_id.text() == "valid.apps.googleusercontent.com"
            assert secret.echoMode() == ui.QLineEdit.EchoMode.Password
            client_id.setText("replacement.apps.googleusercontent.com")
            secret.setText("new-secret")
            return int(ui.QDialog.DialogCode.Accepted)
        connect = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Connetti"
        )
        assert connect.isEnabled()
        configure = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Configura ora"
        )
        assert not configure.isHidden()
        dialog.findChild(ui.QTimer).timeout.emit()
        assert not configure.isHidden()
        configure.click()
        assert not any(
            ui.GOOGLE_CLIENT_ID_ERROR in label.text()
            for label in dialog.findChildren(ui.QLabel)
        )
        dialog.accept()
        return 0

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    ui.MainWindow._show_connections_dialog(parent)
    assert saved == [("google-workspace", "replacement.apps.googleusercontent.com", "new-secret")]

    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_ID", "invalid-id")

    def execute_invalid_dialog(dialog):
        configure = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Configura ora"
        )
        assert not configure.isHidden()
        assert any(
            ui.GOOGLE_CLIENT_ID_ERROR in label.text()
            for label in dialog.findChildren(ui.QLabel)
        )
        dialog.accept()
        return 0

    monkeypatch.setattr(ui.QDialog, "exec", execute_invalid_dialog)
    ui.MainWindow._show_connections_dialog(parent)


def test_connect_button_explains_missing_service_endpoint(monkeypatch):
    item = _connector(transport_configured=False)
    messages, opened = _click_connector_button(monkeypatch, item, "Connetti")

    assert messages == [
        (
            "Connettore non configurato",
            "Test Provider non può ancora collegarsi: manca l'endpoint MCP del servizio.",
        )
    ]
    assert not opened


def test_connect_button_opens_authorization_page(monkeypatch):
    item = _connector()
    messages, opened = _click_connector_button(
        monkeypatch,
        item,
        "Connetti",
        begin=lambda _connector_id: "https://provider.test/authorize",
    )

    assert opened == ["https://provider.test/authorize"]
    assert not messages


def test_connect_button_does_not_open_browser_when_callback_server_fails(monkeypatch):
    item = _connector()

    def fail_to_start(_connector_id):
        raise RuntimeError("OAuth callback port 8770 is already in use.")

    messages, opened = _click_connector_button(
        monkeypatch,
        item,
        "Connetti",
        begin=fail_to_start,
    )

    assert not opened
    assert messages == [
        (
            "Connessione OAuth",
            "Connessione non avviata: RuntimeError: "
            "OAuth callback port 8770 is already in use.",
        )
    ]


def test_missing_oauth_prompt_offers_configure_now(monkeypatch):
    class FakeMessageBox:
        class Icon:
            Information = object()

        class ButtonRole:
            AcceptRole = object()

        class StandardButton:
            Cancel = object()

        def __init__(self, _parent):
            self._buttons = []

        def setIcon(self, _icon):
            pass

        def setWindowTitle(self, _title):
            pass

        def setText(self, _text):
            pass

        def addButton(self, *args):
            button = object()
            self._buttons.append(button)
            return button

        def exec(self):
            self._clicked = self._buttons[0]

        def clickedButton(self):
            return self._clicked

    parent = QWidget()
    opened = []
    parent._configure_connector_oauth = lambda connector: (
        opened.append(connector["id"]) or True
    )
    monkeypatch.setattr(ui, "QMessageBox", FakeMessageBox)

    assert ui.MainWindow._prompt_connector_oauth_setup(
        parent, {"id": "github", "name": "GitHub"}, parent
    )
    assert opened == ["github"]


def test_higgsfield_uses_dynamic_registration_without_credential_form(monkeypatch):
    item = _connector(oauth_configured=True)
    item["id"] = "higgsfield"
    item["name"] = "Higgsfield"
    item["oauth_dynamic_registration"] = True
    item["oauth_requires_client_secret"] = False
    saved = []
    messages, opened = _click_connector_button(
        monkeypatch,
        item,
        "Connetti",
        begin=lambda _connector_id: "https://provider.test/authorize",
        save_credentials=lambda *args: saved.append(args),
    )
    assert opened == ["https://provider.test/authorize"]
    assert not saved
    assert not messages


def test_public_apis_section_activates_and_searches_catalog(monkeypatch):
    _app()
    parent = QWidget()
    parent._public_apis_workers = set()
    parent.get_connectors = lambda: [_connector()]
    state = {"status": "inactive", "message": "Attiva per iniziare"}
    parent.get_public_apis_status = lambda: dict(state)

    def activate():
        state.update(status="active", message="Catalogo attivo")
        return dict(state)

    parent.activate_public_apis = activate
    parent.query_public_apis = lambda query: f"Risultati per {query}: meteo"
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None
    parent.begin_connector_oauth = lambda _connector_id: ""
    parent.revoke_connector = lambda _connector_id: None
    captured = {}

    def execute_dialog(dialog):
        activate_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Attiva Catalogo"
        )
        activate_button.click()
        search_input = next(
            field
            for field in dialog.findChildren(ui.QLineEdit)
            if field.placeholderText().startswith("Cerca per parola chiave")
        )
        search_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Cerca"
        )
        result = next(
            editor
            for editor in dialog.findChildren(ui.QPlainTextEdit)
            if editor.isReadOnly()
        )
        assert not search_input.isHidden() and not search_button.isHidden()
        search_input.setText("weather")
        search_button.click()
        for _ in range(150):
            _app().processEvents()
            if result.toPlainText().startswith("Risultati per"):
                break
            ui.QTest.qWait(20)
        captured["result"] = result.toPlainText()
        dialog.accept()
        return 0

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    ui.MainWindow._show_connections_dialog(parent)
    assert captured["result"] == "Risultati per weather: meteo"


def test_github_oauth_test_shows_http_401_in_red_without_saving(monkeypatch):
    _app()
    parent = QWidget()
    connector = _connector(
        oauth_configured=False,
        oauth_setup=["JARVIS_GITHUB_CLIENT_ID", "JARVIS_GITHUB_CLIENT_SECRET"],
        oauth_setup_url="https://github.com/settings/applications/new",
    )
    connector.update(id="github", name="GitHub")
    tested = []
    saved = []

    def test_credentials(connector_id, client_id, client_secret):
        tested.append((connector_id, client_id, client_secret))
        raise RuntimeError("GitHub API ha restituito HTTP 401: Client Secret non valido.")

    parent.test_connector_oauth = test_credentials
    parent.save_connector_oauth_credentials = (
        lambda *args: saved.append(args)
    )
    captured = {}

    def execute_dialog(dialog):
        fields = dialog.findChildren(ui.QLineEdit)
        client_id = next(field for field in fields if field.placeholderText() == "Client ID")
        client_secret = next(
            field for field in fields if field.placeholderText() == "Client Secret"
        )
        client_id.setText("test-client-id")
        client_secret.setText("test-client-secret")
        next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Verifica Connessione"
        ).click()

        for _ in range(100):
            _app().processEvents()
            status = next(
                label
                for label in dialog.findChildren(ui.QLabel)
                if "GitHub API ha restituito HTTP 401" in label.text()
            ) if any(
                "GitHub API ha restituito HTTP 401" in label.text()
                for label in dialog.findChildren(ui.QLabel)
            ) else None
            if status is not None:
                captured["message"] = status.text()
                captured["style"] = status.styleSheet()
                break
            ui.QTest.qWait(20)
        dialog.reject()
        return int(ui.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    assert not ui.MainWindow._configure_connector_oauth(parent, connector)
    assert tested == [
        ("github", "test-client-id", "test-client-secret")
    ]
    assert "HTTP 401" in captured["message"]
    assert "color: #ff5c68" in captured["style"]
    assert not saved


def test_github_oauth_test_shows_reachability_success_in_green(monkeypatch):
    _app()
    parent = QWidget()
    connector = _connector(
        oauth_configured=False,
        oauth_setup=["JARVIS_GITHUB_CLIENT_ID", "JARVIS_GITHUB_CLIENT_SECRET"],
        oauth_setup_url="https://github.com/settings/applications/new",
    )
    connector.update(id="github", name="GitHub")
    parent.test_connector_oauth = lambda *_args: (
        "API GitHub raggiungibile. Il Client Secret verrà verificato da GitHub "
        "durante il login OAuth."
    )
    parent.save_connector_oauth_credentials = lambda *_args: None
    captured = {}

    def execute_dialog(dialog):
        fields = dialog.findChildren(ui.QLineEdit)
        next(field for field in fields if field.placeholderText() == "Client ID").setText(
            "test-client-id"
        )
        next(
            field
            for field in fields
            if field.placeholderText() == "Client Secret"
        ).setText("test-client-secret")
        next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Verifica Connessione"
        ).click()

        for _ in range(100):
            _app().processEvents()
            status = next(
                (
                    label
                    for label in dialog.findChildren(ui.QLabel)
                    if "API GitHub raggiungibile" in label.text()
                ),
                None,
            )
            if status is not None:
                captured["message"] = status.text()
                captured["style"] = status.styleSheet()
                break
            ui.QTest.qWait(20)
        dialog.reject()
        return int(ui.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    assert not ui.MainWindow._configure_connector_oauth(parent, connector)
    assert "API GitHub raggiungibile" in captured["message"]
    assert "Client Secret verrà verificato" in captured["message"]
    assert "color: #35d07f" in captured["style"]


def test_github_manual_token_dialog_saves_without_opening_browser(monkeypatch):
    _app()
    parent = QWidget()
    connector = _connector(status="disconnected", oauth_configured=False)
    connector.update(
        id="github",
        name="GitHub",
        oauth_setup=["JARVIS_GITHUB_CLIENT_ID", "JARVIS_GITHUB_CLIENT_SECRET"],
        oauth_setup_url="https://github.com/settings/applications/new",
    )
    saved = []
    messages = []
    opened = []

    def save_token(connector_id, token):
        saved.append((connector_id, token))
        connector["status"] = "connected"
        connector["scopes_granted"] = []

    parent.save_connector_token = save_token
    parent.get_connectors = lambda: [connector]
    parent.begin_connector_oauth = lambda _connector_id: ""
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None
    parent.revoke_connector = lambda _connector_id: None
    parent._configure_github_pat = lambda item: (
        ui.MainWindow._configure_github_pat(parent, item)
    )
    monkeypatch.setattr(ui.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)
    monkeypatch.setattr(
        ui.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append((title, text)),
    )
    monkeypatch.setattr(
        ui.QMessageBox,
        "warning",
        lambda _parent, title, text: messages.append((title, text)),
    )

    def execute_dialog(dialog):
        if dialog.windowTitle() == "Usa Token Manuale — GitHub":
            token_field = next(
                field
                for field in dialog.findChildren(ui.QLineEdit)
                if field.placeholderText() == "ghp_…"
            )
            assert token_field.echoMode() == ui.QLineEdit.EchoMode.Password
            token_field.setText("fake-github-pat")
            assert any(
                "repo e read:org" in label.text()
                for label in dialog.findChildren(ui.QLabel)
            )
            ui.QTest.qWait(450)
            assert saved == [("github", "fake-github-pat")]
            assert any(
                "salvato nel vault cifrato" in label.text()
                for label in dialog.findChildren(ui.QLabel)
            )
            next(
                button
                for button in dialog.findChildren(QPushButton)
                if button.text() == "Chiudi"
            ).click()
            return int(ui.QDialog.DialogCode.Accepted)

        assert any(
            button.text() == "Usa Token Manuale"
            for button in dialog.findChildren(QPushButton)
        )
        next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Usa Token Manuale"
        ).click()
        dialog.accept()
        return int(ui.QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    ui.MainWindow._show_connections_dialog(parent)

    assert saved == [("github", "fake-github-pat")]
    assert connector["status"] == "connected"
    assert not opened
    assert not messages


@pytest.mark.parametrize(
    ("connector_id", "name", "oauth_error"),
    [
        ("github", "GitHub", "bad_verification_code: codice OAuth scaduto."),
        (
            "google-workspace", "Google Workspace",
            "invalid_client: Client OAuth non valido: verifica Client ID e Client Secret. "
            "Dettaglio del provider: The OAuth client was not found.",
        ),
    ],
)
def test_connections_dialog_surfaces_oauth_callback_error_once(
    monkeypatch, connector_id, name, oauth_error
):
    _app()
    parent = QWidget()
    connector = _connector(status="error")
    connector.update(
        id=connector_id,
        name=name,
        oauth_error=oauth_error,
    )
    parent.get_connectors = lambda: [connector]
    parent.begin_connector_oauth = lambda _connector_id: ""
    parent.save_connector_oauth_credentials = None
    parent.grant_connector_scopes = lambda _connector_id, _scopes: None
    parent.revoke_connector = lambda _connector_id: None
    messages = []
    monkeypatch.setattr(
        ui.QMessageBox,
        "warning",
        lambda _parent, title, text: messages.append((title, text)),
    )
    captured = {}

    def execute_dialog(dialog):
        timer = dialog.findChild(ui.QTimer)
        assert timer is not None
        timer.timeout.emit()
        status = next(
            label
            for label in dialog.findChildren(ui.QLabel)
            if "Errore OAuth:" in label.text()
        )
        captured["style"] = status.styleSheet()
        timer.timeout.emit()
        dialog.accept()
        return 0

    monkeypatch.setattr(ui.QDialog, "exec", execute_dialog)
    ui.MainWindow._show_connections_dialog(parent)
    assert messages == [
        (
            "Connessione OAuth",
            f"{name}: {oauth_error}",
        )
    ]
    assert "color: #ff5c68" in captured["style"]


def test_disconnect_button_revokes_token_and_reports_success(monkeypatch):
    item = _connector(status="connected")
    revoked = []
    messages, opened = _click_connector_button(
        monkeypatch,
        item,
        "Disconnetti",
        revoke=lambda: revoked.append(True),
    )

    assert revoked == [True]
    assert item["status"] == "disconnected"
    assert messages == [
        ("Disconnessione", "Test Provider è stato disconnesso da Jarvis.")
    ]
    assert not opened


def test_disconnect_button_explains_when_already_disconnected(monkeypatch):
    item = _connector()
    messages, opened = _click_connector_button(monkeypatch, item, "Disconnetti")

    assert messages == [("Disconnessione", "Test Provider è già disconnesso.")]
    assert not opened
