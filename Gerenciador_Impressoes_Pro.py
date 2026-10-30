#!/usr/bin/env python3
import sys
import os
import subprocess
import shutil
import json
import urllib.request
import urllib.error
import csv
import ssl
import tempfile
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QComboBox, QSpinBox, QLineEdit,
                             QFileDialog, QMessageBox, QGroupBox, QFormLayout,
                             QScrollArea, QSplitter, QProgressBar, QFrame, QShortcut,
                             QMenuBar, QMenu, QAction, QDialog, QTableWidget, QTableWidgetItem,
                             QHeaderView, QTextEdit, QCheckBox, QDialogButtonBox, QTabWidget,
                             QProgressDialog, QSizePolicy)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QProcess, QUrl
from PyQt5.QtGui import QPixmap, QImage, QKeySequence, QFont, QPalette, QIcon, QDesktopServices
from PyQt5.QtPrintSupport import QPrinterInfo

# Garantir localização dos certificados CA raiz para conexões seguras
if "SSL_CERT_FILE" not in os.environ:
    for _ca_bundle in [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/ca-bundle.pem",
        "/etc/ssl/cert.pem"
    ]:
        if os.path.exists(_ca_bundle):
            os.environ["SSL_CERT_FILE"] = _ca_bundle
            break

CURRENT_VERSION = "v1.3.1"
SETTINGS_DIR = os.path.expanduser("~/.config/gerenciador_impressoes_pro")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
HISTORY_FILE = os.path.join(SETTINGS_DIR, "history.json")

SUPPORTED_EXTENSIONS = [
    '.pdf',
    '.docx', '.doc', '.odt', '.rtf', '.txt',
    '.xlsx', '.xls', '.ods', '.csv',
    '.pptx', '.ppt', '.odp'
]

SUPPORTED_MIME_TYPES = (
    "application/pdf;"
    "application/vnd.oasis.opendocument.text;"
    "application/vnd.oasis.opendocument.spreadsheet;"
    "application/vnd.oasis.opendocument.presentation;"
    "application/msword;"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
    "application/vnd.ms-excel;"
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;"
    "application/vnd.ms-powerpoint;"
    "application/vnd.openxmlformats-officedocument.presentationml.presentation;"
    "text/plain;"
    "text/rtf;"
    "text/csv;"
)


def load_settings():
    default_settings = {
        "cups_server": "",
        "cups_port": 631,
        "default_printer": "Salvar como PDF",
        "default_paper": "A4",
        "keep_history": True,
        "max_history_entries": 100,
        "script_url": "https://raw.githubusercontent.com/LucasTelesEriceira/gerenciador-impressoes/main/instalar_impressoras.sh"
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_settings.update(data)
        except Exception:
            pass
    return default_settings


def save_settings(settings_dict):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_history_entry(entry):
    settings = load_settings()
    if not settings.get("keep_history", True):
        return
    history = load_history()
    history.insert(0, entry)
    max_entries = settings.get("max_history_entries", 100)
    history = history[:max_entries]
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


def clear_history():
    if os.path.exists(HISTORY_FILE):
        try:
            os.remove(HISTORY_FILE)
        except Exception:
            pass


def get_system_printers(cups_server="", cups_port=631):
    """
    Busca todas as impressoras disponíveis no sistema ou no servidor CUPS remoto.
    Possui fallback automático para CUPS local se o servidor remoto não responder.
    """
    printers = []
    
    # 1. Tentar servidor remoto especificado se houver
    if cups_server:
        target = f"{cups_server}:{cups_port}" if ":" not in cups_server else cups_server
        for cmd in [['lpstat', '-h', target, '-e'], ['lpstat', '-h', target, '-a']]:
            try:
                env = os.environ.copy()
                env["CUPS_SERVER"] = target
                output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env, timeout=1.0)
                for line in output.strip().split('\n'):
                    if line and not line.startswith('lpstat:'):
                        name = line.split()[0].strip()
                        if name and name not in printers:
                            printers.append(name)
                if printers:
                    return printers
            except Exception:
                pass

    # 2. Fallback para CUPS local (sem CUPS_SERVER remoto)
    env_local = os.environ.copy()
    if "CUPS_SERVER" in env_local:
        del env_local["CUPS_SERVER"]

    for cmd in [['lpstat', '-e'], ['lpstat', '-a'], ['lpstat', '-p']]:
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env_local, timeout=1.0)
            for line in output.strip().split('\n'):
                if line and not line.startswith('lpstat:'):
                    if len(cmd) > 1 and cmd[1] == '-p':
                        parts = line.split()
                        if len(parts) >= 2 and parts[0].lower() in ['impressora', 'printer']:
                            name = parts[1]
                        else:
                            name = parts[0]
                    else:
                        name = line.split()[0].strip()
                    if name and name not in printers:
                        printers.append(name)
            if printers:
                break
        except Exception:
            pass

    # 3. Fallback nativo do sistema operacional (Windows / Qt / cups-browsed)
    if not printers:
        try:
            for p in QPrinterInfo.availablePrinterNames():
                if p and p not in printers:
                    printers.append(p)
        except Exception:
            pass

    return printers


class PrinterLoaderThread(QThread):
    """Thread não bloqueante para descoberta rápida de impressoras locais/remotas sem travar a interface."""
    printers_ready = pyqtSignal(list, str)

    def __init__(self, cups_server="", cups_port=631, default_printer="Salvar como PDF"):
        super().__init__()
        self.cups_server = cups_server
        self.cups_port = cups_port
        self.default_printer = default_printer

    def run(self):
        # 1. Aplicar ambiente CUPS sem travar a interface
        if self.cups_server:
            target = f"{self.cups_server}:{self.cups_port}" if ":" not in self.cups_server else self.cups_server
            try:
                subprocess.check_call(['lpstat', '-h', target, '-r'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                os.environ["CUPS_SERVER"] = target
            except Exception:
                if "CUPS_SERVER" in os.environ:
                    del os.environ["CUPS_SERVER"]
        elif "CUPS_SERVER" in os.environ:
            del os.environ["CUPS_SERVER"]

        # 2. Descobrir impressoras
        printers = ["Salvar como PDF"]
        try:
            detected = get_system_printers(self.cups_server, self.cups_port)
            for p in detected:
                if p not in printers:
                    printers.append(p)
        except Exception:
            pass
        self.printers_ready.emit(printers, self.default_printer)


def is_monochrome_printer(printer_name, cups_server=""):
    """Detecta se uma impressora é monocromática (apenas Preto e Branco)."""
    if not printer_name or printer_name == "Salvar como PDF":
        return False
    try:
        cmd = ['lpoptions', '-p', printer_name, '-l']
        env = os.environ.copy()
        if cups_server:
            cmd.extend(['-h', cups_server])
            env["CUPS_SERVER"] = cups_server
        else:
            if "CUPS_SERVER" in env:
                del env["CUPS_SERVER"]

        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env, timeout=1.0)
        
        color_found = False
        mono_only = False
        
        for line in output.splitlines():
            line_lower = line.lower()
            if 'colormodel' in line_lower or 'print-color-mode' in line_lower:
                if any(c in line_lower for c in ['rgb', 'cmyk', '*color', 'color=true']):
                    color_found = True
                if '*gray' in line_lower or '*monochrome' in line_lower or '*mono' in line_lower:
                    if not any(c in line_lower for c in ['rgb', 'cmyk', 'color']):
                        mono_only = True
        
        if mono_only and not color_found:
            return True
    except Exception:
        pass
    return False


def get_printer_trays(printer_name, cups_server=""):
    """
    Obtém as bandejas de entrada (InputSlot / media-source) disponíveis para a impressora informada.
    Retorna uma lista de tuplas: (label_exibicao, valor_raw, is_default)
    """
    fallback_trays = [
        ("Automática (Padrão)", "Auto", True),
        ("Bandeja 1 (Main Tray)", "Tray1", False),
        ("Bandeja 2 (Lower Tray)", "Tray2", False),
        ("Bandeja 3 (Optional Tray)", "Tray3", False),
        ("Alimentação Manual (Bypass/Manual Feed)", "Manual", False),
        ("Alimentador de Envelopes", "Envelope", False)
    ]

    if not printer_name or printer_name == "Salvar como PDF":
        return [("Automática (Padrão)", "Auto", True)]

    try:
        cmd = ['lpoptions', '-p', printer_name, '-l']
        env = os.environ.copy()
        if cups_server:
            cmd.extend(['-h', cups_server])
            env["CUPS_SERVER"] = cups_server
        else:
            if "CUPS_SERVER" in env:
                del env["CUPS_SERVER"]

        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env, timeout=1.0)

        slot_line = None
        for line in output.splitlines():
            if ':' not in line:
                continue
            key_part, choices_part = line.split(':', 1)
            opt_key = key_part.split('/')[0].strip().lower()
            if opt_key in ['inputslot', 'mediasource', 'media-source', 'inputbin', 'input-slot']:
                slot_line = choices_part.strip()
                break

        if not slot_line:
            return fallback_trays

        choices = slot_line.split()
        parsed_trays = []
        has_default = False

        for choice in choices:
            is_def = choice.startswith('*')
            clean = choice.lstrip('*')

            if '/' in clean:
                raw_val, display_val = clean.split('/', 1)
            else:
                raw_val = display_val = clean

            raw_lower = raw_val.lower()
            disp_lower = display_val.lower()

            if raw_lower in ['auto', 'automatic', 'default', 'auto-select'] or disp_lower in ['auto', 'automatic']:
                label = "Automática (Padrão)"
            elif 'tray1' in raw_lower or 'tray 1' in raw_lower or 'tray-1' in raw_lower or raw_lower == '1' or 'main' in disp_lower:
                label = "Bandeja 1 (Main Tray)"
            elif 'tray2' in raw_lower or 'tray 2' in raw_lower or 'tray-2' in raw_lower or raw_lower == '2' or 'lower' in disp_lower:
                label = "Bandeja 2 (Lower Tray)"
            elif 'tray3' in raw_lower or 'tray 3' in raw_lower or 'tray-3' in raw_lower or raw_lower == '3':
                label = "Bandeja 3 (Optional Tray)"
            elif 'tray4' in raw_lower or 'tray 4' in raw_lower or 'tray-4' in raw_lower or raw_lower == '4':
                label = "Bandeja 4"
            elif any(m in raw_lower or m in disp_lower for m in ['manual', 'bypass', 'mpf', 'multipurpose']):
                label = "Alimentação Manual (Bypass/Manual Feed)"
            elif 'rear' in raw_lower or 'rear' in disp_lower:
                label = "Bandeja Traseira (Rear Tray)"
            elif 'envelope' in raw_lower or 'env' in raw_lower or 'envelope' in disp_lower:
                label = "Alimentador de Envelopes"
            else:
                label = f"{display_val}" if display_val != raw_val else raw_val

            if is_def:
                has_default = True

            parsed_trays.append((label, raw_val, is_def))

        if parsed_trays:
            if not has_default and len(parsed_trays) > 0:
                label, raw, _ = parsed_trays[0]
                parsed_trays[0] = (label, raw, True)
            return parsed_trays

    except Exception:
        pass

    return fallback_trays


def parse_page_range(range_str, total_pages):
    """Converte uma string de intervalo (ex: '1-5, 8, 11-13') em uma lista ordenada de índices (0-indexed)."""
    if not range_str or not range_str.strip():
        return list(range(total_pages))
    pages = set()
    parts = range_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            sub = part.split('-')
            if len(sub) == 2:
                try:
                    start = int(sub[0])
                    end = int(sub[1])
                    for p in range(start, end + 1):
                        if 1 <= p <= total_pages:
                            pages.add(p - 1)
                except ValueError:
                    pass
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages:
                    pages.add(p - 1)
            except ValueError:
                pass
    res = sorted(list(pages))
    return res if res else list(range(total_pages))


def get_paper_size_pts(paper_name):
    sizes = {
        "A4": (595.28, 841.89),
        "Carta (Letter)": (612.0, 792.0),
        "A3": (841.89, 1190.55),
        "A5": (419.53, 595.28),
        "Ofício (Legal)": (612.0, 1008.0)
    }
    return sizes.get(paper_name, (595.28, 841.89))


def apply_nup_to_pages(pages, nup_str, paper_size_name="A4"):
    """Agrupa uma lista de PageObjects do PyPDF em folhas N-up (2, 4, 6, 9 ou 16 por folha)."""
    if nup_str == "1 por folha" or not nup_str:
        return pages

    is_doc_landscape = False
    if pages:
        p0 = pages[0]
        pw0 = float(p0.mediabox.width)
        ph0 = float(p0.mediabox.height)
        rot0 = getattr(p0, 'rotation', 0) or 0
        if rot0 in (90, 270):
            pw0, ph0 = ph0, pw0
        is_doc_landscape = (pw0 > ph0)

    if not is_doc_landscape:
        n_map = {
            "2 por folha": (2, 2, 1, True),
            "4 por folha": (4, 2, 2, False),
            "6 por folha": (6, 3, 2, True),
            "9 por folha": (9, 3, 3, False),
            "16 por folha": (16, 4, 4, False)
        }
    else:
        n_map = {
            "2 por folha": (2, 1, 2, False),
            "4 por folha": (4, 2, 2, True),
            "6 por folha": (6, 2, 3, False),
            "9 por folha": (9, 3, 3, True),
            "16 por folha": (16, 4, 4, True)
        }

    if nup_str not in n_map:
        return pages

    from pypdf import PageObject, Transformation
    n, cols, rows, is_sheet_landscape = n_map[nup_str]
    base_w, base_h = get_paper_size_pts(paper_size_name)

    if is_sheet_landscape:
        sheet_w = max(base_w, base_h)
        sheet_h = min(base_w, base_h)
    else:
        sheet_w = min(base_w, base_h)
        sheet_h = max(base_w, base_h)

    cell_w = sheet_w / cols
    cell_h = sheet_h / rows

    new_sheets = []
    total_input_pages = len(pages)

    for chunk_start in range(0, total_input_pages, n):
        chunk = pages[chunk_start : chunk_start + n]
        new_sheet = PageObject.create_blank_page(width=sheet_w, height=sheet_h)

        for idx, page in enumerate(chunk):
            col = idx % cols
            row = idx // cols

            y_offset = sheet_h - (row + 1) * cell_h
            x_offset = col * cell_w

            pw = float(page.mediabox.width)
            ph = float(page.mediabox.height)
            rot = getattr(page, 'rotation', 0) or 0
            if rot in (90, 270):
                pw, ph = ph, pw

            scale = min(cell_w / pw, cell_h / ph) * 0.95
            scaled_w = pw * scale
            scaled_h = ph * scale

            pos_x = x_offset + (cell_w - scaled_w) / 2.0
            pos_y = y_offset + (cell_h - scaled_h) / 2.0

            t = Transformation().scale(scale, scale).translate(pos_x, pos_y)
            new_sheet.merge_transformed_page(page, t)

        new_sheets.append(new_sheet)

    return new_sheets


def apply_poster_to_pages(pages, poster_str, paper_size_name="A4"):
    """
    Divide cada página em um mosaico de folhas (Modo Cartaz / Poster 2x2, 3x3 ou 4x4).
    """
    if not poster_str or poster_str == "Desativado":
        return pages, 1, 1

    if "2x2" in poster_str:
        cols, rows = 2, 2
    elif "3x3" in poster_str:
        cols, rows = 3, 3
    elif "4x4" in poster_str:
        cols, rows = 4, 4
    else:
        return pages, 1, 1

    from pypdf import PageObject, Transformation

    base_w, base_h = get_paper_size_pts(paper_size_name)
    poster_w = cols * base_w
    poster_h = rows * base_h

    new_sheets = []
    for page in pages:
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)
        rot = getattr(page, 'rotation', 0) or 0
        if rot in (90, 270):
            pw, ph = ph, pw

        scale = min(poster_w / pw, poster_h / ph)
        scaled_w = pw * scale
        scaled_h = ph * scale

        offset_x = (poster_w - scaled_w) / 2.0
        offset_y = (poster_h - scaled_h) / 2.0

        for r in range(rows):
            for c in range(cols):
                sheet = PageObject.create_blank_page(width=base_w, height=base_h)
                tx = offset_x - (c * base_w)
                ty = offset_y - ((rows - 1 - r) * base_h)

                t = Transformation().scale(scale, scale).translate(tx, ty)
                if rot != 0:
                    p_copy = PageObject.create_blank_page(width=pw, height=ph)
                    p_copy.merge_page(page)
                    sheet.merge_transformed_page(p_copy, t)
                else:
                    sheet.merge_transformed_page(page, t)

                new_sheets.append(sheet)

    return new_sheets, cols, rows


def fit_page_to_orientation_and_scale(page, target_orientation, scaling_mode="Ajustar à Folha (Fit)", custom_scale=100, paper_size_name="A4", margin_mm=5.0):
    """
    Ajusta a página do PDF aplicando orientação e modo de dimensionamento.
    """
    from pypdf import PageObject, Transformation

    rot = getattr(page, 'rotation', 0) or 0
    w_doc = float(page.mediabox.width)
    h_doc = float(page.mediabox.height)

    if rot in (90, 270):
        w_doc, h_doc = h_doc, w_doc

    is_portrait = (h_doc >= w_doc)
    base_w, base_h = get_paper_size_pts(paper_size_name)

    if "Paisagem" in target_orientation:
        target_w = max(base_w, base_h)
        target_h = min(base_w, base_h)
    elif "Retrato" in target_orientation:
        target_w = min(base_w, base_h)
        target_h = max(base_w, base_h)
    else:  # Automático
        if is_portrait:
            target_w = min(base_w, base_h)
            target_h = max(base_w, base_h)
        else:
            target_w = max(base_w, base_h)
            target_h = min(base_w, base_h)

    margin_pt = margin_mm * 2.83465
    printable_w = max(10.0, target_w - (2 * margin_pt))
    printable_h = max(10.0, target_h - (2 * margin_pt))

    if scaling_mode == "Escala Personalizada":
        scale = max(0.1, min(4.0, float(custom_scale) / 100.0))
    elif scaling_mode == "Tamanho Real (100%)":
        if w_doc > printable_w or h_doc > printable_h:
            scale = min(printable_w / w_doc, printable_h / h_doc)
        else:
            scale = 1.0
    elif scaling_mode == "Reduzir Páginas Grandes":
        if w_doc > printable_w or h_doc > printable_h:
            scale = min(printable_w / w_doc, printable_h / h_doc)
        else:
            scale = 1.0
    else:  # "Ajustar à Folha (Fit)"
        scale = min(printable_w / w_doc, printable_h / h_doc)

    new_page = PageObject.create_blank_page(width=target_w, height=target_h)

    scaled_w = w_doc * scale
    scaled_h = h_doc * scale

    tx = (target_w - scaled_w) / 2.0
    ty = (target_h - scaled_h) / 2.0

    transform = Transformation().scale(scale, scale).translate(tx, ty)

    if rot != 0:
        page.rotate(-rot)

    page.add_transformation(transform)
    new_page.merge_page(page)
    return new_page, scale, target_w, target_h


class PreviewWorkerThread(QThread):
    preview_ready = pyqtSignal(str, int, int, float, float, float, str)
    pdf_converted = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, file_path, page_num=1, orientation="Automático (Padrão)", scaling_mode="Ajustar à Folha (Fit)", custom_scale=100, paper_size="A4", page_range="", nup="1 por folha", poster="Desativado", cached_pdf=""):
        super().__init__()
        self.file_path = file_path
        self.page_num = page_num
        self.orientation = orientation
        self.scaling_mode = scaling_mode
        self.custom_scale = custom_scale
        self.paper_size = paper_size
        self.page_range = page_range
        self.nup = nup
        self.poster = poster
        self.cached_pdf = cached_pdf

    def run(self):
        tmp_files = []
        try:
            current_file = self.cached_pdf if (self.cached_pdf and os.path.exists(self.cached_pdf)) else self.file_path

            if not current_file.lower().endswith('.pdf'):
                out_dir = "/tmp"
                subprocess.check_call(["libreoffice", "--headless", "--convert-to", "pdf", current_file, "--outdir", out_dir])
                base = os.path.splitext(os.path.basename(current_file))[0]
                converted = os.path.join(out_dir, f"{base}.pdf")
                if os.path.exists(converted):
                    current_file = converted
                    self.pdf_converted.emit(converted)
                else:
                    self.error.emit("Falha ao converter arquivo para pré-visualização.")
                    return

            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(current_file)
            total_doc_pages = len(reader.pages)

            if total_doc_pages == 0:
                self.error.emit("O documento não possui páginas válidas.")
                return

            selected_indices = parse_page_range(self.page_range, total_doc_pages)
            selected_pages = [reader.pages[i] for i in selected_indices if i < total_doc_pages]

            if not selected_pages:
                self.error.emit("Nenhuma página válida no intervalo especificado.")
                return

            if self.nup != "1 por folha":
                selected_pages = apply_nup_to_pages(selected_pages, self.nup, self.paper_size)

            total_base_pages = len(selected_pages)
            if total_base_pages == 0:
                self.error.emit("Erro ao calcular páginas do documento.")
                return

            poster_info = ""

            if self.poster and self.poster != "Desativado":
                cols, rows = 2, 2
                if "3x3" in self.poster:
                    cols, rows = 3, 3
                elif "4x4" in self.poster:
                    cols, rows = 4, 4

                sheets_per_page = cols * rows
                total_pages = total_base_pages * sheets_per_page
                preview_page_num = max(1, min(self.page_num, total_pages))

                base_page_idx = (preview_page_num - 1) // sheets_per_page
                tile_idx = (preview_page_num - 1) % sheets_per_page
                tile_row = (tile_idx // cols) + 1
                tile_col = (tile_idx % cols) + 1

                base_page = selected_pages[base_page_idx]
                poster_sheets, _, _ = apply_poster_to_pages([base_page], self.poster, self.paper_size)

                target_tile = poster_sheets[tile_idx]
                poster_info = f"Cartaz {cols}x{rows} [Linha {tile_row}, Coluna {tile_col}] (Pág. {base_page_idx + 1}/{total_base_pages})"

                target_page, calc_scale, tw, th = fit_page_to_orientation_and_scale(
                    target_tile,
                    target_orientation=self.orientation,
                    scaling_mode=self.scaling_mode,
                    custom_scale=self.custom_scale,
                    paper_size_name=self.paper_size
                )
                calc_scale = calc_scale * cols * 100.0
            else:
                total_pages = total_base_pages
                preview_page_num = max(1, min(self.page_num, total_pages))

                is_default_orient = ("Automático" in self.orientation)
                is_default_scale = (self.scaling_mode == "Ajustar à Folha (Fit)")
                is_full_doc = (not self.page_range or not self.page_range.strip())

                if self.nup == "1 por folha" and is_default_orient and is_default_scale and is_full_doc:
                    import glob
                    out_prefix = f"/tmp/prev_fast_{os.getpid()}_{preview_page_num}"
                    cmd = ["pdftoppm", "-jpeg", "-jpegopt", "quality=85", "-r", "90", "-f", str(preview_page_num), "-l", str(preview_page_num), current_file, out_prefix]
                    subprocess.check_call(cmd)
                    matching = glob.glob(f"{out_prefix}*.jpg") or glob.glob(f"{out_prefix}*.jpeg")
                    if matching:
                        img_path = matching[0]
                        p = reader.pages[preview_page_num - 1]
                        tw = float(p.mediabox.width)
                        th = float(p.mediabox.height)
                        rot = getattr(p, 'rotation', 0) or 0
                        if rot in (90, 270):
                            tw, th = th, tw
                        paper_w_mm = tw * 0.352778
                        paper_h_mm = th * 0.352778
                        self.preview_ready.emit(img_path, preview_page_num, total_pages, 100.0, paper_w_mm, paper_h_mm, "")
                        return

                target_page, calc_scale, tw, th = fit_page_to_orientation_and_scale(
                    selected_pages[preview_page_num - 1],
                    target_orientation=self.orientation,
                    scaling_mode=self.scaling_mode,
                    custom_scale=self.custom_scale,
                    paper_size_name=self.paper_size
                )
                calc_scale = calc_scale * 100.0

            orient_tmp = f"/tmp/prev_orient_{os.getpid()}.pdf"
            writer = PdfWriter()
            writer.add_page(target_page)

            with open(orient_tmp, "wb") as f:
                writer.write(f)
            current_file = orient_tmp
            tmp_files.append(orient_tmp)

            import glob
            out_prefix = f"/tmp/prev_{os.getpid()}_{preview_page_num}"
            cmd = ["pdftoppm", "-jpeg", "-jpegopt", "quality=85", "-r", "90", "-f", "1", "-l", "1", current_file, out_prefix]
            subprocess.check_call(cmd)

            matching = glob.glob(f"{out_prefix}*.jpg") or glob.glob(f"{out_prefix}*.jpeg") or glob.glob(f"{out_prefix}*.png")
            if matching:
                img_path = matching[0]
                paper_w_mm = tw * 0.352778
                paper_h_mm = th * 0.352778
                self.preview_ready.emit(img_path, preview_page_num, total_pages, calc_scale, paper_w_mm, paper_h_mm, poster_info)
            else:
                self.error.emit("Erro ao gerar imagem de pré-visualização.")

        except Exception as e:
            self.error.emit(str(e))
        finally:
            for f in tmp_files:
                if f.endswith('.pdf') and os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass


class PrintWorkerThread(QThread):
    progress = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, file_path, printer, copies, paper_size, orientation, scaling_mode, custom_scale, duplex, color, nup, poster, page_range, tray="Automática (Padrão)", save_path="", cups_server=""):
        super().__init__()
        self.file_path = file_path
        self.printer = printer
        self.copies = copies
        self.paper_size = paper_size
        self.orientation = orientation
        self.scaling_mode = scaling_mode
        self.custom_scale = custom_scale
        self.duplex = duplex
        self.color = color
        self.nup = nup
        self.poster = poster
        self.page_range = page_range
        self.tray = tray
        self.save_path = save_path
        self.cups_server = cups_server

    def run(self):
        tmp_files = []
        current_file = self.file_path

        try:
            if not current_file.lower().endswith('.pdf'):
                self.progress.emit("Convertendo documento para PDF via LibreOffice...")
                out_dir = "/tmp"
                subprocess.check_call(["libreoffice", "--headless", "--convert-to", "pdf", current_file, "--outdir", out_dir])
                base = os.path.splitext(os.path.basename(current_file))[0]
                converted = os.path.join(out_dir, f"{base}.pdf")
                if os.path.exists(converted):
                    current_file = converted
                    tmp_files.append(converted)
                else:
                    raise Exception("Falha na conversão para PDF pelo LibreOffice.")

            if self.page_range and self.page_range.strip():
                self.progress.emit("Filtrando intervalo de páginas...")
                from pypdf import PdfReader, PdfWriter
                reader = PdfReader(current_file)
                total_pages = len(reader.pages)
                selected_indices = parse_page_range(self.page_range, total_pages)

                if len(selected_indices) < total_pages:
                    range_tmp = f"/tmp/range_{os.getpid()}.pdf"
                    writer = PdfWriter()
                    for idx in selected_indices:
                        writer.add_page(reader.pages[idx])
                    with open(range_tmp, "wb") as f:
                        writer.write(f)
                    current_file = range_tmp
                    tmp_files.append(range_tmp)

            if self.nup and self.nup != "1 por folha":
                self.progress.emit("Agrupando páginas (N-Up)...")
                from pypdf import PdfReader, PdfWriter
                reader = PdfReader(current_file)
                nup_sheets = apply_nup_to_pages(reader.pages, self.nup, self.paper_size)
                nup_tmp = f"/tmp/nup_{os.getpid()}.pdf"
                writer = PdfWriter()
                for sheet in nup_sheets:
                    writer.add_page(sheet)
                with open(nup_tmp, "wb") as f:
                    writer.write(f)
                current_file = nup_tmp
                tmp_files.append(nup_tmp)

            if self.poster and self.poster != "Desativado":
                self.progress.emit("Gerando modo cartaz (poster)...")
                from pypdf import PdfReader, PdfWriter
                reader = PdfReader(current_file)
                poster_sheets, cols, rows = apply_poster_to_pages(reader.pages, self.poster, self.paper_size)
                poster_tmp = f"/tmp/poster_{os.getpid()}.pdf"
                writer = PdfWriter()
                for sheet in poster_sheets:
                    writer.add_page(sheet)
                with open(poster_tmp, "wb") as f:
                    writer.write(f)
                current_file = poster_tmp
                tmp_files.append(poster_tmp)

            self.progress.emit("Ajustando orientação e escala da página...")
            from pypdf import PdfWriter, PdfReader
            orient_tmp = f"/tmp/orient_{os.getpid()}.pdf"
            writer = PdfWriter()
            reader = PdfReader(current_file)

            for page in reader.pages:
                new_page, _, _, _ = fit_page_to_orientation_and_scale(
                    page,
                    target_orientation=self.orientation,
                    scaling_mode=self.scaling_mode,
                    custom_scale=self.custom_scale,
                    paper_size_name=self.paper_size
                )
                writer.add_page(new_page)

            with open(orient_tmp, "wb") as f:
                writer.write(f)

            current_file = orient_tmp
            tmp_files.append(orient_tmp)

            if self.copies > 1:
                self.progress.emit("Duplicando cópias do documento...")
                from pypdf import PdfWriter, PdfReader
                copies_tmp = f"/tmp/copies_{os.getpid()}.pdf"
                writer = PdfWriter()
                reader = PdfReader(current_file)
                for _ in range(self.copies):
                    for page in reader.pages:
                        writer.add_page(page)
                with open(copies_tmp, "wb") as f:
                    writer.write(f)
                current_file = copies_tmp
                tmp_files.append(copies_tmp)

            if self.printer == "Salvar como PDF":
                if self.save_path:
                    self.progress.emit("Salvando arquivo PDF...")
                    shutil.copy(current_file, self.save_path)
                    self.finished_signal.emit(True, f"Arquivo salvo com sucesso em:\n{self.save_path}")
                else:
                    self.finished_signal.emit(False, "Caminho de salvamento não especificado.")
            else:
                self.progress.emit(f"Enviando trabalho para a impressora {self.printer}...")
                if sys.platform == "win32":
                    try:
                        # Envio nativo no Windows usando comando do sistema
                        ps_cmd = f'Start-Process -FilePath "{current_file}" -Verb PrintTo -ArgumentList "\"{self.printer}\"" -PassThru | Wait-Process'
                        subprocess.check_call(["powershell", "-NoProfile", "-Command", ps_cmd])
                        self.finished_signal.emit(True, f"Enviado com sucesso para a impressora '{self.printer}'!")
                    except Exception as win_err:
                        self.finished_signal.emit(False, f"Falha ao enviar impressão no Windows:\n{str(win_err)}")
                else:
                    lp_args = ["lp"]
                    if self.cups_server:
                        lp_args.extend(["-h", self.cups_server])
                    lp_args.extend(["-d", self.printer])

                    if "Borda Maior" in self.duplex:
                        lp_args.extend(["-o", "sides=two-sided-long-edge"])
                    elif "Borda Menor" in self.duplex:
                        lp_args.extend(["-o", "sides=two-sided-short-edge"])
                    else:
                        lp_args.extend(["-o", "sides=one-sided"])

                    if "Preto" in self.color:
                        lp_args.extend(["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"])
                    else:
                        lp_args.extend(["-o", "print-color-mode=color"])

                    if self.tray and self.tray != "Automática (Padrão)" and self.tray != "Auto":
                        if "Bandeja 1" in self.tray or self.tray in ["Tray1", "tray-1", "TRAY1"]:
                            lp_args.extend(["-o", f"InputSlot={self.tray}", "-o", "media-source=tray-1"])
                        elif "Bandeja 2" in self.tray or self.tray in ["Tray2", "tray-2", "TRAY2"]:
                            lp_args.extend(["-o", f"InputSlot={self.tray}", "-o", "media-source=tray-2"])
                        elif "Bandeja 3" in self.tray or self.tray in ["Tray3", "tray-3", "TRAY3"]:
                            lp_args.extend(["-o", f"InputSlot={self.tray}", "-o", "media-source=tray-3"])
                        elif "Manual" in self.tray or self.tray in ["Manual", "MANUAL", "manual"]:
                            lp_args.extend(["-o", f"InputSlot={self.tray}", "-o", "media-source=manual"])
                        elif "Envelope" in self.tray or self.tray in ["Envelope", "ENVELOPE", "envelope"]:
                            lp_args.extend(["-o", f"InputSlot={self.tray}", "-o", "media-source=envelope"])
                        else:
                            lp_args.extend(["-o", f"InputSlot={self.tray}", "-o", f"media-source={self.tray}"])

                    media_map = {"A4": "A4", "Carta (Letter)": "Letter", "A3": "A3", "A5": "A5", "Ofício (Legal)": "Legal"}
                    media_name = media_map.get(self.paper_size, "A4")
                    lp_args.extend(["-o", f"media={media_name}"])
                    lp_args.append(current_file)
                    subprocess.check_call(lp_args)
                    self.finished_signal.emit(True, f"Enviado com sucesso para a impressora '{self.printer}'!")

        except Exception as e:
            self.finished_signal.emit(False, f"Ocorreu um erro no processamento:\n{str(e)}")
        finally:
            for f in tmp_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass


def get_ssl_context():
    """
    Retorna um contexto SSL configurado para tentar verificar certificados de CA do sistema,
    ou fallback com certificados de certifi / padrão do sistema.
    """
    ctx = None
    for ca_path in [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/ca-bundle.pem",
        "/etc/ssl/cert.pem"
    ]:
        if os.path.exists(ca_path):
            try:
                ctx = ssl.create_default_context(cafile=ca_path)
                break
            except Exception:
                pass
    if ctx is None:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
    return ctx


def safe_urlopen(req_or_url, timeout=30):
    """
    Abre uma requisição HTTP/HTTPS de forma segura e resiliente a falhas
    de certificados locais em ambientes AppImage, empacotados ou com certificados customizados.
    """
    if isinstance(req_or_url, str):
        req = urllib.request.Request(req_or_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    else:
        req = req_or_url

    try:
        ctx = get_ssl_context()
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        return opener.open(req, timeout=timeout)
    except Exception as e:
        err_str = str(e).lower()
        if "certificate" in err_str or "ssl" in err_str or "verify_failed" in err_str:
            unverified_ctx = ssl._create_unverified_context()
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=unverified_ctx))
            return opener.open(req, timeout=timeout)
        raise


class UpdateCheckerThread(QThread):
    checked = pyqtSignal(bool, str, dict, str)

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version

    def run(self):
        try:
            url = "https://api.github.com/repos/LucasTelesEriceira/gerenciador-impressoes/releases/latest"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with safe_urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8', errors='replace'))
            latest_version = data.get("tag_name", "")

            clean_latest = latest_version.lstrip("v").strip()
            clean_curr = self.current_version.lstrip("v").strip()
            has_update = bool(clean_latest and clean_latest != clean_curr)

            self.checked.emit(has_update, latest_version, data, "")
        except Exception as e:
            self.checked.emit(False, "", {}, str(e))


class UpdateDownloadThread(QThread):
    progress = pyqtSignal(int, int)  # (bytes_downloaded, total_bytes)
    finished = pyqtSignal(str)       # local_dest_path
    error = pyqtSignal(str)

    def __init__(self, download_url, dest_path):
        super().__init__()
        self.download_url = download_url
        self.dest_path = dest_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            req = urllib.request.Request(self.download_url, headers={'User-Agent': 'Mozilla/5.0'})
            response = safe_urlopen(req, timeout=30)
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 64 * 1024

            with open(self.dest_path, 'wb') as f:
                while True:
                    if self._is_cancelled:
                        return
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.progress.emit(downloaded, total_size)

            if not self._is_cancelled:
                self.finished.emit(self.dest_path)
        except Exception as e:
            self.error.emit(str(e))


class DropZoneFrame(QFrame):
    clicked = pyqtSignal()
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

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
                    self.file_dropped.emit(path)
                    event.acceptProposedAction()


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
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Data/Hora", "Arquivo", "Impressora", "Cópias", "Papel", "Status"])
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

            status_item = QTableWidgetItem(entry.get("status", ""))
            if entry.get("status") == "Sucesso":
                status_item.setForeground(Qt.darkGreen)
            else:
                status_item.setForeground(Qt.red)
            self.table.setItem(row, 5, status_item)

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
                    writer = csv.DictWriter(f, fieldnames=["timestamp", "filename", "file_path", "printer", "copies", "paper", "color", "duplex", "status", "details"])
                    writer.writeheader()
                    writer.writerows(self.history_data)
                QMessageBox.information(self, "Sucesso", f"Histórico exportado para:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Falha ao exportar CSV:\n{str(e)}")


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

        # Badge visual de status da conexão
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

        self.chk_keep_history = QCheckBox("Salvar histórico de arquivos impressos")
        self.chk_keep_history.setChecked(self.settings.get("keep_history", True))
        layout_general.addRow("Histórico:", self.chk_keep_history)

        self.sp_max_history = QSpinBox()
        self.sp_max_history.setRange(10, 1000)
        self.sp_max_history.setValue(int(self.settings.get("max_history_entries", 100)))
        layout_general.addRow("Máx. Registros do Histórico:", self.sp_max_history)

        main_layout.addWidget(group_general)

        # ---------------------------------------------------------------------
        # Botões Salvar / Cancelar
        # ---------------------------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_and_close)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self.setLayout(main_layout)

        # Checa status inicial da conexão
        self.refresh_initial_status()

    def set_status_badge(self, text, status_type):
        """Atualiza o badge de status com estilo consistente com o tema do sistema."""
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
        self.settings["keep_history"] = self.chk_keep_history.isChecked()
        self.settings["max_history_entries"] = self.sp_max_history.value()

        save_settings(self.settings)
        self.main_app.settings = self.settings
        self.main_app.apply_cups_environment()
        self.main_app.load_printers()
        self.accept()
        QMessageBox.information(self, "Sucesso", "Configurações salvas com sucesso!")


class ServerManagerDialog(QDialog):
    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        if hasattr(main_app, "settings"):
            self.settings = main_app.settings
        else:
            self.settings = main_app if isinstance(main_app, dict) else load_settings()

        self.setWindowTitle("Central do Servidor CUPS e Instalador de Drivers")
        self.resize(720, 560)
        self.process = None

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        tabs = QTabWidget()

        # =========================================================================
        # ABA 1: Servidor CUPS Local (Administração da Máquina Servidora)
        # =========================================================================
        tab_server = QWidget()
        layout_server = QVBoxLayout(tab_server)
        layout_server.setSpacing(10)

        server_info = QLabel(
            "<b>Painel de Administração do Servidor de Impressão CUPS:</b><br>"
            "Utilize esta ferramenta no computador que atua (ou atuará) como <b>Servidor Central de Impressão</b> da escola ou escritório. "
            "Aqui você ativa o compartilhamento na rede local e verifica o estado dos daemons CUPS e Avahi."
        )
        server_info.setWordWrap(True)
        server_info.setStyleSheet("border: 1px solid #94A3B8; padding: 10px; border-radius: 6px;")
        layout_server.addWidget(server_info)

        # Grupo de Status dos Daemons
        group_status = QGroupBox("Estado dos Serviços e Compartilhamento de Rede")
        form_status = QFormLayout(group_status)
        form_status.setVerticalSpacing(8)

        self.lbl_cups_service = QLabel("Consultando...")
        self.lbl_avahi_service = QLabel("Consultando...")
        self.lbl_sharing_status = QLabel("Consultando...")

        form_status.addRow("Serviço CUPS (cups.service):", self.lbl_cups_service)
        form_status.addRow("Descoberta de Rede (avahi-daemon):", self.lbl_avahi_service)
        form_status.addRow("Compartilhamento na Rede:", self.lbl_sharing_status)

        self.btn_refresh_status = QPushButton("🔄 Atualizar Status")
        self.btn_refresh_status.clicked.connect(self.check_local_server_status)
        form_status.addRow("", self.btn_refresh_status)

        layout_server.addWidget(group_status)

        # Grupo de Ações Administrativas
        group_actions = QGroupBox("Ações Administrativas (Requer senha de Administrador)")
        layout_actions = QVBoxLayout(group_actions)
        layout_actions.setSpacing(8)

        btns_admin_layout = QHBoxLayout()
        self.btn_enable_server = QPushButton("🚀 Ativar Modo Servidor na Rede")
        self.btn_enable_server.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 8px 12px; border-radius: 4px;")
        self.btn_enable_server.clicked.connect(self.enable_network_server)
        btns_admin_layout.addWidget(self.btn_enable_server)

        self.btn_restart_services = QPushButton("🔄 Reiniciar CUPS e Avahi")
        self.btn_restart_services.clicked.connect(self.restart_cups_services)
        btns_admin_layout.addWidget(self.btn_restart_services)

        self.btn_disable_server = QPushButton("🔒 Desativar Rede (Apenas Local)")
        self.btn_disable_server.clicked.connect(self.disable_network_server)
        btns_admin_layout.addWidget(self.btn_disable_server)

        layout_actions.addLayout(btns_admin_layout)
        layout_server.addWidget(group_actions)

        # Grupo de Filas Locais
        group_printers = QGroupBox("Impressoras Locais Instaladas nesta Máquina")
        layout_printers = QVBoxLayout(group_printers)
        self.txt_local_printers = QTextEdit()
        self.txt_local_printers.setReadOnly(True)
        self.txt_local_printers.setMaximumHeight(100)
        self.txt_local_printers.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout_printers.addWidget(self.txt_local_printers)
        layout_server.addWidget(group_printers)

        tabs.addTab(tab_server, "🖥️ Servidor CUPS Local")

        # =========================================================================
        # ABA 2: Instalação de Impressoras via Script
        # =========================================================================
        tab_script = QWidget()
        layout_script = QVBoxLayout(tab_script)
        layout_script.setSpacing(10)

        if sys.platform.startswith("linux"):
            script_info = QLabel(
                "<b>Instalação Automatizada de Drivers e Impressoras:</b><br>"
                "Baixe e execute scripts de instalação (.sh) para configurar impressoras automaticamente nesta máquina. "
                "Você pode utilizar a URL do GitHub ou selecionar um arquivo de script local."
            )
            script_info.setWordWrap(True)
            layout_script.addWidget(script_info)

            form_script = QFormLayout()
            self.txt_url = QLineEdit(self.settings.get("script_url", "https://raw.githubusercontent.com/LucasTelesEriceira/gerenciador-impressoes/main/instalar_impressoras.sh"))
            form_script.addRow("URL do Script (GitHub / Web):", self.txt_url)

            btn_browse_script = QPushButton("📁 Escolher Arquivo de Script Local (.sh)...")
            btn_browse_script.clicked.connect(self.browse_local_script)
            form_script.addRow("Ou arquivo local:", btn_browse_script)

            layout_script.addLayout(form_script)

            self.btn_run = QPushButton("🚀 Executar Script de Instalação")
            self.btn_run.setStyleSheet("background-color: #10B981; color: white; font-weight: bold; padding: 8px; border-radius: 4px;")
            self.btn_run.clicked.connect(self.run_installation)
            layout_script.addWidget(self.btn_run)

            self.log_console = QTextEdit()
            self.log_console.setReadOnly(True)
            self.log_console.setStyleSheet("background-color: #0F172A; color: #38BDF8; font-family: monospace; font-size: 11px; border-radius: 4px;")
            self.log_console.setPlaceholderText("A saída da execução do script aparecerá aqui...")
            layout_script.addWidget(self.log_console)
        else:
            win_notice = QLabel(
                "<h3>ℹ️ Gerenciamento no Windows</h3>"
                "<p>A execução de scripts Bash (.sh) com <code>pkexec</code> é exclusiva para sistemas Linux.</p>"
                "<p>No Windows, configure impressoras pelo Painel de Controle ou utilize as impressoras compartilhadas da rede.</p>"
            )
            win_notice.setWordWrap(True)
            layout_script.addWidget(win_notice)
            layout_script.addStretch()

        tabs.addTab(tab_script, "📥 Instalar via Script")

        main_layout.addWidget(tabs)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        main_layout.addWidget(btn_close)

        self.setLayout(main_layout)

        # Checa status ao inicializar
        self.check_local_server_status()

    def check_local_server_status(self):
        if not sys.platform.startswith("linux"):
            self.lbl_cups_service.setText("Não aplicável (Windows)")
            self.lbl_avahi_service.setText("Não aplicável (Windows)")
            self.lbl_sharing_status.setText("Não aplicável (Windows)")
            return

        # 1. CUPS Service
        try:
            out_cups = subprocess.check_output(["systemctl", "is-active", "cups"], text=True, stderr=subprocess.DEVNULL).strip()
            if out_cups == "active":
                self.lbl_cups_service.setText("🟢 <b>Ativo</b> (Em execução)")
            else:
                self.lbl_cups_service.setText(f"⚪ <b>{out_cups.capitalize()}</b>")
        except Exception:
            self.lbl_cups_service.setText("🔴 <b>Inativo / Não instalado</b>")

        # 2. Avahi Daemon
        try:
            out_avahi = subprocess.check_output(["systemctl", "is-active", "avahi-daemon"], text=True, stderr=subprocess.DEVNULL).strip()
            if out_avahi == "active":
                self.lbl_avahi_service.setText("🟢 <b>Ativo</b> (Descoberta na rede em funcionamento)")
            else:
                self.lbl_avahi_service.setText(f"⚪ <b>{out_avahi.capitalize()}</b>")
        except Exception:
            self.lbl_avahi_service.setText("🔴 <b>Inativo / Não instalado</b>")

        # 3. Sharing status via cupsctl
        try:
            out_ctl = subprocess.check_output(["cupsctl"], text=True, stderr=subprocess.DEVNULL)
            is_shared = "_share_printers=1" in out_ctl and "_remote_any=1" in out_ctl
            if is_shared:
                self.lbl_sharing_status.setText("🟢 <b>Ativado</b> (Aceita conexões da rede local)")
            else:
                self.lbl_sharing_status.setText("⚪ <b>Desativado</b> (Apenas conexões locais)")
        except Exception:
            self.lbl_sharing_status.setText("⚪ Indisponível")

        # 4. Lista de impressoras locais
        try:
            out_lp = subprocess.check_output(["lpstat", "-p"], text=True, stderr=subprocess.DEVNULL).strip()
            if out_lp:
                self.txt_local_printers.setPlainText(out_lp)
            else:
                self.txt_local_printers.setPlainText("Nenhuma impressora configurada localmente nesta máquina.")
        except Exception:
            self.txt_local_printers.setPlainText("Não foi possível listar as impressoras locais.")

    def enable_network_server(self):
        if not sys.platform.startswith("linux"):
            return
        cmd = "cupsctl --remote-any --share-printers && systemctl enable --now cups avahi-daemon"
        self.execute_admin_command(cmd, "Ativação do Modo Servidor de Rede")

    def restart_cups_services(self):
        if not sys.platform.startswith("linux"):
            return
        cmd = "systemctl restart cups avahi-daemon"
        self.execute_admin_command(cmd, "Reinicialização dos Serviços CUPS e Avahi")

    def disable_network_server(self):
        if not sys.platform.startswith("linux"):
            return
        cmd = "cupsctl --no-remote-any --no-share-printers"
        self.execute_admin_command(cmd, "Desativação do Compartilhamento de Rede")

    def execute_admin_command(self, bash_cmd, action_name):
        full_cmd = f"pkexec bash -c '{bash_cmd}'"
        try:
            res = subprocess.run(full_cmd, shell=True, text=True, capture_output=True)
            if res.returncode == 0:
                QMessageBox.information(self, "Sucesso", f"{action_name} concluída com sucesso!")
                self.check_local_server_status()
            else:
                err = res.stderr.strip() or f"Código de saída: {res.returncode}"
                QMessageBox.warning(self, "Aviso", f"Não foi possível concluir a ação:\n{err}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao executar comando:\n{str(e)}")

    def browse_local_script(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar Script de Instalação", "", "Scripts Shell (*.sh);;Todos os Arquivos (*)")
        if path:
            self.txt_url.setText(path)

    def run_installation(self):
        if not sys.platform.startswith("linux"):
            return
        target = self.txt_url.text().strip()
        if not target:
            QMessageBox.warning(self, "Aviso", "Informe a URL ou o arquivo do script.")
            return

        self.settings["script_url"] = target
        save_settings(self.settings)

        self.log_console.clear()
        self.btn_run.setEnabled(False)

        if target.startswith("http://") or target.startswith("https://"):
            self.log_console.append(f"[*] Baixando e iniciando script de: {target}\n")
            script_tmp = f"/tmp/install_printers_{os.getpid()}.sh"
            cmd = f"curl -sSL '{target}' -o '{script_tmp}' && chmod +x '{script_tmp}' && pkexec '{script_tmp}'"
        else:
            self.log_console.append(f"[*] Executando script local: {target}\n")
            cmd = f"chmod +x '{target}' && pkexec '{target}'"

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.on_finished)
        self.process.start("bash", ["-c", cmd])

    def on_stdout(self):
        if self.process:
            data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
            self.log_console.append(data)

    def on_stderr(self):
        if self.process:
            data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
            self.log_console.append(data)

    def on_finished(self, exit_code, exit_status):
        self.btn_run.setEnabled(True)
        if exit_code == 0:
            self.log_console.append("\n[✓] Processo concluído com sucesso!")
            self.check_local_server_status()
            if hasattr(self.main_app, "load_printers"):
                self.main_app.load_printers()
        else:
            self.log_console.append(f"\n[X] Processo finalizado com código de saída {exit_code}.")


# Alias para retrocompatibilidade
PrinterInstallerDialog = ServerManagerDialog


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
        except Exception:
            pass

    def cancel_selected_job(self):
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Aviso", "Selecione um trabalho da fila.")
            return
        row = selected[0].row()
        job_id = self.table.item(row, 0).text()

        reply = QMessageBox.question(self, "Cancelar Trabalho", f"Deseja realmente cancelar o trabalho '{job_id}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
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
                QMessageBox.critical(self, "Erro", f"Falha ao cancelar trabalho:\n{str(e)}")


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre o Gerenciador Avançado de Impressão")
        self.setFixedSize(500, 370)

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
            "• Suporte a PDF, Word (DOCX/DOC), LibreOffice (ODT), Planilhas (XLSX/XLS/ODS/CSV), Apresentações (PPTX/PPT/ODP) e Texto<br>"
            "• Integração nativa com o sistema ('Abrir com...') e lançadores de aplicativos<br>"
            "• Pré-visualização ultra-rápida (QThread + pdftoppm)<br>"
            "• Suporte a N-Up (slides por folha) e Modo Cartaz (Pôster)<br>"
            "• Gerenciamento completo de Servidor CUPS (local/remoto) e fila em tempo real<br>"
            "• Histórico de impressões com exportação CSV e reimpressão<br>"
            "• Atualizações automáticas seguras e integradas<br>"
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


class PrintManagerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.file_path = ""
        self.cached_pdf_path = ""
        self.current_page = 1
        self.total_pages = 1
        self.preview_worker = None
        self.print_worker = None
        self.update_worker = None
        self.current_preview_img = ""
        self.theme_mode = "system"
        self.settings = load_settings()
        self.initUI()
        if sys.platform.startswith("linux"):
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(800, lambda: self.integrate_with_system(silent=True))

    def apply_cups_environment(self):
        server = self.settings.get("cups_server", "").strip()
        port = self.settings.get("cups_port", 631)
        if server:
            target = f"{server}:{port}" if ":" not in server else server
            try:
                subprocess.check_call(['lpstat', '-h', target, '-r'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                os.environ["CUPS_SERVER"] = target
                return
            except Exception:
                pass
        if "CUPS_SERVER" in os.environ:
            del os.environ["CUPS_SERVER"]

    def initUI(self):
        self.setWindowTitle("Gerenciador Avançado de Impressão (Nativo + QThread)")
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(760, 480)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            target_w = min(1050, max(760, int(avail.width() * 0.92)))
            target_h = min(740, max(480, int(avail.height() * 0.88)))
            self.resize(target_w, target_h)
        else:
            self.resize(1050, 720)
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
        self.lbl_drop_title.setStyleSheet("font-size: 13px; font-weight: bold;")

        self.lbl_drop_sub = QLabel("ou clique para selecionar (PDF, Word, Planilhas, Slides, TXT)")
        self.lbl_drop_sub.setAlignment(Qt.AlignCenter)
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

        self.cb_printers = QComboBox()
        form_opts.addRow("Impressora:", self.cb_printers)

        self.sp_copies = QSpinBox()
        self.sp_copies.setRange(1, 999)
        form_opts.addRow("Quantidade (Cópias):", self.sp_copies)

        self.txt_page_range = QLineEdit()
        self.txt_page_range.setPlaceholderText("Ex: 1-5, 8, 11-13 (vazio = todas)")
        self.txt_page_range.editingFinished.connect(self.on_page_range_changed)
        form_opts.addRow("Páginas Específicas:", self.txt_page_range)

        self.cb_paper_size = QComboBox()
        self.cb_paper_size.addItems(["A4", "Carta (Letter)", "A3", "A5", "Ofício (Legal)"])
        self.cb_paper_size.setCurrentText(self.settings.get("default_paper", "A4"))
        self.cb_paper_size.currentIndexChanged.connect(self.on_setting_changed)
        form_opts.addRow("Tamanho do Papel:", self.cb_paper_size)

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

        self.cb_duplex = QComboBox()
        self.cb_duplex.addItems(["Apenas Frente", "Frente e Verso (Borda Maior)", "Frente e Verso (Borda Menor)"])
        form_opts.addRow("Frente e Verso:", self.cb_duplex)

        self.cb_color = QComboBox()
        self.cb_color.addItems(["Colorido (Padrão)", "Preto e Branco"])
        form_opts.addRow("Cores:", self.cb_color)

        self.cb_nup = QComboBox()
        self.cb_nup.addItems(["1 por folha", "2 por folha", "4 por folha", "6 por folha", "9 por folha", "16 por folha"])
        self.cb_nup.currentIndexChanged.connect(self.on_nup_changed)
        form_opts.addRow("Agrupar (Slides/N-Up):", self.cb_nup)

        self.cb_poster = QComboBox()
        self.cb_poster.addItems(["Desativado", "Cartaz 2x2 (4 folhas)", "Cartaz 3x3 (9 folhas)", "Cartaz 4x4 (16 folhas)"])
        self.cb_poster.currentIndexChanged.connect(self.on_poster_changed)
        form_opts.addRow("Modo Cartaz (Pôster):", self.cb_poster)

        # Política de expansão uniforme para que TODOS os inputs tenham a mesma largura perfeita
        for widget in [
            self.cb_printers, self.sp_copies, self.txt_page_range,
            self.cb_paper_size, self.cb_tray, self.cb_orientation,
            self.cb_scaling_mode, self.sp_custom_scale, self.cb_duplex,
            self.cb_color, self.cb_nup, self.cb_poster
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

        # Painel Fixo no Rodapé: Status, Progresso e Botão de Ação
        # Fica sempre visível e acessível sem precisar de rolagem
        bottom_panel = QVBoxLayout()
        bottom_panel.setContentsMargins(0, 4, 0, 0)
        bottom_panel.setSpacing(6)

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

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([450, 600])

        main_layout.addWidget(splitter)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # Inicializar impressoras e conexões de sinal APÓS criação de todos os componentes
        self.load_printers()
        self.cb_printers.currentIndexChanged.connect(self.on_printer_changed)

        self.apply_theme()
        self.setup_shortcuts()
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

    def on_printer_changed(self):
        if not hasattr(self, 'cb_color') or not hasattr(self, 'cb_printers'):
            return
        printer = self.cb_printers.currentText()
        server = self.settings.get("cups_server", "").strip()
        port = self.settings.get("cups_port", 631)
        target_server = f"{server}:{port}" if (server and ":" not in server) else server

        if not printer or printer == "Salvar como PDF":
            self.cb_color.setEnabled(True)
            self.cb_color.setToolTip("Selecione o modo de cor")
            self.update_trays(printer, target_server)
            return

        if is_monochrome_printer(printer, target_server):
            self.cb_color.setCurrentText("Preto e Branco")
            self.cb_color.setEnabled(False)
            self.cb_color.setToolTip("Impressora Monocromática (Preto e Branco) detectada automaticamente.")
        else:
            self.cb_color.setEnabled(True)
            self.cb_color.setToolTip("Selecione o modo de cor")

        self.update_trays(printer, target_server)

    def setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+O"), self, self.select_file)
        QShortcut(QKeySequence("Ctrl+W"), self, self.clear_selected_file)
        QShortcut(QKeySequence("Delete"), self, self.clear_selected_file)
        QShortcut(QKeySequence("Ctrl+P"), self, self.process_and_print)
        QShortcut(QKeySequence("Ctrl+R"), self, self.load_preview)
        QShortcut(QKeySequence("Ctrl+H"), self, self.open_history_dialog)
        QShortcut(QKeySequence("Ctrl+J"), self, self.open_queue_dialog)
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
            self.on_nup_changed()

    def clear_selected_file(self):
        self.file_path = ""
        self.cached_pdf_path = ""
        self.current_preview_img = ""
        self.current_page = 1
        self.total_pages = 1

        self.lbl_file.setText("Nenhum arquivo selecionado")
        self.lbl_drop_title.setText("Arraste e solte seu documento aqui")
        self.lbl_drop_sub.setText("ou clique para selecionar (PDF, Word, Planilhas, Slides, TXT)")
        self.lbl_preview.setPixmap(QPixmap())
        self.lbl_preview.setText("Selecione ou arraste um documento para visualizar a prévia")
        self.lbl_page_info.setText("Página 0 de 0")
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
            self.cb_orientation.setCurrentText(target_orient)

        if self.file_path:
            self.load_preview()

    def on_poster_changed(self):
        is_poster_active = (self.cb_poster.currentText() != "Desativado")
        if is_poster_active:
            self.cb_nup.blockSignals(True)
            self.cb_nup.setCurrentText("1 por folha")
            self.cb_nup.setEnabled(False)
            self.cb_nup.blockSignals(False)
        else:
            self.cb_nup.setEnabled(True)

        if self.file_path:
            self.load_preview()

    def on_setting_changed(self):
        if self.file_path:
            self.load_preview()

    def on_page_range_changed(self):
        self.current_page = 1
        if self.file_path:
            self.load_preview()

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

    def load_preview(self):
        if not self.file_path:
            return

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
        nup = self.cb_nup.currentText()
        poster = self.cb_poster.currentText()

        self.preview_worker = PreviewWorkerThread(
            self.file_path,
            self.current_page,
            orientation=orientation,
            scaling_mode=scaling_mode,
            custom_scale=custom_scale,
            paper_size=paper_size,
            page_range=page_range,
            nup=nup,
            poster=poster,
            cached_pdf=self.cached_pdf_path
        )
        self.preview_worker.preview_ready.connect(self.on_preview_ready)
        self.preview_worker.pdf_converted.connect(self.on_pdf_converted)
        self.preview_worker.error.connect(self.on_preview_error)
        self.preview_worker.start()

    def on_preview_ready(self, img_path, page_num, total_pages, calc_scale, paper_w_mm, paper_h_mm, poster_info=""):
        self.current_page = page_num
        self.total_pages = total_pages
        self.current_preview_img = img_path
        self.progress_bar.setVisible(False)

        pixmap = QPixmap(img_path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(self.scroll_preview.width() - 30, self.scroll_preview.height() - 30,
                                          Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_preview.setPixmap(scaled_pixmap)
        else:
            self.lbl_preview.setText("Falha ao carregar imagem da prévia.")

        self.lbl_page_info.setText(f"Folha {self.current_page} de {self.total_pages}")
        self.btn_prev_page.setEnabled(self.current_page > 1)
        self.btn_next_page.setEnabled(self.current_page < self.total_pages)

    def on_preview_error(self, err_msg):
        self.progress_bar.setVisible(False)
        self.lbl_preview.setText(f"Erro na prévia: {err_msg}")
        self.lbl_page_info.setText("Prévia indisponível")
        self.btn_prev_page.setEnabled(False)
        self.btn_next_page.setEnabled(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.current_preview_img and os.path.exists(self.current_preview_img):
            pixmap = QPixmap(self.current_preview_img)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(self.scroll_preview.width() - 30, self.scroll_preview.height() - 30,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_preview.setPixmap(scaled_pixmap)

    def process_and_print(self):
        if not self.file_path:
            QMessageBox.warning(self, "Aviso", "Selecione um documento primeiro!")
            return

        printer = self.cb_printers.currentText()
        copies = self.sp_copies.value()
        paper_size = self.cb_paper_size.currentText()
        tray = self.cb_tray.currentData() or self.cb_tray.currentText()
        orientation = self.cb_orientation.currentText()
        scaling_mode = self.cb_scaling_mode.currentText()
        custom_scale = self.sp_custom_scale.value()
        duplex = self.cb_duplex.currentText()
        color = self.cb_color.currentText()
        nup = self.cb_nup.currentText()
        poster = self.cb_poster.currentText()
        page_range = self.txt_page_range.text().strip()

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

        server = self.settings.get("cups_server", "").strip()
        port = self.settings.get("cups_port", 631)
        target_server = f"{server}:{port}" if (server and ":" not in server) else server

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
            nup=nup,
            poster=poster,
            page_range=page_range,
            tray=tray,
            save_path=save_path,
            cups_server=target_server
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
            "color": self.cb_color.currentText(),
            "duplex": self.cb_duplex.currentText(),
            "status": "Sucesso" if success else "Erro",
            "details": message
        }
        save_history_entry(entry)

        if success:
            QMessageBox.information(self, "Sucesso", message)
        else:
            QMessageBox.critical(self, "Erro", message)

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
            progress_dlg.close()
            try:
                if is_linux:
                    os.replace(downloaded_file, current_appimage)
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
                script_path = os.path.abspath(__file__)
                exec_cmd = f'python3 "{script_path}"'

            # 2. Localizar o ícone do projeto
            icon_source = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
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


if __name__ == "__main__":
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
