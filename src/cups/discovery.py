import os
import re
import subprocess
from PyQt5.QtPrintSupport import QPrinterInfo
from src.config import get_clean_host_env, logger

_CUPS_PRINTER_BW = 0x0004
_CUPS_PRINTER_COLOR = 0x0008


def get_system_printers(cups_server="", cups_port=631):
    """
    Busca todas as impressoras disponíveis no sistema ou no servidor CUPS remoto.
    Possui fallback automático para CUPS local se o servidor remoto não responder.
    """
    printers = []
    base_env = get_clean_host_env()

    # 1. Tentar servidor remoto especificado se houver
    if cups_server:
        target = f"{cups_server}:{cups_port}" if ":" not in cups_server else cups_server
        for cmd in [['lpstat', '-h', target, '-e'], ['lpstat', '-h', target, '-a']]:
            try:
                env = base_env.copy()
                env["CUPS_SERVER"] = target
                output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env, timeout=1.0)
                for line in output.splitlines():
                    if not line or line[0].isspace() or line.startswith('lpstat:'):
                        continue
                    name = line.split()[0].strip()
                    if name and name not in printers:
                        printers.append(name)
                if printers:
                    logger.info(f"Impressoras descobertas via servidor CUPS remoto ({target}): {printers}")
                    return printers
            except Exception as e:
                logger.debug(f"Falha ao consultar impressoras no servidor remoto {target}: {e}")

    # 2. Fallback para CUPS local (sem CUPS_SERVER remoto)
    env_local = base_env.copy()
    env_local.pop("CUPS_SERVER", None)

    for cmd in [['lpstat', '-e'], ['lpstat', '-a'], ['lpstat', '-p']]:
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, env=env_local, timeout=1.0)
            for line in output.splitlines():
                if not line or line[0].isspace() or line.startswith('lpstat:'):
                    continue
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
        except Exception as e:
            logger.debug(f"Falha ao consultar impressoras via CUPS local: {e}")

    # 3. Fallback nativo do sistema operacional (Windows / Qt / cups-browsed)
    if not printers:
        try:
            for p in QPrinterInfo.availablePrinterNames():
                if p and p not in printers:
                    printers.append(p)
        except Exception as e:
            logger.warning(f"Falha no fallback QPrinterInfo: {e}")

    logger.info(f"Total de impressoras detectadas no sistema: {len(printers)}")
    return printers


def is_monochrome_printer(printer_name, cups_server=""):
    """Detecta se uma impressora é monocromática (apenas Preto e Branco)."""
    if not printer_name or printer_name == "Salvar como PDF":
        return False

    env = get_clean_host_env()
    base_cmd = ['lpoptions', '-p', printer_name]
    if cups_server:
        base_cmd.extend(['-h', cups_server])
        env["CUPS_SERVER"] = cups_server
    else:
        env.pop("CUPS_SERVER", None)

    try:
        # 1. Verifica flags reais do CUPS (printer-type: CUPS_PRINTER_BW=0x4 sem CUPS_PRINTER_COLOR=0x8)
        output_attrs = subprocess.check_output(base_cmd, text=True, stderr=subprocess.DEVNULL, env=env, timeout=2.5)
        m_pt = re.search(r'printer-type=(\d+)', output_attrs)
        if m_pt:
            pt = int(m_pt.group(1))
            has_color = bool(pt & _CUPS_PRINTER_COLOR)
            has_bw = bool(pt & _CUPS_PRINTER_BW)

            m_mm = re.search(r"printer-make-and-model='([^']*)'|printer-make-and-model=(\S+)", output_attrs)
            make_model = (m_mm.group(1) or m_mm.group(2) or "") if m_mm else ""
            is_accepting = "printer-is-accepting-jobs=false" not in output_attrs

            # Ignora filas temporárias offline do cups-browsed que caem em 'Local Raw Printer' pausada
            if not (make_model == "Local Raw Printer" and not is_accepting):
                if has_bw and not has_color:
                    return True
    except Exception as e:
        logger.debug(f"Não foi possível verificar atributos CUPS da impressora {printer_name}: {e}")

    try:
        # 2. Verifica opções explícitas de cor no PPD (-l) caso o PPD declare ColorDevice=True mas só tenha Gray/Mono
        output_l = subprocess.check_output(base_cmd + ['-l'], text=True, stderr=subprocess.DEVNULL, env=env, timeout=2.5)
        color_found = False
        mono_only = False

        for line in output_l.splitlines():
            line_lower = line.lower()
            if any(k in line_lower for k in ('colormodel', 'print-color-mode', 'ink/')):
                if any(c in line_lower for c in ['rgb', 'cmyk', 'color', 'color=true']):
                    color_found = True
                elif any(m in line_lower for m in ['*gray', '*monochrome', '*mono']):
                    mono_only = True

        if color_found:
            return False
        if mono_only:
            return True
    except Exception as e:
        logger.debug(f"Não foi possível consultar PPD (-l) da impressora {printer_name}: {e}")

    try:
        # 3. Fallback nativo via QPrinterInfo (Windows / Qt)
        pinfo = QPrinterInfo.printerInfo(printer_name)
        if not pinfo.isNull() and pinfo.makeAndModel() != "Local Raw Printer":
            modes = pinfo.supportedColorModes()
            if modes and all(int(m) == 0 for m in modes):
                return True
    except Exception as e:
        logger.debug(f"Não foi possível verificar suporte de cor via Qt para {printer_name}: {e}")

    return False


def printer_supports_duplex(printer_name, cups_server=""):
    """Verifica se a impressora suporta duplex automático via PPD."""
    if not printer_name or printer_name == "Salvar como PDF":
        return True
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
        for line in output.splitlines():
            line_lower = line.lower()
            if 'duplex' in line_lower or 'sides' in line_lower:
                # Se contiver opções além de None (ex: DuplexNoTumble, DuplexTumble, two-sided-long-edge)
                if any(opt in line_lower for opt in ['duplexnotumble', 'duplextumble', 'two-sided', 'sides=two']):
                    return True
    except Exception as e:
        logger.debug(f"Não foi possível verificar duplex da impressora {printer_name}: {e}")
    return False

