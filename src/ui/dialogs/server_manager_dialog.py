import os
import sys
import subprocess
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QTabWidget, 
                             QWidget, QFileDialog, QMessageBox, QComboBox, QCheckBox,
                             QScrollArea, QFrame)
from PyQt5.QtCore import QProcess, Qt, QTimer
from src.config import load_settings, save_settings, get_clean_host_env, logger

class ServerManagerDialog(QDialog):
    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        if hasattr(main_app, "settings"):
            self.settings = main_app.settings
        else:
            self.settings = main_app if isinstance(main_app, dict) else load_settings()

        self.setWindowTitle("Central do Servidor CUPS e Instalador de Drivers")
        self.resize(720, 560)
        self.process = None

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        tabs = QTabWidget()

        # =========================================================================
        # ABA 1: Servidor CUPS Local (Administração da Máquina Servidora)
        # =========================================================================
        tab_server = QWidget()
        layout_server = QVBoxLayout(tab_server)
        layout_server.setSpacing(10)

        server_info = QLabel(
            "<b>Painel de Administração do Servidor de Impressão CUPS:</b><br>"
            "Utilize esta ferramenta no computador que atua (ou atuará) como <b>Servidor Central de Impressão</b> da escola ou escritório. "
            "Aqui você ativa o compartilhamento na rede local e verifica o estado dos daemons CUPS e Avahi."
        )
        server_info.setWordWrap(True)
        server_info.setStyleSheet("border: 1px solid #94A3B8; padding: 10px; border-radius: 6px;")
        layout_server.addWidget(server_info)

        # Grupo de Status dos Daemons
        group_status = QGroupBox("Estado dos Serviços e Compartilhamento de Rede")
        form_status = QFormLayout(group_status)
        form_status.setVerticalSpacing(8)

        self.lbl_cups_service = QLabel("Consultando...")
        self.lbl_avahi_service = QLabel("Consultando...")
        self.lbl_sharing_status = QLabel("Consultando...")

        form_status.addRow("Serviço CUPS (cups.service):", self.lbl_cups_service)
        form_status.addRow("Descoberta de Rede (avahi-daemon):", self.lbl_avahi_service)
        form_status.addRow("Compartilhamento na Rede:", self.lbl_sharing_status)

        self.btn_refresh_status = QPushButton("🔄 Atualizar Status")
        self.btn_refresh_status.clicked.connect(self.check_local_server_status)
        form_status.addRow("", self.btn_refresh_status)

        layout_server.addWidget(group_status)

        # Grupo de Ações Administrativas
        group_actions = QGroupBox("Ações Administrativas (Requer senha de Administrador)")
        layout_actions = QVBoxLayout(group_actions)
        layout_actions.setSpacing(8)

        btns_admin_layout = QHBoxLayout()
        self.btn_enable_server = QPushButton("🚀 Ativar Modo Servidor na Rede")
        self.btn_enable_server.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 8px 12px; border-radius: 4px;")
        self.btn_enable_server.clicked.connect(self.enable_network_server)
        btns_admin_layout.addWidget(self.btn_enable_server)

        self.btn_restart_services = QPushButton("🔄 Reiniciar CUPS e Avahi")
        self.btn_restart_services.clicked.connect(self.restart_cups_services)
        btns_admin_layout.addWidget(self.btn_restart_services)

        self.btn_disable_server = QPushButton("🔒 Desativar Rede (Apenas Local)")
        self.btn_disable_server.clicked.connect(self.disable_network_server)
        btns_admin_layout.addWidget(self.btn_disable_server)

        layout_actions.addLayout(btns_admin_layout)
        layout_server.addWidget(group_actions)

        # Grupo de Filas Locais
        group_printers = QGroupBox("Impressoras Locais Instaladas nesta Máquina")
        layout_printers = QVBoxLayout(group_printers)
        self.txt_local_printers = QTextEdit()
        self.txt_local_printers.setReadOnly(True)
        self.txt_local_printers.setMaximumHeight(100)
        self.txt_local_printers.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout_printers.addWidget(self.txt_local_printers)
        layout_server.addWidget(group_printers)

        tabs.addTab(tab_server, "🖥️ Servidor CUPS Local")

        # =========================================================================
        # ABA 2: Instalação de Impressoras via Script
        # =========================================================================
        tab_script = QWidget()
        layout_script = QVBoxLayout(tab_script)
        layout_script.setSpacing(10)

        if sys.platform.startswith("linux"):
            script_info = QLabel(
                "<b>Instalação Automatizada de Drivers e Impressoras:</b><br>"
                "Baixe e execute scripts de instalação (.sh) para configurar impressoras automaticamente nesta máquina. "
                "Você pode utilizar a URL do GitHub ou selecionar um arquivo de script local."
            )
            script_info.setWordWrap(True)
            layout_script.addWidget(script_info)

            form_script = QFormLayout()
            self.txt_url = QLineEdit(self.settings.get("script_url", "https://raw.githubusercontent.com/LucasTelesEriceira/gerenciador-impressoes/main/instalar_impressoras.sh"))
            form_script.addRow("URL do Script (GitHub / Web):", self.txt_url)

            btn_browse_script = QPushButton("📁 Escolher Arquivo de Script Local (.sh)...")
            btn_browse_script.clicked.connect(self.browse_local_script)
            form_script.addRow("Ou arquivo local:", btn_browse_script)

            layout_script.addLayout(form_script)

            self.btn_run = QPushButton("🚀 Executar Script de Instalação")
            self.btn_run.setStyleSheet("background-color: #10B981; color: white; font-weight: bold; padding: 8px; border-radius: 4px;")
            self.btn_run.clicked.connect(self.run_installation)
            layout_script.addWidget(self.btn_run)

            self.log_console = QTextEdit()
            self.log_console.setReadOnly(True)
            self.log_console.setStyleSheet("background-color: #0F172A; color: #38BDF8; font-family: monospace; font-size: 11px; border-radius: 4px;")
            self.log_console.setPlaceholderText("A saída da execução do script aparecerá aqui...")
            layout_script.addWidget(self.log_console)
        else:
            win_notice = QLabel(
                "<h3>ℹ️ Gerenciamento no Windows</h3>"
                "<p>A execução de scripts Bash (.sh) com <code>pkexec</code> é exclusiva para sistemas Linux.</p>"
                "<p>No Windows, configure impressoras pelo Painel de Controle ou utilize as impressoras compartilhadas da rede.</p>"
            )
            win_notice.setWordWrap(True)
            layout_script.addWidget(win_notice)
            layout_script.addStretch()

        tabs.addTab(tab_script, "📥 Instalar via Script")

        # =========================================================================
        # ABA 3: Ajustes e Otimizações de Drivers & PPD (Hardware & Rotação Duplex)
        # =========================================================================
        tab_ppd = QWidget()
        layout_ppd = QVBoxLayout(tab_ppd)
        layout_ppd.setSpacing(10)

        if sys.platform.startswith("linux"):
            ppd_info = QLabel(
                "<b>Ajustes Avançados de Drivers e Arquivos PPD:</b><br>"
                "Drivers de impressoras no Linux frequentemente omitem diretivas essenciais ou vêm com opções de fábrica desligadas. "
                "Aqui você corrige a <b>rotação de 180° do verso no duplex</b> (evitando folhas impressas de ponta-cabeça), "
                "elimina páginas em branco extras e desbloqueia gavetas/módulos opcionais."
            )
            ppd_info.setWordWrap(True)
            ppd_info.setStyleSheet("border: 1px solid #94A3B8; padding: 10px; border-radius: 6px;")
            layout_ppd.addWidget(ppd_info)

            # Seletor de Fila Local
            group_select_queue = QGroupBox("Selecione a Impressora Local")
            layout_select_queue = QHBoxLayout(group_select_queue)
            layout_select_queue.setSpacing(10)

            self.cb_ppd_printers = QComboBox()
            self.cb_ppd_printers.currentIndexChanged.connect(self.on_ppd_printer_changed)
            layout_select_queue.addWidget(self.cb_ppd_printers, stretch=1)

            btn_refresh_ppds = QPushButton("🔄 Recarregar Filas")
            btn_refresh_ppds.clicked.connect(self.load_local_ppd_printers)
            layout_select_queue.addWidget(btn_refresh_ppds)

            layout_ppd.addWidget(group_select_queue)

            # Painel com as Opções de Ajuste
            scroll_ppd = QScrollArea()
            scroll_ppd.setWidgetResizable(True)
            scroll_ppd.setFrameShape(QFrame.NoFrame)

            content_ppd = QWidget()
            layout_opts_ppd = QVBoxLayout(content_ppd)
            layout_opts_ppd.setSpacing(10)

            group_tweaks = QGroupBox("Otimizações e Correções Disponíveis")
            form_tweaks = QFormLayout(group_tweaks)
            form_tweaks.setVerticalSpacing(10)

            # 1. cupsBackSide (Rotated)
            self.chk_opt_backside = QCheckBox("Inverter Rotação do Verso Duplex (*cupsBackSide: Rotated)")
            self.chk_opt_backside.setToolTip("Aplica rotação de 180° automática na face do verso pelo filtro pdftopdf. Corrige impressoras Brother, Ricoh e HP que imprimem o verso invertido.")
            self.lbl_status_backside = QLabel("Verificando...")
            self.lbl_status_backside.setStyleSheet("font-weight: bold;")
            form_tweaks.addRow(self.chk_opt_backside, self.lbl_status_backside)

            # 2. cupsEvenDuplex
            self.chk_opt_evenduplex = QCheckBox("Evitar Folha em Branco no Duplex (*cupsEvenDuplex: True)")
            self.chk_opt_evenduplex.setToolTip("Impede que a impressora ejete uma página em branco no final de trabalhos com número ímpar de páginas em frente e verso.")
            self.lbl_status_evenduplex = QLabel("Verificando...")
            self.lbl_status_evenduplex.setStyleSheet("font-weight: bold;")
            form_tweaks.addRow(self.chk_opt_evenduplex, self.lbl_status_evenduplex)

            # 3. InstalledDuplex
            self.chk_opt_installed_duplex = QCheckBox("Habilitar Unidade Duplex de Hardware (InstalledDuplex=True)")
            self.chk_opt_installed_duplex.setToolTip("Informa ao CUPS que o acessório mecânico de frente e verso está fisicamente instalado na máquina.")
            self.lbl_status_installed_duplex = QLabel("Verificando...")
            self.lbl_status_installed_duplex.setStyleSheet("font-weight: bold;")
            form_tweaks.addRow(self.chk_opt_installed_duplex, self.lbl_status_installed_duplex)

            # 4. LowerTray / Bandeja 2
            self.chk_opt_lower_tray = QCheckBox("Habilitar Bandeja Inferior / Gaveta 2 (LowerTray=Installed)")
            self.chk_opt_lower_tray.setToolTip("Desbloqueia a seleção da bandeja de alimentação inferior que costuma vir desativada de fábrica.")
            self.lbl_status_lower_tray = QLabel("Verificando...")
            self.lbl_status_lower_tray.setStyleSheet("font-weight: bold;")
            form_tweaks.addRow(self.chk_opt_lower_tray, self.lbl_status_lower_tray)

            # 5. Default Duplex Long Edge
            self.chk_opt_default_duplex = QCheckBox("Definir Duplex (Borda Longa) como Padrão de Fábrica")
            self.chk_opt_default_duplex.setToolTip("Define two-sided-long-edge como opção padrão para novos trabalhos da fila.")
            self.lbl_status_default_duplex = QLabel("Verificando...")
            self.lbl_status_default_duplex.setStyleSheet("font-weight: bold;")
            form_tweaks.addRow(self.chk_opt_default_duplex, self.lbl_status_default_duplex)

            layout_opts_ppd.addWidget(group_tweaks)

            # Botão de Ação
            self.btn_apply_ppd_tweaks = QPushButton("⚡ Aplicar Otimizações Selecionadas (Requer Administrador)")
            self.btn_apply_ppd_tweaks.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold; padding: 10px; border-radius: 6px; font-size: 13px;")
            self.btn_apply_ppd_tweaks.clicked.connect(self.apply_ppd_tweaks)
            layout_opts_ppd.addWidget(self.btn_apply_ppd_tweaks)

            self.lbl_ppd_action_status = QLabel("")
            self.lbl_ppd_action_status.setAlignment(Qt.AlignCenter)
            self.lbl_ppd_action_status.setStyleSheet("font-weight: bold; color: #059669;")
            layout_opts_ppd.addWidget(self.lbl_ppd_action_status)

            layout_opts_ppd.addStretch()
            scroll_ppd.setWidget(content_ppd)
            layout_ppd.addWidget(scroll_ppd)
        else:
            win_notice_ppd = QLabel(
                "<h3>ℹ️ Gerenciamento no Windows</h3>"
                "<p>A edição direta de arquivos PPD e comandos de driver CUPS é exclusiva para servidores/clientes Linux.</p>"
            )
            win_notice_ppd.setWordWrap(True)
            layout_ppd.addWidget(win_notice_ppd)
            layout_ppd.addStretch()

        tabs.addTab(tab_ppd, "⚙️ Ajustes de PPD e Drivers")

        main_layout.addWidget(tabs)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        main_layout.addWidget(btn_close)

        self.setLayout(main_layout)
        # Carregamento assíncrono para que a janela abra instantaneamente sem travar a UI
        QTimer.singleShot(50, self.check_local_server_status)
        if sys.platform.startswith("linux"):
            QTimer.singleShot(150, self.load_local_ppd_printers)

    def check_local_server_status(self):
        if not sys.platform.startswith("linux"):
            self.lbl_cups_service.setText("Não aplicável (Windows)")
            self.lbl_avahi_service.setText("Não aplicável (Windows)")
            self.lbl_sharing_status.setText("Não aplicável (Windows)")
            return

        env_local = get_clean_host_env()
        env_local.pop("CUPS_SERVER", None)

        # 1. CUPS Service
        try:
            out_cups = subprocess.check_output(["systemctl", "is-active", "cups"], text=True, stderr=subprocess.DEVNULL, timeout=1.5).strip()
            if out_cups == "active":
                self.lbl_cups_service.setText("🟢 <b>Ativo</b> (Em execução)")
            else:
                self.lbl_cups_service.setText(f"⚪ <b>{out_cups.capitalize()}</b>")
        except Exception:
            self.lbl_cups_service.setText("🔴 <b>Inativo / Não instalado</b>")

        # 2. Avahi Daemon
        try:
            out_avahi = subprocess.check_output(["systemctl", "is-active", "avahi-daemon"], text=True, stderr=subprocess.DEVNULL, timeout=1.5).strip()
            if out_avahi == "active":
                self.lbl_avahi_service.setText("🟢 <b>Ativo</b> (Descoberta na rede em funcionamento)")
            else:
                self.lbl_avahi_service.setText(f"⚪ <b>{out_avahi.capitalize()}</b>")
        except Exception:
            self.lbl_avahi_service.setText("🔴 <b>Inativo / Não instalado</b>")

        # 3. Sharing status via cupsctl (sempre local, com timeout de 2s)
        try:
            out_ctl = subprocess.check_output(["cupsctl"], env=env_local, text=True, stderr=subprocess.DEVNULL, timeout=2.0)
            is_shared = "_share_printers=1" in out_ctl and "_remote_any=1" in out_ctl
            if is_shared:
                self.lbl_sharing_status.setText("🟢 <b>Ativado</b> (Aceita conexões da rede local)")
            else:
                self.lbl_sharing_status.setText("⚪ <b>Desativado</b> (Apenas conexões locais)")
        except Exception:
            self.lbl_sharing_status.setText("⚪ Indisponível")

        # 4. Lista de impressoras locais
        try:
            out_lp = subprocess.check_output(["lpstat", "-p"], env=env_local, text=True, stderr=subprocess.DEVNULL, timeout=2.0).strip()
            if out_lp:
                self.txt_local_printers.setPlainText(out_lp)
            else:
                self.txt_local_printers.setPlainText("Nenhuma impressora configurada localmente nesta máquina.")
        except Exception:
            self.txt_local_printers.setPlainText("Não foi possível listar as impressoras locais.")

    def enable_network_server(self):
        if not sys.platform.startswith("linux"):
            return
        cmd = "cupsctl --remote-any --share-printers && systemctl enable --now cups avahi-daemon"
        self.execute_admin_command(cmd, "Ativação do Modo Servidor de Rede")

    def restart_cups_services(self):
        if not sys.platform.startswith("linux"):
            return
        cmd = "systemctl restart cups avahi-daemon"
        self.execute_admin_command(cmd, "Reinicialização dos Serviços CUPS e Avahi")

    def disable_network_server(self):
        if not sys.platform.startswith("linux"):
            return
        cmd = "cupsctl --no-remote-any --no-share-printers"
        self.execute_admin_command(cmd, "Desativação do Compartilhamento de Rede")

    def execute_admin_command(self, bash_cmd, action_name):
        full_cmd = f"pkexec bash -c '{bash_cmd}'"
        try:
            res = subprocess.run(full_cmd, shell=True, text=True, capture_output=True)
            if res.returncode == 0:
                QMessageBox.information(self, "Sucesso", f"{action_name} concluída com sucesso!")
                self.check_local_server_status()
            else:
                err = res.stderr.strip() or f"Código de saída: {res.returncode}"
                QMessageBox.warning(self, "Aviso", f"Não foi possível concluir a ação:\n{err}")
        except Exception as e:
            logger.error(f"Erro ao executar comando administrativo: {e}")
            QMessageBox.critical(self, "Erro", f"Falha ao executar comando:\n{str(e)}")

    def browse_local_script(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar Script de Instalação", "", "Scripts Shell (*.sh);;Todos os Arquivos (*)")
        if path:
            self.txt_url.setText(path)

    def run_installation(self):
        if not sys.platform.startswith("linux"):
            return
        target = self.txt_url.text().strip()
        if not target:
            QMessageBox.warning(self, "Aviso", "Informe a URL ou o arquivo do script.")
            return

        self.settings["script_url"] = target
        save_settings(self.settings)

        self.log_console.clear()
        self.btn_run.setEnabled(False)

        if target.startswith("http://") or target.startswith("https://"):
            self.log_console.append(f"[*] Baixando e iniciando script de: {target}\n")
            script_tmp = f"/tmp/install_printers_{os.getpid()}.sh"
            cmd = f"curl -sSL '{target}' -o '{script_tmp}' && chmod +x '{script_tmp}' && pkexec '{script_tmp}'"
        else:
            self.log_console.append(f"[*] Executando script local: {target}\n")
            cmd = f"chmod +x '{target}' && pkexec '{target}'"

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.on_finished)
        self.process.start("bash", ["-c", cmd])

    def on_stdout(self):
        if self.process:
            data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
            self.log_console.append(data)

    def on_stderr(self):
        if self.process:
            data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
            self.log_console.append(data)

    def on_finished(self, exit_code, exit_status):
        self.btn_run.setEnabled(True)
        if exit_code == 0:
            self.log_console.append("\n[✓] Processo concluído com sucesso!")
            self.check_local_server_status()
            if hasattr(self.main_app, "load_printers"):
                self.main_app.load_printers()
        else:
            self.log_console.append(f"\n[X] Processo finalizado com código de saída {exit_code}.")

    # =========================================================================
    # Métodos de Gerenciamento de Drivers & Arquivos PPD
    # =========================================================================
    def load_local_ppd_printers(self):
        if not sys.platform.startswith("linux"):
            return
        self.cb_ppd_printers.blockSignals(True)
        self.cb_ppd_printers.clear()

        printers = []
        # Obter filas que possuem arquivo PPD correspondente em /etc/cups/ppd/
        ppd_dir = "/etc/cups/ppd"
        if os.path.exists(ppd_dir):
            try:
                for f in sorted(os.listdir(ppd_dir)):
                    if f.endswith(".ppd"):
                        queue_name = f[:-4]
                        printers.append(queue_name)
            except Exception as e:
                logger.warning(f"Erro ao listar diretório {ppd_dir}: {e}")

        # Fallback para lpstat se diretório não puder ser lido
        if not printers:
            try:
                out = subprocess.check_output(["lpstat", "-p"], text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].lower() in ["impressora", "printer"]:
                        printers.append(parts[1])
            except Exception:
                pass

        for p in printers:
            self.cb_ppd_printers.addItem(p)

        self.cb_ppd_printers.blockSignals(False)
        self.lbl_ppd_action_status.setText("")
        self.on_ppd_printer_changed()

    def on_ppd_printer_changed(self):
        queue = self.cb_ppd_printers.currentText().strip()
        if not queue:
            self.btn_apply_ppd_tweaks.setEnabled(False)
            self.lbl_status_backside.setText("--")
            self.lbl_status_evenduplex.setText("--")
            self.lbl_status_installed_duplex.setText("--")
            self.lbl_status_lower_tray.setText("--")
            self.lbl_status_default_duplex.setText("--")
            return

        self.btn_apply_ppd_tweaks.setEnabled(True)
        self.check_printer_ppd_status(queue)

    def check_printer_ppd_status(self, queue):
        ppd_path = f"/etc/cups/ppd/{queue}.ppd"

        # 1. Checar diretivas PPD (*cupsBackSide e *cupsEvenDuplex)
        has_backside = False
        has_evenduplex = False
        try:
            # grep /etc/cups/ppd/
            res_bs = subprocess.run(f"grep -i 'cupsbackside' '{ppd_path}'", shell=True, capture_output=True, text=True)
            if res_bs.returncode == 0 and "rotated" in res_bs.stdout.lower():
                has_backside = True

            res_ed = subprocess.run(f"grep -i 'cupsevenduplex' '{ppd_path}'", shell=True, capture_output=True, text=True)
            if res_ed.returncode == 0 and "true" in res_ed.stdout.lower():
                has_evenduplex = True
        except Exception as e:
            logger.debug(f"Falha ao ler PPD via grep: {e}")

        if has_backside:
            self.lbl_status_backside.setText("🟢 Ativado (Rotated)")
            self.lbl_status_backside.setStyleSheet("color: #10B981; font-weight: bold;")
            self.chk_opt_backside.setChecked(True)
        else:
            self.lbl_status_backside.setText("⚪ Padrão / Não configurado")
            self.lbl_status_backside.setStyleSheet("color: #94A3B8; font-weight: normal;")
            self.chk_opt_backside.setChecked(False)

        if has_evenduplex:
            self.lbl_status_evenduplex.setText("🟢 Ativado (True)")
            self.lbl_status_evenduplex.setStyleSheet("color: #10B981; font-weight: bold;")
            self.chk_opt_evenduplex.setChecked(True)
        else:
            self.lbl_status_evenduplex.setText("⚪ Padrão / Não configurado")
            self.lbl_status_evenduplex.setStyleSheet("color: #94A3B8; font-weight: normal;")
            self.chk_opt_evenduplex.setChecked(False)

        # 2. Checar opções via lpoptions (InstalledDuplex, LowerTray, sides)
        opts_out = ""
        try:
            env_local = get_clean_host_env()
            env_local.pop("CUPS_SERVER", None)
            res_opt = subprocess.run(["lpoptions", "-p", queue, "-l"], env=env_local, capture_output=True, text=True, timeout=1.5)
            opts_out = res_opt.stdout
        except Exception:
            pass

        # InstalledDuplex
        if "InstalledDuplex" in opts_out or "Option1" in opts_out:
            if "*True" in opts_out or "*Installed" in opts_out:
                self.lbl_status_installed_duplex.setText("🟢 Ativado")
                self.lbl_status_installed_duplex.setStyleSheet("color: #10B981; font-weight: bold;")
                self.chk_opt_installed_duplex.setChecked(True)
            else:
                self.lbl_status_installed_duplex.setText("⚪ Desativado / Opcional")
                self.lbl_status_installed_duplex.setStyleSheet("color: #94A3B8; font-weight: normal;")
                self.chk_opt_installed_duplex.setChecked(False)
        else:
            self.lbl_status_installed_duplex.setText("⚪ Não listado no driver")
            self.lbl_status_installed_duplex.setStyleSheet("color: #94A3B8; font-weight: normal;")
            self.chk_opt_installed_duplex.setChecked(False)

        # LowerTray
        if "LowerTray" in opts_out:
            if "*Installed" in opts_out or "*True" in opts_out:
                self.lbl_status_lower_tray.setText("🟢 Ativada")
                self.lbl_status_lower_tray.setStyleSheet("color: #10B981; font-weight: bold;")
                self.chk_opt_lower_tray.setChecked(True)
            else:
                self.lbl_status_lower_tray.setText("⚪ Desativada")
                self.lbl_status_lower_tray.setStyleSheet("color: #94A3B8; font-weight: normal;")
                self.chk_opt_lower_tray.setChecked(False)
        else:
            self.lbl_status_lower_tray.setText("⚪ Não aplicável / Não listado")
            self.lbl_status_lower_tray.setStyleSheet("color: #94A3B8; font-weight: normal;")
            self.chk_opt_lower_tray.setChecked(False)

        # sides=two-sided-long-edge
        if "two-sided-long-edge" in opts_out:
            if "*two-sided-long-edge" in opts_out:
                self.lbl_status_default_duplex.setText("🟢 Padrão Ativo (Borda Longa)")
                self.lbl_status_default_duplex.setStyleSheet("color: #10B981; font-weight: bold;")
                self.chk_opt_default_duplex.setChecked(True)
            else:
                self.lbl_status_default_duplex.setText("⚪ Um lado (one-sided)")
                self.lbl_status_default_duplex.setStyleSheet("color: #94A3B8; font-weight: normal;")
                self.chk_opt_default_duplex.setChecked(False)
        else:
            self.lbl_status_default_duplex.setText("⚪ Fila sem duplex nativo")
            self.lbl_status_default_duplex.setStyleSheet("color: #94A3B8; font-weight: normal;")
            self.chk_opt_default_duplex.setChecked(False)

    def apply_ppd_tweaks(self):
        queue = self.cb_ppd_printers.currentText().strip()
        if not queue:
            QMessageBox.warning(self, "Aviso", "Selecione uma fila de impressão primeiro.")
            return

        ppd_path = f"/etc/cups/ppd/{queue}.ppd"
        bash_cmds = []

        # 1. Rotação do Verso (*cupsBackSide: Rotated)
        if self.chk_opt_backside.isChecked():
            # Remove ocorrências anteriores se houver, depois injeta após *CloseUI: *Duplex
            bash_cmds.append(f"sed -i '/\\*cupsBackSide:/d' '{ppd_path}'")
            bash_cmds.append(f"if grep -q '\\*CloseUI: \\*Duplex' '{ppd_path}'; then sed -i '/\\*CloseUI: \\*Duplex/a *cupsBackSide: Rotated' '{ppd_path}'; else echo '*cupsBackSide: Rotated' >> '{ppd_path}'; fi")
        else:
            bash_cmds.append(f"sed -i '/\\*cupsBackSide:/d' '{ppd_path}'")

        # 2. Folha em branco no duplex (*cupsEvenDuplex: True)
        if self.chk_opt_evenduplex.isChecked():
            bash_cmds.append(f"sed -i '/\\*cupsEvenDuplex:/d' '{ppd_path}'")
            bash_cmds.append(f"if grep -q '\\*CloseUI: \\*Duplex' '{ppd_path}'; then sed -i '/\\*CloseUI: \\*Duplex/a *cupsEvenDuplex: True' '{ppd_path}'; else echo '*cupsEvenDuplex: True' >> '{ppd_path}'; fi")
        else:
            bash_cmds.append(f"sed -i '/\\*cupsEvenDuplex:/d' '{ppd_path}'")

        # 3. Unidade Duplex instalada
        if self.chk_opt_installed_duplex.isChecked():
            bash_cmds.append(f"lpadmin -p '{queue}' -o InstalledDuplex=True || true")
            bash_cmds.append(f"lpadmin -p '{queue}' -o Option1=True || true")
        else:
            bash_cmds.append(f"lpadmin -p '{queue}' -o InstalledDuplex=False || true")

        # 4. Bandeja Inferior
        if self.chk_opt_lower_tray.isChecked():
            bash_cmds.append(f"lpadmin -p '{queue}' -o LowerTray=Installed || true")

        # 5. Duplex padrão borda longa
        if self.chk_opt_default_duplex.isChecked():
            bash_cmds.append(f"lpadmin -p '{queue}' -o sides=two-sided-long-edge || true")
        else:
            bash_cmds.append(f"lpadmin -p '{queue}' -o sides=one-sided || true")

        # Reiniciar CUPS para carregar novas diretivas PPD
        bash_cmds.append("systemctl restart cups")

        full_bash = " && ".join(bash_cmds)
        logger.info(f"Aplicando ajustes de PPD para a fila {queue}: {full_bash}")

        self.lbl_ppd_action_status.setText("⏳ Aplicando ajustes com privilégios de administrador...")
        self.btn_apply_ppd_tweaks.setEnabled(False)

        cmd_exec = f"pkexec bash -c \"{full_bash}\""
        try:
            res = subprocess.run(cmd_exec, shell=True, text=True, capture_output=True)
            self.btn_apply_ppd_tweaks.setEnabled(True)
            if res.returncode == 0:
                self.lbl_ppd_action_status.setText("✓ Otimizações aplicadas com sucesso!")
                QMessageBox.information(
                    self,
                    "Sucesso",
                    f"As otimizações da fila '{queue}' foram aplicadas com sucesso e o serviço CUPS foi reiniciado!"
                )
                self.check_printer_ppd_status(queue)
                if hasattr(self.main_app, "load_printers"):
                    self.main_app.load_printers()
            else:
                err = res.stderr.strip() or f"Código: {res.returncode}"
                self.lbl_ppd_action_status.setText("❌ Erro ao aplicar ajustes.")
                QMessageBox.warning(self, "Aviso", f"Não foi possível concluir os ajustes:\n{err}")
        except Exception as e:
            self.btn_apply_ppd_tweaks.setEnabled(True)
            self.lbl_ppd_action_status.setText("❌ Falha de execução.")
            logger.error(f"Erro ao aplicar ajustes de PPD: {e}")
            QMessageBox.critical(self, "Erro", f"Falha ao executar comando:\n{str(e)}")

# Alias para retrocompatibilidade
PrinterInstallerDialog = ServerManagerDialog
