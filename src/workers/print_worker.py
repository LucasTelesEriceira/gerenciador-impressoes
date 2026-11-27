import os
import sys
import shutil
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal
from src.config import get_clean_host_env, logger
from src.core.geometry import parse_page_range, fit_page_to_orientation_and_scale, configure_pypdf_limits
from src.core.layout import (
    apply_nup_to_pages, apply_poster_to_pages, apply_cut_marks_to_page,
    apply_booklet_to_pages
)
from src.core.raster import convert_to_pdf_via_libreoffice, rasterize_pdf_to_images_pdf
from src.cups.ppd import resolve_effective_print_options

class PrintWorkerThread(QThread):
    progress = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, file_path, printer, copies, paper_size, orientation, scaling_mode, custom_scale, duplex, color, nup, poster, page_range, page_subset="Todas as Páginas", reverse_order=False, print_as_image=False, tray="Automática (Padrão)", save_path="", cups_server="", quality=None, media_type=None, print_speed=None, mirror_horizontal=False, poster_overlap_mm=5.0, cut_marks="Desativado", booklet="Desativado", margins_mm=None):
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
        self.quality = quality
        self.media_type = media_type
        self.print_speed = print_speed
        self.nup = nup
        self.poster = poster
        self.poster_overlap_mm = poster_overlap_mm
        self.page_range = page_range
        self.page_subset = page_subset
        self.reverse_order = reverse_order
        self.print_as_image = print_as_image
        self.tray = tray
        self.save_path = save_path
        self.cups_server = cups_server
        self.mirror_horizontal = mirror_horizontal
        self.cut_marks = cut_marks
        self.booklet = booklet
        self.margins_mm = dict(margins_mm) if isinstance(margins_mm, dict) else {"left": 5.0, "right": 5.0, "top": 5.0, "bottom": 5.0}

    def run(self):
        configure_pypdf_limits()
        tmp_files = []
        current_file = self.file_path

        try:
            if not current_file.lower().endswith('.pdf'):
                self.progress.emit("Convertendo documento para PDF via LibreOffice...")
                try:
                    current_file = convert_to_pdf_via_libreoffice(current_file)
                    tmp_files.append(current_file)
                except Exception as e:
                    raise Exception(f"Falha na conversão para PDF pelo LibreOffice: {e}")

            # Filtrar intervalo, subconjunto e inversão de páginas
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(current_file)
            total_pages = len(reader.pages)
            selected_indices = parse_page_range(
                self.page_range,
                total_pages,
                subset=self.page_subset,
                reverse_order=self.reverse_order
            )

            needs_page_filter = (
                (self.page_range and self.page_range.strip()) or
                ("Todas" not in self.page_subset) or
                self.reverse_order
            )

            if needs_page_filter:
                self.progress.emit("Filtrando e ordenando páginas...")
                if len(selected_indices) == 0:
                    raise Exception("Nenhuma página selecionada para impressão com os filtros atuais.")
                range_tmp = f"/tmp/range_{os.getpid()}.pdf"
                writer = PdfWriter()
                for idx in selected_indices:
                    writer.add_page(reader.pages[idx])
                with open(range_tmp, "wb") as f:
                    writer.write(f)
                current_file = range_tmp
                tmp_files.append(range_tmp)

            if self.booklet and self.booklet != "Desativado":
                self.progress.emit("Montando imposição de Livreto (Booklet)...")
                from pypdf import PdfReader, PdfWriter
                reader = PdfReader(current_file)
                draw_fold = bool(self.cut_marks and self.cut_marks != "Desativado")
                booklet_sheets = apply_booklet_to_pages(reader.pages, self.booklet, self.paper_size, draw_fold_line=draw_fold)
                booklet_tmp = f"/tmp/booklet_{os.getpid()}.pdf"
                writer = PdfWriter()
                for sheet in booklet_sheets:
                    writer.add_page(sheet)
                with open(booklet_tmp, "wb") as f:
                    writer.write(f)
                current_file = booklet_tmp
                tmp_files.append(booklet_tmp)
            elif self.nup and self.nup != "1 por folha":
                self.progress.emit("Agrupando páginas (N-Up)...")
                from pypdf import PdfReader, PdfWriter
                reader = PdfReader(current_file)
                draw_grid = bool(self.cut_marks and self.cut_marks != "Desativado")
                nup_sheets = apply_nup_to_pages(reader.pages, self.nup, self.paper_size, draw_grid=draw_grid)
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
                poster_sheets, cols, rows = apply_poster_to_pages(reader.pages, self.poster, self.paper_size, poster_overlap_mm=self.poster_overlap_mm)
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
                    paper_size_name=self.paper_size,
                    mirror_horizontal=self.mirror_horizontal,
                    margin_left_mm=self.margins_mm.get("left", 5.0),
                    margin_right_mm=self.margins_mm.get("right", 5.0),
                    margin_top_mm=self.margins_mm.get("top", 5.0),
                    margin_bottom_mm=self.margins_mm.get("bottom", 5.0),
                )
                if self.cut_marks and self.cut_marks != "Desativado":
                    new_page = apply_cut_marks_to_page(new_page, self.cut_marks)
                writer.add_page(new_page)

            with open(orient_tmp, "wb") as f:
                writer.write(f)

            current_file = orient_tmp
            tmp_files.append(orient_tmp)

            if self.print_as_image:
                self.progress.emit("Rasterizando páginas em imagem (300 DPI)...")
                raster_tmp = f"/tmp/raster_{os.getpid()}.pdf"
                rasterize_pdf_to_images_pdf(current_file, raster_tmp, dpi=300)
                current_file = raster_tmp
                tmp_files.append(raster_tmp)

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
                    logger.info(f"Arquivo exportado com sucesso em: {self.save_path}")
                    self.finished_signal.emit(True, f"Arquivo salvo com sucesso em:\n{self.save_path}")
                else:
                    self.finished_signal.emit(False, "Caminho de salvamento não especificado.")
            else:
                self.progress.emit(f"Enviando trabalho para a impressora {self.printer}...")
                if sys.platform == "win32":
                    try:
                        ps_cmd = f'Start-Process -FilePath "{current_file}" -Verb PrintTo -ArgumentList "\"{self.printer}\"" -PassThru | Wait-Process'
                        subprocess.check_call(["powershell", "-NoProfile", "-Command", ps_cmd])
                        logger.info(f"Trabalho despachado no Windows para '{self.printer}'")
                        self.finished_signal.emit(True, f"Enviado com sucesso para a impressora '{self.printer}'!")
                    except Exception as win_err:
                        logger.error(f"Falha de impressão no Windows: {win_err}")
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

                    for opt_arg in resolve_effective_print_options(self.quality, self.print_speed, self.media_type):
                        lp_args.extend(["-o", opt_arg])

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
                    logger.info(f"Executando despacho CUPS: {' '.join(lp_args)}")
                    subprocess.check_call(lp_args, env=get_clean_host_env())
                    self.finished_signal.emit(True, f"Enviado com sucesso para a impressora '{self.printer}'!")

        except Exception as e:
            logger.error(f"Erro no PrintWorkerThread: {e}", exc_info=True)
            self.finished_signal.emit(False, f"Ocorreu um erro no processamento:\n{str(e)}")
        finally:
            for f in tmp_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
