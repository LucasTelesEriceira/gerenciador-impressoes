#!/usr/bin/env python3
import sys
import os
import subprocess
import shutil
import json
import urllib.request
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QComboBox, QSpinBox, 
                             QFileDialog, QMessageBox, QGroupBox, QFormLayout)
from PyQt5.QtCore import Qt

CURRENT_VERSION = "v1.0.0"

class PrintManagerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.file_path = ""
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle("Gerenciador Avançado de Impressão (Nativo)")
        self.resize(550, 600)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        
        # 1. Arquivo
        group_file = QGroupBox("1. Seleção de Documento")
        form_file = QFormLayout()
        self.lbl_file = QLabel("Nenhum arquivo selecionado")
        self.lbl_file.setStyleSheet("color: #2c3e50; font-weight: bold;")
        self.btn_select = QPushButton("Escolher Arquivo (PDF, DOCX, ODT)...")
        self.btn_select.clicked.connect(self.select_file)
        form_file.addRow(self.btn_select)
        form_file.addRow(QLabel("Arquivo:"), self.lbl_file)
        group_file.setLayout(form_file)
        main_layout.addWidget(group_file)
        
        # Opções de Impressão
        group_opts = QGroupBox("2. Configurações de Impressão")
        form_opts = QFormLayout()
        
        self.cb_printers = QComboBox()
        self.load_printers()
        form_opts.addRow("Impressora:", self.cb_printers)
        
        self.sp_copies = QSpinBox()
        self.sp_copies.setRange(1, 999)
        form_opts.addRow("Quantidade (Cópias):", self.sp_copies)
        
        self.cb_duplex = QComboBox()
        self.cb_duplex.addItems(["Apenas Frente", "Frente e Verso (Borda Maior)", "Frente e Verso (Borda Menor)"])
        form_opts.addRow("Frente e Verso:", self.cb_duplex)
        
        self.cb_color = QComboBox()
        self.cb_color.addItems(["Colorido (Padrão)", "Preto e Branco"])
        form_opts.addRow("Cores:", self.cb_color)
        
        self.cb_nup = QComboBox()
        self.cb_nup.addItems(["1 por folha", "2 por folha", "4 por folha", "6 por folha", "9 por folha"])
        form_opts.addRow("Agrupar (Slides/N-Up):", self.cb_nup)
        
        self.cb_poster = QComboBox()
        self.cb_poster.addItems(["Desativado", "Cartaz 2x2 (4 folhas A4)", "Cartaz 3x3 (9 folhas A4)", "Cartaz 4x4 (16 folhas A4)"])
        form_opts.addRow("Modo Cartaz (Pôster):", self.cb_poster)
        
        group_opts.setLayout(form_opts)
        main_layout.addWidget(group_opts)
        
        # Botão Ação
        self.btn_action = QPushButton("PROCESSAR E IMPRIMIR")
        self.btn_action.setMinimumHeight(50)
        self.btn_action.setStyleSheet("background-color: #27ae60; color: white; font-size: 14px; font-weight: bold; border-radius: 5px;")
        self.btn_action.clicked.connect(self.process_and_print)
        main_layout.addWidget(self.btn_action)
        
        # Botão de Atualização
        self.btn_update = QPushButton(f"Verificar Atualizações (Atual: {CURRENT_VERSION})")
        self.btn_update.setStyleSheet("background-color: #34495e; color: white; border-radius: 5px; padding: 5px;")
        self.btn_update.clicked.connect(self.check_for_updates)
        main_layout.addWidget(self.btn_update)
        
        self.setLayout(main_layout)

    def check_for_updates(self):
        try:
            self.btn_update.setText("Procurando...")
            self.btn_update.setEnabled(False)
            QApplication.processEvents()
            
            url = "https://api.github.com/repos/LucasTelesEriceira/gerenciador-impressoes/releases/latest"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                
            latest_version = data.get("tag_name", "")
            if latest_version and latest_version != CURRENT_VERSION:
                reply = QMessageBox.question(
                    self, 'Atualização Disponível!',
                    f"Uma nova versão ({latest_version}) foi encontrada!\n\nDeseja baixar e atualizar agora?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    self.perform_update(data)
            else:
                QMessageBox.information(self, "Atualizado", "Você já está usando a versão mais recente!")
                
        except Exception as e:
            QMessageBox.warning(self, "Erro", f"Não foi possível verificar atualizações.\n{str(e)}")
        finally:
            self.btn_update.setText(f"Verificar Atualizações (Atual: {CURRENT_VERSION})")
            self.btn_update.setEnabled(True)

    def perform_update(self, release_data):
        appimage_url = None
        for asset in release_data.get("assets", []):
            if asset.get("name", "").endswith(".AppImage"):
                appimage_url = asset.get("browser_download_url")
                break
                
        if not appimage_url:
            QMessageBox.warning(self, "Erro", "Arquivo .AppImage não encontrado no lançamento do GitHub.")
            return
            
        current_appimage = os.environ.get("APPIMAGE")
        if not current_appimage:
            QMessageBox.information(self, "Aviso", "O programa não está rodando como um AppImage isolado.\n(Para atualizar, você precisa rodar a versão compilada).")
            return
            
        try:
            self.btn_update.setText("Baixando atualização... Aguarde!")
            QApplication.processEvents()
            
            req = urllib.request.Request(appimage_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                with open(current_appimage, 'wb') as f:
                    shutil.copyfileobj(response, f)
            
            os.chmod(current_appimage, 0o755)
            
            QMessageBox.information(self, "Sucesso!", "Atualização concluída com sucesso!\nO aplicativo será reiniciado.")
            
            os.execv(current_appimage, [current_appimage] + sys.argv[1:])
            
        except Exception as e:
            QMessageBox.critical(self, "Erro fatal", f"Falha ao tentar baixar/aplicar a atualização:\n{str(e)}")
            self.btn_update.setText(f"Verificar Atualizações (Atual: {CURRENT_VERSION})")
            
    def load_printers(self):
        printers = ["Salvar como PDF"]
        try:
            output = subprocess.check_output(['lpstat', '-a'], text=True)
            for line in output.strip().split('\n'):
                if line:
                    printers.append(line.split()[0])
        except Exception:
            pass
        self.cb_printers.addItems(printers)

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecione o Documento", "", "Documentos (*.pdf *.docx *.doc *.odt *.txt *.rtf);;Todos (*)")
        if path:
            self.file_path = path
            self.lbl_file.setText(os.path.basename(path))

    def process_and_print(self):
        if not self.file_path:
            QMessageBox.warning(self, "Aviso", "Selecione um documento primeiro!")
            return
            
        printer = self.cb_printers.currentText()
        copies = self.sp_copies.value()
        
        self.btn_action.setText("Processando... Aguarde")
        self.btn_action.setEnabled(False)
        QApplication.processEvents()
        
        tmp_files = []
        current_file = self.file_path
        
        try:
            # 1. Converter se não for PDF usando LibreOffice
            if not current_file.lower().endswith('.pdf'):
                out_dir = "/tmp"
                subprocess.check_call(["libreoffice", "--headless", "--convert-to", "pdf", current_file, "--outdir", out_dir])
                base = os.path.splitext(os.path.basename(current_file))[0]
                converted = os.path.join(out_dir, f"{base}.pdf")
                if os.path.exists(converted):
                    current_file = converted
                    tmp_files.append(converted)
                else:
                    raise Exception("Falha na conversão para PDF pelo LibreOffice.")

            # 2. Modo Cartaz usando pdftools.pdfposter internamente
            poster_val = self.cb_poster.currentText()
            if poster_val != "Desativado":
                import pdftools.pdfposter.cmd
                scale = "2x2"
                if "3x3" in poster_val: scale = "3x3"
                if "4x4" in poster_val: scale = "4x4"
                
                poster_tmp = f"/tmp/poster_{os.getpid()}.pdf"
                
                # Intercepta sys.argv para simular chamada de comando
                old_argv = sys.argv
                sys.argv = ['pdfposter', '-m', 'a4', '-p', f'{scale}a4', current_file, poster_tmp]
                try:
                    pdftools.pdfposter.cmd.main()
                finally:
                    sys.argv = old_argv
                
                current_file = poster_tmp
                tmp_files.append(poster_tmp)
                
            # 3. Múltiplas Cópias via PyPDF nativo
            if copies > 1:
                from pypdf import PdfWriter, PdfReader
                copies_tmp = f"/tmp/copies_{os.getpid()}.pdf"
                
                writer = PdfWriter()
                reader = PdfReader(current_file)
                
                for _ in range(copies):
                    for page in reader.pages:
                        writer.add_page(page)
                
                with open(copies_tmp, "wb") as f:
                    writer.write(f)
                    
                current_file = copies_tmp
                tmp_files.append(copies_tmp)

            # 4. Finalização (Salvar PDF ou Enviar para Impressora)
            if printer == "Salvar como PDF":
                save_path, _ = QFileDialog.getSaveFileName(self, "Salvar PDF Processado", os.path.basename(current_file), "PDF (*.pdf)")
                if save_path:
                    shutil.copy(current_file, save_path)
                    QMessageBox.information(self, "Sucesso", f"Arquivo salvo com sucesso em:\n{save_path}")
            else:
                lp_args = ["lp", "-d", printer]
                
                # Duplex
                duplex_val = self.cb_duplex.currentText()
                if "Borda Maior" in duplex_val:
                    lp_args.extend(["-o", "sides=two-sided-long-edge"])
                elif "Borda Menor" in duplex_val:
                    lp_args.extend(["-o", "sides=two-sided-short-edge"])
                else:
                    lp_args.extend(["-o", "sides=one-sided"])
                    
                # Cor
                if "Preto" in self.cb_color.currentText():
                    lp_args.extend(["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"])
                else:
                    lp_args.extend(["-o", "print-color-mode=color"])
                    
                # N-Up
                nup_val = self.cb_nup.currentText()
                if nup_val != "1 por folha":
                    lp_args.extend(["-o", f"number-up={nup_val.split()[0]}"])
                    
                lp_args.extend(["-o", "media=A4", "-o", "fit-to-page", current_file])
                subprocess.check_call(lp_args)
                QMessageBox.information(self, "Sucesso", f"Enviado para a impressora {printer}!")
                
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Ocorreu um erro no processamento:\n{str(e)}")
            
        finally:
            self.btn_action.setText("PROCESSAR E IMPRIMIR")
            self.btn_action.setEnabled(True)
            for f in tmp_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Tenta usar o estilo Breeze nativo do KDE se disponível
    app.setStyle("Breeze")
    
    window = PrintManagerApp()
    window.show()
    sys.exit(app.exec_())
