# -*- coding: utf-8 -*-
"""
UI Dialogs package.
"""

from .history_dialog import HistoryDialog
from .settings_dialog import SettingsDialog
from .server_manager_dialog import ServerManagerDialog, PrinterInstallerDialog
from .queue_dialog import QueueDialog
from .maintenance_dialog import MaintenanceDialog
from .misc_dialogs import AboutDialog, ShortcutsDialog

__all__ = [
    "HistoryDialog",
    "SettingsDialog",
    "ServerManagerDialog",
    "PrinterInstallerDialog",
    "QueueDialog",
    "MaintenanceDialog",
    "AboutDialog",
    "ShortcutsDialog",
]
