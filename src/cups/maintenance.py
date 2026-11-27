# -*- coding: utf-8 -*-
"""
CUPS / IPP Printer Supply Levels (Ink / Toner / Waste Ink) and Maintenance Utilities.
"""

import os
import re
import shlex
import subprocess
import tempfile
from datetime import datetime
from urllib.parse import urlparse

from pypdf import PdfWriter, PageObject
from pypdf.generic import DecodedStreamObject, NameObject

from src.config import get_clean_host_env, logger


_STATE_LABELS = {
    "3": "Pronta (Inativa)",
    "4": "Imprimindo",
    "5": "Pausada / Parada",
}

_MARKER_TYPE_LABELS = {
    "ink": "Tinta",
    "ink-cartridge": "Cartucho / Tanque",
    "ink-ribbon": "Fita",
    "toner": "Toner",
    "waste-ink": "Caixa de Manutenção",
    "waste-toner": "Reservatório de Resíduos",
    "opc": "Cilindro / Fotocondutor",
    "fuser": "Fuser",
}


def _unescape_cups_value(val):
    if val is None:
        return ""
    # CUPS lpoptions escapes spaces as '\ ' inside attribute lists
    return val.replace("\\ ", " ").strip()


def parse_lpoptions_attrs(output):
    """Faz parsing robusto da saída de 'lpoptions -p <fila>' em um dicionário."""
    attrs = {}
    if not output:
        return attrs
    try:
        tokens = shlex.split(output)
    except ValueError:
        tokens = output.split()

    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            attrs[k.strip()] = _unescape_cups_value(v)
        else:
            attrs[tok.strip()] = ""
    return attrs


def _split_cups_csv(value):
    if not value or value == "none":
        return []
    # Split on commas that are not escaped
    parts = re.split(r'(?<!\\),', value)
    return [_unescape_cups_value(p) for p in parts if p.strip() != ""]


def _infer_marker_color(raw_name, provided_color):
    if provided_color and re.match(r'^#[0-9a-fA-F]{6}$', provided_color.strip()):
        return provided_color.strip()
    low = raw_name.lower()
    if any(k in low for k in ("cyan", "ciano")):
        return "#00B8F4"
    if any(k in low for k in ("magenta",)):
        return "#EC4899"
    if any(k in low for k in ("yellow", "amarelo")):
        return "#EAB308"
    if any(k in low for k in ("black", "preto", "pgbk", "toner", "cartridge")):
        return "#1E293B"
    if any(k in low for k in ("waste", "mc", "residu")):
        return "#0D9488"
    return "#64748B"


def _format_marker_name(raw_name, marker_type):
    clean = raw_name.strip()
    low = clean.lower()
    if marker_type == "waste-ink" or low in ("mc", "maintenance box", "waste ink"):
        return "Caixa de Manutenção (Resíduos)"
    if low == "black ink bottle":
        return "Preto (Tanque)"
    if low == "cyan ink bottle":
        return "Ciano (Tanque)"
    if low == "magenta ink bottle":
        return "Magenta (Tanque)"
    if low == "yellow ink bottle":
        return "Amarelo (Tanque)"
    if low.startswith("black"):
        return f"Preto ({clean})" if clean.lower() != "black" else "Preto"
    if low == "cyan":
        return "Ciano"
    if low == "magenta":
        return "Magenta"
    if low == "yellow":
        return "Amarelo"
    return clean


def _extract_web_url(device_uri):
    if not device_uri:
        return ""
    try:
        parsed = urlparse(device_uri)
        scheme = (parsed.scheme or "").lower()
        if scheme in ("ipp", "ipps", "http", "https", "socket", "lpd"):
            host = parsed.hostname
            if host and host not in ("localhost", "127.0.0.1", "::1"):
                web_scheme = "https" if scheme in ("ipps", "https") else "http"
                return f"{web_scheme}://{host}"
    except Exception:
        pass
    return ""


def _query_ipptool_markers(device_uri, timeout=1.5):
    """Consulta níveis de suprimentos diretamente via IPP caso o CUPS esteja sem cache."""
    if not device_uri or not device_uri.startswith(("ipp://", "ipps://")):
        return {}
    test_file = "/usr/share/cups/ipptool/get-printer-attributes.test"
    if not os.path.exists(test_file):
        return {}
    try:
        out = subprocess.check_output(
            ["ipptool", "-T", str(timeout), "-t", device_uri, test_file],
            text=True, stderr=subprocess.DEVNULL, env=get_clean_host_env(), timeout=timeout + 0.8
        )
        parsed = {}
        for line in out.splitlines():
            m = re.match(r'^\s*(marker-[a-z-]+)\s+\([^)]+\)\s*=\s*(.+)$', line)
            if m:
                parsed[m.group(1).strip()] = m.group(2).strip()
        return parsed
    except Exception as e:
        logger.debug("ipptool direto falhou para %s: %s", device_uri, e)
        return {}


def get_printer_supply_and_status(printer_name, cups_server="", query_network=False):
    """
    Obtém status da fila, comandos suportados pelo driver e níveis de tinta/toner/resíduos.
    """
    info = {
        "printer_name": printer_name or "",
        "model": "",
        "device_uri": "",
        "state": "3",
        "state_label": "Desconhecido",
        "state_reasons": "none",
        "is_accepting": True,
        "printer_commands": [],
        "supports_clean": False,
        "supports_selftest": False,
        "is_usb_epson": False,
        "web_url": "",
        "markers": [],
        "last_updated": "",
        "source": "none",
        "error": "",
    }

    if not printer_name or printer_name == "Salvar como PDF":
        info["model"] = "Exportação Virtual PDF"
        info["state_label"] = "Disponível"
        return info

    env = get_clean_host_env()
    cmd = ["lpoptions", "-p", printer_name]
    if cups_server:
        cmd.extend(["-h", cups_server])
        env["CUPS_SERVER"] = cups_server
    else:
        env.pop("CUPS_SERVER", None)

    try:
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env, timeout=2.5).strip()
    except Exception as e:
        info["error"] = f"Não foi possível consultar a fila '{printer_name}': {e}"
        return info

    attrs = parse_lpoptions_attrs(output)
    info["model"] = attrs.get("printer-make-and-model", "")
    info["device_uri"] = attrs.get("device-uri", "")
    state_code = attrs.get("printer-state", "3")
    info["state"] = state_code
    info["state_label"] = _STATE_LABELS.get(state_code, f"Estado {state_code}")
    info["state_reasons"] = attrs.get("printer-state-reasons", "none")
    info["is_accepting"] = attrs.get("printer-is-accepting-jobs", "true").lower() != "false"
    info["web_url"] = _extract_web_url(info["device_uri"])

    cmds_raw = attrs.get("printer-commands", "")
    if cmds_raw and cmds_raw.lower() != "none":
        info["printer_commands"] = [c.strip() for c in cmds_raw.split(",") if c.strip()]
    info["supports_clean"] = any(c.lower() == "clean" for c in info["printer_commands"])
    info["supports_selftest"] = any(c.lower() == "printselftestpage" for c in info["printer_commands"])
    info["is_usb_epson"] = (
        info["device_uri"].lower().startswith("usb://")
        and "epson" in (info["model"] + " " + info["device_uri"]).lower()
    )

    marker_names = _split_cups_csv(attrs.get("marker-names", ""))
    marker_levels = _split_cups_csv(attrs.get("marker-levels", ""))
    marker_colors = _split_cups_csv(attrs.get("marker-colors", ""))
    marker_types = _split_cups_csv(attrs.get("marker-types", ""))
    marker_lows = _split_cups_csv(attrs.get("marker-low-levels", ""))
    marker_highs = _split_cups_csv(attrs.get("marker-high-levels", ""))

    source = "cups" if marker_names and marker_levels else "none"

    if (not marker_names or not marker_levels) and query_network and info["device_uri"].startswith(("ipp://", "ipps://")):
        live_attrs = _query_ipptool_markers(info["device_uri"], timeout=1.5)
        if live_attrs.get("marker-names") and live_attrs.get("marker-levels"):
            marker_names = _split_cups_csv(live_attrs.get("marker-names", ""))
            marker_levels = _split_cups_csv(live_attrs.get("marker-levels", ""))
            marker_colors = _split_cups_csv(live_attrs.get("marker-colors", ""))
            marker_types = _split_cups_csv(live_attrs.get("marker-types", ""))
            marker_lows = _split_cups_csv(live_attrs.get("marker-low-levels", ""))
            marker_highs = _split_cups_csv(live_attrs.get("marker-high-levels", ""))
            source = "ipp"

    info["source"] = source

    try:
        ts = int(attrs.get("marker-change-time", "0") or "0")
        if ts > 0:
            info["last_updated"] = datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        elif source == "ipp":
            info["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass

    markers = []
    count = max(len(marker_names), len(marker_levels))
    for i in range(count):
        raw_name = marker_names[i] if i < len(marker_names) else f"Suprimento {i + 1}"
        m_type = marker_types[i] if i < len(marker_types) else "ink"
        m_color = _infer_marker_color(raw_name, marker_colors[i] if i < len(marker_colors) else "")

        try:
            level = int(marker_levels[i]) if i < len(marker_levels) else -1
        except ValueError:
            level = -1

        try:
            low_lvl = int(marker_lows[i]) if i < len(marker_lows) else 15
        except ValueError:
            low_lvl = 15

        try:
            high_lvl = int(marker_highs[i]) if i < len(marker_highs) else 100
        except ValueError:
            high_lvl = 100

        is_waste = m_type == "waste-ink" or raw_name.strip().lower() in ("mc", "waste-ink", "waste ink")
        threshold = max(low_lvl, 15) if not is_waste else (low_lvl if low_lvl > 0 else 15)
        is_low = (0 <= level <= threshold) or (level == -3 and not is_waste)

        markers.append({
            "name": _format_marker_name(raw_name, m_type),
            "raw_name": raw_name,
            "type": m_type,
            "type_label": _MARKER_TYPE_LABELS.get(m_type, m_type),
            "color": m_color,
            "level": level,
            "low_level": low_lvl,
            "high_level": high_lvl,
            "is_waste": is_waste,
            "is_low": is_low,
        })

    info["markers"] = markers
    return info


def format_ink_summary_line(info):
    """Formata um resumo curto em 1 linha dos níveis de tinta/toner: (texto, has_low)."""
    markers = info.get("markers") or []
    if not markers:
        return "", False
    parts = []
    has_low = False
    for m in markers:
        lvl = m["level"]
        if lvl < 0:
            continue
        short_name = m["name"].split("(")[0].strip()
        if m["is_waste"]:
            short_name = "Caixa Manut."
        if m["is_low"]:
            has_low = True
            parts.append(f"⚠️ {short_name}: {lvl}%")
        else:
            parts.append(f"{short_name}: {lvl}%")
    if not parts:
        return "", False
    return "🧴 Suprimentos: " + "  ·  ".join(parts), has_low


def generate_nozzle_check_pdf(output_path, printer_name="", is_mono=False):
    """
    Gera um PDF A4 vetorial de verificação visual de bicos e purga leve (CMYK + Preto).
    Se is_mono=True, gera apenas padrões de preto e escala de cinza.
    """
    w, h = 595.28, 841.89
    ops = []

    # Fundo branco + borda técnica fina
    ops.append("q\n1 w\n0.2 G\n28 28 539.28 785.89 re S\nQ\n")

    # Cabeçalho (em fontes padrão PDF Helvetica sem dependência externa)
    safe_printer = re.sub(r'[^\x20-\x7e]', '_', printer_name or "Impressora")
    safe_printer = safe_printer.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Barras de purga sólida + degraus (100%, 60%, 30%)
    if is_mono:
        channels = [
            ("Preto (K)", "0 0 0 1 k", "0 0 0 0.6 k", "0 0 0 0.25 k"),
            ("Cinza Escuro", "0 0 0 0.8 k", "0 0 0 0.45 k", "0 0 0 0.15 k"),
        ]
    else:
        channels = [
            ("Preto (K)", "0 0 0 1 k", "0 0 0 0.6 k", "0 0 0 0.25 k"),
            ("Ciano (C)", "1 0 0 0 k", "0.6 0 0 0 k", "0.25 0 0 0 k"),
            ("Magenta (M)", "0 1 0 0 k", "0 0.6 0 0 k", "0 0 0.25 0 k"),
            ("Amarelo (Y)", "0 0 1 0 k", "0 0 0.6 0 k", "0 0 0.25 0 k"),
        ]

    top_y = 665.0
    bar_h = 44.0
    gap = 20.0

    for idx, (label, c100, c60, c25) in enumerate(channels):
        y = top_y - idx * (bar_h + gap)
        ops.append(f"q\n{c100}\n50 {y:.2f} 240 {bar_h:.2f} re f\nQ\n")
        ops.append(f"q\n{c60}\n300 {y:.2f} 120 {bar_h:.2f} re f\nQ\n")
        ops.append(f"q\n{c25}\n430 {y:.2f} 115 {bar_h:.2f} re f\nQ\n")
        ops.append(f"q\n0.5 w\n0.4 G\n50 {y:.2f} 495 {bar_h:.2f} re S\nQ\n")
        ops.append(f"BT\n/F1 9 Tf\n0.2 G\n50 {y + bar_h + 4:.2f} Td\n({label}) Tj\nET\n")

    # Grade de escada fina (Nozzle Check) para detectar falhas individuais de bicos
    grid_y_base = 340.0
    for c_idx, (label, c100, _, _) in enumerate(channels):
        stroke_cmd = c100.replace(" k", " K")
        gx0 = 50.0 + c_idx * 126.0
        ops.append(f"BT\n/F1 9 Tf\n0.2 G\n{gx0:.2f} {grid_y_base + 14:.2f} Td\n({label}) Tj\nET\n")
        ops.append(f"q\n0.6 w\n{stroke_cmd}\n")
        for step in range(18):
            sy = grid_y_base - step * 10.0
            sx = gx0 + (step % 3) * 34.0
            ops.append(f"{sx:.2f} {sy:.2f} m {sx + 30.0:.2f} {sy:.2f} l S\n")
            if step % 3 == 0 and step < 15:
                ops.append(f"{sx:.2f} {sy:.2f} m {sx:.2f} {sy - 20.0:.2f} l S\n")
        ops.append("Q\n")

    # Cruzetas de alinhamento no rodapé
    ops.append("q\n0.8 w\n0 0 0 1 K\n")
    for cx in (120.0, 297.64, 475.0):
        cy = 95.0
        ops.append(f"{cx - 22:.2f} {cy:.2f} m {cx + 22:.2f} {cy:.2f} l S\n")
        ops.append(f"{cx:.2f} {cy - 22:.2f} m {cx:.2f} {cy + 22:.2f} l S\n")
        ops.append(f"{cx - 10:.2f} {cy - 10:.2f} 20 20 re S\n")
    ops.append("Q\n")

    # Texto informativo com fonte padrão Helvetica
    title_stream = (
        f"BT\n/F1 15 Tf\n0 0 0 1 k\n50 778 Td\n(Verificacao de Bicos e Alinhamento - {safe_printer}) Tj\n"
        f"/F1 10 Tf\n0 -18 Td\n(Gerado em: {now_str} | Gerenciador de Impressoes Pro) Tj\n"
        f"0 -18 Td\n(Confira falhas nas linhas finas abaixo e uniformidade nas barras solidas.) Tj\nET\n"
    )
    ops.append(title_stream)

    stream_bytes = "".join(ops).encode("latin-1", errors="replace")

    writer = PdfWriter()
    page = PageObject.create_blank_page(width=w, height=h)
    stream = DecodedStreamObject()
    stream.set_data(stream_bytes)
    page[NameObject("/Contents")] = stream

    from pypdf.generic import DictionaryObject
    font_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_dict})
    })
    page[NameObject("/Resources")] = resources
    writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def _build_lp_base(printer_name, cups_server=""):
    cmd = ["lp"]
    env = get_clean_host_env()
    if cups_server:
        cmd.extend(["-h", cups_server])
        env["CUPS_SERVER"] = cups_server
    else:
        env.pop("CUPS_SERVER", None)
    cmd.extend(["-d", printer_name])
    return cmd, env


def send_nozzle_check_page(printer_name, cups_server="", is_mono=False):
    if not printer_name or printer_name == "Salvar como PDF":
        raise ValueError("Selecione uma impressora física válida.")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        generate_nozzle_check_pdf(tmp_path, printer_name=printer_name, is_mono=is_mono)
        cmd, env = _build_lp_base(printer_name, cups_server)
        cmd.extend([
            "-t", "Verificacao de Bicos - Gerenciador Pro",
            "-o", "media=A4",
            "-o", "print-quality=4",
            "-o", "print-color-mode=monochrome" if is_mono else "print-color-mode=color",
            tmp_path,
        ])
        subprocess.check_call(cmd, env=env, timeout=10)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def send_cups_test_page(printer_name, cups_server=""):
    if not printer_name or printer_name == "Salvar como PDF":
        raise ValueError("Selecione uma impressora física válida.")

    test_candidates = [
        "/usr/share/cups/data/default-testpage.pdf",
        "/usr/share/cups/data/testprint",
    ]
    test_file = next((p for p in test_candidates if os.path.exists(p)), None)
    tmp_generated = None
    try:
        if not test_file:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_generated = tmp.name
            generate_nozzle_check_pdf(tmp_generated, printer_name=printer_name, is_mono=False)
            test_file = tmp_generated

        cmd, env = _build_lp_base(printer_name, cups_server)
        cmd.extend(["-t", "Pagina de Teste CUPS", test_file])
        subprocess.check_call(cmd, env=env, timeout=10)
    finally:
        if tmp_generated and os.path.exists(tmp_generated):
            try:
                os.remove(tmp_generated)
            except Exception:
                pass


def run_cups_maintenance_command(printer_name, command_text, cups_server=""):
    """
    Envia comando oficial application/vnd.cups-command para drivers compatíveis
    (ex.: Canon GX7000 'Clean all' / 'PrintSelfTestPage').
    """
    if not printer_name or printer_name == "Salvar como PDF":
        raise ValueError("Selecione uma impressora física válida.")

    payload = f"#CUPS-COMMAND\n{command_text.strip()}\n"
    with tempfile.NamedTemporaryFile("w", suffix=".cmd", encoding="utf-8", delete=False) as tmp:
        tmp.write(payload)
        tmp_path = tmp.name
    try:
        cmd, env = _build_lp_base(printer_name, cups_server)
        cmd.extend([
            "-t", f"Manutencao CUPS ({command_text.strip()})",
            "-o", "document-format=application/vnd.cups-command",
            tmp_path,
        ])
        subprocess.check_call(cmd, env=env, timeout=10)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def run_escputil_usb_maintenance(action="nozzle-check"):
    """Executa manutenção Epson via escputil quando conectada localmente por USB."""
    flag_map = {
        "clean": "--clean-head",
        "nozzle-check": "--nozzle-check",
        "align": "--align-head",
    }
    flag = flag_map.get(action)
    if not flag:
        raise ValueError(f"Ação escputil inválida: {action}")
    res = subprocess.run(
        ["escputil", flag, "-u"],
        text=True, capture_output=True, env=get_clean_host_env(), timeout=20
    )
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(detail or "Falha ao comunicar com a Epson USB via escputil.")
    return (res.stdout or "Comando enviado com sucesso.").strip()


def resume_cups_printer(printer_name, cups_server=""):
    """Tenta reativar e aceitar trabalhos na fila CUPS."""
    env = get_clean_host_env()
    host_args = ["-h", cups_server] if cups_server else []
    if cups_server:
        env["CUPS_SERVER"] = cups_server
    else:
        env.pop("CUPS_SERVER", None)

    for tool in ("cupsenable", "cupsaccept"):
        res = subprocess.run([tool] + host_args + [printer_name], text=True, capture_output=True, env=env, timeout=5)
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "").strip()
            raise RuntimeError(err or f"Falha ao executar {tool} em {printer_name}.")
