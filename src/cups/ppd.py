import os
import re
import subprocess
from src.config import get_clean_host_env, logger


_VARIANT_SUFFIX_RE = re.compile(r'^(.+?)_(SUPERDRAFT|DRAFT|NORMAL|STANDARD|HIGH)$', re.IGNORECASE)
_DISPLAY_SUFFIX_RE = re.compile(r'[- ](Photo RPM|Standard|High|Normal|Draft)$', re.IGNORECASE)


def _run_lpoptions_l(printer_name, cups_server=""):
    """Executa 'lpoptions -p <printer> -l' com ambiente limpo e timeout curto."""
    cmd = ['lpoptions', '-p', printer_name, '-l']
    env = get_clean_host_env()
    if cups_server:
        cmd.extend(['-h', cups_server])
        env["CUPS_SERVER"] = cups_server
    else:
        env.pop("CUPS_SERVER", None)

    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env, timeout=1.5)


def _extract_lpoptions_line(output, candidate_keys):
    """Retorna (opt_key_raw, choices_part) para a primeira chave correspondente."""
    for line in output.splitlines():
        if ':' not in line:
            continue
        key_part, choices_part = line.split(':', 1)
        opt_key_raw = key_part.split('/')[0].strip()
        opt_key = opt_key_raw.lower()
        if opt_key in candidate_keys:
            if opt_key == 'media' and any(s in choices_part.lower() for s in ['a4', 'letter', 'legal']):
                continue
            return opt_key_raw, choices_part.strip()
    return None, None


def _has_combined_mediatype_variants(output):
    """Detecta PPDs (como Epson ESC/P-R) que embutem qualidade/velocidade no MediaType (*_HIGH/*_NORMAL/*_DRAFT)."""
    _, media_line = _extract_lpoptions_line(
        output, ['mediatype', 'media-type', 'papertype', 'paper-type', 'media']
    )
    if not media_line:
        return False

    matches = 0
    for choice in media_line.split():
        raw_val = choice.lstrip('*').split('/', 1)[0]
        if _VARIANT_SUFFIX_RE.match(raw_val):
            matches += 1
            if matches >= 2:
                return True
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
        output = _run_lpoptions_l(printer_name, cups_server)
        _, slot_line = _extract_lpoptions_line(
            output, ['inputslot', 'mediasource', 'media-source', 'inputbin', 'input-slot']
        )

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

    except Exception as e:
        logger.debug(f"Erro ao obter bandejas para {printer_name}: {e}")

    return fallback_trays


def get_printer_qualities(printer_name, cups_server=""):
    """
    Obtém as opções de qualidade de impressão para a impressora informada.
    Retorna uma lista de tuplas: (label_exibicao, dict_data, is_default)
    onde dict_data = {"level": "normal"|"draft"|"high", "ppd_key": opt_key, "ppd_val": raw_val, "mode": ...}
    """
    fallback_qualities = [
        ("Normal (Padrão)", {"level": "normal", "ppd_key": "", "ppd_val": "", "mode": "ipp"}, True),
        ("Rascunho (Econômico / Rápido)", {"level": "draft", "ppd_key": "", "ppd_val": "", "mode": "ipp"}, False),
        ("Alta Qualidade (Foto / Nítido)", {"level": "high", "ppd_key": "", "ppd_val": "", "mode": "ipp"}, False),
    ]

    if not printer_name or printer_name == "Salvar como PDF":
        return fallback_qualities

    try:
        output = _run_lpoptions_l(printer_name, cups_server)
        target_opt_key, quality_line = _extract_lpoptions_line(
            output, ['cupsprintquality', 'printquality', 'print-quality', 'outputmode', 'quality', 'cnquality']
        )

        if not quality_line:
            if _has_combined_mediatype_variants(output):
                return [
                    ("Normal (Padrão)", {"level": "normal", "ppd_key": "", "ppd_val": "", "mode": "media_variants"}, True),
                    ("Rascunho (Econômico / Rápido)", {"level": "draft", "ppd_key": "", "ppd_val": "", "mode": "media_variants"}, False),
                    ("Alta Qualidade (Foto / Nítido)", {"level": "high", "ppd_key": "", "ppd_val": "", "mode": "media_variants"}, False),
                ]
            return fallback_qualities

        choices = quality_line.split()
        parsed = []
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

            if any(k in raw_lower or k in disp_lower for k in ['draft', 'fast', 'rascunho', 'economic', 'economico']):
                level = "draft"
                label = f"Rascunho ({display_val})" if display_val.lower() not in ["draft", "rascunho"] else "Rascunho (Econômico / Rápido)"
            elif any(k in raw_lower or k in disp_lower for k in ['high', 'best', 'photo', 'fine', 'alta', 'otima', 'ótima']):
                level = "high"
                label = f"Alta Qualidade ({display_val})" if display_val.lower() not in ["high", "best"] else "Alta Qualidade (Foto / Nítido)"
            elif any(k in raw_lower or k in disp_lower for k in ['normal', 'standard', 'padrao', 'padrão']):
                level = "normal"
                label = f"Normal ({display_val})" if display_val.lower() not in ["normal", "standard"] else "Normal (Padrão)"
            else:
                level = "normal"
                label = display_val

            if is_def:
                has_default = True

            parsed.append((label, {"level": level, "ppd_key": target_opt_key, "ppd_val": raw_val, "mode": "ppd"}, is_def))

        if parsed:
            if not has_default and len(parsed) > 0:
                l, d, _ = parsed[0]
                parsed[0] = (l, d, True)
            return parsed

    except Exception as e:
        logger.debug(f"Erro ao obter qualidades para {printer_name}: {e}")

    return fallback_qualities


def format_media_type_label(raw_val, display_val):
    raw_lower = raw_val.lower()
    disp_lower = display_val.lower()
    combined = f"{raw_val} {display_val}".lower()
    has_custom_disp = bool(display_val) and disp_lower != raw_lower

    if any(k in combined for k in ['ultra glossy', 'platina']):
        if has_custom_disp and disp_lower not in ['ultra glossy', 'platina']:
            return f"Papel Fotográfico Ultra Brilhoso ({display_val})"
        return "Papel Fotográfico Ultra Brilhoso (Epson Ultra Glossy)" if 'platina' in raw_lower else "Papel Fotográfico Ultra Brilhoso (Ultra Glossy)"
    elif any(k in combined for k in ['semigloss', 'semi-gloss', 'psglos', 'luster']):
        if has_custom_disp and disp_lower not in ['semigloss', 'semi-gloss', 'psglos', 'luster']:
            return f"Papel Fotográfico Semibrilho ({display_val})"
        if raw_lower == 'psglos':
            return "Papel Fotográfico Semibrilho (Epson Premium Semigloss)"
        if raw_lower in ['luster', 'semigloss']:
            return f"Papel Fotográfico Semibrilho ({raw_val.capitalize()})"
        return "Papel Fotográfico Semibrilho"
    elif any(k in combined for k in ['glossy', 'brilhante', 'brilhoso', 'pmphoto', 'lcpp']):
        if has_custom_disp and disp_lower != 'glossy':
            return f"Papel Fotográfico Brilhoso ({display_val})"
        if raw_lower == 'pmphoto':
            return "Papel Fotográfico Brilhoso (Epson Premium Glossy)"
        if raw_lower == 'lcpp':
            return "Papel Fotográfico Brilhoso (Photo Paper Glossy)"
        if raw_lower == 'glossygold':
            return "Papel Fotográfico Brilhoso (Glossy Gold)"
        if raw_lower == 'glossypaper':
            return "Papel Fotográfico Brilhoso (Glossy Paper)"
        return "Papel Fotográfico Brilhoso (Glossy)"
    elif any(k in combined for k in ['matte', 'fosco', 'pmmatt']):
        if has_custom_disp and disp_lower != 'matte':
            return f"Papel Fotográfico Fosco ({display_val})"
        if raw_lower == 'pmmatt':
            return "Papel Fotográfico Fosco (Epson Matte)"
        return "Papel Fotográfico Fosco (Matte)"
    elif any(k in combined for k in ['photo quality ink jet', 'sfine', 'highres']):
        if has_custom_disp:
            return f"Papel Alta Resolução ({display_val})"
        if raw_lower == 'sfine':
            return "Papel Alta Resolução (Photo Quality Ink Jet)"
        return "Papel Alta Resolução"
    elif any(k in combined for k in ['photo', 'foto']):
        return f"Papel Fotográfico ({display_val})" if has_custom_disp and disp_lower != 'photo' else "Papel Fotográfico (Foto)"
    elif any(k in combined for k in ['recycled', 'reciclado']):
        return f"Papel Reciclado ({display_val})" if has_custom_disp and disp_lower != 'recycled' else "Papel Reciclado"
    elif any(k in combined for k in ['cardstock', 'heavy', 'thick', 'cartao', 'cartão', 'grosso']):
        return f"Papel Cartão / Grosso ({display_val})" if has_custom_disp and disp_lower not in ['cardstock', 'heavy', 'thick'] else "Papel Cartão / Grosso"
    elif any(k in combined for k in ['label', 'etiqueta', 'adesivo']):
        return f"Etiquetas / Adesivo ({display_val})" if has_custom_disp and disp_lower not in ['label', 'labels'] else "Etiquetas / Adesivo"
    elif any(k in combined for k in ['letterhead', 'timbrado']):
        if has_custom_disp and disp_lower != 'letterhead':
            return f"Papel Timbrado ({display_val})"
        return "Papel Timbrado (Letterhead)"
    elif raw_lower in ['env', 'envelope'] or 'envelope' in combined:
        return f"Envelope ({display_val})" if has_custom_disp and disp_lower not in ['envelope', 'env'] else "Envelope"
    elif any(k in combined for k in ['transparency', 'transparencia', 'transparência']):
        return f"Transparência ({display_val})" if has_custom_disp and disp_lower != 'transparency' else "Transparência"
    elif any(k in combined for k in ['plain', 'stationery', 'comum', 'padrao', 'padrão']):
        return "Papel Comum (Padrão)" if raw_lower in ['plain', 'stationery'] else f"Papel Comum ({display_val})"
    else:
        return display_val if has_custom_disp else raw_val


def map_media_type_to_ipp(raw_val, display_val):
    combined = f"{raw_val} {display_val}".lower()
    if any(k in combined for k in ['glossy', 'brilhante', 'brilhoso', 'platina', 'pmphoto', 'lcpp', 'psglos', 'semigloss', 'luster']):
        return "photographic-glossy"
    elif any(k in combined for k in ['matte', 'fosco', 'pmmatt']):
        return "photographic-matte"
    elif any(k in combined for k in ['photo', 'foto', 'sfine']):
        return "photographic"
    elif any(k in combined for k in ['recycled', 'reciclado']):
        return "stationery-recycled"
    elif any(k in combined for k in ['cardstock', 'heavy', 'thick', 'cartao', 'cartão', 'grosso']):
        return "cardstock"
    elif any(k in combined for k in ['label', 'etiqueta', 'adesivo']):
        return "labels"
    elif any(k in combined for k in ['letterhead', 'timbrado']):
        return "stationery-letterhead"
    elif any(k in combined for k in ['envelope']) or raw_val.lower().startswith('env'):
        return "envelope"
    elif any(k in combined for k in ['transparency', 'transparencia', 'transparência']):
        return "transparency"
    return "stationery"


def get_printer_media_types(printer_name, cups_server=""):
    """
    Obtém os tipos de papel/mídia (MediaType / media-type) disponíveis para a impressora informada.
    Em drivers como Epson ESC/P-R, agrupa variantes *_HIGH / *_NORMAL / *_DRAFT em um único tipo
    de papel com dicionário 'variants' para que Qualidade e Velocidade selecionem a variante exata.
    """
    fallback_media_types = [
        ("Papel Comum (Padrão)", {"ipp": "stationery", "ppd_key": "", "ppd_val": "Plain"}, True),
        ("Papel Fotográfico Brilhoso (Glossy)", {"ipp": "photographic-glossy", "ppd_key": "", "ppd_val": "Glossy"}, False),
        ("Papel Fotográfico Fosco (Matte)", {"ipp": "photographic-matte", "ppd_key": "", "ppd_val": "Matte"}, False),
        ("Papel Fotográfico (Foto)", {"ipp": "photographic", "ppd_key": "", "ppd_val": "Photo"}, False),
        ("Papel Reciclado", {"ipp": "stationery-recycled", "ppd_key": "", "ppd_val": "Recycled"}, False),
        ("Papel Cartão / Grosso", {"ipp": "cardstock", "ppd_key": "", "ppd_val": "Cardstock"}, False),
        ("Etiquetas / Adesivo", {"ipp": "labels", "ppd_key": "", "ppd_val": "Labels"}, False),
        ("Envelope", {"ipp": "envelope", "ppd_key": "", "ppd_val": "Envelope"}, False),
        ("Transparência", {"ipp": "transparency", "ppd_key": "", "ppd_val": "Transparency"}, False)
    ]

    if not printer_name or printer_name == "Salvar como PDF":
        return fallback_media_types

    try:
        output = _run_lpoptions_l(printer_name, cups_server)
        target_opt_key, media_line = _extract_lpoptions_line(
            output, ['mediatype', 'media-type', 'papertype', 'paper-type', 'media']
        )

        if not media_line:
            return fallback_media_types

        choices = media_line.split()
        raw_entries = []
        variant_matches = 0

        for choice in choices:
            is_def = choice.startswith('*')
            clean = choice.lstrip('*')
            if '/' in clean:
                raw_val, display_val = clean.split('/', 1)
            else:
                raw_val = display_val = clean
            if _VARIANT_SUFFIX_RE.match(raw_val):
                variant_matches += 1
            raw_entries.append((raw_val, display_val, is_def))

        if variant_matches >= 2:
            groups = {}
            group_order = []

            for raw_val, display_val, is_def in raw_entries:
                m = _VARIANT_SUFFIX_RE.match(raw_val)
                if m:
                    base_key = m.group(1)
                    tier_raw = m.group(2).lower()
                    tier = "normal" if tier_raw == "standard" else tier_raw
                    clean_disp = _DISPLAY_SUFFIX_RE.sub('', display_val).strip(' -')
                    if not clean_disp or clean_disp.upper() == raw_val.upper():
                        clean_disp = base_key
                else:
                    base_key = raw_val
                    tier = "normal"
                    clean_disp = display_val

                if base_key not in groups:
                    groups[base_key] = {
                        "base_key": base_key,
                        "clean_disp": clean_disp,
                        "variants": {},
                        "is_def": False,
                        "first_raw": raw_val,
                        "default_raw": None,
                    }
                    group_order.append(base_key)

                grp = groups[base_key]
                grp["variants"][tier] = raw_val
                if is_def:
                    grp["is_def"] = True
                    grp["default_raw"] = raw_val

            parsed = []
            has_default = False
            for base_key in group_order:
                grp = groups[base_key]
                variants = grp["variants"]
                clean_disp = grp["clean_disp"]
                ipp_val = map_media_type_to_ipp(base_key, clean_disp)

                if base_key.lower() in ('plain', 'stationery'):
                    label = "Papel Comum (Padrão)"
                else:
                    label = format_media_type_label(base_key, clean_disp)

                # Sempre priorizar _NORMAL (ou _DRAFT) como padrão seguro, evitando travar em _HIGH
                default_ppd_val = (
                    variants.get("normal")
                    or variants.get("draft")
                    or grp["default_raw"]
                    or grp["first_raw"]
                )
                is_def = grp["is_def"]
                if is_def:
                    has_default = True

                parsed.append((
                    label,
                    {
                        "ipp": ipp_val,
                        "ppd_key": target_opt_key,
                        "ppd_val": default_ppd_val,
                        "variants": variants,
                    },
                    is_def
                ))

            if parsed:
                if not has_default:
                    l, d, _ = parsed[0]
                    parsed[0] = (l, d, True)
                return parsed

        parsed = []
        has_default = False
        for raw_val, display_val, is_def in raw_entries:
            label = format_media_type_label(raw_val, display_val)
            ipp_val = map_media_type_to_ipp(raw_val, display_val)
            if is_def:
                has_default = True
            parsed.append((label, {"ipp": ipp_val, "ppd_key": target_opt_key, "ppd_val": raw_val}, is_def))

        if parsed:
            if not has_default and len(parsed) > 0:
                l, d, _ = parsed[0]
                parsed[0] = (l, d, True)
            return parsed

    except Exception as e:
        logger.debug(f"Erro ao obter tipos de papel para {printer_name}: {e}")

    return fallback_media_types


def format_speed_label(raw_val, display_val):
    combined = f"{raw_val} {display_val}".lower()
    if any(k in combined for k in ['fast', 'high', 'rapida', 'rápida', 'turbo']):
        return f"Rápida ({display_val})" if display_val.lower() not in ['fast', 'high', 'rapida', 'rápida'] else "Rápida (Priorizar Velocidade)"
    elif any(k in combined for k in ['slow', 'low', 'lenta', 'quiet', 'silent', 'silenciosa']):
        return f"Lenta / Silenciosa ({display_val})" if display_val.lower() not in ['slow', 'low', 'quiet', 'silent'] else "Lenta / Silenciosa (Maior Precisão)"
    elif any(k in combined for k in ['normal', 'standard', 'padrao', 'padrão', 'auto', 'default']):
        return f"Normal ({display_val})" if display_val.lower() not in ['normal', 'standard', 'default'] else "Normal (Padrão)"
    else:
        return display_val if display_val != raw_val else raw_val


def get_printer_speeds(printer_name, cups_server=""):
    """
    Obtém as opções de velocidade de impressão (PrintSpeed / Speed / QuietMode) disponíveis para a impressora.
    Retorna uma lista de tuplas: (label_exibicao, dict_data, is_default)
    onde dict_data inclui:
      - speed: "normal" | "fast" | "slow"
      - ppd_key / ppd_val: preenchidos apenas quando o PPD realmente expõe a opção
      - native: True se suportado nativamente no PPD, False caso contrário
      - mode: "ppd" | "media_variants" | "ipp_quality"
    """
    def _build_virtual_speeds(mode):
        return [
            ("Normal (Padrão)", {"speed": "normal", "ppd_key": "", "ppd_val": "", "native": False, "mode": mode}, True),
            ("Rápida (Priorizar Velocidade)", {"speed": "fast", "ppd_key": "", "ppd_val": "", "native": False, "mode": mode}, False),
            ("Lenta / Silenciosa (Maior Precisão)", {"speed": "slow", "ppd_key": "", "ppd_val": "", "native": False, "mode": mode}, False),
        ]

    if not printer_name or printer_name == "Salvar como PDF":
        return _build_virtual_speeds("ipp_quality")

    try:
        output = _run_lpoptions_l(printer_name, cups_server)
        target_opt_key, speed_line = _extract_lpoptions_line(
            output,
            ['printspeed', 'speed', 'cupsprintspeed', 'cupsspeed', 'quietmode', 'silentmode', 'cnquietmode', 'print-speed']
        )

        if not speed_line:
            mode = "media_variants" if _has_combined_mediatype_variants(output) else "ipp_quality"
            return _build_virtual_speeds(mode)

        choices = speed_line.split()
        parsed = []
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
            combined = f"{raw_lower} {disp_lower}"

            if any(k in combined for k in ['fast', 'high', 'rapida', 'rápida', 'turbo']):
                speed_type = "fast"
            elif any(k in combined for k in ['slow', 'low', 'lenta', 'quiet', 'silent', 'silenciosa', 'on']):
                speed_type = "slow"
            else:
                speed_type = "normal"

            label = format_speed_label(raw_val, display_val)

            if is_def:
                has_default = True

            parsed.append((
                label,
                {"speed": speed_type, "ppd_key": target_opt_key, "ppd_val": raw_val, "native": True, "mode": "ppd"},
                is_def
            ))

        if parsed:
            if not has_default and len(parsed) > 0:
                l, d, _ = parsed[0]
                parsed[0] = (l, d, True)
            return parsed

    except Exception as e:
        logger.debug(f"Erro ao obter velocidades para {printer_name}: {e}")

    return _build_virtual_speeds("ipp_quality")


def resolve_effective_print_options(quality=None, print_speed=None, media_type=None):
    """
    Resolve os parâmetros '-o' efetivos para CUPS/IPP combinando Qualidade, Velocidade e Tipo de Papel.
    - Para drivers com variantes no MediaType (ex: Epson ESC/P-R PLAIN_NORMAL/PLAIN_HIGH/PMPHOTO_DRAFT),
      escolhe a variante correta conforme qualidade e velocidade sem nunca enviar chaves inexistentes.
    - Só envia chaves PPD de qualidade/velocidade quando o PPD realmente as declara.
    """
    # 1. Normalizar nível de qualidade
    q_level = ""
    if isinstance(quality, dict):
        q_level = str(quality.get("level", "")).lower()
    if not q_level and quality:
        q_str = str(quality).lower()
        if any(k in q_str for k in ["rascunho", "draft"]):
            q_level = "draft"
        elif any(k in q_str for k in ["alta", "high", "best", "foto", "ótima", "otima"]):
            q_level = "high"
        else:
            q_level = "normal"
    if not q_level:
        q_level = "normal"

    # 2. Normalizar nível de velocidade
    s_level = ""
    if isinstance(print_speed, dict):
        s_level = str(print_speed.get("speed", "")).lower()
    if not s_level and print_speed:
        s_str = str(print_speed).lower()
        if any(k in s_str for k in ["rapida", "rápida", "fast"]):
            s_level = "fast"
        elif any(k in s_str for k in ["lenta", "slow", "quiet", "silenciosa"]):
            s_level = "slow"
        else:
            s_level = "normal"
    if not s_level:
        s_level = "normal"

    opts = []

    # 3. Qualidade IPP padrão (print-quality: 3=draft, 4=normal, 5=high)
    # Quando Qualidade está em Normal, Velocidade Rápida reduz para 3 (draft) e Lenta aumenta para 5 (precision).
    if q_level == "draft":
        ipp_quality = 3
    elif q_level == "high":
        ipp_quality = 5
    elif s_level == "fast":
        ipp_quality = 3
    elif s_level == "slow":
        ipp_quality = 5
    else:
        ipp_quality = 4

    if quality or print_speed:
        opts.append(f"print-quality={ipp_quality}")

    if isinstance(quality, dict):
        q_key = quality.get("ppd_key")
        q_val = quality.get("ppd_val")
        if q_key and q_val:
            opts.append(f"{q_key}={q_val}")

    # 4. Tipo de Papel / Mídia (e variantes Epson ESC/P-R)
    if media_type:
        ipp_type = ""
        m_key = ""
        m_val = ""
        variants = None

        if isinstance(media_type, dict):
            ipp_type = media_type.get("ipp", "")
            m_key = media_type.get("ppd_key", "")
            m_val = media_type.get("ppd_val", "")
            variants = media_type.get("variants")
        else:
            raw_str = str(media_type)
            ipp_type = map_media_type_to_ipp(raw_str, raw_str)
            m_val = raw_str

        if isinstance(variants, dict) and variants:
            if q_level == "high":
                tier_order = ("high", "normal", "draft", "superdraft")
            elif q_level == "draft" or (q_level == "normal" and s_level == "fast"):
                tier_order = ("draft", "superdraft", "normal", "high")
            elif q_level == "normal" and s_level == "slow":
                tier_order = ("high", "normal", "draft", "superdraft")
            else:
                tier_order = ("normal", "draft", "superdraft", "high")

            for tier in tier_order:
                if variants.get(tier):
                    m_val = variants[tier]
                    break

        if ipp_type:
            opts.append(f"media-type={ipp_type}")
        if m_key and m_val:
            opts.append(f"{m_key}={m_val}")
        elif m_val and m_val not in ["Plain", "stationery"]:
            opts.append(f"MediaType={m_val}")

    # 5. Velocidade nativa do PPD (somente quando o driver realmente expõe a opção)
    if isinstance(print_speed, dict):
        s_key = print_speed.get("ppd_key")
        s_val = print_speed.get("ppd_val")
        if s_key and s_val:
            opts.append(f"{s_key}={s_val}")

    return opts

