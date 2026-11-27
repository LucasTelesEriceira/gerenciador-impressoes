import os
import subprocess
import tempfile
from PIL import Image
from src.config import get_clean_host_env, logger

def convert_to_pdf_via_libreoffice(input_path, out_dir="/tmp"):
    """
    Converte qualquer documento suportado (.docx, .xlsx, .pptx, .odt, .txt, etc.)
    em PDF usando a instância headless do LibreOffice.
    """
    cmd = ["libreoffice", "--headless", "--convert-to", "pdf", input_path, "--outdir", out_dir]
    logger.info(f"Convertendo documento para PDF via LibreOffice: {input_path}")
    subprocess.check_call(cmd, env=get_clean_host_env())
    base = os.path.splitext(os.path.basename(input_path))[0]
    converted = os.path.join(out_dir, f"{base}.pdf")
    if os.path.exists(converted):
        return converted
    raise RuntimeError(f"Falha ao gerar arquivo PDF convertido em {converted}")


def rasterize_pdf_to_images_pdf(input_pdf_path, output_pdf_path, dpi=300):
    """
    Converte todas as páginas do documento PDF em imagens de alta resolução (DPI configurável)
    e reconstrói um PDF contendo unicamente essas imagens rasterizadas.
    Isso contorna falhas crônicas de drivers e RIPs com fontes corrompidas ou vetores complexos.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        prefix = os.path.join(tmp_dir, "rast_page")
        cmd = ["pdftoppm", "-png", "-r", str(dpi), input_pdf_path, prefix]
        logger.info(f"Rasterizando PDF em imagens a {dpi} DPI...")
        subprocess.check_call(cmd, env=get_clean_host_env())
        
        rendered_pngs = sorted([
            os.path.join(tmp_dir, f)
            for f in os.listdir(tmp_dir)
            if f.startswith("rast_page") and f.endswith(".png")
        ])
        
        if not rendered_pngs:
            raise RuntimeError("Nenhuma página pôde ser rasterizada pelo pdftoppm.")
        
        images = [Image.open(p).convert("RGB") for p in rendered_pngs]
        images[0].save(
            output_pdf_path,
            save_all=True,
            append_images=images[1:],
            resolution=float(dpi)
        )
        logger.info(f"PDF rasterizado com sucesso gerado em {output_pdf_path} ({len(images)} páginas).")
        return output_pdf_path
