import os
import math
import time
import subprocess
import glob
from PyQt5.QtCore import QThread, pyqtSignal
from src.config import get_clean_host_env, logger
from src.core.geometry import (
    parse_page_range, fit_page_to_orientation_and_scale,
    get_normalized_page_transform, configure_pypdf_limits
)
from src.core.layout import (
    apply_nup_to_pages, apply_poster_to_pages, apply_cut_marks_to_page,
    apply_booklet_to_pages, compute_booklet_sheet_pairs
)
from src.core.raster import convert_to_pdf_via_libreoffice

class PreviewWorkerThread(QThread):
    preview_ready = pyqtSignal(str, int, int, float, float, float, str)
    pdf_converted = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, file_path, page_num=1, orientation="Automático (Padrão)", scaling_mode="Ajustar à Folha (Fit)", custom_scale=100, paper_size="A4", page_range="", page_subset="Todas as Páginas", reverse_order=False, nup="1 por folha", poster="Desativado", poster_overlap_mm=5.0, cached_pdf="", mirror_horizontal=False, cut_marks="Desativado", booklet="Desativado", margins_mm=None):
        super().__init__()
        self.file_path = file_path
        self.page_num = page_num
        self.orientation = orientation
        self.scaling_mode = scaling_mode
        self.custom_scale = custom_scale
        self.paper_size = paper_size
        self.page_range = page_range
        self.page_subset = page_subset
        self.reverse_order = reverse_order
        self.nup = nup
        self.poster = poster
        self.poster_overlap_mm = poster_overlap_mm
        self.cached_pdf = cached_pdf
        self.mirror_horizontal = mirror_horizontal
        self.cut_marks = cut_marks
        self.booklet = booklet
        self.margins_mm = dict(margins_mm) if isinstance(margins_mm, dict) else {"left": 5.0, "right": 5.0, "top": 5.0, "bottom": 5.0}

    def run(self):
        configure_pypdf_limits()
        tmp_files = []
        try:
            current_file = self.cached_pdf if (self.cached_pdf and os.path.exists(self.cached_pdf)) else self.file_path

            if not current_file.lower().endswith('.pdf'):
                try:
                    converted = convert_to_pdf_via_libreoffice(current_file)
                    current_file = converted
                    self.pdf_converted.emit(converted)
                except Exception as e:
                    self.error.emit(f"Falha ao converter arquivo para pré-visualização: {e}")
                    return

            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(current_file)
            total_doc_pages = len(reader.pages)

            if total_doc_pages == 0:
                self.error.emit("O documento não possui páginas válidas.")
                return

            selected_indices = parse_page_range(self.page_range, total_doc_pages, subset=self.page_subset, reverse_order=self.reverse_order)
            selected_pages = [reader.pages[i] for i in selected_indices if i < total_doc_pages]

            if not selected_pages:
                self.error.emit("Nenhuma página válida no intervalo especificado.")
                return

            is_booklet_active = bool(self.booklet and self.booklet != "Desativado")
            is_poster_active = bool(self.poster and self.poster != "Desativado")
            nup_total_pages = None
            nup_preview_page_num = None
            booklet_info = ""

            if is_booklet_active:
                pairs = compute_booklet_sheet_pairs(len(selected_pages), self.booklet)
                if pairs:
                    nup_total_pages = len(pairs)
                    nup_preview_page_num = max(1, min(self.page_num, nup_total_pages))
                    l_idx, r_idx, side_lbl, phys_sheet = pairs[nup_preview_page_num - 1]
                    l_txt = str(l_idx + 1) if l_idx is not None else "Branco"
                    r_txt = str(r_idx + 1) if r_idx is not None else "Branco"
                    booklet_info = f"Livreto {phys_sheet} ({side_lbl}: págs {l_txt} | {r_txt})"
                    selected_pages = apply_booklet_to_pages(
                        selected_pages,
                        self.booklet,
                        self.paper_size,
                        draw_fold_line=True,
                        sheet_indices=[nup_preview_page_num - 1],
                    )
            elif self.nup != "1 por folha":
                if not is_poster_active:
                    try:
                        n_per_sheet = int(self.nup.split()[0])
                    except Exception:
                        n_per_sheet = 1
                    if n_per_sheet > 1:
                        nup_total_pages = math.ceil(len(selected_pages) / n_per_sheet)
                        nup_preview_page_num = max(1, min(self.page_num, nup_total_pages))
                        _, pw0, ph0 = get_normalized_page_transform(selected_pages[0])
                        is_doc_land = (pw0 > ph0)
                        c_start = (nup_preview_page_num - 1) * n_per_sheet
                        chunk = selected_pages[c_start : c_start + n_per_sheet]
                        selected_pages = apply_nup_to_pages(
                            chunk, self.nup, self.paper_size, draw_grid=True, is_doc_landscape=is_doc_land
                        )
                    else:
                        selected_pages = apply_nup_to_pages(selected_pages, self.nup, self.paper_size, draw_grid=True)
                else:
                    selected_pages = apply_nup_to_pages(selected_pages, self.nup, self.paper_size, draw_grid=True)

            total_base_pages = len(selected_pages)
            if total_base_pages == 0:
                self.error.emit("Erro ao calcular páginas do documento.")
                return

            poster_info = booklet_info

            if is_poster_active and not is_booklet_active:
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
                poster_sheets, _, _ = apply_poster_to_pages([base_page], self.poster, self.paper_size, poster_overlap_mm=self.poster_overlap_mm)

                target_tile = poster_sheets[tile_idx]
                poster_info = f"Cartaz {cols}x{rows} [Linha {tile_row}, Coluna {tile_col}] (Pág. {base_page_idx + 1}/{total_base_pages})"

                target_page, calc_scale, tw, th = fit_page_to_orientation_and_scale(
                    target_tile,
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
                calc_scale = calc_scale * cols * 100.0
            else:
                total_pages = nup_total_pages if nup_total_pages is not None else total_base_pages
                preview_page_num = nup_preview_page_num if nup_preview_page_num is not None else max(1, min(self.page_num, total_pages))
                sheet_idx = 0 if nup_preview_page_num is not None else (preview_page_num - 1)

                is_default_orient = ("Automático" in self.orientation)
                is_default_scale = (self.scaling_mode == "Ajustar à Folha (Fit)")
                is_full_doc = (not self.page_range or not self.page_range.strip())
                has_cut_marks = bool(self.cut_marks and self.cut_marks != "Desativado")
                has_custom_margins = any(
                    abs(float(self.margins_mm.get(k, 5.0)) - 5.0) > 0.01
                    for k in ("left", "right", "top", "bottom")
                )

                if not is_booklet_active and self.nup == "1 por folha" and is_default_orient and is_default_scale and is_full_doc and not self.mirror_horizontal and not has_cut_marks and not has_custom_margins:
                    run_tag = int(time.time() * 1000)
                    out_prefix = f"/tmp/prev_fast_{os.getpid()}_{run_tag}_{preview_page_num}"
                    cmd = ["pdftoppm", "-jpeg", "-jpegopt", "quality=85", "-r", "90", "-f", str(preview_page_num), "-l", str(preview_page_num), current_file, out_prefix]
                    subprocess.check_call(cmd, env=get_clean_host_env())
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
                    selected_pages[sheet_idx],
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
                calc_scale = calc_scale * 100.0

            if self.cut_marks and self.cut_marks != "Desativado":
                target_page = apply_cut_marks_to_page(target_page, self.cut_marks)

            run_tag = int(time.time() * 1000)
            orient_tmp = f"/tmp/prev_orient_{os.getpid()}_{run_tag}.pdf"
            writer = PdfWriter()
            writer.add_page(target_page)

            with open(orient_tmp, "wb") as f:
                writer.write(f)
            current_file = orient_tmp
            tmp_files.append(orient_tmp)

            out_prefix = f"/tmp/prev_{os.getpid()}_{run_tag}_{preview_page_num}"
            cmd = ["pdftoppm", "-jpeg", "-jpegopt", "quality=85", "-r", "90", "-f", "1", "-l", "1", current_file, out_prefix]
            subprocess.check_call(cmd, env=get_clean_host_env())

            matching = glob.glob(f"{out_prefix}*.jpg") or glob.glob(f"{out_prefix}*.jpeg") or glob.glob(f"{out_prefix}*.png")
            if matching:
                img_path = matching[0]
                paper_w_mm = tw * 0.352778
                paper_h_mm = th * 0.352778
                self.preview_ready.emit(img_path, preview_page_num, total_pages, calc_scale, paper_w_mm, paper_h_mm, poster_info)
            else:
                self.error.emit("Erro ao gerar imagem de pré-visualização.")

        except Exception as e:
            logger.error(f"Erro no PreviewWorkerThread: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            for f in tmp_files:
                if f.endswith('.pdf') and os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
