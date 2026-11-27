# -*- coding: utf-8 -*-
"""
Miscellaneous dialogs: AboutDialog and ShortcutsDialog.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView
)

from src.config import CURRENT_VERSION


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre o Gerenciador Avançado de Impressão")
        self.setFixedSize(500, 390)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        lbl_title = QLabel("🖨️ Gerenciador Avançado de Impressão Pro")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2563EB;")
        layout.addWidget(lbl_title)

        lbl_ver = QLabel(f"Versão {CURRENT_VERSION}")
        lbl_ver.setAlignment(Qt.AlignCenter)
        lbl_ver.setStyleSheet("font-size: 12px; color: #64748B;")
        layout.addWidget(lbl_ver)

        info_text = (
            "<p align='center'>Solução completa e de alta performance para gerenciamento e preparação de impressão no Linux e Windows.</p>"
            "<hr>"
            "<b>Destaques da Versão " + CURRENT_VERSION + ":</b><br>"
            "• Presets Rápidos de Impressão (Sublimação, Foto, Apostila 2-em-1, Pôster, Rascunho)<br>"
            "• Espelhamento Horizontal de Páginas para Sublimação e Transfer Térmico<br>"
            "• Modo Cartaz com Sobreposição Ajustável (Overlap / Margem de Colagem)<br>"
            "• Impressão como Imagem (Rasterização em 300 DPI anti-falhas)<br>"
            "• Ordem Reversa e Seleção de Páginas Pares / Ímpares<br>"
            "• Seleção de Qualidade de Impressão, Tipo de Papel e Velocidade via CUPS/IPP<br>"
            "• Suporte a PDF, Word (DOCX/DOC), LibreOffice (ODT), Planilhas (XLSX/ODS), Slides (PPTX/ODP)<br>"
            "• Pré-visualização ultra-rápida assíncrona (pdftoppm + QThread)<br>"
            "• Histórico com exportação CSV e gerenciador de fila em tempo real<br>"
            "<hr>"
            "<p align='center'>Desenvolvido para máxima produtividade.<br>"
            "<a href='https://github.com/LucasTelesEriceira/gerenciador-impressoes'>Repositório GitHub</a></p>"
        )
        lbl_info = QLabel(info_text)
        lbl_info.setOpenExternalLinks(True)
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self.setLayout(layout)


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atalhos de Teclado")
        self.resize(480, 340)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Atalho", "Descrição"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        shortcuts = [
            ("Ctrl + O", "Abrir / Selecionar Documento"),
            ("Ctrl + W ou Delete", "Remover / Limpar Documento Selecionado"),
            ("Ctrl + P", "Processar e Imprimir Documento"),
            ("Ctrl + R", "Atualizar Pré-visualização"),
            ("Ctrl + H", "Abrir Histórico de Impressões"),
            ("Ctrl + J", "Abrir Fila de Impressão CUPS"),
            ("Ctrl + M", "Abrir Manutenção e Níveis de Tinta"),
            ("Ctrl + ,", "Abrir Configurações e Preferências"),
            ("F1", "Abrir esta Ajuda de Atalhos"),
            ("Setas / PgUp / PgDn", "Navegar pelas Páginas da Pré-visualização")
        ]

        table.setRowCount(len(shortcuts))
        for row, (key, desc) in enumerate(shortcuts):
            item_key = QTableWidgetItem(key)
            item_key.setTextAlignment(Qt.AlignCenter)
            item_key.setFont(QFont("Monospace", 9, QFont.Bold))
            table.setItem(row, 0, item_key)
            table.setItem(row, 1, QTableWidgetItem(desc))

        layout.addWidget(table)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self.setLayout(layout)
