import math
from pypdf import PageObject, Transformation
from pypdf.generic import DecodedStreamObject, NameObject
from src.core.geometry import get_paper_size_pts, get_normalized_page_transform

def apply_nup_to_pages(pages, nup_str, paper_size_name="A4", draw_grid=False, is_doc_landscape=None):
    """Agrupa uma lista de PageObjects do PyPDF em folhas N-up (2, 4, 6, 9 ou 16 por folha)."""
    if nup_str == "1 por folha" or not nup_str:
        return pages

    if is_doc_landscape is None:
        is_doc_landscape = False
        if pages:
            _, pw0, ph0 = get_normalized_page_transform(pages[0])
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

            base_t, pw, ph = get_normalized_page_transform(page)

            scale = min(cell_w / pw, cell_h / ph) * 0.95
            scaled_w = pw * scale
            scaled_h = ph * scale

            pos_x = x_offset + (cell_w - scaled_w) / 2.0
            pos_y = y_offset + (cell_h - scaled_h) / 2.0

            t = base_t.scale(scale, scale).translate(pos_x, pos_y)
            new_sheet.merge_transformed_page(page, t)

        if draw_grid and (cols > 1 or rows > 1):
            grid_ops = ["q\n0.4 w\n[3 3] 0 d\n0.4 G\n"]
            for c in range(1, cols):
                gx = c * cell_w
                grid_ops.append(f"{gx:.2f} 0 m {gx:.2f} {sheet_h:.2f} l S\n")
            for r in range(1, rows):
                gy = r * cell_h
                grid_ops.append(f"0 {gy:.2f} m {sheet_w:.2f} {gy:.2f} l S\n")
            grid_ops.append("Q\n")
            grid_stream = "".join(grid_ops).encode("latin-1")
            grid_overlay = PageObject.create_blank_page(width=sheet_w, height=sheet_h)
            g_stream = DecodedStreamObject()
            g_stream.set_data(grid_stream)
            grid_overlay[NameObject("/Contents")] = g_stream
            new_sheet.merge_page(grid_overlay)

        new_sheets.append(new_sheet)

    return new_sheets


def apply_poster_to_pages(pages, poster_str, paper_size_name="A4", poster_overlap_mm=5.0):
    """
    Divide cada página em um mosaico de folhas (Modo Cartaz / Poster 2x2, 3x3 ou 4x4)
    com sobreposição configurável (overlap em mm) para colagem e emenda perfeita de murais.
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

    base_w, base_h = get_paper_size_pts(paper_size_name)
    overlap_pts = max(0.0, float(poster_overlap_mm) * (72.0 / 25.4))

    poster_w = cols * base_w - (cols - 1) * overlap_pts
    poster_h = rows * base_h - (rows - 1) * overlap_pts

    new_sheets = []
    for page in pages:
        base_t, pw, ph = get_normalized_page_transform(page)

        scale = min(poster_w / pw, poster_h / ph)
        scaled_w = pw * scale
        scaled_h = ph * scale

        offset_x = (poster_w - scaled_w) / 2.0
        offset_y = (poster_h - scaled_h) / 2.0

        for r in range(rows):
            for c in range(cols):
                sheet = PageObject.create_blank_page(width=base_w, height=base_h)
                tile_origin_x = c * (base_w - overlap_pts)
                tile_origin_y = (rows - 1 - r) * (base_h - overlap_pts)

                tx = offset_x - tile_origin_x
                ty = offset_y - tile_origin_y

                t = base_t.scale(scale, scale).translate(tx, ty)
                sheet.merge_transformed_page(page, t)

                new_sheets.append(sheet)

    return new_sheets, cols, rows


def apply_mirror_to_pages(pages, mirror_horizontal=True):
    """
    Aplica espelhamento horizontal em cada página (flip horizontal)
    para estampas térmicas em canecas, camisas e brindes sublimáticos.
    """
    if not mirror_horizontal:
        return pages

    mirrored_pages = []
    for page in pages:
        base_t, w, h = get_normalized_page_transform(page)
        blank = PageObject.create_blank_page(width=w, height=h)
        t = base_t.scale(-1, 1).translate(tx=w, ty=0)
        blank.merge_transformed_page(page, t)
        mirrored_pages.append(blank)
    return mirrored_pages


def apply_cut_marks_to_page(page, mark_type, margin_mm=5.0):
    """
    Aplica marcas de corte e guias de refile em uma página individual do PDF.
    Tipos suportados:
      - 'Marcas de Corte nos Cantos (Cruzetas)'
      - 'Borda Fina Delimitadora (Contorno)'
      - 'Linha Guia Pontilhada'
      - 'Cantos + Borda Fina'
    """
    if not mark_type or mark_type == "Desativado":
        return page

    w = float(page.mediabox.width)
    h = float(page.mediabox.height)

    # Margem padrão de refile (convertida de mm para pontos)
    margin = float(margin_mm) * 2.83465
    arm = 18.0  # Comprimento dos braços da cruzeta (aprox. 6.3 mm)

    lines = ["q\n"]

    if mark_type == "Marcas de Corte nos Cantos (Cruzetas)":
        lines.append("0.5 w\n0.2 G\n")
        # Inferior Esquerdo (Bottom-Left)
        lines.append(f"{margin - arm:.2f} {margin:.2f} m {margin:.2f} {margin:.2f} l S\n")
        lines.append(f"{margin:.2f} {margin - arm:.2f} m {margin:.2f} {margin:.2f} l S\n")
        # Inferior Direito (Bottom-Right)
        lines.append(f"{w - margin:.2f} {margin:.2f} m {w - margin + arm:.2f} {margin:.2f} l S\n")
        lines.append(f"{w - margin:.2f} {margin - arm:.2f} m {w - margin:.2f} {margin:.2f} l S\n")
        # Superior Esquerdo (Top-Left)
        lines.append(f"{margin - arm:.2f} {h - margin:.2f} m {margin:.2f} {h - margin:.2f} l S\n")
        lines.append(f"{margin:.2f} {h - margin:.2f} m {margin:.2f} {h - margin + arm:.2f} l S\n")
        # Superior Direito (Top-Right)
        lines.append(f"{w - margin:.2f} {h - margin:.2f} m {w - margin + arm:.2f} {h - margin:.2f} l S\n")
        lines.append(f"{w - margin:.2f} {h - margin:.2f} m {w - margin:.2f} {h - margin + arm:.2f} l S\n")

    elif mark_type == "Borda Fina Delimitadora (Contorno)":
        lines.append("0.5 w\n0.35 G\n")
        lines.append(f"{margin:.2f} {margin:.2f} {w - 2 * margin:.2f} {h - 2 * margin:.2f} re S\n")

    elif mark_type == "Linha Guia Pontilhada":
        lines.append("0.5 w\n[3 3] 0 d\n0.35 G\n")
        lines.append(f"{margin:.2f} {margin:.2f} {w - 2 * margin:.2f} {h - 2 * margin:.2f} re S\n")

    elif mark_type == "Cantos + Borda Fina":
        # Cruzetas de canto
        lines.append("0.5 w\n0.2 G\n")
        lines.append(f"{margin - arm:.2f} {margin:.2f} m {margin:.2f} {margin:.2f} l S\n")
        lines.append(f"{margin:.2f} {margin - arm:.2f} m {margin:.2f} {margin:.2f} l S\n")
        lines.append(f"{w - margin:.2f} {margin:.2f} m {w - margin + arm:.2f} {margin:.2f} l S\n")
        lines.append(f"{w - margin:.2f} {margin - arm:.2f} m {w - margin:.2f} {margin:.2f} l S\n")
        lines.append(f"{margin - arm:.2f} {h - margin:.2f} m {margin:.2f} {h - margin:.2f} l S\n")
        lines.append(f"{margin:.2f} {h - margin:.2f} m {margin:.2f} {h - margin + arm:.2f} l S\n")
        lines.append(f"{w - margin:.2f} {h - margin:.2f} m {w - margin + arm:.2f} {h - margin:.2f} l S\n")
        lines.append(f"{w - margin:.2f} {h - margin:.2f} m {w - margin:.2f} {h - margin + arm:.2f} l S\n")
        # Retângulo sutil
        lines.append("0.35 w\n0.5 G\n")
        lines.append(f"{margin:.2f} {margin:.2f} {w - 2 * margin:.2f} {h - 2 * margin:.2f} re S\n")
    else:
        return page

    lines.append("Q\n")
    stream_data = "".join(lines).encode("latin-1")

    overlay = PageObject.create_blank_page(width=w, height=h)
    stream = DecodedStreamObject()
    stream.set_data(stream_data)
    overlay[NameObject("/Contents")] = stream

    if getattr(page, "indirect_reference", None) is not None:
        base_t, vw, vh = get_normalized_page_transform(page)
        detached = PageObject.create_blank_page(width=vw, height=vh)
        detached.merge_transformed_page(page, base_t)
        detached.merge_page(overlay)
        return detached

    page.merge_page(overlay)
    return page


def apply_cut_marks_to_pages(pages, mark_type, margin_mm=5.0):
    """
    Aplica as marcas de corte e guias de refile em uma lista de páginas.
    """
    if not mark_type or mark_type == "Desativado":
        return pages

    processed_pages = []
    for page in pages:
        processed_pages.append(apply_cut_marks_to_page(page, mark_type, margin_mm=margin_mm))
    return processed_pages


def compute_booklet_sheet_pairs(total_pages, booklet_mode="Livreto Completo (Frente e Verso)"):
    """
    Calcula a ordem de imposição (saddle-stitch / dobra ao meio) para Livreto.
    Retorna lista de tuplas (left_idx_or_none, right_idx_or_none, side_label, sheet_num) em 0-based.
    """
    if total_pages <= 0 or not booklet_mode or booklet_mode == "Desativado":
        return []

    total_padded = max(4, math.ceil(total_pages / 4) * 4)
    num_physical_sheets = total_padded // 4

    mode_low = booklet_mode.lower()
    include_front = ("apenas versos" not in mode_low)
    include_back = ("apenas frentes" not in mode_low)

    pairs = []
    for k in range(num_physical_sheets):
        if include_front:
            l_idx = total_padded - 1 - 2 * k
            r_idx = 2 * k
            pairs.append((
                l_idx if l_idx < total_pages else None,
                r_idx if r_idx < total_pages else None,
                "Frente",
                k + 1,
            ))
        if include_back:
            l_idx = 2 * k + 1
            r_idx = total_padded - 2 - 2 * k
            pairs.append((
                l_idx if l_idx < total_pages else None,
                r_idx if r_idx < total_pages else None,
                "Verso",
                k + 1,
            ))
    return pairs


def apply_booklet_to_pages(pages, booklet_mode="Livreto Completo (Frente e Verso)", paper_size_name="A4", draw_fold_line=False, sheet_indices=None):
    """
    Aplica imposição de Livreto (Booklet 2-em-1 com reordenação para dobra ao meio).
    Quando sheet_indices é informado (ex: [0]), gera apenas as folhas solicitadas (otimização para prévia).
    """
    if not pages or not booklet_mode or booklet_mode == "Desativado":
        return pages

    pairs = compute_booklet_sheet_pairs(len(pages), booklet_mode)
    if not pairs:
        return pages

    _, pw0, ph0 = get_normalized_page_transform(pages[0])
    is_doc_landscape = (pw0 > ph0)

    if not is_doc_landscape:
        cols, rows, is_sheet_landscape = 2, 1, True
    else:
        cols, rows, is_sheet_landscape = 1, 2, False

    base_w, base_h = get_paper_size_pts(paper_size_name)
    if is_sheet_landscape:
        sheet_w = max(base_w, base_h)
        sheet_h = min(base_w, base_h)
    else:
        sheet_w = min(base_w, base_h)
        sheet_h = max(base_w, base_h)

    cell_w = sheet_w / cols
    cell_h = sheet_h / rows

    target_indices = range(len(pairs)) if sheet_indices is None else sheet_indices
    new_sheets = []

    for p_idx in target_indices:
        if p_idx < 0 or p_idx >= len(pairs):
            continue
        left_idx, right_idx, _, _ = pairs[p_idx]
        new_sheet = PageObject.create_blank_page(width=sheet_w, height=sheet_h)

        for slot_idx, src_idx in enumerate((left_idx, right_idx)):
            if src_idx is None or src_idx >= len(pages):
                continue
            page = pages[src_idx]
            col = slot_idx % cols
            row = slot_idx // cols
            y_offset = sheet_h - (row + 1) * cell_h
            x_offset = col * cell_w

            base_t, pw, ph = get_normalized_page_transform(page)
            scale = min(cell_w / pw, cell_h / ph) * 0.95
            scaled_w = pw * scale
            scaled_h = ph * scale
            pos_x = x_offset + (cell_w - scaled_w) / 2.0
            pos_y = y_offset + (cell_h - scaled_h) / 2.0

            t = base_t.scale(scale, scale).translate(pos_x, pos_y)
            new_sheet.merge_transformed_page(page, t)

        if draw_fold_line:
            if cols == 2:
                gx = cell_w
                fold_ops = f"q\n0.4 w\n[3 3] 0 d\n0.4 G\n{gx:.2f} 0 m {gx:.2f} {sheet_h:.2f} l S\nQ\n"
            else:
                gy = cell_h
                fold_ops = f"q\n0.4 w\n[3 3] 0 d\n0.4 G\n0 {gy:.2f} m {sheet_w:.2f} {gy:.2f} l S\nQ\n"
            overlay = PageObject.create_blank_page(width=sheet_w, height=sheet_h)
            g_stream = DecodedStreamObject()
            g_stream.set_data(fold_ops.encode("latin-1"))
            overlay[NameObject("/Contents")] = g_stream
            new_sheet.merge_page(overlay)

        new_sheets.append(new_sheet)

    return new_sheets

