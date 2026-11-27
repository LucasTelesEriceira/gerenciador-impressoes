import os
import csv
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QPushButton, QMessageBox, QFileDialog)
from PyQt5.QtCore import Qt
from src.config import load_history, clear_history, logger

class HistoryDialog(QDialog):
    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.setWindowTitle("Histórico de Impressões")
        self.resize(780, 460)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["Data/Hora", "Arquivo", "Impressora", "Cópias", "Papel", "Tipo de Papel", "Qualidade", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        self.btn_reprint = QPushButton("🔁 Reabrir Selecionado")
        self.btn_reprint.clicked.connect(self.reprint_selected)
        btn_layout.addWidget(self.btn_reprint)

        self.btn_export = QPushButton("💾 Exportar CSV")
        self.btn_export.clicked.connect(self.export_csv)
        btn_layout.addWidget(self.btn_export)

        self.btn_clear = QPushButton("🗑️ Limpar Histórico")
        self.btn_clear.clicked.connect(self.clear_all_history)
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.load_data()

    def load_data(self):
        self.history_data = load_history()
        self.table.setRowCount(len(self.history_data))
        for row, entry in enumerate(self.history_data):
            self.table.setItem(row, 0, QTableWidgetItem(entry.get("timestamp", "")))
            self.table.setItem(row, 1, QTableWidgetItem(entry.get("filename", "")))
            self.table.setItem(row, 2, QTableWidgetItem(entry.get("printer", "")))
            self.table.setItem(row, 3, QTableWidgetItem(str(entry.get("copies", 1))))
            self.table.setItem(row, 4, QTableWidgetItem(entry.get("paper", "")))
            self.table.setItem(row, 5, QTableWidgetItem(entry.get("media_type", "Papel Comum (Padrão)")))
            self.table.setItem(row, 6, QTableWidgetItem(entry.get("quality", "Normal (Padrão)")))

            status_item = QTableWidgetItem(entry.get("status", ""))
            if entry.get("status") == "Sucesso":
                status_item.setForeground(Qt.darkGreen)
            else:
                status_item.setForeground(Qt.red)
            self.table.setItem(row, 7, status_item)

    def reprint_selected(self):
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            QMessageBox.warning(self, "Aviso", "Selecione um item do histórico.")
            return
        row = selected_rows[0].row()
        entry = self.history_data[row]
        file_path = entry.get("file_path", "")
        if file_path and os.path.exists(file_path):
            self.main_app.load_selected_file(file_path)
            printer = entry.get("printer", "")
            idx = self.main_app.cb_printers.findText(printer)
            if idx >= 0:
                self.main_app.cb_printers.setCurrentIndex(idx)
            media_type = entry.get("media_type", "")
            if media_type and hasattr(self.main_app, "cb_media_type"):
                idx_m = self.main_app.cb_media_type.findText(media_type)
                if idx_m < 0:
                    media_base = media_type.split('(')[0].strip().lower()
                    if media_base:
                        idx_m = self.main_app.cb_media_type.findText(media_base, Qt.MatchContains)
                if idx_m >= 0:
                    self.main_app.cb_media_type.setCurrentIndex(idx_m)
            quality = entry.get("quality", "")
            if quality and hasattr(self.main_app, "cb_quality"):
                idx_q = self.main_app.cb_quality.findText(quality)
                if idx_q >= 0:
                    self.main_app.cb_quality.setCurrentIndex(idx_q)
            print_speed = entry.get("print_speed", "")
            if print_speed and hasattr(self.main_app, "cb_print_speed"):
                idx_s = self.main_app.cb_print_speed.findText(print_speed)
                if idx_s >= 0:
                    self.main_app.cb_print_speed.setCurrentIndex(idx_s)
            mirror_val = entry.get("mirror")
            if mirror_val is not None and hasattr(self.main_app, "chk_mirror_horizontal"):
                self.main_app.chk_mirror_horizontal.setChecked(mirror_val in (True, "Sim", "true", "True", 1))
            self.accept()
            QMessageBox.information(self, "Reimpressão", f"Arquivo '{os.path.basename(file_path)}' carregado com sucesso!")
        else:
            QMessageBox.warning(self, "Erro", f"O arquivo original não foi encontrado no caminho:\n{file_path}")

    def clear_all_history(self):
        reply = QMessageBox.question(self, "Confirmar", "Deseja realmente apagar todo o histórico de impressões?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            clear_history()
            self.load_data()

    def export_csv(self):
        if not self.history_data:
            QMessageBox.information(self, "Aviso", "O histórico está vazio.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar Histórico CSV", "historico_impressoes.csv", "CSV (*.csv)")
        if path:
            try:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["timestamp", "filename", "file_path", "printer", "copies", "paper", "media_type", "quality", "print_speed", "color", "duplex", "mirror", "status", "details"], extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(self.history_data)
                logger.info(f"Histórico exportado para CSV: {path}")
                QMessageBox.information(self, "Sucesso", f"Histórico exportado para:\n{path}")
            except Exception as e:
                logger.error(f"Erro ao exportar CSV de histórico: {e}")
                QMessageBox.critical(self, "Erro", f"Falha ao exportar CSV:\n{str(e)}")
