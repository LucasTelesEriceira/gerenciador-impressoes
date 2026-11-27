#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerenciador de Impressões Pro
Entrypoint do aplicativo.

Inicializa o runtime Qt, configura atributos High-DPI,
carrega a janela principal modular e despacha a execução.
"""

import sys
import os

# Adiciona o diretório raiz ao sys.path para importações absolutas do pacote src
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

# Aliases de compatibilidade para módulos legados
from src.config import (
    CURRENT_VERSION, SETTINGS_DIR, LOGS_DIR, SETTINGS_FILE, HISTORY_FILE,
    load_settings, save_settings, load_history, save_history_entry, clear_history,
    get_all_presets, BUILTIN_PRESETS, get_clean_host_env, logger
)
from src.core.geometry import parse_page_range, fit_page_to_orientation_and_scale
from src.core.layout import (
    apply_nup_to_pages, apply_poster_to_pages, apply_mirror_to_pages,
    apply_cut_marks_to_page, apply_cut_marks_to_pages
)
from src.core.raster import convert_to_pdf_via_libreoffice, rasterize_pdf_to_images_pdf
from src.cups.discovery import get_system_printers, is_monochrome_printer
from src.cups.ppd import (
    get_printer_trays, get_printer_qualities, get_printer_media_types, get_printer_speeds,
    map_media_type_to_ipp
)
from src.workers.printer_loader import PrinterLoaderThread
from src.workers.preview_worker import PreviewWorkerThread
from src.workers.print_worker import PrintWorkerThread
from src.workers.updater_worker import UpdateCheckerThread, UpdateDownloadThread
from src.ui.widgets.drop_zone import DropZoneFrame
from src.ui.dialogs import (
    HistoryDialog, SettingsDialog, ServerManagerDialog, PrinterInstallerDialog,
    QueueDialog, AboutDialog, ShortcutsDialog
)
from src.ui.main_window import PrintManagerApp


def main():
    logger.info("Iniciando Gerenciador de Impressões Pro %s", CURRENT_VERSION)

    # Configurações de High-DPI para telas 2K/4K
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    window = PrintManagerApp()

    # Abrir documento diretamente se passado por argumento (ex: botão direito -> 'Abrir com...')
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        window.load_selected_file(sys.argv[1])

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
