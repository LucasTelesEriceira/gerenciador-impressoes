# Gerenciador de Impressões Pro 🖨️

Solução completa e de alta performance para preparação, pré-visualização, estimativa de custos e gerenciamento de impressão no **Linux (BigLinux / KDE Plasma / GNOME)** e **Windows**.

Desenvolvido para atender tanto **gráficas rápidas e estúdios de personalização/sublimação** quanto **escolas, secretarias e ambientes corporativos**.

---

## 🌟 Principais Recursos

### 🎨 Gráficas Rápidas e Personalizados (Sublimação & Brindes)
- **Espelhamento Horizontal para Sublimação (Flip Horizontal):** Inverte geometricamente páginas do PDF para transferência térmica em canecas, camisas, brindes e transfers têxteis, com pré-visualização em tempo real.
- **Marcas de Corte e Refile [RF-15]:** Adiciona cruzetas de precisão nos 4 cantos para guilhotina/estilete, bordas delimitadoras ou linhas guia pontilhadas. No modo N-Up, traça automaticamente a grade de divisão entre as células.
- **Modo Cartaz / Pôster com Sobreposição (Overlap) Ajustável:** Divide o documento em mosaicos (2x2 = 4 folhas, 3x3 = 9 folhas, 4x4 = 16 folhas) com margem configurável em milímetros (0 a 50 mm) para colagem e emenda perfeita de murais.
- **Impressão como Imagem (Rasterização 300 DPI):** Contorna falhas crônicas de fontes quebradas, vetores complexos do Corel/Illustrator e PostScript corrompido rasterizando o documento em alta resolução antes do envio ao CUPS.

### 🏫 Escolas e Escritórios
- **Presets Rápidos de Impressão:** Perfis instantâneos com 1 clique:
  - *Sublimação / Transfer (Canecas/Brindes)*
  - *Adesivo / Foto Glossy (Alta Definição)*
  - *Escola: Provas e Atividades (Econômico)*
  - *Escola: Apostila Frente e Verso (2 em 1)*
  - *Mural Escolar: Cartaz 2x2 (4 Folhas)*
  - *Perfis Customizados*: Crie, salve e gerencie seus próprios perfis.
- **Controle de Páginas Inteligente:** Seleção de intervalos específicos (`1-5, 8`), subconjuntos (apenas pares ou apenas ímpares) e ordem invertida (decrescente $N \to 1$).
- **Controle de Múltiplas Cópias via Software:** Duplicação garantida em nível de documento PDF para contornar drivers de rede (Brother, Epson, HP) que ignoram o comando de cópias do CUPS.
- **Suporte Multiformato N-Nativo:** Conversão transparente em background via LibreOffice para PDF, Word (`.docx`, `.doc`), OpenDocument (`.odt`, `.ods`, `.odp`), Planilhas (`.xlsx`, `.xls`, `.csv`), Slides (`.pptx`, `.ppt`) e Textos (`.txt`, `.rtf`).

### 💰 Gestão de Consumo e Segurança
- **Estimador de Papel e Custo em Tempo Real [RF-06]:** Calcula instantaneamente o consumo de folhas físicas e o valor total estimado em R$ com base em páginas selecionadas, N-Up, modo cartaz, duplex, cópias, tipo de papel e cor. Permite parametrizar custos unitários nas preferências.
- **Validação Pré-Impressão e Alertas [RF-08]:**
  - Impede disparos com intervalos vazios ou inválidos.
  - Alerta de grande volume (confirmação para $\ge 50$ folhas físicas).
  - Alerta de duplex em impressoras sem duplex automático por hardware.
  - Alerta de secagem para grandes lotes em papel fotográfico/adesivo.
- **Notificações Nativas do Desktop [RF-07]:** Notificações pop-up nativas via `notify-send` (libnotify/KDE Plasma) e bandeja do sistema (`QSystemTrayIcon`) ao término ou falha do trabalho.
- **Histórico e Fila CUPS:** Histórico com exportação CSV, reimpressão instantânea e gerenciador de fila CUPS em tempo real (`lpstat -o` / cancelamento de jobs).

---

## 🏗️ Arquitetura do Projeto

O projeto adota uma arquitetura limpa e modular desacoplada em `src/`:

```
Gerenciador-Impressoes-Pro/
├── Gerenciador_Impressoes_Pro.py   # Entrypoint oficial de execução
├── src/
│   ├── config.py                   # Configurações, presets, logs rotativos e ambiente limpo
│   ├── core/
│   │   ├── geometry.py             # Parser de páginas, dimensões e transformações geométricas
│   │   ├── layout.py               # Algoritmos N-Up, Modo Cartaz, Espelhamento e Marcas de Corte
│   │   └── raster.py               # Conversão LibreOffice e Rasterização anti-falhas em 300 DPI
│   ├── cups/
│   │   ├── discovery.py            # Descoberta de impressoras locais/remotas, duplex e monocromia
│   │   └── ppd.py                  # PPD/IPP de bandejas, qualidades, tipos de papel e velocidade
│   ├── workers/
│   │   ├── preview_worker.py       # Thread assíncrona de pré-visualização em alta velocidade
│   │   ├── print_worker.py         # Thread de processamento e despacho ao CUPS
│   │   ├── printer_loader.py       # Thread de carregamento de impressoras em background
│   │   └── updater_worker.py       # Thread de verificação e atualização automática
│   └── ui/
│       ├── main_window.py          # Janela principal e integração com BigLinux/Plasma
│       ├── widgets/                # Componentes customizados (DropZoneFrame, etc.)
│       └── dialogs/                # Diálogos de Histórico, Configurações, Servidor, Fila, Sobre
```

---

## 🚀 Como Executar

### Pré-requisitos (Linux):
```bash
sudo apt install python3-pyqt5 poppler-utils libreoffice cups cups-client
```

### Instalação de dependências:
```bash
pip install -r requirements.txt
```

### Executar diretamente:
```bash
python3 Gerenciador_Impressoes_Pro.py
```

---

## 📦 Construção do Pacote AppImage e Executável Windows

O repositório possui integração contínua (GitHub Actions) que compila automaticamente:
- **Linux:** Pacote `.AppImage` x86_64 compatível com BigLinux, Ubuntu, Debian, Fedora, Arch e KDE Plasma.
- **Windows:** Executável único `.exe` compilado via PyInstaller.

Para compilar localmente:
```bash
# Compilar binário via PyInstaller
pyinstaller --noconfirm --onedir --windowed \
  --name "Gerenciador_Impressoes_Pro" \
  --add-data "icon.png:." \
  --hidden-import pdftools.pdfposter.cmd \
  --hidden-import pypdf \
  Gerenciador_Impressoes_Pro.py
```