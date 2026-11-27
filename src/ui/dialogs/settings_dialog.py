from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, 
                             QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, QComboBox, QCheckBox, 
                             QDialogButtonBox, QMessageBox, QApplication)
from src.config import load_settings, save_settings, logger
from src.cups.discovery import get_system_printers

class SettingsDialog(QDialog):
    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.setWindowTitle("Configurações e Preferências")
        self.resize(540, 420)

        self.settings = load_settings()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # ---------------------------------------------------------------------
        # SEÇÃO 1: Conexão com Servidor de Impressão CUPS (Rede Local)
        # ---------------------------------------------------------------------
        group_server = QGroupBox("Servidor de Impressão CUPS (Rede Local)")
        layout_server = QVBoxLayout(group_server)
        layout_server.setSpacing(10)

        self.lbl_server_status = QLabel()
        self.lbl_server_status.setWordWrap(True)
        layout_server.addWidget(self.lbl_server_status)

        form_server = QFormLayout()
        form_server.setVerticalSpacing(8)

        self.txt_cups_server = QLineEdit(self.settings.get("cups_server", ""))
        self.txt_cups_server.setPlaceholderText("Ex: 192.168.1.28 ou servidor.local (deixe vazio para usar modo local)")
        self.txt_cups_server.textChanged.connect(self.on_server_text_changed)
        form_server.addRow("Endereço do Servidor (IP/Host):", self.txt_cups_server)

        self.sp_cups_port = QSpinBox()
        self.sp_cups_port.setRange(1, 65535)
        self.sp_cups_port.setValue(int(self.settings.get("cups_port", 631)))
        form_server.addRow("Porta do Servidor:", self.sp_cups_port)

        layout_server.addLayout(form_server)

        btns_conn_layout = QHBoxLayout()
        self.btn_test = QPushButton("🔍 Testar Conexão")
        self.btn_test.clicked.connect(lambda: self.test_connection(silent=False))
        btns_conn_layout.addWidget(self.btn_test)

        self.btn_use_local = QPushButton("💻 Usar Impressoras Locais")
        self.btn_use_local.clicked.connect(self.use_local_printers)
        btns_conn_layout.addWidget(self.btn_use_local)

        layout_server.addLayout(btns_conn_layout)
        main_layout.addWidget(group_server)

        # ---------------------------------------------------------------------
        # SEÇÃO 2: Preferências Gerais de Impressão
        # ---------------------------------------------------------------------
        group_general = QGroupBox("Preferências Gerais")
        layout_general = QFormLayout(group_general)
        layout_general.setVerticalSpacing(8)

        self.cb_default_paper = QComboBox()
        self.cb_default_paper.addItems(["A4", "Carta (Letter)", "A3", "A5", "Ofício (Legal)"])
        self.cb_default_paper.setCurrentText(self.settings.get("default_paper", "A4"))
        layout_general.addRow("Tamanho de Papel Padrão:", self.cb_default_paper)

        self.cb_default_media_type = QComboBox()
        self.cb_default_media_type.addItems([
            "Papel Comum (Padrão)",
            "Papel Fotográfico Brilhoso (Glossy)",
            "Papel Fotográfico Fosco (Matte)",
            "Papel Fotográfico (Foto)",
            "Papel Reciclado",
            "Papel Cartão / Grosso",
            "Etiquetas / Adesivo",
            "Envelope",
            "Transparência"
        ])
        self.cb_default_media_type.setCurrentText(self.settings.get("default_media_type", "Papel Comum (Padrão)"))
        layout_general.addRow("Tipo de Papel Padrão:", self.cb_default_media_type)

        self.cb_default_quality = QComboBox()
        self.cb_default_quality.addItems(["Normal (Padrão)", "Rascunho (Econômico / Rápido)", "Alta Qualidade (Foto / Nítido)"])
        self.cb_default_quality.setCurrentText(self.settings.get("default_quality", "Normal (Padrão)"))
        layout_general.addRow("Qualidade de Impressão Padrão:", self.cb_default_quality)

        self.cb_default_print_speed = QComboBox()
        self.cb_default_print_speed.addItems(["Normal (Padrão)", "Rápida (Priorizar Velocidade)", "Lenta / Silenciosa (Maior Precisão)"])
        self.cb_default_print_speed.setCurrentText(self.settings.get("default_print_speed", "Normal (Padrão)"))
        layout_general.addRow("Velocidade de Impressão Padrão:", self.cb_default_print_speed)

        self.chk_keep_history = QCheckBox("Salvar histórico de arquivos impressos")
        self.chk_keep_history.setChecked(self.settings.get("keep_history", True))
        layout_general.addRow("Histórico:", self.chk_keep_history)

        self.sp_max_history = QSpinBox()
        self.sp_max_history.setRange(10, 1000)
        self.sp_max_history.setValue(int(self.settings.get("max_history_entries", 100)))
        layout_general.addRow("Máx. Registros do Histórico:", self.sp_max_history)

        self.sp_cost_sheet = QDoubleSpinBox()
        self.sp_cost_sheet.setRange(0.0, 100.0)
        self.sp_cost_sheet.setSingleStep(0.5)
        self.sp_cost_sheet.setDecimals(2)
        self.sp_cost_sheet.setValue(float(self.settings.get("cost_per_sheet_cents", 5.0)))
        self.sp_cost_sheet.setSuffix(" centavos (R$)")
        self.sp_cost_sheet.setToolTip("Custo médio de 1 folha de papel em centavos de Real (ex: 5.0 = R$ 0,05)")
        layout_general.addRow("Custo Médio por Folha:", self.sp_cost_sheet)

        self.sp_cost_ink = QDoubleSpinBox()
        self.sp_cost_ink.setRange(0.0, 100.0)
        self.sp_cost_ink.setSingleStep(1.0)
        self.sp_cost_ink.setDecimals(2)
        self.sp_cost_ink.setValue(float(self.settings.get("cost_per_page_ink_cents", 10.0)))
        self.sp_cost_ink.setSuffix(" centavos (R$)")
        self.sp_cost_ink.setToolTip("Custo médio estimado de tinta/toner por página A4 (5% de cobertura) em centavos (ex: 10.0 = R$ 0,10)")
        layout_general.addRow("Custo Médio de Tinta/Pág.:", self.sp_cost_ink)

        main_layout.addWidget(group_general)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_and_close)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self.setLayout(main_layout)
        self.refresh_initial_status()

    def set_status_badge(self, text, status_type):
        if status_type == "connected":
            self.lbl_server_status.setText(f"🟢 <b>Status: Conectado</b> — {text}")
            self.lbl_server_status.setStyleSheet("border: 1px solid #10B981; color: #10B981; padding: 8px; border-radius: 6px;")
        elif status_type == "error":
            self.lbl_server_status.setText(f"🔴 <b>Status: Inacessível</b> — {text}")
            self.lbl_server_status.setStyleSheet("border: 1px solid #EF4444; color: #EF4444; padding: 8px; border-radius: 6px;")
        else:
            self.lbl_server_status.setText(f"⚪ <b>Status: Modo Local</b> — {text}")
            self.lbl_server_status.setStyleSheet("border: 1px solid #94A3B8; color: #94A3B8; padding: 8px; border-radius: 6px;")

    def on_server_text_changed(self):
        current = self.txt_cups_server.text().strip()
        if not current:
            self.set_status_badge("Utilizando impressoras locais deste computador.", "local")

    def refresh_initial_status(self):
        server = self.txt_cups_server.text().strip()
        if not server:
            self.set_status_badge("Utilizando impressoras locais deste computador.", "local")
        else:
            self.test_connection(silent=True)

    def test_connection(self, silent=False):
        server = self.txt_cups_server.text().strip()
        port = self.sp_cups_port.value()
        if not server:
            self.set_status_badge("Nenhum servidor configurado. Utilizando impressoras locais.", "local")
            if not silent:
                QMessageBox.information(self, "Modo Local", "Nenhum endereço informado. O aplicativo está utilizando as impressoras locais.")
            return

        self.set_status_badge(f"Verificando comunicação com {server}:{port}...", "local")
        QApplication.processEvents()

        printers = get_system_printers(server, port)
        if printers:
            msg = f"{server}:{port} ({len(printers)} impressora(s) disponível(is))"
            self.set_status_badge(msg, "connected")
            if not silent:
                printers_str = "\n".join([f"• {p}" for p in printers])
                QMessageBox.information(self, "Conexão Bem-Sucedida", f"Conectado ao servidor CUPS em {server}:{port}!\n\nImpressoras encontradas:\n{printers_str}")
        else:
            msg = f"Não foi possível responder em {server}:{port}. Verifique o IP e a rede."
            self.set_status_badge(msg, "error")
            if not silent:
                QMessageBox.warning(self, "Falha de Conexão", f"Não foi possível obter resposta de '{server}:{port}'.\n\nVerifique se o servidor está ligado, na mesma rede e aceitando conexões.")

    def use_local_printers(self):
        self.txt_cups_server.clear()
        self.set_status_badge("Utilizando impressoras locais deste computador.", "local")
        QMessageBox.information(self, "Modo Local", "Campo do servidor limpo. Ao salvar, o aplicativo voltará a utilizar as impressoras locais.")

    def save_and_close(self):
        self.settings["cups_server"] = self.txt_cups_server.text().strip()
        self.settings["cups_port"] = self.sp_cups_port.value()
        self.settings["default_paper"] = self.cb_default_paper.currentText()
        self.settings["default_media_type"] = self.cb_default_media_type.currentText()
        self.settings["default_quality"] = self.cb_default_quality.currentText()
        self.settings["default_print_speed"] = self.cb_default_print_speed.currentText()
        self.settings["keep_history"] = self.chk_keep_history.isChecked()
        self.settings["max_history_entries"] = self.sp_max_history.value()
        self.settings["cost_per_sheet_cents"] = self.sp_cost_sheet.value()
        self.settings["cost_per_page_ink_cents"] = self.sp_cost_ink.value()

        save_settings(self.settings)
        self.main_app.settings = self.settings
        self.main_app.apply_cups_environment()
        self.main_app.load_printers()
        if hasattr(self.main_app, "update_cost_estimate"):
            self.main_app.update_cost_estimate()
        self.accept()
        QMessageBox.information(self, "Sucesso", "Configurações salvas com sucesso!")
