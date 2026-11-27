# -*- coding: utf-8 -*-
"""
QueueDialog for Gerenciador de Impressões Pro.
Inspects and manages CUPS print queue jobs (lpstat -o, cancel).
"""

import subprocess
import logging
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)

logger = logging.getLogger("GerenciadorImpressaoPro.QueueDialog")


class QueueDialog(QDialog):
    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.setWindowTitle("Fila de Impressão CUPS")
        self.resize(680, 400)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID do Job", "Impressora", "Usuário", "Tamanho", "Data/Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        self.btn_refresh = QPushButton("🔄 Atualizar Fila")
        self.btn_refresh.clicked.connect(self.load_queue)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_cancel_job = QPushButton("🚫 Cancelar Trabalho Selecionado")
        self.btn_cancel_job.setStyleSheet("background-color: #DC2626; color: white; font-weight: bold;")
        self.btn_cancel_job.clicked.connect(self.cancel_selected_job)
        btn_layout.addWidget(self.btn_cancel_job)

        btn_layout.addStretch()
        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.load_queue()

    def load_queue(self):
        self.table.setRowCount(0)
        try:
            cmd = ['lpstat', '-o']
            server = self.main_app.settings.get("cups_server", "").strip()
            port = self.main_app.settings.get("cups_port", 631)
            if server:
                target = f"{server}:{port}" if ":" not in server else server
                cmd.extend(['-h', target])
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
            if not output:
                return
            lines = output.split('\n')
            self.table.setRowCount(len(lines))
            for row, line in enumerate(lines):
                parts = line.split()
                if len(parts) >= 4:
                    job_id = parts[0]
                    user = parts[1]
                    size = parts[2]
                    date_str = " ".join(parts[3:])
                    printer = job_id.rsplit('-', 1)[0] if '-' in job_id else job_id

                    self.table.setItem(row, 0, QTableWidgetItem(job_id))
                    self.table.setItem(row, 1, QTableWidgetItem(printer))
                    self.table.setItem(row, 2, QTableWidgetItem(user))
                    self.table.setItem(row, 3, QTableWidgetItem(size))
                    self.table.setItem(row, 4, QTableWidgetItem(date_str))
        except Exception as e:
            logger.debug("Falha ao ler fila de impressão: %s", e)

    def cancel_selected_job(self):
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Aviso", "Selecione um trabalho da fila.")
            return
        row = selected[0].row()
        job_id = self.table.item(row, 0).text()

        reply = QMessageBox.question(
            self, "Cancelar Trabalho", f"Deseja realmente cancelar o trabalho '{job_id}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            try:
                cmd = ['cancel', job_id]
                server = self.main_app.settings.get("cups_server", "").strip()
                port = self.main_app.settings.get("cups_port", 631)
                if server:
                    target = f"{server}:{port}" if ":" not in server else server
                    cmd.extend(['-h', target])
                subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
                QMessageBox.information(self, "Sucesso", f"Trabalho '{job_id}' cancelado com sucesso!")
                self.load_queue()
            except Exception as e:
                logger.error("Erro ao cancelar job %s: %s", job_id, e)
                QMessageBox.critical(self, "Erro", f"Falha ao cancelar trabalho:\n{str(e)}")
