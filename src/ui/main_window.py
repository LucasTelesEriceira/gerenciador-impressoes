# -*- coding: utf-8 -*-
"""
Main Application Window for Gerenciador de Impressões Pro.
"""

import os
import sys
import shutil
import tempfile
import subprocess
import logging
from datetime import datetime
from PIL import Image
from pypdf import PdfReader

from PyQt5.QtCore import Qt, QTimer, QUrl, QByteArray, QSize
from PyQt5.QtGui import QPixmap, QImage, QIcon, QPalette, QColor, QFont, QKeySequence, QDesktopServices
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QLineEdit, QFileDialog, QMessageBox, QProgressBar, QProgressDialog, QScrollArea,
    QSplitter, QGroupBox, QFrame, QSizePolicy, QAction, QInputDialog,
    QShortcut, QApplication, QSystemTrayIcon, QStyle, QMenu
)

from src.config import (
    CURRENT_VERSION, CONFIG_DIR, LOGS_DIR, SETTINGS_FILE, HISTORY_FILE,
    SUPPORTED_EXTENSIONS, SUPPORTED_MIME_TYPES, BUILTIN_PRESETS,
    load_settings, save_settings, load_history, save_history_entry,
    get_all_presets, get_clean_host_env
)
from src.core.geometry import parse_page_range, fit_page_to_orientation_and_scale, get_paper_size_pts
from src.core.layout import compute_booklet_sheet_pairs
from src.cups.discovery import get_system_printers, is_monochrome_printer, printer_supports_duplex
from src.cups.ppd import (
    get_printer_trays, get_printer_qualities, get_printer_media_types, get_printer_speeds
)
from src.cups.maintenance import format_ink_summary_line
from src.workers.printer_loader import PrinterLoaderThread
from src.workers.preview_worker import PreviewWorkerThread
from src.workers.print_worker import PrintWorkerThread
from src.workers.updater_worker import UpdateCheckerThread, UpdateDownloadThread
from src.ui.widgets.drop_zone import DropZoneFrame
from src.ui.widgets.wheel_guard import ensure_global_wheel_guard
from src.ui.dialogs import (
    HistoryDialog, SettingsDialog, ServerManagerDialog, PrinterInstallerDialog,
    QueueDialog, MaintenanceDialog, AboutDialog, ShortcutsDialog
)
from src.ui.dialogs.maintenance_dialog import SupplyLoaderThread

logger = logging.getLogger("GerenciadorImpressaoPro.MainWindow")

class PrintManagerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.file_path = ""
        self.cached_pdf_path = ""
        self.current_page = 1
        self.total_pages = 1
        self.doc_total_pages = 0
        self.preview_worker = None
        self.print_worker = None
        self.update_worker = None
        self.current_preview_img = ""
        self.theme_mode = "system"
        self.active_cups_server = ""
        self._cups_server_resolved = False
        self.settings = load_settings()
        ensure_global_wheel_guard()
        self.initUI()
        if sys.platform.startswith("linux"):
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(800, lambda: self.integrate_with_system(silent=True))

    def get_effective_cups_server(self):
        if getattr(self, "_cups_server_resolved", False):
            return getattr(self, "active_cups_server", "")
        return os.environ.get("CUPS_SERVER", "").strip()

    def apply_cups_environment(self):
        server = self.settings.get("cups_server", "").strip()
        port = self.settings.get("cups_port", 631)
        if server:
            target = f"{server}:{port}" if ":" not in server else server
            try:
                subprocess.check_call(['lpstat', '-h', target, '-r'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                os.environ["CUPS_SERVER"] = target
                self.active_cups_server = target
                self._cups_server_resolved = True
                return
            except Exception:
                pass
        if "CUPS_SERVER" in os.environ:
            del os.environ["CUPS_SERVER"]
        self.active_cups_server = ""
        self._cups_server_resolved = True

    def initUI(self):
        self.setWindowTitle("Gerenciador Avançado de Impressão (Nativo + QThread)")
        candidate_dirs = [
            getattr(sys, '_MEIPASS', None),
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            os.getcwd()
        ]
        self.app_icon_path = ""
        for cd in candidate_dirs:
            if cd and os.path.exists(os.path.join(cd, "icon.png")):
                self.app_icon_path = os.path.join(cd, "icon.png")
                break
        if os.path.exists(self.app_icon_path):
            self.setWindowIcon(QIcon(self.app_icon_path))

        # Configurar suporte a bandeja do sistema (clique, menu de contexto e notificações)
        self.tray_icon = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
            if self.app_icon_path and os.path.exists(self.app_icon_path):
                self.tray_icon.setIcon(QIcon(self.app_icon_path))
            else:
                self.tray_icon.setIcon(QIcon.fromTheme("printer", self.style().standardIcon(QStyle.SP_ComputerIcon)))
            self.tray_icon.setToolTip("Gerenciador de Impressões Pro")

            self.tray_menu = QMenu(self)
            self.act_tray_toggle = QAction("Ocultar para Bandeja", self)
            self.act_tray_toggle.triggered.connect(self.toggle_window_from_tray)
            self.tray_menu.addAction(self.act_tray_toggle)
            self.tray_menu.addSeparator()

            act_tray_open = QAction("Abrir Documento...", self)
            act_tray_open.triggered.connect(lambda: (self.show_window_from_tray(), self.select_file()))
            self.tray_menu.addAction(act_tray_open)

            act_tray_queue = QAction("Fila de Impressão (CUPS)...", self)
            act_tray_queue.triggered.connect(lambda: (self.show_window_from_tray(), self.open_queue_dialog()))
            self.tray_menu.addAction(act_tray_queue)

            act_tray_maint = QAction("Manutenção e Níveis de Tinta...", self)
            act_tray_maint.triggered.connect(lambda: (self.show_window_from_tray(), self.open_maintenance_dialog()))
            self.tray_menu.addAction(act_tray_maint)

            act_tray_history = QAction("Histórico de Impressões...", self)
            act_tray_history.triggered.connect(lambda: (self.show_window_from_tray(), self.open_history_dialog()))
            self.tray_menu.addAction(act_tray_history)

            act_tray_settings = QAction("Preferências...", self)
            act_tray_settings.triggered.connect(lambda: (self.show_window_from_tray(), self.open_settings_dialog()))
            self.tray_menu.addAction(act_tray_settings)

            self.tray_menu.addSeparator()
            act_tray_quit = QAction("Sair", self)
            act_tray_quit.triggered.connect(self.close)
            self.tray_menu.addAction(act_tray_quit)

            self.tray_menu.aboutToShow.connect(self._update_tray_menu_labels)
            self.tray_icon.setContextMenu(self.tray_menu)
            self.tray_icon.activated.connect(self.on_tray_icon_activated)
            self.tray_icon.show()
        self.setMinimumSize(880, 560)
        restored = False
        if self.settings.get("window_geometry"):
            try:
                geom = QByteArray.fromHex(self.settings["window_geometry"].encode())
                restored = self.restoreGeometry(geom)
            except Exception as e:
                logger.warning(f"Falha ao restaurar geometria da janela: {e}")

        if not restored:
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                target_w = max(1120, min(1450, int(avail.width() * 0.80)))
                target_h = max(720, min(920, int(avail.height() * 0.84)))
                target_w = min(target_w, max(880, avail.width() - 40))
                target_h = min(target_h, max(560, avail.height() - 60))
                rect = QStyle.alignedRect(Qt.LeftToRight, Qt.AlignCenter, QSize(target_w, target_h), avail)
                self.setGeometry(rect)
            else:
                self.resize(1150, 760)

        if self.settings.get("window_maximized", False):
            self.showMaximized()
        self.setAcceptDrops(True)

        self.create_menu_bar()

        central_widget = QWidget()
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # Painel Esquerdo (Controles e Opções)
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)
        left_panel.setContentsMargins(0, 0, 0, 0)

        # 1. Seleção de Documento
        group_file = QGroupBox("1. Seleção de Documento")
        vbox_file = QVBoxLayout()
        vbox_file.setContentsMargins(12, 14, 12, 12)
        vbox_file.setSpacing(10)

        self.drop_frame = DropZoneFrame()
        self.drop_frame.setObjectName("drop_frame")
        self.drop_frame.clicked.connect(self.select_file)
        self.drop_frame.file_dropped.connect(self.load_selected_file)

        drop_layout = QVBoxLayout()
        drop_layout.setContentsMargins(12, 12, 12, 12)
        drop_layout.setSpacing(4)

        self.lbl_drop_title = QLabel("Arraste e solte seu documento aqui")
        self.lbl_drop_title.setAlignment(Qt.AlignCenter)
        self.lbl_drop_title.setWordWrap(True)
        self.lbl_drop_title.setStyleSheet("font-size: 13px; font-weight: bold;")

        self.lbl_drop_sub = QLabel("ou clique para selecionar (PDF, Word, Planilhas, Slides, TXT)")
        self.lbl_drop_sub.setAlignment(Qt.AlignCenter)
        self.lbl_drop_sub.setWordWrap(True)
        self.lbl_drop_sub.setStyleSheet("font-size: 11px; opacity: 0.8;")

        drop_layout.addWidget(self.lbl_drop_title)
        drop_layout.addWidget(self.lbl_drop_sub)
        self.drop_frame.setLayout(drop_layout)

        # Linha do Arquivo Selecionado (Esquerda: Nome, Direita: Ícone Lixeira/Remover)
        file_info_layout = QHBoxLayout()
        file_info_layout.setContentsMargins(2, 4, 2, 2)
        file_info_layout.setSpacing(8)

        self.lbl_file = QLabel("Nenhum arquivo selecionado")
        self.lbl_file.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_file.setStyleSheet("font-weight: bold; font-size: 12px;")
        file_info_layout.addWidget(self.lbl_file, stretch=1)

        self.btn_remove_icon = QPushButton("🗑️ Remover")
        self.btn_remove_icon.setToolTip("Remover arquivo selecionado (Ctrl+W / Del)")
        self.btn_remove_icon.setCursor(Qt.PointingHandCursor)
        self.btn_remove_icon.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #EF4444;
                border: 1px solid #EF4444;
                border-radius: 4px;
                padding: 3px 8px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #EF4444;
                color: white;
            }
        """)
        self.btn_remove_icon.clicked.connect(self.clear_selected_file)
        self.btn_remove_icon.setVisible(False)
        file_info_layout.addWidget(self.btn_remove_icon)

        vbox_file.addWidget(self.drop_frame)
        vbox_file.addLayout(file_info_layout)
        group_file.setLayout(vbox_file)

        # 2. Configurações de Impressão
        group_opts = QGroupBox("2. Configurações de Impressão")
        form_opts = QFormLayout()
        form_opts.setContentsMargins(12, 14, 12, 12)
        form_opts.setVerticalSpacing(8)
        form_opts.setHorizontalSpacing(10)
        form_opts.setLabelAlignment(Qt.AlignLeft)
        form_opts.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Seletor de Perfil / Presets Rápidos com botões de Salvar e Excluir
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(6)
        preset_layout.setContentsMargins(0, 0, 0, 0)

        self.cb_presets = QComboBox()
        self.cb_presets.setToolTip("Carrega instantaneamente configurações recomendadas para cada tipo de trabalho.")
        preset_layout.addWidget(self.cb_presets, stretch=1)

        self.btn_save_preset = QPushButton("💾 Salvar")
        self.btn_save_preset.setToolTip("Salvar os parâmetros selecionados como um novo preset customizado")
        self.btn_save_preset.setCursor(Qt.PointingHandCursor)
        self.btn_save_preset.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #0369A1;
            }
        """)
        self.btn_save_preset.clicked.connect(self.on_save_preset_clicked)
        preset_layout.addWidget(self.btn_save_preset)

        self.btn_delete_preset = QPushButton("🗑️")
        self.btn_delete_preset.setToolTip("Excluir o preset customizado selecionado")
        self.btn_delete_preset.setCursor(Qt.PointingHandCursor)
        self.btn_delete_preset.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #EF4444;
                border: 1px solid #EF4444;
                border-radius: 4px;
                padding: 4px 6px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #EF4444;
                color: white;
            }
        """)
        self.btn_delete_preset.clicked.connect(self.on_delete_preset_clicked)
        self.btn_delete_preset.setEnabled(False)
        preset_layout.addWidget(self.btn_delete_preset)

        form_opts.addRow("Perfil / Preset:", preset_layout)

        printer_row = QHBoxLayout()
        printer_row.setSpacing(6)
        printer_row.setContentsMargins(0, 0, 0, 0)

        self.cb_printers = QComboBox()
        printer_row.addWidget(self.cb_printers, stretch=1)

        self.btn_maintenance = QPushButton("🧴 Tinta / Manut.")
        self.btn_maintenance.setToolTip("Visualizar níveis de tinta/toner e executar manutenção da impressora (Ctrl+M)")
        self.btn_maintenance.setCursor(Qt.PointingHandCursor)
        self.btn_maintenance.setStyleSheet("""
            QPushButton {
                background-color: #0F766E;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #115E59;
            }
        """)
        self.btn_maintenance.clicked.connect(self.open_maintenance_dialog)
        printer_row.addWidget(self.btn_maintenance)

        printer_col = QVBoxLayout()
        printer_col.setSpacing(2)
        printer_col.setContentsMargins(0, 0, 0, 0)
        printer_col.addLayout(printer_row)

        self.lbl_ink_summary = QLabel("")
        self.lbl_ink_summary.setStyleSheet("font-size: 11px; color: #64748B;")
        self.lbl_ink_summary.setWordWrap(True)
        self.lbl_ink_summary.setVisible(False)
        printer_col.addWidget(self.lbl_ink_summary)

        form_opts.addRow("Impressora:", printer_col)

        self.sp_copies = QSpinBox()
        self.sp_copies.setRange(1, 999)
        form_opts.addRow("Quantidade (Cópias):", self.sp_copies)

        self.txt_page_range = QLineEdit()
        self.txt_page_range.setPlaceholderText("Ex: 1-5, 8, 11-13 (vazio = todas)")
        self.txt_page_range.editingFinished.connect(self.on_page_range_changed)
        form_opts.addRow("Páginas Específicas:", self.txt_page_range)

        self.cb_page_subset = QComboBox()
        self.cb_page_subset.addItems(["Todas as Páginas", "Apenas Páginas Ímpares", "Apenas Páginas Pares"])
        self.cb_page_subset.currentIndexChanged.connect(self.on_page_range_changed)
        form_opts.addRow("Subconjunto:", self.cb_page_subset)

        # Checkboxes de controle avançado de página e renderização
        chk_layout = QVBoxLayout()
        chk_layout.setSpacing(4)
        chk_layout.setContentsMargins(0, 2, 0, 2)

        self.chk_reverse_order = QCheckBox("Inverter ordem das páginas (Decrescente)")
        self.chk_reverse_order.setToolTip("Imprime as páginas de trás para frente. Ideal para impressoras com saída de papel virada para cima.")
        self.chk_reverse_order.stateChanged.connect(self.on_page_range_changed)
        chk_layout.addWidget(self.chk_reverse_order)

        self.chk_mirror_horizontal = QCheckBox("Espelhar horizontalmente (Sublimação / Transfer)")
        self.chk_mirror_horizontal.setToolTip("Inverte a imagem horizontalmente para estampas térmicas em canecas, camisas e brindes sublimáticos.")
        self.chk_mirror_horizontal.stateChanged.connect(self.on_setting_changed)
        chk_layout.addWidget(self.chk_mirror_horizontal)

        self.chk_print_as_image = QCheckBox("Imprimir como Imagem (Evitar erros de fontes)")
        self.chk_print_as_image.setToolTip("Converte o documento em imagens de 300 DPI antes do envio ao CUPS. Elimina falhas de fontes quebradas e vetores complexos.")
        chk_layout.addWidget(self.chk_print_as_image)

        lbl_adv_options = QLabel("Opções Avançadas:")
        lbl_adv_options.setStyleSheet("font-weight: bold; margin-top: 6px; margin-bottom: 2px;")
        form_opts.addRow(lbl_adv_options)
        form_opts.addRow(chk_layout)

        self.cb_paper_size = QComboBox()
        self.cb_paper_size.addItems(["A4", "Carta (Letter)", "A3", "A5", "Ofício (Legal)"])
        self.cb_paper_size.setCurrentText(self.settings.get("default_paper", "A4"))
        self.cb_paper_size.currentIndexChanged.connect(self.on_setting_changed)
        form_opts.addRow("Tamanho do Papel:", self.cb_paper_size)

        self.cb_media_type = QComboBox()
        self.cb_media_type.currentIndexChanged.connect(self.on_setting_changed)
        form_opts.addRow("Tipo de Papel:", self.cb_media_type)

        self.cb_tray = QComboBox()
        form_opts.addRow("Bandeja de Entrada:", self.cb_tray)

        self.cb_orientation = QComboBox()
        self.cb_orientation.addItems(["Automático (Padrão)", "Retrato (Vertical)", "Paisagem (Horizontal)"])
        self.cb_orientation.currentIndexChanged.connect(self.on_setting_changed)
        form_opts.addRow("Orientação:", self.cb_orientation)

        self.cb_scaling_mode = QComboBox()
        self.cb_scaling_mode.addItems(["Ajustar à Folha (Fit)", "Tamanho Real (100%)", "Reduzir Páginas Grandes", "Escala Personalizada"])
        self.cb_scaling_mode.currentIndexChanged.connect(self.on_scaling_mode_changed)
        form_opts.addRow("Dimensionamento (Escala):", self.cb_scaling_mode)

        self.sp_custom_scale = QSpinBox()
        self.sp_custom_scale.setRange(10, 400)
        self.sp_custom_scale.setValue(100)
        self.sp_custom_scale.setSuffix(" %")
        self.sp_custom_scale.setEnabled(False)
        self.sp_custom_scale.valueChanged.connect(self.on_setting_changed)
        form_opts.addRow("Porcentagem da Escala:", self.sp_custom_scale)

        margins_box = QVBoxLayout()
        margins_box.setSpacing(4)
        margins_box.setContentsMargins(0, 0, 0, 0)

        margins_grid = QGridLayout()
        margins_grid.setSpacing(6)
        margins_grid.setContentsMargins(0, 0, 0, 0)

        def _make_margin_spin():
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 10.0)
            sp.setSingleStep(0.05)
            sp.setDecimals(2)
            sp.setValue(0.50)
            sp.setSuffix(" cm")
            sp.valueChanged.connect(self.on_margin_changed)
            return sp

        self.sp_margin_left = _make_margin_spin()
        self.sp_margin_right = _make_margin_spin()
        self.sp_margin_top = _make_margin_spin()
        self.sp_margin_bottom = _make_margin_spin()

        margins_grid.addWidget(QLabel("Esq:"), 0, 0)
        margins_grid.addWidget(self.sp_margin_left, 0, 1)
        margins_grid.addWidget(QLabel("Dir:"), 0, 2)
        margins_grid.addWidget(self.sp_margin_right, 0, 3)
        margins_grid.addWidget(QLabel("Topo:"), 1, 0)
        margins_grid.addWidget(self.sp_margin_top, 1, 1)
        margins_grid.addWidget(QLabel("Inf:"), 1, 2)
        margins_grid.addWidget(self.sp_margin_bottom, 1, 3)
        margins_grid.setColumnStretch(1, 1)
        margins_grid.setColumnStretch(3, 1)
        margins_box.addLayout(margins_grid)

        margins_btns = QHBoxLayout()
        margins_btns.setSpacing(4)
        margins_btns.setContentsMargins(0, 0, 0, 0)
        for lbl_b, val_cm in [("Sem margem (0,00)", 0.0), ("Mínima (0,05)", 0.05), ("Padrão (0,50)", 0.50)]:
            b = QPushButton(lbl_b)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("font-size: 10px; padding: 2px 6px;")
            b.clicked.connect(lambda _chk=False, v=val_cm: self.set_uniform_margins(v))
            margins_btns.addWidget(b)
        margins_box.addLayout(margins_btns)
        form_opts.addRow("Margens da Página:", margins_box)

        self.cb_duplex = QComboBox()
        self.cb_duplex.addItems(["Apenas Frente", "Frente e Verso (Borda Maior)", "Frente e Verso (Borda Menor)"])
        form_opts.addRow("Frente e Verso:", self.cb_duplex)

        self.cb_color = QComboBox()
        self.cb_color.addItems(["Colorido (Padrão)", "Preto e Branco"])
        form_opts.addRow("Cores:", self.cb_color)

        self.cb_quality = QComboBox()
        self.cb_quality.currentIndexChanged.connect(self.on_setting_changed)
        form_opts.addRow("Qualidade de Impressão:", self.cb_quality)

        self.cb_print_speed = QComboBox()
        self.cb_print_speed.currentIndexChanged.connect(self.on_setting_changed)
        form_opts.addRow("Velocidade de Impressão:", self.cb_print_speed)

        self.cb_nup = QComboBox()
        self.cb_nup.addItems(["1 por folha", "2 por folha", "4 por folha", "6 por folha", "9 por folha", "16 por folha"])
        self.cb_nup.currentIndexChanged.connect(self.on_nup_changed)
        form_opts.addRow("Agrupar (Slides/N-Up):", self.cb_nup)

        self.cb_poster = QComboBox()
        self.cb_poster.addItems(["Desativado", "Cartaz 2x2 (4 folhas)", "Cartaz 3x3 (9 folhas)", "Cartaz 4x4 (16 folhas)"])
        self.cb_poster.currentIndexChanged.connect(self.on_poster_changed)
        form_opts.addRow("Modo Cartaz (Pôster):", self.cb_poster)

        self.sp_poster_overlap = QDoubleSpinBox()
        self.sp_poster_overlap.setRange(0.0, 50.0)
        self.sp_poster_overlap.setSingleStep(1.0)
        self.sp_poster_overlap.setValue(5.0)
        self.sp_poster_overlap.setSuffix(" mm")
        self.sp_poster_overlap.setToolTip("Margem de sobreposição nas emendas das folhas para passar cola ou fita adesiva.")
        self.sp_poster_overlap.setEnabled(False)
        self.sp_poster_overlap.valueChanged.connect(self.on_setting_changed)
        form_opts.addRow("Sobreposição do Cartaz:", self.sp_poster_overlap)

        self.cb_booklet = QComboBox()
        self.cb_booklet.addItems([
            "Desativado",
            "Livreto Completo (Frente e Verso)",
            "Livreto Manual — Apenas Frentes",
            "Livreto Manual — Apenas Versos",
        ])
        self.cb_booklet.setToolTip(
            "Reordena e agrupa páginas 2-em-1 em formato de livreto (dobra ao meio).\n"
            "No modo completo, configura automaticamente Frente e Verso (Borda Menor)."
        )
        self.cb_booklet.currentIndexChanged.connect(self.on_booklet_changed)
        form_opts.addRow("Modo Livreto (Booklet):", self.cb_booklet)

        self.cb_cut_marks = QComboBox()
        self.cb_cut_marks.addItems([
            "Desativado",
            "Marcas de Corte nos Cantos (Cruzetas)",
            "Borda Fina Delimitadora (Contorno)",
            "Linha Guia Pontilhada",
            "Cantos + Borda Fina"
        ])
        self.cb_cut_marks.setToolTip("Adiciona guias de refile e marcas de corte nos cantos ou contornos das páginas/células para guilhotina e estilete.")
        self.cb_cut_marks.currentIndexChanged.connect(self.on_setting_changed)
        form_opts.addRow("Marcas de Corte / Refile:", self.cb_cut_marks)

        # Política de expansão uniforme para que TODOS os inputs tenham a mesma largura perfeita
        for widget in [
            self.cb_printers, self.sp_copies, self.txt_page_range, self.cb_page_subset,
            self.cb_paper_size, self.cb_media_type, self.cb_tray, self.cb_orientation,
            self.cb_scaling_mode, self.sp_custom_scale, self.cb_duplex,
            self.cb_color, self.cb_quality, self.cb_print_speed, self.cb_nup, self.cb_poster,
            self.sp_poster_overlap, self.cb_booklet, self.cb_cut_marks
        ]:
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        group_opts.setLayout(form_opts)

        # ScrollArea elegante para as seções de seleção e configuração
        # Permite que a janela diminua livremente sem estourar em monitores 768p ou com escala do Plasma
        scroll_controls = QScrollArea()
        scroll_controls.setWidgetResizable(True)
        scroll_controls.setFrameShape(QFrame.NoFrame)
        scroll_controls.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)
        scroll_layout.addWidget(group_file)
        scroll_layout.addWidget(group_opts)
        scroll_layout.addStretch()

        scroll_controls.setWidget(scroll_content)
        left_panel.addWidget(scroll_controls, stretch=1)

        # Painel Fixo no Rodapé: Estimativa de Consumo/Custo, Status, Progresso e Botão de Ação
        # Fica sempre visível e acessível sem precisar de rolagem
        bottom_panel = QVBoxLayout()
        bottom_panel.setContentsMargins(0, 4, 0, 0)
        bottom_panel.setSpacing(6)

        self.lbl_cost_estimate = QLabel("📄 Folhas estimadas: --  |  💰 Custo estimado: --")
        self.lbl_cost_estimate.setAlignment(Qt.AlignCenter)
        self.lbl_cost_estimate.setWordWrap(True)
        self.lbl_cost_estimate.setStyleSheet("""
            QLabel {
                background-color: rgba(2, 132, 199, 0.08);
                color: #0369A1;
                border: 1px solid rgba(2, 132, 199, 0.25);
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        bottom_panel.addWidget(self.lbl_cost_estimate)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #0284C7; font-weight: bold;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        bottom_panel.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        bottom_panel.addWidget(self.progress_bar)

        self.btn_action = QPushButton("PROCESSAR E IMPRIMIR (Ctrl+P)")
        self.btn_action.setMinimumHeight(44)
        self.btn_action.clicked.connect(self.process_and_print)
        bottom_panel.addWidget(self.btn_action)

        left_panel.addLayout(bottom_panel)

        left_widget = QWidget()
        left_widget.setLayout(left_panel)

        # Painel Direito (Pré-visualização)
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)

        group_preview = QGroupBox("3. Pré-visualização do Documento")
        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(12, 14, 12, 12)
        preview_layout.setSpacing(10)

        nav_layout = QHBoxLayout()
        self.btn_prev_page = QPushButton("◄ Anterior")
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.btn_prev_page.setEnabled(False)
        nav_layout.addWidget(self.btn_prev_page)

        self.lbl_page_info = QLabel("Página 0 de 0")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        self.lbl_page_info.setStyleSheet("font-weight: bold;")
        nav_layout.addWidget(self.lbl_page_info)

        self.btn_next_page = QPushButton("Próxima ►")
        self.btn_next_page.clicked.connect(self.next_page)
        self.btn_next_page.setEnabled(False)
        nav_layout.addWidget(self.btn_next_page)

        self.btn_refresh_preview = QPushButton("Atualizar (Ctrl+R)")
        self.btn_refresh_preview.setToolTip("Recarregar pré-visualização (Ctrl+R)")
        self.btn_refresh_preview.clicked.connect(self.load_preview)
        nav_layout.addWidget(self.btn_refresh_preview)

        preview_layout.addLayout(nav_layout)

        self.lbl_usable_area = QLabel("")
        self.lbl_usable_area.setAlignment(Qt.AlignCenter)
        self.lbl_usable_area.setStyleSheet("font-size: 11px; color: #64748B;")
        preview_layout.addWidget(self.lbl_usable_area)

        self.scroll_preview = QScrollArea()
        self.scroll_preview.setWidgetResizable(True)
        self.scroll_preview.setAlignment(Qt.AlignCenter)

        self.lbl_preview = QLabel("Selecione ou arraste um documento para visualizar a prévia")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setStyleSheet("color: #7f8c8d; font-size: 13px;")
        self.scroll_preview.setWidget(self.lbl_preview)

        preview_layout.addWidget(self.scroll_preview)
        group_preview.setLayout(preview_layout)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        right_panel.addWidget(group_preview)

        left_widget.setMinimumWidth(440)
        right_widget.setMinimumWidth(380)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(left_widget)
        self.splitter.addWidget(right_widget)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        splitter_restored = False
        if self.settings.get("splitter_state"):
            try:
                state = QByteArray.fromHex(self.settings["splitter_state"].encode())
                splitter_restored = self.splitter.restoreState(state)
            except Exception as e:
                logger.warning(f"Falha ao restaurar estado do splitter: {e}")

        if not splitter_restored:
            left_w = 460
            right_w = max(450, self.width() - left_w - 40)
            self.splitter.setSizes([left_w, right_w])

        self.splitter.splitterMoved.connect(lambda pos, index: self.update_preview_scaling())

        main_layout.addWidget(self.splitter)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # Inicializar impressoras e conexões de sinal APÓS criação de todos os componentes
        self.load_presets_ui()
        self.cb_presets.currentIndexChanged.connect(self.on_preset_changed)

        self.load_printers()
        self.cb_printers.currentIndexChanged.connect(self.on_printer_changed)
        self.sp_copies.valueChanged.connect(self.update_cost_estimate)
        self.cb_duplex.currentIndexChanged.connect(self.update_cost_estimate)
        self.cb_color.currentIndexChanged.connect(self.update_cost_estimate)
        self.cb_color.currentIndexChanged.connect(self.update_preview_scaling)

        self.apply_theme()
        self.setup_shortcuts()
        self.update_usable_area_label()
        self.on_printer_changed()

    def create_menu_bar(self):
        menubar = self.menuBar()

        menu_file = menubar.addMenu("&Arquivo")

        act_open = QAction("&Abrir Documento...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.select_file)
        menu_file.addAction(act_open)

        act_remove = QAction("&Remover Documento Atual", self)
        act_remove.setShortcut("Ctrl+W")
        act_remove.triggered.connect(self.clear_selected_file)
        menu_file.addAction(act_remove)

        menu_file.addSeparator()

        act_history = QAction("&Histórico de Impressões...", self)
        act_history.setShortcut("Ctrl+H")
        act_history.triggered.connect(self.open_history_dialog)
        menu_file.addAction(act_history)

        menu_file.addSeparator()

        act_exit = QAction("&Sair", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        menu_file.addAction(act_exit)

        menu_config = menubar.addMenu("&Configurações")

        act_settings = QAction("&Preferências do Cliente e Conexão...", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self.open_settings_dialog)
        menu_config.addAction(act_settings)

        menu_tools = menubar.addMenu("&Ferramentas")

        act_queue = QAction("Fila de Impressão &CUPS...", self)
        act_queue.setShortcut("Ctrl+J")
        act_queue.triggered.connect(self.open_queue_dialog)
        menu_tools.addAction(act_queue)

        act_maint = QAction("🧴 &Manutenção e Níveis de Tinta...", self)
        act_maint.setShortcut("Ctrl+M")
        act_maint.triggered.connect(self.open_maintenance_dialog)
        menu_tools.addAction(act_maint)

        act_installer = QAction("&Central do Servidor CUPS e Drivers...", self)
        act_installer.triggered.connect(self.open_installer_dialog)
        menu_tools.addAction(act_installer)

        if sys.platform.startswith("linux"):
            menu_tools.addSeparator()
            act_integrate = QAction("📦 &Integrar ao Sistema (Atalho e Menu 'Abrir com')...", self)
            act_integrate.triggered.connect(lambda: self.integrate_with_system(silent=False))
            menu_tools.addAction(act_integrate)

        menu_help = menubar.addMenu("A&juda")

        act_shortcuts = QAction("&Atalhos de Teclado", self)
        act_shortcuts.setShortcut("F1")
        act_shortcuts.triggered.connect(self.open_shortcuts_dialog)
        menu_help.addAction(act_shortcuts)

        act_update = QAction("&Verificar Atualizações...", self)
        act_update.triggered.connect(self.check_for_updates)
        menu_help.addAction(act_update)

        menu_help.addSeparator()

        act_about = QAction("&Sobre o Gerenciador", self)
        act_about.triggered.connect(self.open_about_dialog)
        menu_help.addAction(act_about)

    def load_printers(self):
        if not hasattr(self, 'cb_printers'):
            return
        
        # Inicia imediatamente com 'Salvar como PDF' para renderização instantânea da janela
        if self.cb_printers.count() == 0:
            self.cb_printers.blockSignals(True)
            self.cb_printers.addItem("Salvar como PDF")
            self.cb_printers.blockSignals(False)

        server = self.settings.get("cups_server", "").strip()
        port = self.settings.get("cups_port", 631)
        default_printer = self.settings.get("default_printer", "Salvar como PDF")

        # Dispara thread em segundo plano para descoberta de impressoras sem travar a interface
        self.printer_loader = PrinterLoaderThread(server, port, default_printer)
        self.printer_loader.printers_ready.connect(self.on_printers_loaded)
        self.printer_loader.start()

    def on_printers_loaded(self, printers, default_printer):
        if not hasattr(self, 'cb_printers'):
            return
        loader = getattr(self, "printer_loader", None)
        self.active_cups_server = getattr(loader, "active_cups_server", "") if loader else ""
        self._cups_server_resolved = True
        curr_text = self.cb_printers.currentText()
        self.cb_printers.blockSignals(True)
        self.cb_printers.clear()
        self.cb_printers.addItems(printers)

        target = curr_text if (curr_text and curr_text in printers) else default_printer
        idx = self.cb_printers.findText(target)
        if idx >= 0:
            self.cb_printers.setCurrentIndex(idx)
        self.cb_printers.blockSignals(False)
        self.on_printer_changed()

    def update_trays(self, printer_name="", cups_server=""):
        if not hasattr(self, 'cb_tray'):
            return
        self.cb_tray.blockSignals(True)
        self.cb_tray.clear()

        trays = get_printer_trays(printer_name, cups_server)
        default_index = 0
        for i, (label, raw_value, is_def) in enumerate(trays):
            self.cb_tray.addItem(label, raw_value)
            if is_def:
                default_index = i

        if self.cb_tray.count() > 0:
            self.cb_tray.setCurrentIndex(default_index)

        self.cb_tray.blockSignals(False)

    def update_qualities(self, printer_name="", cups_server=""):
        if not hasattr(self, 'cb_quality'):
            return
        self.cb_quality.blockSignals(True)
        self.cb_quality.clear()

        qualities = get_printer_qualities(printer_name, cups_server)
        default_pref = self.settings.get("default_quality", "Normal (Padrão)")
        default_pref_base = default_pref.split('(')[0].strip().lower()
        default_index = -1

        for i, (label, data_val, is_def) in enumerate(qualities):
            self.cb_quality.addItem(label, data_val)
            lbl_lower = label.lower()
            if default_pref and (default_pref.lower() in lbl_lower or lbl_lower in default_pref.lower() or (default_pref_base and default_pref_base in lbl_lower)):
                default_index = i
            elif is_def and default_index == -1:
                default_index = i

        if default_index == -1:
            default_index = 0

        if self.cb_quality.count() > 0:
            self.cb_quality.setCurrentIndex(default_index)
            first_data = self.cb_quality.itemData(0)
            mode = first_data.get("mode", "") if isinstance(first_data, dict) else ""
            if mode == "media_variants":
                self.cb_quality.setToolTip("Qualidade aplicada via variantes de mídia do driver Epson (_DRAFT / _NORMAL / _HIGH) e padrão IPP print-quality.")
            elif mode == "ppd":
                self.cb_quality.setToolTip("Opções nativas de qualidade expostas pelo driver PPD desta impressora.")
            else:
                self.cb_quality.setToolTip("Qualidade enviada via padrão IPP (print-quality=3/4/5).")

        self.cb_quality.blockSignals(False)

    def update_media_types(self, printer_name="", cups_server=""):
        if not hasattr(self, 'cb_media_type'):
            return
        self.cb_media_type.blockSignals(True)
        self.cb_media_type.clear()

        media_types = get_printer_media_types(printer_name, cups_server)
        default_pref = self.settings.get("default_media_type", "Papel Comum (Padrão)")
        default_pref_base = default_pref.split('(')[0].strip().lower()
        default_index = -1

        for i, (label, data_val, is_def) in enumerate(media_types):
            self.cb_media_type.addItem(label, data_val)
            lbl_lower = label.lower()
            if default_pref and (default_pref.lower() in lbl_lower or lbl_lower in default_pref.lower() or (default_pref_base and default_pref_base in lbl_lower)):
                if default_index == -1 or is_def:
                    default_index = i
            elif is_def and default_index == -1:
                default_index = i

        if default_index == -1:
            default_index = 0

        if self.cb_media_type.count() > 0:
            self.cb_media_type.setCurrentIndex(default_index)

        self.cb_media_type.blockSignals(False)

    def update_speeds(self, printer_name="", cups_server=""):
        if not hasattr(self, 'cb_print_speed'):
            return
        self.cb_print_speed.blockSignals(True)
        self.cb_print_speed.clear()

        speeds = get_printer_speeds(printer_name, cups_server)
        default_pref = self.settings.get("default_print_speed", "Normal (Padrão)")
        default_pref_base = default_pref.split('(')[0].strip().lower()
        default_index = -1

        for i, (label, data_val, is_def) in enumerate(speeds):
            self.cb_print_speed.addItem(label, data_val)
            lbl_lower = label.lower()
            if default_pref and (default_pref.lower() in lbl_lower or lbl_lower in default_pref.lower() or (default_pref_base and default_pref_base in lbl_lower)):
                default_index = i
            elif is_def and default_index == -1:
                default_index = i

        if default_index == -1:
            default_index = 0

        if self.cb_print_speed.count() > 0:
            self.cb_print_speed.setCurrentIndex(default_index)
            first_data = self.cb_print_speed.itemData(0)
            mode = first_data.get("mode", "") if isinstance(first_data, dict) else ""
            if mode == "ppd":
                self.cb_print_speed.setToolTip("Opção nativa de velocidade/modo silencioso exposta pelo driver desta impressora.")
            elif mode == "media_variants":
                self.cb_print_speed.setToolTip(
                    "Velocidade do carrinho ajustada via modo de mídia do driver Epson "
                    "(Rápida prioriza Normal/Rascunho e evita passadas lentas de Alta Qualidade) + IPP print-quality."
                )
            else:
                self.cb_print_speed.setToolTip(
                    "O driver PPD desta impressora não expõe controle separado de velocidade do carrinho; "
                    "quando Qualidade estiver em Normal, o aplicativo ajusta via padrão IPP (print-quality)."
                )

        self.cb_print_speed.blockSignals(False)

    def on_printer_changed(self):
        if not hasattr(self, 'cb_color') or not hasattr(self, 'cb_printers'):
            return
        printer = self.cb_printers.currentText()
        target_server = self.get_effective_cups_server()

        if not printer or printer == "Salvar como PDF":
            self.cb_color.setEnabled(True)
            self.cb_color.setToolTip("Selecione o modo de cor")
            prev_color = getattr(self, "_color_before_mono_lock", None)
            if prev_color:
                self.cb_color.setCurrentText(prev_color)
                self._color_before_mono_lock = None
            self.update_trays(printer, target_server)
            self.update_qualities(printer, target_server)
            self.update_media_types(printer, target_server)
            self.update_speeds(printer, target_server)
            self.refresh_ink_summary(printer, target_server)
            return

        if is_monochrome_printer(printer, target_server):
            if self.cb_color.isEnabled():
                self._color_before_mono_lock = self.cb_color.currentText()
            self.cb_color.setCurrentText("Preto e Branco")
            self.cb_color.setEnabled(False)
            self.cb_color.setToolTip("Impressora Monocromática (Preto e Branco) detectada automaticamente.")
        else:
            self.cb_color.setEnabled(True)
            self.cb_color.setToolTip("Selecione o modo de cor")
            prev_color = getattr(self, "_color_before_mono_lock", None)
            if prev_color:
                self.cb_color.setCurrentText(prev_color)
                self._color_before_mono_lock = None

        self.update_trays(printer, target_server)
        self.update_qualities(printer, target_server)
        self.update_media_types(printer, target_server)
        self.update_speeds(printer, target_server)
        self.refresh_ink_summary(printer, target_server)

    def refresh_ink_summary(self, printer_name="", cups_server=""):
        if not hasattr(self, "lbl_ink_summary"):
            return
        if not printer_name or printer_name == "Salvar como PDF":
            self.lbl_ink_summary.setVisible(False)
            self.lbl_ink_summary.setText("")
            return

        req_id = getattr(self, "_ink_req_id", 0) + 1
        self._ink_req_id = req_id

        prev_worker = getattr(self, "ink_summary_worker", None)
        if prev_worker and prev_worker.isRunning():
            prev_worker.wait(500)

        worker = SupplyLoaderThread(printer_name, cups_server=cups_server, query_network=False)
        worker.loaded.connect(lambda info, _mono, rid=req_id: self._on_ink_summary_loaded(info, rid))
        self.ink_summary_worker = worker
        worker.start()

    def _on_ink_summary_loaded(self, info, req_id):
        if req_id != getattr(self, "_ink_req_id", 0) or not hasattr(self, "lbl_ink_summary"):
            return
        if info.get("printer_name") != self.cb_printers.currentText():
            return
        summary_txt, has_low = format_ink_summary_line(info)
        if summary_txt:
            self.lbl_ink_summary.setText(summary_txt)
            self.lbl_ink_summary.setStyleSheet(
                "font-size: 11px; font-weight: bold; color: #EF4444;" if has_low else "font-size: 11px; color: #64748B;"
            )
            self.lbl_ink_summary.setVisible(True)
        else:
            self.lbl_ink_summary.setVisible(False)
            self.lbl_ink_summary.setText("")

    def setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+O"), self, self.select_file)
        QShortcut(QKeySequence("Ctrl+W"), self, self.clear_selected_file)
        QShortcut(QKeySequence("Delete"), self, self.clear_selected_file)
        QShortcut(QKeySequence("Ctrl+P"), self, self.process_and_print)
        QShortcut(QKeySequence("Ctrl+R"), self, self.load_preview)
        QShortcut(QKeySequence("Ctrl+H"), self, self.open_history_dialog)
        QShortcut(QKeySequence("Ctrl+J"), self, self.open_queue_dialog)
        QShortcut(QKeySequence("Ctrl+M"), self, self.open_maintenance_dialog)
        QShortcut(QKeySequence("Ctrl+,"), self, self.open_settings_dialog)
        QShortcut(QKeySequence("F1"), self, self.open_shortcuts_dialog)
        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_page)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_page)
        QShortcut(QKeySequence(Qt.Key_PageUp), self, self.prev_page)
        QShortcut(QKeySequence(Qt.Key_PageDown), self, self.next_page)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if os.path.exists(path):
                    self.load_selected_file(path)
                    event.acceptProposedAction()

    def load_selected_file(self, path):
        if path:
            self.file_path = path
            self.cached_pdf_path = path if path.lower().endswith('.pdf') else ""
            filename = os.path.basename(path)
            self.lbl_file.setText(f"Arquivo: {filename}")
            self.lbl_drop_title.setText(filename)
            self.lbl_drop_sub.setText("Clique ou arraste outro arquivo para substituir")
            self.btn_remove_icon.setVisible(True)
            self.current_page = 1

            if self.cached_pdf_path and os.path.exists(self.cached_pdf_path):
                try:
                    reader = PdfReader(self.cached_pdf_path)
                    self.doc_total_pages = len(reader.pages)
                except Exception:
                    self.doc_total_pages = 0
            else:
                self.doc_total_pages = 0

            self.on_nup_changed()
            self.update_cost_estimate()

    def clear_selected_file(self):
        self.file_path = ""
        self.cached_pdf_path = ""
        self.current_preview_img = ""
        self.current_page = 1
        self.total_pages = 1
        self.doc_total_pages = 0

        self.lbl_file.setText("Nenhum arquivo selecionado")
        self.lbl_drop_title.setText("Arraste e solte seu documento aqui")
        self.lbl_drop_sub.setText("ou clique para selecionar (PDF, Word, Planilhas, Slides, TXT)")
        self.lbl_preview.setPixmap(QPixmap())
        self.lbl_preview.setText("Selecione ou arraste um documento para visualizar a prévia")
        self.lbl_page_info.setText("Página 0 de 0")
        self.lbl_cost_estimate.setText("📄 Folhas estimadas: --  |  💰 Custo estimado: --")
        self.btn_prev_page.setEnabled(False)
        self.btn_next_page.setEnabled(False)
        self.btn_remove_icon.setVisible(False)

    def select_file(self):
        default_dir = os.path.expanduser("~/Documentos/")
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~/")

        filters = (
            "Todos os Formatos Suportados (*.pdf *.docx *.doc *.odt *.xlsx *.xls *.ods *.pptx *.ppt *.odp *.txt *.rtf *.csv);;"
            "Documentos PDF (*.pdf);;"
            "Documentos de Texto (*.docx *.doc *.odt *.txt *.rtf);;"
            "Planilhas (*.xlsx *.xls *.ods *.csv);;"
            "Apresentações de Slides (*.pptx *.ppt *.odp);;"
            "Todos os Arquivos (*)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecione o Documento",
            default_dir,
            filters,
            options=QFileDialog.DontUseNativeDialog
        )
        if path:
            self.load_selected_file(path)

    def apply_theme(self):
        palette = self.palette()
        highlight_color = palette.color(QPalette.Highlight).name()

        qss = f"""
            #drop_frame {{
                border: 2px dashed {highlight_color};
                border-radius: 8px;
                padding: 10px;
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(120, 120, 120, 0.35);
                min-height: 25px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(120, 120, 120, 0.65);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                border: none;
                background: transparent;
                height: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: rgba(120, 120, 120, 0.35);
                min-width: 25px;
                border-radius: 3px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: rgba(120, 120, 120, 0.65);
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """
        self.setStyleSheet(qss)
        self.btn_action.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 6px;
                border: none;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
            QPushButton:disabled {
                background-color: #6EE7B7;
                color: #D1FAE5;
            }
        """)


    def is_current_file_landscape(self):
        target_path = self.cached_pdf_path if (self.cached_pdf_path and os.path.exists(self.cached_pdf_path)) else self.file_path
        if not target_path or not os.path.exists(target_path):
            return False
        try:
            from pypdf import PdfReader
            if not target_path.lower().endswith('.pdf'):
                return False
            reader = PdfReader(target_path)
            if reader.pages:
                p = reader.pages[0]
                w = float(p.mediabox.width)
                h = float(p.mediabox.height)
                rot = getattr(p, 'rotation', 0) or 0
                if rot in (90, 270):
                    w, h = h, w
                return w > h
        except:
            pass
        return False

    def on_scaling_mode_changed(self):
        is_custom = (self.cb_scaling_mode.currentText() == "Escala Personalizada")
        self.sp_custom_scale.setEnabled(is_custom)
        if self.file_path:
            self.load_preview()

    def on_nup_changed(self):
        nup = self.cb_nup.currentText()
        is_land = self.is_current_file_landscape()

        if nup == "1 por folha":
            target_orient = "Automático (Padrão)"
        elif nup == "2 por folha":
            target_orient = "Retrato (Vertical)" if is_land else "Paisagem (Horizontal)"
        elif nup == "4 por folha":
            target_orient = "Paisagem (Horizontal)" if is_land else "Retrato (Vertical)"
        elif nup == "6 por folha":
            target_orient = "Retrato (Vertical)" if is_land else "Paisagem (Horizontal)"
        elif nup == "9 por folha":
            target_orient = "Paisagem (Horizontal)" if is_land else "Retrato (Vertical)"
        elif nup == "16 por folha":
            target_orient = "Paisagem (Horizontal)" if is_land else "Retrato (Vertical)"
        else:
            target_orient = "Automático (Padrão)"

        if target_orient:
            self.cb_orientation.blockSignals(True)
            self.cb_orientation.setCurrentText(target_orient)
            self.cb_orientation.blockSignals(False)

        if self.file_path:
            self.load_preview()
        self.update_cost_estimate()

    def on_poster_changed(self):
        is_poster_active = (self.cb_poster.currentText() != "Desativado")
        self.sp_poster_overlap.setEnabled(is_poster_active)
        if is_poster_active:
            self.cb_nup.blockSignals(True)
            self.cb_nup.setCurrentText("1 por folha")
            self.cb_nup.setEnabled(False)
            self.cb_nup.blockSignals(False)
        else:
            self.cb_nup.setEnabled(True)

        if self.file_path:
            self.load_preview()

    def on_booklet_changed(self):
        booklet = self.cb_booklet.currentText()
        is_active = bool(booklet and booklet != "Desativado")

        widgets = [self.cb_nup, self.cb_poster, self.sp_poster_overlap, self.cb_orientation, self.cb_duplex]
        for w in widgets:
            w.blockSignals(True)
        try:
            if is_active:
                self.cb_nup.setCurrentText("1 por folha")
                self.cb_nup.setEnabled(False)
                self.cb_poster.setCurrentText("Desativado")
                self.cb_poster.setEnabled(False)
                self.sp_poster_overlap.setEnabled(False)

                is_land = self.is_current_file_landscape()
                self.cb_orientation.setCurrentText("Retrato (Vertical)" if is_land else "Paisagem (Horizontal)")
                if "Completo" in booklet:
                    self.cb_duplex.setCurrentText("Frente e Verso (Borda Menor)")
                else:
                    self.cb_duplex.setCurrentText("Apenas Frente")
            else:
                self.cb_nup.setEnabled(True)
                self.cb_poster.setEnabled(True)
                self.cb_orientation.setCurrentText("Automático (Padrão)")
        finally:
            for w in widgets:
                w.blockSignals(False)

        if self.file_path:
            self.load_preview()
        self.update_cost_estimate()

    def _get_margins_mm(self):
        return {
            "left": round(self.sp_margin_left.value() * 10.0, 2),
            "right": round(self.sp_margin_right.value() * 10.0, 2),
            "top": round(self.sp_margin_top.value() * 10.0, 2),
            "bottom": round(self.sp_margin_bottom.value() * 10.0, 2),
        }

    def set_uniform_margins(self, cm_val):
        spins = (self.sp_margin_left, self.sp_margin_right, self.sp_margin_top, self.sp_margin_bottom)
        for sp in spins:
            sp.blockSignals(True)
            sp.setValue(float(cm_val))
            sp.blockSignals(False)
        self.on_margin_changed()

    def on_margin_changed(self):
        self.update_usable_area_label()
        if self.file_path:
            self.load_preview()

    def update_usable_area_label(self, paper_w_mm=None, paper_h_mm=None):
        if not hasattr(self, "lbl_usable_area"):
            return
        if paper_w_mm is None or paper_h_mm is None:
            pw_pt, ph_pt = get_paper_size_pts(self.cb_paper_size.currentText())
            orient = self.cb_orientation.currentText()
            if "Paisagem" in orient:
                pw_pt, ph_pt = max(pw_pt, ph_pt), min(pw_pt, ph_pt)
            elif "Retrato" in orient:
                pw_pt, ph_pt = min(pw_pt, ph_pt), max(pw_pt, ph_pt)
            paper_w_mm = pw_pt * 0.352778
            paper_h_mm = ph_pt * 0.352778

        m = self._get_margins_mm()
        usable_w_cm = max(0.0, (paper_w_mm - m["left"] - m["right"]) / 10.0)
        usable_h_cm = max(0.0, (paper_h_mm - m["top"] - m["bottom"]) / 10.0)
        full_w_cm = paper_w_mm / 10.0
        full_h_cm = paper_h_mm / 10.0
        txt = (
            f"📐 Área útil: {usable_w_cm:.2f} × {usable_h_cm:.2f} cm  "
            f"(Papel: {full_w_cm:.2f} × {full_h_cm:.2f} cm)"
        ).replace(".", ",")
        self.lbl_usable_area.setText(txt)

    def on_setting_changed(self):
        self.update_usable_area_label()
        if self.file_path:
            self.load_preview()
        self.update_cost_estimate()

    def update_cost_estimate(self):
        """
        Calcula a quantidade estimada de folhas e o custo total de papel e tinta.
        Leva em consideração:
          - Páginas selecionadas (intervalo e subconjunto par/ímpar)
          - Agrupamento N-Up (slides por folha)
          - Modo Cartaz (mosaico de folhas)
          - Duplex (Frente e Verso reduz o número de folhas físicas pela metade)
          - Quantidade de cópias
          - Tipo de cor (Colorido vs P&B) e tipo de papel
        """
        if not self.file_path:
            self.lbl_cost_estimate.setText("📄 Folhas estimadas: --  |  💰 Custo estimado: --")
            return

        total_doc_p = self.doc_total_pages
        if total_doc_p <= 0:
            if self.cached_pdf_path and os.path.exists(self.cached_pdf_path):
                try:
                    reader = PdfReader(self.cached_pdf_path)
                    total_doc_p = len(reader.pages)
                    self.doc_total_pages = total_doc_p
                except Exception:
                    pass

        if total_doc_p <= 0:
            self.lbl_cost_estimate.setText("📄 Calculando consumo de papel e custos...")
            return

        page_range = self.txt_page_range.text().strip()
        page_subset = self.cb_page_subset.currentText()
        selected_pages = parse_page_range(page_range, total_doc_p, subset=page_subset)
        count_pages = len(selected_pages)

        if count_pages == 0:
            self.lbl_cost_estimate.setText("📄 Nenhuma página no intervalo selecionado")
            return

        booklet = self.cb_booklet.currentText() if hasattr(self, "cb_booklet") else "Desativado"
        poster = self.cb_poster.currentText()
        nup = self.cb_nup.currentText()

        if booklet and booklet != "Desativado":
            virtual_sheets = len(compute_booklet_sheet_pairs(count_pages, booklet))
        elif poster and poster != "Desativado":
            if "2x2" in poster:
                sheets_per_page = 4
            elif "3x3" in poster:
                sheets_per_page = 9
            elif "4x4" in poster:
                sheets_per_page = 16
            else:
                sheets_per_page = 1
            virtual_sheets = count_pages * sheets_per_page
        elif nup and nup != "1 por folha":
            n_val = 1
            if "2 por folha" in nup:
                n_val = 2
            elif "4 por folha" in nup:
                n_val = 4
            elif "6 por folha" in nup:
                n_val = 6
            elif "9 por folha" in nup:
                n_val = 9
            elif "16 por folha" in nup:
                n_val = 16
            import math
            virtual_sheets = math.ceil(count_pages / n_val)
        else:
            virtual_sheets = count_pages

        copies = max(1, self.sp_copies.value())
        is_duplex = ("Frente e Verso" in self.cb_duplex.currentText())

        import math
        if is_duplex:
            physical_sheets_per_copy = math.ceil(virtual_sheets / 2.0)
        else:
            physical_sheets_per_copy = virtual_sheets

        total_physical_sheets = physical_sheets_per_copy * copies
        total_printed_sides = virtual_sheets * copies

        # Obter custos unitários configurados nas preferências (em centavos de Real)
        cost_sheet_cents = float(self.settings.get("cost_per_sheet_cents", 5.0))
        cost_ink_cents = float(self.settings.get("cost_per_page_ink_cents", 10.0))

        # Modificadores inteligentes conforme papel e cor
        media_type = self.cb_media_type.currentText().lower()
        if "foto" in media_type or "glossy" in media_type or "adesivo" in media_type:
            # Papel especial fotográfico/adesivo tem custo maior
            cost_sheet_cents *= 8.0
            cost_ink_cents *= 2.0
        elif "cartão" in media_type or "grosso" in media_type:
            cost_sheet_cents *= 3.0

        is_color = ("Colorido" in self.cb_color.currentText())
        if not is_color:
            # Impressão monocromática consome cerca de 40% do custo de impressão colorida
            cost_ink_cents *= 0.4

        total_cost_reais = ((total_physical_sheets * cost_sheet_cents) + (total_printed_sides * cost_ink_cents)) / 100.0

        sheets_str = f"{total_physical_sheets} folha{'s' if total_physical_sheets > 1 else ''}"
        if is_duplex:
            sheets_str += f" ({total_printed_sides} págs frente/verso)"
        elif copies > 1:
            sheets_str += f" ({copies} cópias)"

        cost_str = f"R$ {total_cost_reais:.2f}".replace(".", ",")
        self.lbl_cost_estimate.setText(f"📄 Folhas estimadas: <b>{sheets_str}</b>  |  💰 Custo estimado: <b>{cost_str}</b>")

    def load_presets_ui(self, select_name=None):
        """Carrega e popula a lista de presets na interface gráfica."""
        self.cb_presets.blockSignals(True)
        self.cb_presets.clear()
        
        all_presets = get_all_presets(self.settings)
        for name in all_presets.keys():
            self.cb_presets.addItem(name)
            
        if select_name and self.cb_presets.findText(select_name) != -1:
            self.cb_presets.setCurrentText(select_name)
        else:
            self.cb_presets.setCurrentIndex(0)
            
        self.cb_presets.blockSignals(False)
        self.update_preset_buttons_state()

    def update_preset_buttons_state(self):
        """Habilita o botão de exclusão apenas para presets customizados criados pelo usuário."""
        curr = self.cb_presets.currentText()
        is_custom = curr not in BUILTIN_PRESETS
        self.btn_delete_preset.setEnabled(is_custom)

    def on_preset_changed(self):
        """Aplica os parâmetros do preset selecionado na interface."""
        preset_name = self.cb_presets.currentText()
        self.update_preset_buttons_state()
        
        all_presets = get_all_presets(self.settings)
        config = all_presets.get(preset_name, {})
        if not config:
            return  # Modo "Padrão do Sistema (Manual)" mantém configurações atuais

        # Bloquear sinais para atualização atômica e limpa
        widgets_to_block = [
            self.cb_orientation, self.cb_scaling_mode, self.sp_custom_scale,
            self.cb_paper_size, self.cb_media_type, self.cb_duplex, self.cb_color,
            self.cb_quality, self.cb_print_speed, self.cb_nup, self.cb_poster,
            self.sp_poster_overlap, self.cb_booklet,
            self.sp_margin_left, self.sp_margin_right, self.sp_margin_top, self.sp_margin_bottom,
            self.chk_mirror_horizontal, self.chk_reverse_order,
            self.chk_print_as_image
        ]
        for w in widgets_to_block:
            w.blockSignals(True)

        try:
            if "color" in config and self.cb_color.isEnabled():
                idx = self.cb_color.findText(config["color"], Qt.MatchContains)
                if idx != -1:
                    self.cb_color.setCurrentIndex(idx)

            if "duplex" in config:
                idx = self.cb_duplex.findText(config["duplex"], Qt.MatchContains)
                if idx != -1:
                    self.cb_duplex.setCurrentIndex(idx)

            if "orientation" in config:
                idx = self.cb_orientation.findText(config["orientation"], Qt.MatchContains)
                if idx != -1:
                    self.cb_orientation.setCurrentIndex(idx)

            if "paper_size" in config:
                idx = self.cb_paper_size.findText(config["paper_size"], Qt.MatchContains)
                if idx != -1:
                    self.cb_paper_size.setCurrentIndex(idx)

            if "mirror_horizontal" in config:
                self.chk_mirror_horizontal.setChecked(bool(config["mirror_horizontal"]))

            if "reverse_order" in config:
                self.chk_reverse_order.setChecked(bool(config["reverse_order"]))

            if "print_as_image" in config:
                self.chk_print_as_image.setChecked(bool(config["print_as_image"]))

            if "nup" in config:
                idx = self.cb_nup.findText(config["nup"], Qt.MatchContains)
                if idx != -1:
                    self.cb_nup.setCurrentIndex(idx)

            if "poster" in config:
                idx = self.cb_poster.findText(config["poster"], Qt.MatchContains)
                if idx != -1:
                    self.cb_poster.setCurrentIndex(idx)
                is_poster_active = (self.cb_poster.currentText() != "Desativado")
                self.sp_poster_overlap.setEnabled(is_poster_active)
                if is_poster_active:
                    self.cb_nup.setCurrentText("1 por folha")
                    self.cb_nup.setEnabled(False)
                else:
                    self.cb_nup.setEnabled(True)

            if "poster_overlap_mm" in config:
                self.sp_poster_overlap.setValue(float(config["poster_overlap_mm"]))

            if "booklet" in config:
                idx = self.cb_booklet.findText(config["booklet"], Qt.MatchContains)
                self.cb_booklet.setCurrentIndex(idx if idx != -1 else 0)
            else:
                self.cb_booklet.setCurrentIndex(0)

            if "cut_marks" in config:
                idx = self.cb_cut_marks.findText(config["cut_marks"], Qt.MatchContains)
                if idx != -1:
                    self.cb_cut_marks.setCurrentIndex(idx)
                else:
                    self.cb_cut_marks.setCurrentText(config["cut_marks"])

            if "margins_cm" in config and isinstance(config["margins_cm"], dict):
                mc = config["margins_cm"]
                self.sp_margin_left.setValue(float(mc.get("left", 0.50)))
                self.sp_margin_right.setValue(float(mc.get("right", 0.50)))
                self.sp_margin_top.setValue(float(mc.get("top", 0.50)))
                self.sp_margin_bottom.setValue(float(mc.get("bottom", 0.50)))

            # Ajuste inteligente de Qualidade
            if "quality_level" in config:
                target_lvl = config["quality_level"].lower()
                for i in range(self.cb_quality.count()):
                    data = self.cb_quality.itemData(i)
                    txt = self.cb_quality.itemText(i).lower()
                    lvl = data.get("level", "") if isinstance(data, dict) else str(data).lower()
                    if target_lvl in lvl or target_lvl in txt:
                        self.cb_quality.setCurrentIndex(i)
                        break

            # Ajuste inteligente de Velocidade
            if "speed_level" in config:
                target_spd = config["speed_level"].lower()
                for i in range(self.cb_print_speed.count()):
                    data = self.cb_print_speed.itemData(i)
                    txt = self.cb_print_speed.itemText(i).lower()
                    spd = data.get("speed", "") if isinstance(data, dict) else str(data).lower()
                    if target_spd in spd or target_spd in txt:
                        self.cb_print_speed.setCurrentIndex(i)
                        break

            # Ajuste inteligente de Tipo de Papel / Mídia
            if "media_type_pref" in config:
                prefs = [p.lower() for p in config["media_type_pref"]]
                found = False
                for pref in prefs:
                    for i in range(self.cb_media_type.count()):
                        txt = self.cb_media_type.itemText(i).lower()
                        data = self.cb_media_type.itemData(i)
                        ipp = data.get("ipp", "").lower() if isinstance(data, dict) else ""
                        ppd_val = data.get("ppd_val", "").lower() if isinstance(data, dict) else ""
                        if pref in txt or pref in ipp or (ppd_val and pref in ppd_val):
                            self.cb_media_type.setCurrentIndex(i)
                            found = True
                            break
                    if found:
                        break
        finally:
            for w in widgets_to_block:
                w.blockSignals(False)

        if self.file_path:
            self.load_preview()

    def on_save_preset_clicked(self):
        """Salva a configuração atual da interface como um novo preset customizado."""
        name, ok = QInputDialog.getText(
            self, "Salvar Perfil de Impressão",
            "Digite o nome do novo Preset (ex: 'Canecas da Loja', 'Etiquetas Adesivas'):"
        )
        if not ok or not name or not name.strip():
            return
        name = name.strip()

        if name in BUILTIN_PRESETS:
            QMessageBox.warning(self, "Nome Reservado", f"O nome '{name}' é um perfil padrão de fábrica e não pode ser sobrescrito.")
            return

        current_quality = self.cb_quality.currentData()
        q_lvl = current_quality.get("level", "normal") if isinstance(current_quality, dict) else "normal"

        current_speed = self.cb_print_speed.currentData()
        s_lvl = current_speed.get("speed", "normal") if isinstance(current_speed, dict) else "normal"

        current_media = self.cb_media_type.currentData()
        m_ipp = current_media.get("ipp", "stationery") if isinstance(current_media, dict) else "stationery"

        preset_data = {
            "orientation": self.cb_orientation.currentText(),
            "paper_size": self.cb_paper_size.currentText(),
            "duplex": self.cb_duplex.currentText(),
            "color": self.cb_color.currentText(),
            "quality_level": q_lvl,
            "speed_level": s_lvl,
            "media_type_pref": [m_ipp, self.cb_media_type.currentText().lower()],
            "nup": self.cb_nup.currentText(),
            "poster": self.cb_poster.currentText(),
            "poster_overlap_mm": self.sp_poster_overlap.value(),
            "booklet": self.cb_booklet.currentText(),
            "margins_cm": {
                "left": round(self.sp_margin_left.value(), 2),
                "right": round(self.sp_margin_right.value(), 2),
                "top": round(self.sp_margin_top.value(), 2),
                "bottom": round(self.sp_margin_bottom.value(), 2),
            },
            "cut_marks": self.cb_cut_marks.currentText(),
            "mirror_horizontal": self.chk_mirror_horizontal.isChecked(),
            "reverse_order": self.chk_reverse_order.isChecked(),
            "print_as_image": self.chk_print_as_image.isChecked()
        }

        custom_presets = self.settings.get("custom_presets", {})
        custom_presets[name] = preset_data
        self.settings["custom_presets"] = custom_presets
        save_settings(self.settings)

        self.load_presets_ui(select_name=name)
        QMessageBox.information(self, "Sucesso", f"Perfil '{name}' salvo com sucesso!")

    def on_delete_preset_clicked(self):
        """Exclui o preset customizado atualmente selecionado."""
        curr = self.cb_presets.currentText()
        if curr in BUILTIN_PRESETS:
            return

        ans = QMessageBox.question(
            self, "Excluir Perfil",
            f"Deseja realmente remover o perfil '{curr}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ans == QMessageBox.Yes:
            custom_presets = self.settings.get("custom_presets", {})
            if curr in custom_presets:
                del custom_presets[curr]
                self.settings["custom_presets"] = custom_presets
                save_settings(self.settings)
                self.load_presets_ui()
                QMessageBox.information(self, "Perfil Removido", f"O perfil '{curr}' foi excluído.")

    def on_page_range_changed(self):
        self.current_page = 1
        if self.file_path:
            self.load_preview()
        self.update_cost_estimate()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_preview()

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.load_preview()

    def on_pdf_converted(self, path):
        self.cached_pdf_path = path
        try:
            reader = PdfReader(path)
            self.doc_total_pages = len(reader.pages)
        except Exception:
            self.doc_total_pages = 0
        self.update_cost_estimate()

    def load_preview(self):
        if not self.file_path:
            return

        req_id = getattr(self, "_preview_req_id", 0) + 1
        self._preview_req_id = req_id

        self.lbl_preview.setText("Carregando prévia...")
        self.lbl_page_info.setText("Gerando prévia...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.quit()
            self.preview_worker.wait()

        orientation = self.cb_orientation.currentText()
        scaling_mode = self.cb_scaling_mode.currentText()
        custom_scale = self.sp_custom_scale.value()
        paper_size = self.cb_paper_size.currentText()
        page_range = self.txt_page_range.text().strip()
        page_subset = self.cb_page_subset.currentText()
        reverse_order = self.chk_reverse_order.isChecked()
        mirror_horizontal = self.chk_mirror_horizontal.isChecked()
        nup = self.cb_nup.currentText()
        poster = self.cb_poster.currentText()
        poster_overlap_mm = self.sp_poster_overlap.value()
        cut_marks = self.cb_cut_marks.currentText()
        booklet = self.cb_booklet.currentText()

        self.preview_worker = PreviewWorkerThread(
            self.file_path,
            self.current_page,
            orientation=orientation,
            scaling_mode=scaling_mode,
            custom_scale=custom_scale,
            paper_size=paper_size,
            page_range=page_range,
            page_subset=page_subset,
            reverse_order=reverse_order,
            nup=nup,
            poster=poster,
            poster_overlap_mm=poster_overlap_mm,
            cached_pdf=self.cached_pdf_path,
            mirror_horizontal=mirror_horizontal,
            cut_marks=cut_marks,
            booklet=booklet,
            margins_mm=self._get_margins_mm(),
        )
        self.preview_worker.preview_ready.connect(
            lambda img, p, tp, cs, pw, ph, pi="", rid=req_id: self.on_preview_ready(img, p, tp, cs, pw, ph, pi, rid)
        )
        self.preview_worker.pdf_converted.connect(self.on_pdf_converted)
        self.preview_worker.error.connect(
            lambda err, rid=req_id: self.on_preview_error(err, rid)
        )
        self.preview_worker.start()

    def update_preview_scaling(self):
        if self.current_preview_img and os.path.exists(self.current_preview_img):
            pixmap = QPixmap(self.current_preview_img)
            if not pixmap.isNull():
                if hasattr(self, "cb_color") and "Preto" in self.cb_color.currentText():
                    pixmap = QPixmap.fromImage(pixmap.toImage().convertToFormat(QImage.Format_Grayscale8))
                target_w = max(50, self.scroll_preview.width() - 30)
                target_h = max(50, self.scroll_preview.height() - 30)
                scaled_pixmap = pixmap.scaled(target_w, target_h,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_preview.setPixmap(scaled_pixmap)

    def on_preview_ready(self, img_path, page_num, total_pages, calc_scale, paper_w_mm, paper_h_mm, poster_info="", req_id=None):
        if req_id is not None and req_id != getattr(self, "_preview_req_id", 0):
            return
        self.current_page = page_num
        self.total_pages = total_pages
        self.current_preview_img = img_path
        self.progress_bar.setVisible(False)

        pixmap = QPixmap(img_path)
        if not pixmap.isNull():
            self.update_preview_scaling()
        else:
            self.lbl_preview.setText("Falha ao carregar imagem da prévia.")

        if poster_info:
            self.lbl_page_info.setText(f"Folha {self.current_page} de {self.total_pages} — {poster_info}")
        else:
            self.lbl_page_info.setText(f"Folha {self.current_page} de {self.total_pages}")
        self.update_usable_area_label(paper_w_mm=paper_w_mm, paper_h_mm=paper_h_mm)
        self.btn_prev_page.setEnabled(self.current_page > 1)
        self.btn_next_page.setEnabled(self.current_page < self.total_pages)
        self.update_cost_estimate()

    def on_preview_error(self, err_msg, req_id=None):
        if req_id is not None and req_id != getattr(self, "_preview_req_id", 0):
            return
        self.progress_bar.setVisible(False)
        self.lbl_preview.setText(f"Erro na prévia: {err_msg}")
        self.lbl_page_info.setText("Prévia indisponível")
        self.btn_prev_page.setEnabled(False)
        self.btn_next_page.setEnabled(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview_scaling()

    def _update_tray_menu_labels(self):
        if hasattr(self, "act_tray_toggle"):
            if not self.isVisible() or self.isMinimized():
                self.act_tray_toggle.setText("Mostrar Janela")
            else:
                self.act_tray_toggle.setText("Ocultar para Bandeja")

    def show_window_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._update_tray_menu_labels()

    def toggle_window_from_tray(self):
        if not self.isVisible() or self.isMinimized():
            self.show_window_from_tray()
        else:
            self.hide()
            self._update_tray_menu_labels()

    def on_tray_icon_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window_from_tray()

    def closeEvent(self, event):
        try:
            self.settings["window_geometry"] = self.saveGeometry().toHex().data().decode()
            self.settings["window_maximized"] = self.isMaximized()
            if hasattr(self, "splitter"):
                self.settings["splitter_state"] = self.splitter.saveState().toHex().data().decode()
            save_settings(self.settings)
        except Exception as e:
            logger.warning(f"Erro ao salvar estado da janela no fechamento: {e}")

        for attr in ("printer_loader", "ink_summary_worker", "preview_worker", "update_worker"):
            worker = getattr(self, attr, None)
            if worker and worker.isRunning():
                worker.wait(1000)

        if getattr(self, "tray_icon", None):
            self.tray_icon.hide()
        super().closeEvent(event)

    def process_and_print(self):
        if not self.file_path:
            QMessageBox.warning(self, "Aviso", "Selecione um documento primeiro!")
            return

        printer = self.cb_printers.currentText()
        copies = self.sp_copies.value()
        paper_size = self.cb_paper_size.currentText()
        media_type_data = self.cb_media_type.currentData()
        media_type_text = self.cb_media_type.currentText()
        if not media_type_data:
            media_type = {"ipp": "stationery", "label": media_type_text, "ppd_val": "Plain"}
        elif isinstance(media_type_data, dict):
            media_type = dict(media_type_data)
            media_type["label"] = media_type_text
        else:
            media_type = {"ipp": "stationery", "label": media_type_text, "ppd_val": str(media_type_data)}
        tray = self.cb_tray.currentData() or self.cb_tray.currentText()
        orientation = self.cb_orientation.currentText()
        scaling_mode = self.cb_scaling_mode.currentText()
        custom_scale = self.sp_custom_scale.value()
        duplex = self.cb_duplex.currentText()
        color = self.cb_color.currentText()
        quality_data = self.cb_quality.currentData()
        quality_text = self.cb_quality.currentText()
        if not quality_data:
            quality = {"level": "normal", "label": quality_text}
        elif isinstance(quality_data, dict):
            quality = dict(quality_data)
            quality["label"] = quality_text
        else:
            quality = {"level": str(quality_data), "label": quality_text}
        speed_data = self.cb_print_speed.currentData()
        speed_text = self.cb_print_speed.currentText()
        if not speed_data:
            print_speed = {"speed": "normal", "label": speed_text, "ppd_val": "Normal"}
        elif isinstance(speed_data, dict):
            print_speed = dict(speed_data)
            print_speed["label"] = speed_text
        else:
            print_speed = {"speed": "normal", "label": speed_text, "ppd_val": str(speed_data)}
        nup = self.cb_nup.currentText()
        poster = self.cb_poster.currentText()
        poster_overlap_mm = self.sp_poster_overlap.value()
        booklet = self.cb_booklet.currentText()
        page_range = self.txt_page_range.text().strip()
        page_subset = self.cb_page_subset.currentText()
        reverse_order = self.chk_reverse_order.isChecked()
        print_as_image = self.chk_print_as_image.isChecked()
        mirror_horizontal = self.chk_mirror_horizontal.isChecked()

        # -----------------------------------------------------------------
        # [RF-08] Alertas de Inconsistência e Validação Pré-Impressão
        # -----------------------------------------------------------------
        if self.doc_total_pages > 0:
            selected_indices = parse_page_range(page_range, self.doc_total_pages, subset=page_subset)
            if len(selected_indices) == 0:
                QMessageBox.warning(self, "Intervalo Vazio", "Nenhuma página foi selecionada com os filtros e intervalo atuais.\nVerifique o campo 'Páginas Específicas' ou o subconjunto.")
                return

            # Alerta 1: Alto volume de folhas físicas (evita envio acidental de centenas de folhas)
            import math
            count_p = len(selected_indices)
            if booklet and booklet != "Desativado":
                virtual_sheets = len(compute_booklet_sheet_pairs(count_p, booklet))
            elif poster and poster != "Desativado":
                m = 4 if "2x2" in poster else (9 if "3x3" in poster else 16)
                virtual_sheets = count_p * m
            elif nup and nup != "1 por folha":
                n_val = int(nup.split()[0]) if nup.split()[0].isdigit() else 1
                virtual_sheets = math.ceil(count_p / n_val)
            else:
                virtual_sheets = count_p

            is_duplex = ("Frente e Verso" in duplex)
            phys_sheets = math.ceil(virtual_sheets / 2.0) if is_duplex else virtual_sheets
            total_phys = phys_sheets * copies

            if total_phys >= 50 and printer != "Salvar como PDF":
                ans = QMessageBox.question(
                    self, "Alerta de Grande Volume",
                    f"Atenção: Este trabalho irá imprimir <b>{total_phys} folhas físicas</b> na impressora '{printer}'.<br><br>"
                    f"• Páginas ativas: {count_p}<br>"
                    f"• Cópias: {copies}<br>"
                    f"• Frente e Verso: {'Sim' if is_duplex else 'Não'}<br><br>"
                    "Deseja realmente continuar com o envio?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if ans != QMessageBox.Yes:
                    return

            # Alerta 2: Duplex em impressora sem duplex automático
            if is_duplex and printer != "Salvar como PDF":
                server_param = self.get_effective_cups_server()
                if not printer_supports_duplex(printer, server_param):
                    ans = QMessageBox.question(
                        self, "Aviso de Frente e Verso (Duplex)",
                        f"A impressora <b>'{printer}'</b> pode não possuir módulo de duplex automático via hardware.<br><br>"
                        "Se ela for de alimentação manual, a impressão pode sair em folhas separadas a menos que você alimente o papel manualmente.<br><br>"
                        "Deseja prosseguir mesmo assim?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                    )
                    if ans != QMessageBox.Yes:
                        return

            # Alerta 3: Inconsistência de Mídia Especial vs Papel Comum
            media_lbl = media_type_text.lower()
            if ("foto" in media_lbl or "glossy" in media_lbl or "adesivo" in media_lbl) and printer != "Salvar como PDF":
                if copies > 10:
                    ans = QMessageBox.question(
                        self, "Papel Fotográfico / Especial",
                        f"Você selecionou <b>{copies} cópias</b> em <b>{media_type_text}</b>.<br>"
                        "Papéis fotográficos e adesivos demandam maior tempo de secagem e cuidado na bandeja.<br><br>"
                        "Confirmar envio?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                    )
                    if ans != QMessageBox.Yes:
                        return

        save_path = ""
        if printer == "Salvar como PDF":
            save_path, _ = QFileDialog.getSaveFileName(self, "Salvar PDF Processado", os.path.basename(self.file_path), "PDF (*.pdf)")
            if not save_path:
                return

        self.btn_action.setText("Processando em segundo plano...")
        self.btn_action.setEnabled(False)
        self.lbl_status.setText("Iniciando processamento...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        target_server = self.get_effective_cups_server()

        self.print_worker = PrintWorkerThread(
            file_path=self.file_path,
            printer=printer,
            copies=copies,
            paper_size=paper_size,
            orientation=orientation,
            scaling_mode=scaling_mode,
            custom_scale=custom_scale,
            duplex=duplex,
            color=color,
            quality=quality,
            media_type=media_type,
            print_speed=print_speed,
            nup=nup,
            poster=poster,
            page_range=page_range,
            page_subset=page_subset,
            reverse_order=reverse_order,
            print_as_image=print_as_image,
            tray=tray,
            save_path=save_path,
            cups_server=target_server,
            mirror_horizontal=mirror_horizontal,
            poster_overlap_mm=poster_overlap_mm,
            cut_marks=self.cb_cut_marks.currentText(),
            booklet=booklet,
            margins_mm=self._get_margins_mm(),
        )
        self.print_worker.progress.connect(self.on_print_progress)
        self.print_worker.finished_signal.connect(self.on_print_finished)
        self.print_worker.start()

    def on_print_progress(self, msg):
        self.lbl_status.setText(msg)

    def on_print_finished(self, success, message):
        self.btn_action.setText("PROCESSAR E IMPRIMIR (Ctrl+P)")
        self.btn_action.setEnabled(True)
        self.lbl_status.setText("")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setVisible(False)

        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filename": os.path.basename(self.file_path) if self.file_path else "Desconhecido",
            "file_path": self.file_path,
            "printer": self.cb_printers.currentText(),
            "copies": self.sp_copies.value(),
            "paper": self.cb_paper_size.currentText(),
            "media_type": self.cb_media_type.currentText(),
            "color": self.cb_color.currentText(),
            "quality": self.cb_quality.currentText(),
            "print_speed": self.cb_print_speed.currentText(),
            "duplex": self.cb_duplex.currentText(),
            "mirror": "Sim" if self.chk_mirror_horizontal.isChecked() else "Não",
            "cut_marks": self.cb_cut_marks.currentText(),
            "cost_summary": self.lbl_cost_estimate.text(),
            "status": "Sucesso" if success else "Erro",
            "details": message
        }
        save_history_entry(entry)

        if success:
            self.show_desktop_notification(
                "Impressão Concluída",
                f"O documento '{entry['filename']}' foi enviado com sucesso para '{entry['printer']}'!",
                is_error=False
            )
            QMessageBox.information(self, "Sucesso", message)
        else:
            self.show_desktop_notification(
                "Falha na Impressão",
                f"Erro ao imprimir '{entry['filename']}':\n{message}",
                is_error=True
            )
            QMessageBox.critical(self, "Erro", message)

    def show_desktop_notification(self, title, body, is_error=False):
        """
        Dispara uma notificação nativa do ambiente desktop (KDE Plasma / BigLinux / GNOME / Windows).
        Prioriza libnotify (notify-send) no Linux com fallback para QSystemTrayIcon.
        """
        # 1. No Linux, tentar notify-send com ambiente limpo do host
        if sys.platform.startswith("linux"):
            try:
                cmd = ["notify-send", "-a", "Gerenciador de Impressões Pro"]
                if is_error:
                    cmd.extend(["-u", "critical"])
                else:
                    cmd.extend(["-u", "normal"])

                if hasattr(self, "app_icon_path") and self.app_icon_path and os.path.exists(self.app_icon_path):
                    cmd.extend(["-i", self.app_icon_path])
                else:
                    cmd.extend(["-i", "printer"])

                cmd.extend([title, body])
                subprocess.Popen(cmd, env=get_clean_host_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception as e:
                logger.debug("notify-send não pôde ser executado: %s", e)

        # 2. Fallback via QSystemTrayIcon (KDE / Windows / Qt)
        try:
            if hasattr(self, "tray_icon") and self.tray_icon and self.tray_icon.isVisible():
                icon_type = QSystemTrayIcon.Critical if is_error else QSystemTrayIcon.Information
                self.tray_icon.showMessage(title, body, icon_type, 4000)
        except Exception as e:
            logger.debug("Falha na notificação via QSystemTrayIcon: %s", e)

    def open_history_dialog(self):
        dlg = HistoryDialog(self, parent=self)
        dlg.exec_()

    def open_settings_dialog(self):
        dlg = SettingsDialog(self, parent=self)
        dlg.exec_()

    def open_installer_dialog(self):
        dlg = PrinterInstallerDialog(self, parent=self)
        dlg.exec_()

    def open_queue_dialog(self):
        dlg = QueueDialog(self, parent=self)
        dlg.exec_()

    def open_maintenance_dialog(self):
        curr_p = self.cb_printers.currentText() if hasattr(self, "cb_printers") else ""
        dlg = MaintenanceDialog(self, initial_printer=curr_p, parent=self)
        dlg.exec_()
        final_p = self.cb_printers.currentText() if hasattr(self, "cb_printers") else curr_p
        self.refresh_ink_summary(final_p, self.get_effective_cups_server())

    def open_about_dialog(self):
        dlg = AboutDialog(parent=self)
        dlg.exec_()

    def open_shortcuts_dialog(self):
        dlg = ShortcutsDialog(parent=self)
        dlg.exec_()

    def check_for_updates(self):
        self.lbl_status.setText("Procurando atualizações em segundo plano...")
        self.update_worker = UpdateCheckerThread(CURRENT_VERSION)
        self.update_worker.checked.connect(self.on_update_checked)
        self.update_worker.start()

    def on_update_checked(self, has_update, latest_version, release_data, error_msg):
        self.lbl_status.setText("")
        if error_msg:
            QMessageBox.warning(
                self, "Verificação de Atualizações",
                f"Não foi possível verificar atualizações no momento.\n\nDetalhes:\n{error_msg}"
            )
            return

        if has_update:
            body = release_data.get("body", "")
            notes = f"\n\nNotas do lançamento:\n{body[:250]}..." if body else ""
            reply = QMessageBox.question(
                self, 'Atualização Disponível!',
                f"Uma nova versão ({latest_version}) foi encontrada!\n(Versão instalada: {CURRENT_VERSION}){notes}\n\nDeseja baixar e atualizar agora?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.perform_update(release_data)
        else:
            QMessageBox.information(
                self, "Atualizado",
                f"Você já está usando a versão mais recente ({CURRENT_VERSION})!"
            )

    def perform_update(self, release_data):
        is_windows = sys.platform.startswith("win32")
        is_linux = sys.platform.startswith("linux")

        target_asset = None
        asset_url = None
        asset_name = ""

        # Encontrar o asset correspondente ao sistema operacional
        for asset in release_data.get("assets", []):
            name = asset.get("name", "")
            if is_windows and name.endswith(".exe"):
                target_asset = asset
                asset_url = asset.get("browser_download_url")
                asset_name = name
                break
            elif is_linux and name.endswith(".AppImage"):
                target_asset = asset
                asset_url = asset.get("browser_download_url")
                asset_name = name
                break

        html_url = release_data.get("html_url", "https://github.com/LucasTelesEriceira/gerenciador-impressoes/releases")

        if not asset_url:
            reply = QMessageBox.question(
                self, "Instalador Não Encontrado",
                f"Não foi encontrado um pacote binário automatizado para o seu sistema ({sys.platform}) neste lançamento.\n\nDeseja abrir a página do GitHub para baixar manualmente?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(html_url))
            return

        # Verificar se está rodando em ambiente compilado/instalado
        is_frozen = getattr(sys, 'frozen', False)
        current_appimage = os.environ.get("APPIMAGE")

        if is_linux and not current_appimage:
            reply = QMessageBox.question(
                self, "Execução em Modo Script",
                "O programa está sendo executado diretamente a partir do código Python ou de um diretório descompactado, e não a partir de um pacote .AppImage montado.\n\nDeseja abrir a página do lançamento no GitHub para baixar o novo pacote?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(html_url))
            return

        if is_windows and not is_frozen:
            reply = QMessageBox.question(
                self, "Execução em Modo Script",
                "O programa está sendo executado diretamente via script Python no Windows.\n\nDeseja abrir a página do lançamento no GitHub para baixar o executável (.exe) da nova versão?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(html_url))
            return

        # Preparar arquivo de destino temporário
        if is_linux:
            dest_tmp = current_appimage + ".part"
        else:
            dest_tmp = os.path.join(tempfile.gettempdir(), f"Gerenciador_Impressoes_Pro_{release_data.get('tag_name', 'new')}.exe")

        # Configurar diálogo de progresso modal
        progress_dlg = QProgressDialog(f"Iniciando download de {asset_name}...", "Cancelar", 0, 100, self)
        progress_dlg.setWindowTitle("Baixando Atualização")
        progress_dlg.setWindowModality(Qt.WindowModal)
        progress_dlg.setMinimumDuration(0)
        progress_dlg.setValue(0)

        download_thread = UpdateDownloadThread(asset_url, dest_tmp)

        def on_progress(downloaded, total):
            if total > 0:
                percent = int((downloaded / total) * 100)
                progress_dlg.setValue(percent)
                mb_down = downloaded / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                progress_dlg.setLabelText(f"Baixando {asset_name}...\n{mb_down:.1f} MB de {mb_total:.1f} MB ({percent}%)")
            else:
                mb_down = downloaded / (1024 * 1024)
                progress_dlg.setLabelText(f"Baixando {asset_name}...\n{mb_down:.1f} MB baixados...")

        def on_cancelled():
            download_thread.cancel()
            try:
                if os.path.exists(dest_tmp):
                    os.remove(dest_tmp)
            except Exception:
                pass
            self.lbl_status.setText("Atualização cancelada.")

        def on_finished(downloaded_file):
            try:
                progress_dlg.canceled.disconnect(on_cancelled)
            except Exception:
                pass
            progress_dlg.close()
            try:
                if not os.path.exists(downloaded_file):
                    raise FileNotFoundError(f"Arquivo de atualização temporário não encontrado: {downloaded_file}")

                if is_linux:
                    try:
                        os.replace(downloaded_file, current_appimage)
                    except OSError:
                        shutil.copyfile(downloaded_file, current_appimage)
                        try:
                            os.remove(downloaded_file)
                        except Exception:
                            pass
                    os.chmod(current_appimage, 0o755)
                    QMessageBox.information(
                        self, "Atualização Concluída",
                        "O aplicativo foi atualizado com sucesso!\nO sistema será reiniciado agora."
                    )
                    os.execv(current_appimage, [current_appimage] + sys.argv[1:])
                elif is_windows:
                    current_exe = sys.executable
                    batch_path = os.path.join(tempfile.gettempdir(), "update_gerenciador.bat")
                    with open(batch_path, "w", encoding="cp1252") as f:
                        f.write(f'''@echo off
timeout /t 2 /nobreak > NUL
copy /y "{downloaded_file}" "{current_exe}"
del "{downloaded_file}"
start "" "{current_exe}"
del "%~f0"
''')
                    QMessageBox.information(
                        self, "Atualização Concluída",
                        "O aplicativo foi atualizado com sucesso!\nO sistema será reiniciado agora."
                    )
                    detached = 0x00000008  # DETACHED_PROCESS
                    subprocess.Popen(["cmd.exe", "/c", batch_path], creationflags=detached)
                    QApplication.quit()
                    sys.exit(0)
            except Exception as ex:
                QMessageBox.critical(self, "Erro ao Aplicar Atualização", f"Falha ao substituir o arquivo executável:\n{str(ex)}")

        def on_error(err_msg):
            try:
                progress_dlg.canceled.disconnect(on_cancelled)
            except Exception:
                pass
            progress_dlg.close()
            try:
                if os.path.exists(dest_tmp):
                    os.remove(dest_tmp)
            except Exception:
                pass
            QMessageBox.critical(self, "Erro no Download", f"Falha ao baixar a atualização:\n{err_msg}")
            self.lbl_status.setText("")

        progress_dlg.canceled.connect(on_cancelled)
        download_thread.progress.connect(on_progress)
        download_thread.finished.connect(on_finished)
        download_thread.error.connect(on_error)

        # Guarda referência para o Garbage Collector não descartar a thread
        self._current_download_thread = download_thread
        download_thread.start()

    def integrate_with_system(self, silent=False):
        if not sys.platform.startswith("linux"):
            if not silent:
                QMessageBox.information(self, "Aviso", "A integração com lançador e menu de contexto é exclusiva para Linux.")
            return

        try:
            home = os.path.expanduser("~")
            apps_dir = os.path.join(home, ".local", "share", "applications")
            desktop_path = os.path.join(apps_dir, "gerenciador-impressoes.desktop")

            # Se já estiver integrado e for checagem silenciosa de inicialização, ignora para abrir instantaneamente
            if silent and os.path.exists(desktop_path):
                return

            # 1. Determinar o executável correto
            appimage_path = os.environ.get("APPIMAGE")
            if appimage_path and os.path.exists(appimage_path):
                exec_cmd = f'"{appimage_path}"'
            elif getattr(sys, 'frozen', False):
                exec_cmd = f'"{sys.executable}"'
            else:
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                entrypoint = os.path.join(project_root, "Gerenciador_Impressoes_Pro.py")
                script_path = entrypoint if os.path.exists(entrypoint) else os.path.abspath(sys.argv[0])
                exec_cmd = f'python3 "{script_path}"'

            # 2. Localizar o ícone do projeto
            candidate_dirs = [
                getattr(sys, '_MEIPASS', None),
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                os.path.dirname(sys.executable),
                os.getcwd()
            ]
            icon_source = ""
            for cd in candidate_dirs:
                if cd and os.path.exists(os.path.join(cd, "icon.png")):
                    icon_source = os.path.join(cd, "icon.png")
                    break
            if not os.path.exists(icon_source):
                base_dir = os.path.dirname(sys.executable)
                candidate = os.path.join(base_dir, "icon.png")
                if os.path.exists(candidate):
                    icon_source = candidate

            # 3. Instalar ícones nos diretórios padrão do usuário
            icons_base = os.path.join(home, ".local", "share", "icons", "hicolor")
            pixmaps_dir = os.path.join(home, ".local", "share", "pixmaps")
            os.makedirs(pixmaps_dir, exist_ok=True)

            if os.path.exists(icon_source):
                try:
                    from PIL import Image
                    src_img = Image.open(icon_source)
                    for sz in [16, 32, 48, 64, 128, 256, 512]:
                        sz_dir = os.path.join(icons_base, f"{sz}x{sz}", "apps")
                        os.makedirs(sz_dir, exist_ok=True)
                        dest_file = os.path.join(sz_dir, "gerenciador-impressoes.png")
                        if not os.path.exists(dest_file):
                            resized = src_img.resize((sz, sz), Image.Resampling.LANCZOS)
                            resized.save(dest_file)
                except Exception:
                    sz_dir = os.path.join(icons_base, "256x256", "apps")
                    os.makedirs(sz_dir, exist_ok=True)
                    shutil.copyfile(icon_source, os.path.join(sz_dir, "gerenciador-impressoes.png"))

                shutil.copyfile(icon_source, os.path.join(pixmaps_dir, "gerenciador-impressoes.png"))

            # 4. Criar o arquivo .desktop com suporte a %F e todos os tipos MIME
            os.makedirs(apps_dir, exist_ok=True)
            desktop_content = f"""[Desktop Entry]
Name=Gerenciador de Impressões Pro
GenericName=Gerenciador de Impressão
Comment=Gerenciador Avançado de Impressão, Pré-visualização e Fila CUPS
Exec={exec_cmd} %F
Icon=gerenciador-impressoes
Terminal=false
Type=Application
Categories=Office;Utility;Printing;
MimeType={SUPPORTED_MIME_TYPES}
StartupNotify=true
"""
            with open(desktop_path, "w", encoding="utf-8") as f:
                f.write(desktop_content)
            os.chmod(desktop_path, 0o755)

            # 5. Atualizar bancos de dados do ambiente desktop
            if not silent:
                try:
                    subprocess.run(["update-desktop-database", apps_dir], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                try:
                    subprocess.run(["kbuildsycoca6"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    try:
                        subprocess.run(["kbuildsycoca5"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                QMessageBox.information(
                    self, "Integração Concluída",
                    "O Gerenciador de Impressões Pro foi integrado com sucesso ao sistema!\n\n"
                    "• Ícone oficial adicionado ao lançador de aplicativos do BigLinux.\n"
                    "• Habilitada a opção 'Abrir com...' no menu de contexto (botão direito) do Dolphin para PDF, Word, Planilhas, Slides e Textos."
                )
            else:
                # Disparo assíncrono para não atrasar a inicialização da interface
                try:
                    subprocess.Popen(["update-desktop-database", apps_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                try:
                    subprocess.Popen(["kbuildsycoca6"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    try:
                        subprocess.Popen(["kbuildsycoca5"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, "Falha na Integração", f"Não foi possível concluir a integração com o sistema:\n{str(e)}")

