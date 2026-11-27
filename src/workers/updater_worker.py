import os
import json
import ssl
import urllib.request
import urllib.error
from PyQt5.QtCore import QThread, pyqtSignal
from src.config import logger

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
            logger.warning("Falha de validação de certificado SSL. Utilizando fallback unverified_context.")
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
            logger.error(f"Erro ao verificar atualizações: {e}")
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
                if total_size > 0 and downloaded < total_size:
                    raise Exception(f"Download incompleto ({downloaded} de {total_size} bytes baixados).")
                self.finished.emit(self.dest_path)
        except Exception as e:
            logger.error(f"Erro no download da atualização: {e}")
            self.error.emit(str(e))
