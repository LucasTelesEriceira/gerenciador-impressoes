from pypdf import PageObject, Transformation


def configure_pypdf_limits():
    """Amplia os limites de parsing de content streams do pypdf >= 7.x no contexto da thread atual."""
    try:
        from pypdf._configuration import overwrite_configuration
        overwrite_configuration(
            stream_parsing_work_maximum_count=100_000_000,
            stream_decoding_work_maximum_length=1_000_000_000,
        )
    except Exception:
        pass

def parse_page_range(range_str, total_pages, subset="Todas as Páginas", reverse_order=False):
    """
    Converte uma string de intervalo (ex: '1-5, 8, 11-13') em uma lista ordenada de índices (0-indexed).
    Aplica filtros de subconjunto (Todas as Páginas, Apenas Páginas Ímpares, Apenas Páginas Pares)
    e inversão de ordem caso solicitado.
    """
    if not range_str or not range_str.strip():
        base_indices = list(range(total_pages))
    else:
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
        base_indices = sorted(list(pages)) if pages else list(range(total_pages))

    if "Ímpares" in subset or "Impares" in subset:
        res = [idx for idx in base_indices if ((idx + 1) % 2 != 0)]
    elif "Pares" in subset:
        res = [idx for idx in base_indices if ((idx + 1) % 2 == 0)]
    else:
        res = base_indices

    if reverse_order:
        res = list(reversed(res))

    return res


def get_paper_size_pts(paper_name):
    """Retorna as dimensões em pontos (pt) do formato de papel escolhido."""
    sizes = {
        "A4": (595.28, 841.89),
        "Carta (Letter)": (612.0, 792.0),
        "A3": (841.89, 1190.55),
        "A5": (419.53, 595.28),
        "Ofício (Legal)": (612.0, 1008.0)
    }
    return sizes.get(paper_name, (595.28, 841.89))


def get_normalized_page_transform(page):
    """
    Retorna (base_transform, visual_width, visual_height) normalizando origem da MediaBox
    e eventual rotação (/Rotate 90/180/270) sem mutar o PageObject original de um PdfReader.
    """
    mb = page.mediabox
    raw_w = float(mb.width)
    raw_h = float(mb.height)
    raw_l = float(mb.left)
    raw_b = float(mb.bottom)
    rot = (getattr(page, 'rotation', 0) or 0) % 360

    t = Transformation().translate(-raw_l, -raw_b)
    if rot == 90:
        t = t.rotate(-90).translate(0, raw_w)
        return t, raw_h, raw_w
    elif rot == 180:
        t = t.rotate(-180).translate(raw_w, raw_h)
        return t, raw_w, raw_h
    elif rot == 270:
        t = t.rotate(-270).translate(raw_h, 0)
        return t, raw_h, raw_w
    return t, raw_w, raw_h


def fit_page_to_orientation_and_scale(
    page,
    target_orientation,
    scaling_mode="Ajustar à Folha (Fit)",
    custom_scale=100,
    paper_size_name="A4",
    margin_mm=5.0,
    mirror_horizontal=False,
    margin_left_mm=None,
    margin_right_mm=None,
    margin_top_mm=None,
    margin_bottom_mm=None,
):
    """
    Ajusta a página do PDF aplicando orientação, modo de dimensionamento, margens individuais
    (esquerda, direita, topo, inferior em mm) e espelhamento horizontal opcional.
    Compatível com pypdf >= 7.0 (não muta PageObject ligado a PdfReader).
    """
    base_transform, w_doc, h_doc = get_normalized_page_transform(page)

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

    pt_per_mm = 2.83465
    ml = max(0.0, float(margin_mm if margin_left_mm is None else margin_left_mm)) * pt_per_mm
    mr = max(0.0, float(margin_mm if margin_right_mm is None else margin_right_mm)) * pt_per_mm
    mt = max(0.0, float(margin_mm if margin_top_mm is None else margin_top_mm)) * pt_per_mm
    mb = max(0.0, float(margin_mm if margin_bottom_mm is None else margin_bottom_mm)) * pt_per_mm

    printable_w = max(10.0, target_w - (ml + mr))
    printable_h = max(10.0, target_h - (mt + mb))

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

    tx = ml + (printable_w - scaled_w) / 2.0
    ty = mb + (printable_h - scaled_h) / 2.0

    transform = base_transform.scale(scale, scale).translate(tx, ty)
    if mirror_horizontal:
        transform = transform.scale(-1, 1).translate(tx=target_w, ty=0)

    new_page.merge_transformed_page(page, transform)
    return new_page, scale, target_w, target_h
