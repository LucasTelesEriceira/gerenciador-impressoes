import os
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal
from src.cups.discovery import get_system_printers
from src.config import logger

class PrinterLoaderThread(QThread):
    """Thread não bloqueante para descoberta rápida de impressoras locais/remotas sem travar a interface."""
    printers_ready = pyqtSignal(list, str)

    def __init__(self, cups_server="", cups_port=631, default_printer="Salvar como PDF"):
        super().__init__()
        self.cups_server = cups_server
        self.cups_port = cups_port
        self.default_printer = default_printer
        self.active_cups_server = ""

    def run(self):
        # 1. Aplicar ambiente CUPS sem travar a interface
        self.active_cups_server = ""
        if self.cups_server:
            target = f"{self.cups_server}:{self.cups_port}" if ":" not in self.cups_server else self.cups_server
            try:
                subprocess.check_call(['lpstat', '-h', target, '-r'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                os.environ["CUPS_SERVER"] = target
                self.active_cups_server = target
                logger.info(f"Ambiente CUPS conectado ao servidor remoto: {target}")
            except Exception as e:
                logger.warning(f"Servidor CUPS remoto {target} inacessível: {e}")
                if "CUPS_SERVER" in os.environ:
                    del os.environ["CUPS_SERVER"]
        elif "CUPS_SERVER" in os.environ:
            del os.environ["CUPS_SERVER"]

        # 2. Descobrir impressoras usando somente o servidor efetivo (remoto acessível ou local)
        printers = ["Salvar como PDF"]
        try:
            detected = get_system_printers(self.active_cups_server, self.cups_port)
            for p in detected:
                if p not in printers:
                    printers.append(p)
        except Exception as e:
            logger.error(f"Erro ao listar impressoras na PrinterLoaderThread: {e}")

        self.printers_ready.emit(printers, self.default_printer)
