# Gerenciador Avançado de Impressão Escolar 🖨️

Este projeto é um utilitário desenvolvido especialmente para ambientes escolares (e para a distribuição **BigLinux**) para gerenciar impressões e contornar bugs crônicos de drivers de impressora.

## Recursos
- **Aba de Cópias via Software**: Se a sua impressora (como algumas da Brother e Epson em rede) ignoram pedidos de múltiplas cópias, este programa contorna o erro replicando as páginas do PDF em software (`pypdf`) e enviando um documento único para a impressora.
- **Função Cartaz**: Você precisa colar folhas A4 na parede? A Função Cartaz fatia o seu documento (ex: 2x2, 3x3) usando `pdfposter`.
- **Salvar como PDF**: O utilitário também permite exportar o documento com todos os efeitos (N-Up, Cartaz, etc) em um arquivo final PDF, agindo como uma "impressora virtual".
- **Conversão Automática**: Totalmente integrado com o `libreoffice` para converter arquivos Word (`.docx`, `.odt`, `.txt`) para PDF em background.
- **Sem dependências externas**: Processado internamente e empacotável em um formato AppImage!

## Instruções para Compilar o AppImage
1. `python3 -m venv venv`
2. `source venv/bin/activate`
3. `pip install pypdf pdftools.pdfposter PyQt5 pyinstaller`
4. `pyinstaller --onefile --windowed --hidden-import pdftools.pdfposter.cmd --hidden-import pypdf Gerenciador_Impressoes_Pro.py`