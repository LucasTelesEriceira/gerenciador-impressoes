import os
import json
import logging
from logging.handlers import RotatingFileHandler

# Versão Oficial do Sistema
CURRENT_VERSION = "v1.4.0"

# Diretórios e Arquivos de Configuração
SETTINGS_DIR = os.path.expanduser("~/.config/gerenciador_impressoes_pro")
CONFIG_DIR = SETTINGS_DIR
LOGS_DIR = os.path.join(SETTINGS_DIR, "logs")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
HISTORY_FILE = os.path.join(SETTINGS_DIR, "history.json")
LOG_FILE = os.path.join(LOGS_DIR, "app.log")

# Garantir existência dos diretórios
os.makedirs(SETTINGS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Configuração do Sistema Estruturado de Logging
logger = logging.getLogger("GerenciadorImpressoes")
logger.setLevel(logging.INFO)

if not logger.handlers:
    # Handler de rotação em arquivo (máx 5MB, até 3 backups)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s:%(filename)s:%(lineno)d]: %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler para saída no terminal/console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)

# Garantir localização dos certificados CA raiz para conexões seguras
if "SSL_CERT_FILE" not in os.environ:
    for _ca_bundle in [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/ca-bundle.pem",
        "/etc/ssl/cert.pem"
    ]:
        if os.path.exists(_ca_bundle):
            os.environ["SSL_CERT_FILE"] = _ca_bundle
            break


def get_clean_host_env():
    """
    Retorna o ambiente do sistema host limpo de variáveis injetadas pelo AppImage ou PyInstaller
    (como LD_LIBRARY_PATH, LD_PRELOAD, PYTHONHOME, PYTHONPATH).
    Isso impede que binários do sistema operacional (pdftoppm, libreoffice, lp, etc.)
    tentem carregar bibliotecas empacotadas no AppImage que causam incompatibilidade de versão (ex: libstdc++.so.6).
    """
    env = os.environ.copy()
    if "ORIG_LD_LIBRARY_PATH" in env:
        env["LD_LIBRARY_PATH"] = env["ORIG_LD_LIBRARY_PATH"]
    else:
        env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


SUPPORTED_EXTENSIONS = [
    '.pdf',
    '.docx', '.doc', '.odt', '.rtf', '.txt',
    '.xlsx', '.xls', '.ods', '.csv',
    '.pptx', '.ppt', '.odp'
]

SUPPORTED_MIME_TYPES = (
    "application/pdf;"
    "application/vnd.oasis.opendocument.text;"
    "application/vnd.oasis.opendocument.spreadsheet;"
    "application/vnd.oasis.opendocument.presentation;"
    "application/msword;"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
    "application/vnd.ms-excel;"
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;"
    "application/vnd.ms-powerpoint;"
    "application/vnd.openxmlformats-officedocument.presentationml.presentation;"
    "text/plain;"
    "text/rtf;"
    "text/csv;"
)


BUILTIN_PRESETS = {
    "Padrão do Sistema (Manual)": {},
    "Sublimação / Transfer (Canecas/Brindes)": {
        "mirror_horizontal": True,
        "quality_level": "high",
        "media_type_pref": ["glossy", "photo", "matte", "special"],
        "nup": "1 por folha",
        "poster": "Desativado",
        "cut_marks": "Desativado"
    },
    "Adesivo / Foto Glossy (Alta Definição)": {
        "mirror_horizontal": False,
        "quality_level": "high",
        "media_type_pref": ["glossy", "photo"],
        "speed_level": "normal",
        "nup": "1 por folha",
        "poster": "Desativado",
        "cut_marks": "Marcas de Corte nos Cantos (Cruzetas)"
    },
    "Escola: Provas e Atividades (Econômico)": {
        "color": "Preto e Branco",
        "quality_level": "draft",
        "speed_level": "fast",
        "media_type_pref": ["plain", "stationery"],
        "nup": "1 por folha",
        "poster": "Desativado",
        "mirror_horizontal": False,
        "cut_marks": "Desativado"
    },
    "Escola: Apostila Frente e Verso (2 em 1)": {
        "nup": "2 por folha",
        "duplex": "Frente e Verso (Borda Maior)",
        "color": "Preto e Branco",
        "poster": "Desativado",
        "mirror_horizontal": False,
        "cut_marks": "Linha Guia Pontilhada"
    },
    "Mural Escolar: Cartaz 2x2 (4 Folhas)": {
        "poster": "Cartaz 2x2 (4 folhas)",
        "poster_overlap_mm": 5.0,
        "nup": "1 por folha",
        "mirror_horizontal": False,
        "cut_marks": "Desativado"
    }
}


def get_all_presets(settings_dict):
    """Retorna dicionário unindo os presets de fábrica aos presets customizados do usuário."""
    presets = dict(BUILTIN_PRESETS)
    user_presets = settings_dict.get("custom_presets", {})
    if isinstance(user_presets, dict):
        presets.update(user_presets)
    return presets


def load_settings():
    default_settings = {
        "cups_server": "",
        "cups_port": 631,
        "default_printer": "Salvar como PDF",
        "default_paper": "A4",
        "default_media_type": "Papel Comum (Padrão)",
        "default_quality": "Normal (Padrão)",
        "default_print_speed": "Normal (Padrão)",
        "cost_per_sheet_cents": 5.0,
        "cost_per_page_ink_cents": 10.0,
        "keep_history": True,
        "max_history_entries": 100,
        "script_url": "https://raw.githubusercontent.com/LucasTelesEriceira/gerenciador-impressoes/main/instalar_impressoras.sh"
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_settings.update(data)
        except Exception as e:
            logger.warning(f"Falha ao carregar settings.json: {e}")
    return default_settings


def save_settings(settings_dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        logger.info("Configurações salvas com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao salvar configurações em {SETTINGS_FILE}: {e}")


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Falha ao carregar history.json: {e}")
    return []


def save_history_entry(entry):
    settings = load_settings()
    if not settings.get("keep_history", True):
        return
    history = load_history()
    history.insert(0, entry)
    max_entries = settings.get("max_history_entries", 100)
    history = history[:max_entries]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar entrada no histórico: {e}")


def clear_history():
    if os.path.exists(HISTORY_FILE):
        try:
            os.remove(HISTORY_FILE)
            logger.info("Histórico de impressões apagado.")
        except Exception as e:
            logger.error(f"Erro ao limpar histórico: {e}")
