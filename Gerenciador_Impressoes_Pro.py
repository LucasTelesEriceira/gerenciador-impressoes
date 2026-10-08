#!/usr/bin/env python3
import sys
import os
import subprocess
import shutil
import json
import urllib.request
import csv
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QComboBox, QSpinBox, QLineEdit,
                             QFileDialog, QMessageBox, QGroupBox, QFormLayout,
                             QScrollArea, QSplitter, QProgressBar, QFrame, QShortcut,
                             QMenuBar, QMenu, QAction, QDialog, QTableWidget, QTableWidgetItem,
                             QHeaderView, QTextEdit, QCheckBox, QDialogButtonBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QProcess
from PyQt5.QtGui import QPixmap, QImage, QKeySequence, QFont, QPalette

CURRENT_VERSION = "v1.1.0"
SETTINGS_DIR = os.path.expanduser("~/.config/gerenciador_impressoes_pro")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
HISTORY_FILE = os.path.join(SETTINGS_DIR, "history.json")


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
                output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env)
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
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env_local)
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

    return printers


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

        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env)
        
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

        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env)

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


class UpdateCheckerThread(QThread):
    checked = pyqtSignal(bool, str, dict, str)

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version

    def run(self):
        try:
            url = "https://api.github.com/repos/LucasTelesEriceira/gerenciador-impressoes/releases/latest"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            latest_version = data.get("tag_name", "")
            has_update = bool(latest_version and latest_version != self.current_version)
            self.checked.emit(has_update, latest_version, data, "")
        except Exception as e:
            self.checked.emit(False, "", {}, str(e))


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
                if ext in ['.pdf', '.docx', '.doc', '.odt', '.txt', '.rtf']:
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
        self.resize(520, 360)

        self.settings = load_settings()

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setVerticalSpacing(8)

        self.txt_cups_server = QLineEdit(self.settings.get("cups_server", ""))
        self.txt_cups_server.setPlaceholderText("Ex: localhost ou 192.168.1.100 (vazio = padrão)")
        form.addRow("Servidor CUPS (IP/Host):", self.txt_cups_server)

        self.sp_cups_port = QSpinBox()
        self.sp_cups_port.setRange(1, 65535)
        self.sp_cups_port.setValue(int(self.settings.get("cups_port", 631)))
        form.addRow("Porta CUPS:", self.sp_cups_port)

        self.cb_default_paper = QComboBox()
        self.cb_default_paper.addItems(["A4", "Carta (Letter)", "A3", "A5", "Ofício (Legal)"])
        self.cb_default_paper.setCurrentText(self.settings.get("default_paper", "A4"))
        form.addRow("Tamanho de Papel Padrão:", self.cb_default_paper)

        self.chk_keep_history = QCheckBox("Salvar histórico de arquivos impressos")
        self.chk_keep_history.setChecked(self.settings.get("keep_history", True))
        form.addRow("Histórico:", self.chk_keep_history)

        self.sp_max_history = QSpinBox()
        self.sp_max_history.setRange(10, 1000)
        self.sp_max_history.setValue(int(self.settings.get("max_history_entries", 100)))
        form.addRow("Máx. Registros do Histórico:", self.sp_max_history)

        self.txt_script_url = QLineEdit(self.settings.get("script_url", ""))
        self.txt_script_url.setPlaceholderText("URL do script .sh no GitHub")
        form.addRow("URL Script Impressoras (GitHub):", self.txt_script_url)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def save_and_close(self):
        self.settings["cups_server"] = self.txt_cups_server.text().strip()
        self.settings["cups_port"] = self.sp_cups_port.value()
        self.settings["default_paper"] = self.cb_default_paper.currentText()
        self.settings["keep_history"] = self.chk_keep_history.isChecked()
        self.settings["max_history_entries"] = self.sp_max_history.value()
        self.settings["script_url"] = self.txt_script_url.text().strip()

        save_settings(self.settings)
        self.main_app.settings = self.settings
        self.main_app.apply_cups_environment()
        self.main_app.load_printers()
        self.accept()
        QMessageBox.information(self, "Sucesso", "Configurações salvas com sucesso!")


class PrinterInstallerDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Assistente de Instalação de Impressoras (GitHub)")
        self.resize(680, 480)
        self.process = None

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        info_label = QLabel("Esta ferramenta permite baixar e executar o script de instalação de drivers e impressoras do GitHub.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        form = QFormLayout()
        self.txt_url = QLineEdit(self.settings.get("script_url", "https://raw.githubusercontent.com/LucasTelesEriceira/gerenciador-impressoes/main/instalar_impressoras.sh"))
        form.addRow("URL do Script (Bash):", self.txt_url)
        layout.addLayout(form)

        self.btn_run = QPushButton("🚀 Baixar e Executar Instalação")
        self.btn_run.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 8px; border-radius: 4px;")
        self.btn_run.clicked.connect(self.run_installation)
        layout.addWidget(self.btn_run)

        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #1E293B; color: #38BDF8; font-family: monospace; font-size: 11px;")
        layout.addWidget(self.log_console)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)

        self.setLayout(layout)

    def run_installation(self):
        url = self.txt_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Aviso", "Informe a URL do script do GitHub.")
            return

        self.log_console.clear()
        self.log_console.append(f"[*] Baixando e iniciando script de: {url}\n")
        self.btn_run.setEnabled(False)

        script_tmp = f"/tmp/install_printers_{os.getpid()}.sh"
        cmd = f"curl -sSL '{url}' -o '{script_tmp}' && chmod +x '{script_tmp}' && pkexec '{script_tmp}'"

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.on_finished)

        self.process.start("bash", ["-c", cmd])

    def on_stdout(self):
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
        self.log_console.append(data)

    def on_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
        self.log_console.append(data)

    def on_finished(self, exit_code, exit_status):
        self.btn_run.setEnabled(True)
        if exit_code == 0:
            self.log_console.append("\n[✓] Processo concluído com sucesso!")
        else:
            self.log_console.append(f"\n[X] Processo finalizado com código de saída {exit_code}.")


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
            "<p align='center'>Solução completa e de alta performance para gerenciamento e preparação de impressão no Linux.</p>"
            "<hr>"
            "<b>Destaques do Sistema:</b><br>"
            "• Pré-visualização ultra-rápida (QThread + pdftoppm)<br>"
            "• Suporte a N-Up (slides por folha) e Modo Cartaz (Poster)<br>"
            "• Suporte a Servidor CUPS remoto e controle de fila<br>"
            "• Histórico de impressões com exportação CSV e reimpressão<br>"
            "• Integração com scripts automatizados do GitHub<br>"
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
        self.apply_cups_environment()
        self.initUI()

    def apply_cups_environment(self):
        server = self.settings.get("cups_server", "").strip()
        port = self.settings.get("cups_port", 631)
        if server:
            target = f"{server}:{port}" if ":" not in server else server
            try:
                subprocess.check_call(['lpstat', '-h', target, '-r'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                os.environ["CUPS_SERVER"] = target
                return
            except Exception:
                pass
        if "CUPS_SERVER" in os.environ:
            del os.environ["CUPS_SERVER"]

    def initUI(self):
        self.setWindowTitle("Gerenciador Avançado de Impressão (Nativo + QThread)")
        self.resize(1050, 740)
        self.setAcceptDrops(True)

        self.create_menu_bar()

        central_widget = QWidget()
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # Painel Esquerdo (Controles e Opções)
        left_panel = QVBoxLayout()
        left_panel.setSpacing(12)

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

        self.lbl_drop_sub = QLabel("ou clique para selecionar (PDF, DOCX, ODT, TXT)")
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
        left_panel.addWidget(group_file)

        # 2. Configurações de Impressão
        group_opts = QGroupBox("2. Configurações de Impressão")
        form_opts = QFormLayout()
        form_opts.setContentsMargins(12, 14, 12, 12)
        form_opts.setVerticalSpacing(8)
        form_opts.setHorizontalSpacing(10)


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

        group_opts.setLayout(form_opts)
        left_panel.addWidget(group_opts)

        # Status & Barra de Progresso
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #0284C7; font-weight: bold;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        left_panel.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        left_panel.addWidget(self.progress_bar)

        # Botão Ação
        self.btn_action = QPushButton("PROCESSAR E IMPRIMIR (Ctrl+P)")
        self.btn_action.setMinimumHeight(44)
        self.btn_action.clicked.connect(self.process_and_print)
        left_panel.addWidget(self.btn_action)

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

        act_settings = QAction("&Preferências e Servidor CUPS...", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self.open_settings_dialog)
        menu_config.addAction(act_settings)

        menu_tools = menubar.addMenu("&Ferramentas")

        act_queue = QAction("Fila de Impressão &CUPS...", self)
        act_queue.setShortcut("Ctrl+J")
        act_queue.triggered.connect(self.open_queue_dialog)
        menu_tools.addAction(act_queue)

        act_installer = QAction("Instalar Impressoras (&Script GitHub)...", self)
        act_installer.triggered.connect(self.open_installer_dialog)
        menu_tools.addAction(act_installer)

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
        self.cb_printers.blockSignals(True)
        self.cb_printers.clear()

        printers = ["Salvar como PDF"]
        server = self.settings.get("cups_server", "").strip()
        port = self.settings.get("cups_port", 631)

        detected = get_system_printers(server, port)
        for p in detected:
            if p not in printers:
                printers.append(p)

        self.cb_printers.addItems(printers)
        default_printer = self.settings.get("default_printer", "Salvar como PDF")
        idx = self.cb_printers.findText(default_printer)
        if idx >= 0:
            self.cb_printers.setCurrentIndex(idx)
        self.cb_printers.blockSignals(False)

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
                if ext in ['.pdf', '.docx', '.doc', '.odt', '.txt', '.rtf']:
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
        self.lbl_drop_sub.setText("ou clique para selecionar (PDF, DOCX, ODT, TXT)")
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

        filters = "Todos os Arquivos (*);;Documentos PDF (*.pdf);;Documentos Word (*.docx *.doc);;Documentos LibreOffice (*.odt);;Arquivos de Texto (*.txt *.rtf)"
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
        """
        self.setStyleSheet(qss)
        self.btn_action.setStyleSheet("background-color: #10B981; color: white; font-size: 14px; font-weight: bold; border-radius: 6px; border: none;")


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
        dlg = PrinterInstallerDialog(self.settings, parent=self)
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
            QMessageBox.warning(self, "Erro", f"Não foi possível verificar atualizações.\n{error_msg}")
            return

        if has_update:
            reply = QMessageBox.question(
                self, 'Atualização Disponível!',
                f"Uma nova versão ({latest_version}) foi encontrada!\n\nDeseja baixar e atualizar agora?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.perform_update(release_data)
        else:
            QMessageBox.information(self, "Atualizado", "Você já está usando a versão mais recente!")

    def perform_update(self, release_data):
        appimage_url = None
        for asset in release_data.get("assets", []):
            if asset.get("name", "").endswith(".AppImage"):
                appimage_url = asset.get("browser_download_url")
                break

        if not appimage_url:
            QMessageBox.warning(self, "Erro", "Arquivo .AppImage não encontrado no lançamento do GitHub.")
            return

        current_appimage = os.environ.get("APPIMAGE")
        if not current_appimage:
            QMessageBox.information(self, "Aviso", "O programa não está rodando como um AppImage isolado.\n(Para atualizar, você precisa rodar a versão compilada).")
            return

        try:
            self.lbl_status.setText("Baixando atualização... Aguarde!")
            QApplication.processEvents()

            req = urllib.request.Request(appimage_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                with open(current_appimage, 'wb') as f:
                    shutil.copyfileobj(response, f)

            os.chmod(current_appimage, 0o755)

            QMessageBox.information(self, "Sucesso!", "Atualização concluída com sucesso!\nO aplicativo será reiniciado.")
            os.execv(current_appimage, [current_appimage] + sys.argv[1:])

        except Exception as e:
            QMessageBox.critical(self, "Erro fatal", f"Falha ao tentar baixar/aplicar a atualização:\n{str(e)}")
            self.lbl_status.setText("")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Breeze")

    window = PrintManagerApp()
    window.show()
    sys.exit(app.exec_())
