# -*- coding: utf-8 -*-
"""
MaintenanceDialog for Gerenciador de Impressões Pro.
Displays CUPS/IPP supply levels (ink, toner, waste ink box) and driver-aware maintenance actions.
"""

import html
import logging
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QComboBox, QProgressBar, QScrollArea,
    QWidget, QFrame, QMessageBox
)

from src.cups.discovery import is_monochrome_printer
from src.cups.maintenance import (
    get_printer_supply_and_status,
    send_nozzle_check_page,
    send_cups_test_page,
    run_cups_maintenance_command,
    run_escputil_usb_maintenance,
    resume_cups_printer,
)

logger = logging.getLogger("GerenciadorImpressaoPro.MaintenanceDialog")


class SupplyLoaderThread(QThread):
    loaded = pyqtSignal(dict, bool)

    def __init__(self, printer_name, cups_server="", query_network=False):
        super().__init__()
        self.printer_name = printer_name
        self.cups_server = cups_server
        self.query_network = query_network

    def run(self):
        info = get_printer_supply_and_status(
            self.printer_name,
            cups_server=self.cups_server,
            query_network=self.query_network,
        )
        is_mono = is_monochrome_printer(self.printer_name, self.cups_server) if self.printer_name else False
        self.loaded.emit(info, is_mono)


class MaintenanceActionThread(QThread):
    finished_action = pyqtSignal(bool, str)

    def __init__(self, action_key, printer_name, cups_server="", is_mono=False):
        super().__init__()
        self.action_key = action_key
        self.printer_name = printer_name
        self.cups_server = cups_server
        self.is_mono = is_mono

    def run(self):
        try:
            if self.action_key == "nozzle_check":
                send_nozzle_check_page(self.printer_name, self.cups_server, is_mono=self.is_mono)
                self.finished_action.emit(True, f"Página de verificação de bicos enviada para '{self.printer_name}'.")
            elif self.action_key == "test_page":
                send_cups_test_page(self.printer_name, self.cups_server)
                self.finished_action.emit(True, f"Página de teste enviada para '{self.printer_name}'.")
            elif self.action_key == "cups_clean":
                run_cups_maintenance_command(self.printer_name, "Clean all", self.cups_server)
                self.finished_action.emit(True, f"Comando de limpeza de cabeça enviado para '{self.printer_name}'.")
            elif self.action_key == "cups_selftest":
                run_cups_maintenance_command(self.printer_name, "PrintSelfTestPage", self.cups_server)
                self.finished_action.emit(True, f"Autoteste oficial do driver enviado para '{self.printer_name}'.")
            elif self.action_key == "escputil_clean":
                out = run_escputil_usb_maintenance("clean")
                self.finished_action.emit(True, f"Limpeza USB Epson concluída:\n{out}")
            elif self.action_key == "resume":
                resume_cups_printer(self.printer_name, self.cups_server)
                self.finished_action.emit(True, f"Fila '{self.printer_name}' reativada e aceitando trabalhos.")
            else:
                self.finished_action.emit(False, f"Ação desconhecida: {self.action_key}")
        except Exception as e:
            logger.error("Erro na ação de manutenção %s: %s", self.action_key, e)
            self.finished_action.emit(False, str(e))


class MaintenanceDialog(QDialog):
    def __init__(self, main_app, initial_printer="", parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_info = {}
        self.current_is_mono = False
        self.loader_thread = None
        self.action_thread = None
        self._load_req_id = 0
        self._has_printers = False

        self.setWindowTitle("Manutenção de Impressoras e Níveis de Tinta")
        self.resize(720, 620)

        root = QVBoxLayout()
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Seleção de Impressora + Atualização
        top_row = QHBoxLayout()
        lbl_p = QLabel("Impressora:")
        lbl_p.setStyleSheet("font-weight: bold;")
        top_row.addWidget(lbl_p)

        self.cb_printer = QComboBox()
        self.cb_printer.setMinimumWidth(280)
        printers = []
        if hasattr(main_app, "cb_printers"):
            for i in range(main_app.cb_printers.count()):
                p = main_app.cb_printers.itemText(i)
                if p and p != "Salvar como PDF":
                    printers.append(p)
        if printers:
            self._has_printers = True
            self.cb_printer.addItems(printers)
        else:
            self._has_printers = False
            self.cb_printer.addItem("Nenhuma impressora física detectada")
            self.cb_printer.setEnabled(False)

        target_p = initial_printer
        if not target_p and hasattr(main_app, "cb_printers"):
            target_p = main_app.cb_printers.currentText()
        if target_p and target_p in printers:
            self.cb_printer.setCurrentText(target_p)

        self.cb_printer.currentIndexChanged.connect(lambda: self.refresh_printer_info(query_network=False))
        top_row.addWidget(self.cb_printer, stretch=1)

        self.btn_refresh = QPushButton("🔄 Atualizar Leituras")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(lambda: self.refresh_printer_info(query_network=True))
        top_row.addWidget(self.btn_refresh)
        root.addLayout(top_row)

        # Card de Status da Fila e Modelo
        group_status = QGroupBox("Status e Informações da Impressora")
        grid_st = QGridLayout()
        grid_st.setContentsMargins(12, 14, 12, 12)
        grid_st.setHorizontalSpacing(12)
        grid_st.setVerticalSpacing(6)

        self.lbl_model = QLabel("-")
        self.lbl_uri = QLabel("-")
        self.lbl_uri.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_state = QLabel("-")
        self.lbl_updated = QLabel("-")

        self.btn_resume = QPushButton("▶ Retomar Fila")
        self.btn_resume.setVisible(False)
        self.btn_resume.setCursor(Qt.PointingHandCursor)
        self.btn_resume.setStyleSheet("background-color: #16A34A; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px;")
        self.btn_resume.clicked.connect(lambda: self.run_action("resume"))

        grid_st.addWidget(QLabel("<b>Modelo / Driver:</b>"), 0, 0)
        grid_st.addWidget(self.lbl_model, 0, 1, 1, 2)
        grid_st.addWidget(QLabel("<b>Conexão (URI):</b>"), 1, 0)
        grid_st.addWidget(self.lbl_uri, 1, 1, 1, 2)
        grid_st.addWidget(QLabel("<b>Estado da Fila:</b>"), 2, 0)
        grid_st.addWidget(self.lbl_state, 2, 1)
        grid_st.addWidget(self.btn_resume, 2, 2, alignment=Qt.AlignRight)
        grid_st.addWidget(QLabel("<b>Leitura dos Níveis:</b>"), 3, 0)
        grid_st.addWidget(self.lbl_updated, 3, 1, 1, 2)
        grid_st.setColumnStretch(1, 1)

        group_status.setLayout(grid_st)
        root.addWidget(group_status)

        # Card de Níveis de Tinta / Toner / Caixa de Manutenção
        group_markers = QGroupBox("Níveis de Tinta, Toner e Suprimentos")
        markers_outer = QVBoxLayout()
        markers_outer.setContentsMargins(10, 14, 10, 10)

        self.scroll_markers = QScrollArea()
        self.scroll_markers.setWidgetResizable(True)
        self.scroll_markers.setFrameShape(QFrame.NoFrame)
        self.scroll_markers.setMinimumHeight(180)

        self.markers_container = QWidget()
        self.markers_layout = QVBoxLayout(self.markers_container)
        self.markers_layout.setContentsMargins(4, 4, 4, 4)
        self.markers_layout.setSpacing(10)
        self.scroll_markers.setWidget(self.markers_container)

        markers_outer.addWidget(self.scroll_markers)
        group_markers.setLayout(markers_outer)
        root.addWidget(group_markers, stretch=1)

        # Card de Manutenção e Diagnóstico
        group_maint = QGroupBox("Ações de Manutenção e Diagnóstico")
        maint_layout = QGridLayout()
        maint_layout.setContentsMargins(12, 14, 12, 12)
        maint_layout.setSpacing(8)

        self.btn_nozzle = QPushButton("🔍 Verificar Bicos / Purga Leve")
        self.btn_nozzle.setToolTip("Imprime página vetorial com barras CMYK + Preto e grade fina para verificar falhas de bicos.")
        self.btn_nozzle.setCursor(Qt.PointingHandCursor)
        self.btn_nozzle.clicked.connect(lambda: self.confirm_and_run(
            "nozzle_check",
            "Verificação de Bicos",
            "Será impressa 1 folha A4 com padrão CMYK/Preto de verificação de bicos e alinhamento. Continuar?"
        ))

        self.btn_testpage = QPushButton("🖨️ Página de Teste (CUPS)")
        self.btn_testpage.setToolTip("Envia a página de teste padrão do sistema para validar comunicação e cores.")
        self.btn_testpage.setCursor(Qt.PointingHandCursor)
        self.btn_testpage.clicked.connect(lambda: self.confirm_and_run(
            "test_page",
            "Página de Teste",
            "Enviar página de teste padrão para a impressora selecionada?"
        ))

        self.btn_clean = QPushButton("🧼 Limpeza de Cabeça (Driver)")
        self.btn_clean.setCursor(Qt.PointingHandCursor)
        self.btn_clean.clicked.connect(self._on_clean_clicked)

        self.btn_selftest = QPushButton("🧪 Autoteste do Driver")
        self.btn_selftest.setCursor(Qt.PointingHandCursor)
        self.btn_selftest.clicked.connect(lambda: self.confirm_and_run(
            "cups_selftest",
            "Autoteste do Driver",
            "Executar o autoteste interno (PrintSelfTestPage) suportado pelo driver desta impressora?"
        ))

        self.btn_web = QPushButton("🌐 Abrir Painel Web da Impressora")
        self.btn_web.setCursor(Qt.PointingHandCursor)
        self.btn_web.clicked.connect(self._open_printer_web)

        maint_layout.addWidget(self.btn_nozzle, 0, 0)
        maint_layout.addWidget(self.btn_testpage, 0, 1)
        maint_layout.addWidget(self.btn_clean, 1, 0)
        maint_layout.addWidget(self.btn_selftest, 1, 1)
        maint_layout.addWidget(self.btn_web, 2, 0, 1, 2)

        group_maint.setLayout(maint_layout)
        root.addWidget(group_maint)

        # Rodapé
        footer = QHBoxLayout()
        self.lbl_footer_status = QLabel("Pronto.")
        self.lbl_footer_status.setStyleSheet("color: #64748B; font-size: 11px;")
        footer.addWidget(self.lbl_footer_status, stretch=1)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        root.addLayout(footer)

        self.setLayout(root)

        if printers:
            self.refresh_printer_info(query_network=False)
        else:
            self._set_no_printers_state()

    def _effective_cups_server(self):
        if hasattr(self.main_app, "get_effective_cups_server"):
            return self.main_app.get_effective_cups_server()
        return ""

    def _set_no_printers_state(self):
        for btn in (self.btn_refresh, self.btn_nozzle, self.btn_testpage, self.btn_clean, self.btn_selftest, self.btn_web):
            btn.setEnabled(False)
        self._clear_markers_ui("Nenhuma impressora física configurada no sistema.")

    def _clear_markers_ui(self, message="", add_stretch=True):
        while self.markers_layout.count():
            item = self.markers_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        if message:
            lbl = QLabel(message)
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #94A3B8; padding: 18px;")
            self.markers_layout.addWidget(lbl)
        if add_stretch:
            self.markers_layout.addStretch()

    def refresh_printer_info(self, query_network=False):
        if not self._has_printers:
            return
        printer_name = self.cb_printer.currentText()
        if not printer_name:
            return

        self._load_req_id += 1
        req_id = self._load_req_id

        self.btn_refresh.setEnabled(False)
        self.lbl_footer_status.setText(
            "Consultando impressora na rede..." if query_network else "Lendo informações da fila CUPS..."
        )

        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.wait(1000)

        self.loader_thread = SupplyLoaderThread(
            printer_name,
            cups_server=self._effective_cups_server(),
            query_network=query_network,
        )
        self.loader_thread.loaded.connect(lambda info, is_mono, rid=req_id: self._on_info_loaded(info, is_mono, rid))
        self.loader_thread.start()

    def _on_info_loaded(self, info, is_mono, req_id=None):
        if req_id is not None and req_id != self._load_req_id:
            return
        self.btn_refresh.setEnabled(self._has_printers)
        self.current_info = info
        self.current_is_mono = is_mono

        if info.get("error"):
            self.lbl_model.setText("-")
            self.lbl_uri.setText("-")
            self.lbl_state.setText("Erro de consulta")
            self.lbl_updated.setText("-")
            self._clear_markers_ui(info["error"])
            self.lbl_footer_status.setText("Falha ao consultar impressora.")
            return

        self.lbl_model.setText(info.get("model") or "Não informado")
        self.lbl_uri.setText(info.get("device_uri") or "-")

        state_code = info.get("state", "3")
        state_lbl = info.get("state_label", "-")
        reasons = info.get("state_reasons", "none")
        reason_suffix = f" ({reasons})" if reasons and reasons != "none" else ""
        if state_code == "5" or not info.get("is_accepting", True):
            self.lbl_state.setText(f"⚠️ {state_lbl}{reason_suffix}")
            self.lbl_state.setStyleSheet("color: #EF4444; font-weight: bold;")
            self.btn_resume.setVisible(True)
            self.btn_resume.setEnabled(True)
        elif state_code == "4":
            self.lbl_state.setText(f"🖨️ {state_lbl}{reason_suffix}")
            self.lbl_state.setStyleSheet("color: #0284C7; font-weight: bold;")
            self.btn_resume.setVisible(False)
        else:
            self.lbl_state.setText(f"✅ {state_lbl}{reason_suffix}")
            self.lbl_state.setStyleSheet("color: #16A34A; font-weight: bold;")
            self.btn_resume.setVisible(False)

        last_upd = info.get("last_updated")
        src = info.get("source")
        if last_upd:
            src_txt = "consulta IPP ao vivo" if src == "ipp" else "cache do CUPS"
            self.lbl_updated.setText(f"{last_upd} ({src_txt})")
        else:
            self.lbl_updated.setText("Sem leitura registrada ainda")

        # Preencher barras de suprimentos
        markers = info.get("markers") or []
        if markers:
            self._clear_markers_ui(add_stretch=False)

            for m in markers:
                row_w = QWidget()
                row_l = QVBoxLayout(row_w)
                row_l.setContentsMargins(2, 2, 2, 2)
                row_l.setSpacing(3)

                hdr = QHBoxLayout()
                safe_name = html.escape(str(m["name"]))
                safe_type = html.escape(str(m["type_label"]))
                title_txt = f"<b>{safe_name}</b> <span style='color:#64748B; font-size:11px;'>({safe_type})</span>"
                lbl_name = QLabel(title_txt)
                hdr.addWidget(lbl_name)
                hdr.addStretch()

                lvl = m["level"]
                if lvl >= 0:
                    lvl_txt = f"{lvl}%"
                    if m["is_low"]:
                        lvl_txt += "  ⚠️ Baixo" if not m["is_waste"] else "  ⚠️ Atenção"
                elif lvl == -2:
                    lvl_txt = "OK (sem %)"
                elif lvl == -3:
                    lvl_txt = "⚠️ Nível baixo"
                else:
                    lvl_txt = "Desconhecido"

                lbl_lvl = QLabel(lvl_txt)
                lbl_lvl.setStyleSheet("color: #EF4444; font-weight: bold;" if m["is_low"] else "font-weight: bold;")
                hdr.addWidget(lbl_lvl)
                row_l.addLayout(hdr)

                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(max(0, min(100, lvl)) if lvl >= 0 else 0)
                bar.setTextVisible(False)
                bar.setFixedHeight(14)

                chunk_color = m["color"]
                border_color = "#CBD5E1" if chunk_color.upper() in ("#EAB308", "#FFFF00") else "rgba(148,163,184,0.35)"
                bar.setStyleSheet(f"""
                    QProgressBar {{
                        border: 1px solid {border_color};
                        border-radius: 5px;
                        background-color: rgba(148, 163, 184, 0.16);
                    }}
                    QProgressBar::chunk {{
                        background-color: {chunk_color};
                        border-radius: 4px;
                    }}
                """)
                row_l.addWidget(bar)
                self.markers_layout.addWidget(row_w)

            self.markers_layout.addStretch()
        else:
            uri = info.get("device_uri", "")
            if uri == "file:///dev/null" or "Local Raw" in info.get("model", ""):
                msg = "Esta fila está configurada como 'Local Raw Printer' / offline.\nNíveis de suprimentos não estão disponíveis."
            else:
                msg = (
                    "O CUPS ainda não possui leitura de tinta/toner registrada para esta impressora.\n"
                    "Clique em '🔄 Atualizar Leituras' estando na rede da impressora ou após imprimir um documento."
                )
            self._clear_markers_ui(msg)

        # Habilitação dinâmica dos botões de manutenção
        self.btn_nozzle.setEnabled(True)
        self.btn_testpage.setEnabled(True)

        if info.get("supports_clean"):
            self.btn_clean.setEnabled(True)
            self.btn_clean.setToolTip("Executa limpeza de cabeça oficial suportada pelo driver CUPS desta impressora (ex.: Canon GX7000).")
        elif info.get("is_usb_epson"):
            self.btn_clean.setEnabled(True)
            self.btn_clean.setToolTip("Executa limpeza de cabeça via escputil na impressora Epson conectada por USB.")
        else:
            self.btn_clean.setEnabled(False)
            self.btn_clean.setToolTip(
                "O driver CUPS desta impressora não expõe limpeza remota via driver.\n"
                "Use 'Verificar Bicos / Purga Leve' ou abra o 'Painel Web da Impressora' se disponível."
            )

        if info.get("supports_selftest"):
            self.btn_selftest.setEnabled(True)
            self.btn_selftest.setToolTip("Imprime a página de autoteste interna do driver (PrintSelfTestPage).")
        else:
            self.btn_selftest.setEnabled(False)
            self.btn_selftest.setToolTip("O driver desta impressora não declara o comando PrintSelfTestPage no PPD.")

        web_url = info.get("web_url", "")
        if web_url:
            self.btn_web.setEnabled(True)
            self.btn_web.setText(f"🌐 Abrir Painel Web ({web_url})")
            self.btn_web.setToolTip(f"Abre a interface administrativa oficial da impressora no navegador ({web_url}).")
        else:
            self.btn_web.setEnabled(False)
            self.btn_web.setText("🌐 Painel Web Indisponível")
            self.btn_web.setToolTip("Impressora não utiliza endereço IP de rede acessível via navegador.")

        self.lbl_footer_status.setText(f"Pronto — {info.get('printer_name')}.")

    def _on_clean_clicked(self):
        if self.current_info.get("supports_clean"):
            self.confirm_and_run(
                "cups_clean",
                "Limpeza de Cabeça",
                "A limpeza consome um pouco de tinta para desobstruir os bicos de impressão. Deseja iniciar?"
            )
        elif self.current_info.get("is_usb_epson"):
            self.confirm_and_run(
                "escputil_clean",
                "Limpeza Epson USB",
                "Executar ciclo de limpeza de cabeça via USB (escputil)?"
            )

    def _open_printer_web(self):
        url = self.current_info.get("web_url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def confirm_and_run(self, action_key, title, message):
        reply = QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.run_action(action_key)

    def run_action(self, action_key):
        printer_name = self.cb_printer.currentText()
        if not printer_name or not self._has_printers:
            return
        if self.action_thread and self.action_thread.isRunning():
            return

        self.cb_printer.setEnabled(False)
        for b in (self.btn_refresh, self.btn_nozzle, self.btn_testpage, self.btn_clean, self.btn_selftest, self.btn_resume):
            b.setEnabled(False)
        self.lbl_footer_status.setText(f"Executando operação em '{printer_name}'...")

        self.action_thread = MaintenanceActionThread(
            action_key,
            printer_name,
            cups_server=self._effective_cups_server(),
            is_mono=self.current_is_mono,
        )
        self.action_thread.finished_action.connect(self._on_action_finished)
        self.action_thread.start()

    def _on_action_finished(self, ok, msg):
        self.cb_printer.setEnabled(self._has_printers)
        if ok:
            QMessageBox.information(self, "Manutenção", msg)
        else:
            QMessageBox.warning(self, "Aviso na Manutenção", msg)
        self.refresh_printer_info(query_network=False)

    def _wait_threads(self):
        for t in (self.loader_thread, self.action_thread):
            if t and t.isRunning():
                t.wait(2000)

    def accept(self):
        self._wait_threads()
        super().accept()

    def reject(self):
        self._wait_threads()
        super().reject()

    def closeEvent(self, event):
        self._wait_threads()
        super().closeEvent(event)
