"""
Validación de archivos subidos por estudiantes y usuarios externos.

Capas de defensa (en orden de costo creciente):
  1. Tamaño — rechaza antes de leer contenido
  2. Magic bytes — verifica que el contenido sea lo que dice ser
  3. Extensión — consistencia entre nombre y contenido
  4. Decodificación real:
       - Imágenes: Pillow intenta abrir y decodificar pixel a pixel
         (detecta polyglots y truncados), además limita dimensiones
       - PDFs: pypdf verifica estructura y rechaza si contiene JavaScript
  5. Re-serialización de imágenes: se devuelve la imagen limpia en memoria
     (sin EXIF ni payloads ocultos) cuando el llamador lo solicita
"""

import io
import logging
import os

import magic
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}

# Límites
MAX_BYTES = 10 * 1024 * 1024  # 10 MB en disco
MAX_IMAGE_PIXELS = 4000 * 4000  # 16 Mpx — mayor bloquea image bombs
MAX_PDF_PAGES = 200

# Pillow tiene su propia protección anti-decompression-bomb; la configuramos explícitamente
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def is_allowed(file_obj, size: int) -> tuple[bool, str | None]:
    """Valida extensión, magic bytes y estructura interna.

    No transforma el archivo — sólo decide si es aceptable.
    Para imágenes que serán almacenadas, llamar además a sanitize_image().
    """
    # 1. Tamaño
    if size > MAX_BYTES:
        return False, f"El archivo supera el máximo de {MAX_BYTES // (1024 * 1024)} MB."

    # 2. Magic bytes (contenido real, no Content-Type del cliente)
    try:
        file_obj.seek(0)
        buffer = file_obj.read(4096)
        file_obj.seek(0)
        actual_mime = magic.from_buffer(buffer, mime=True)
    except Exception:
        return False, "No se pudo leer el tipo de archivo."

    if actual_mime not in ALLOWED_MIMES:
        return False, f"Tipo de archivo no permitido: {actual_mime}."

    # 3. Extensión coherente con el contenido
    filename = getattr(file_obj, "name", "")
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXTS:
        return False, f"Extensión no permitida: {ext}."

    # 4a. Validación profunda de imagen
    if actual_mime.startswith("image/"):
        ok, err = _validate_image(file_obj)
        if not ok:
            return False, err

    # 4b. Validación profunda de PDF
    elif actual_mime == "application/pdf":
        ok, err = _validate_pdf(file_obj)
        if not ok:
            return False, err

    return True, None


def sanitize_image(file_obj) -> io.BytesIO:
    """Decodifica y re-serializa la imagen como JPEG sin EXIF ni metadata.

    Llamar sólo después de que is_allowed() devuelva True para una imagen.
    Devuelve un BytesIO listo para guardar (puntero al inicio).
    Levanta ValueError si la imagen no puede procesarse.
    """
    try:
        file_obj.seek(0)
        with Image.open(file_obj) as img:
            img.verify()  # Detecta truncados / datos corruptos al final

        file_obj.seek(0)
        with Image.open(file_obj) as img:
            img.load()  # Decodifica todos los píxeles
            # Convertir a RGB (descarta canal alpha, EXIF y perfiles ICC)
            rgb = img.convert("RGB")

        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=88, optimize=True)
        out.seek(0)
        return out
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(f"La imagen no pudo ser procesada: {exc}") from exc


# ── helpers internos ──────────────────────────────────────────────────────────


def _validate_image(file_obj) -> tuple[bool, str | None]:
    """Intenta decodificar la imagen con Pillow para detectar polyglots y truncados."""
    try:
        file_obj.seek(0)
        with Image.open(file_obj) as img:
            # Verifica cabecera y metadatos sin decodificar todos los píxeles
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        logger.warning("Imagen rechazada por Pillow: %s", exc)
        return False, "El archivo no es una imagen válida o está corrupto."
    except Image.DecompressionBombError:
        return False, "La imagen excede el límite de píxeles permitido."
    finally:
        # verify() cierra el archivo internamente en algunos casos; lo reseteamos
        try:
            file_obj.seek(0)
        except Exception:
            pass

    # Segunda pasada: decodificación real de píxeles (detecta payloads ocultos al final)
    try:
        file_obj.seek(0)
        with Image.open(file_obj) as img:
            img.load()
    except (OSError, SyntaxError) as exc:
        logger.warning("Imagen rechazada en decodificación completa: %s", exc)
        return False, "El archivo de imagen no pudo ser decodificado completamente."
    except Image.DecompressionBombError:
        return False, "La imagen excede el límite de píxeles permitido."
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass

    return True, None


def _validate_pdf(file_obj) -> tuple[bool, str | None]:
    """Verifica la estructura del PDF y rechaza si contiene JavaScript embebido o no puede inspeccionarse."""
    try:
        import pypdf

        file_obj.seek(0)
        reader = pypdf.PdfReader(file_obj, strict=False)

        if len(reader.pages) > MAX_PDF_PAGES:
            return False, f"El PDF supera el máximo de {MAX_PDF_PAGES} páginas."

        # Buscar JavaScript en el catálogo del documento
        catalog = reader.trailer.get("/Root", {})
        if _pdf_has_javascript(catalog):
            logger.warning("PDF rechazado: contiene JavaScript embebido en catálogo")
            return False, "El PDF contiene JavaScript y no está permitido."

        # Buscar en todas las páginas y sus anotaciones/acciones
        for idx, page in enumerate(reader.pages):
            if _pdf_has_javascript(page):
                logger.warning("PDF rechazado: página %d contiene JavaScript embebido", idx + 1)
                return False, "El PDF contiene JavaScript y no está permitido."

    except ValueError as exc:
        logger.warning("PDF rechazado por inspección de seguridad incompleta: %s", exc)
        return False, f"El archivo PDF no pudo ser verificado de forma segura: {exc}"
    except Exception as exc:
        logger.warning("PDF rechazado por error de estructura: %s", exc)
        return False, "El archivo PDF no tiene una estructura válida."
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass

    return True, None


def _pdf_has_javascript(obj, _visited=None, depth: int = 0) -> bool:
    """Recorre recursivamente el árbol de objetos del PDF buscando /JS o /JavaScript o acciones de script.

    Inspecciona eventos en /AA (/O, /C, /E, /X, /PO, /PC, etc.), anotaciones, catálogos y referencias indirectas,
    con protección contra ciclos y límite de profundidad.
    Si la inspección no puede completarse de forma segura (profundidad excesiva o falla de resolución),
    lanza ValueError para forzar el rechazo fail-closed del archivo.
    """
    if depth > 35:
        raise ValueError("El archivo PDF excede la profundidad máxima de anidamiento permitida.")

    if _visited is None:
        _visited = set()

    import pypdf.generic as g

    if isinstance(obj, g.IndirectObject) or (
        hasattr(obj, "get_object") and not isinstance(obj, (g.DictionaryObject, g.ArrayObject, dict, list))
    ):
        try:
            obj = obj.get_object()
        except Exception as exc:
            raise ValueError(f"No se pudo resolver un objeto indirecto del PDF: {exc}") from exc

    obj_id = id(obj)
    if obj_id in _visited:
        return False
    _visited.add(obj_id)

    if isinstance(obj, (g.DictionaryObject, dict)):
        for k, v in obj.items():
            k_str = str(k)
            if k_str in ("/JS", "/JavaScript", "JS", "JavaScript"):
                return True
            if k_str in ("/S", "S") and str(v) in ("/JavaScript", "JavaScript"):
                return True

        for k, v in obj.items():
            k_str = str(k)
            if k_str in ("/XObject", "/Font", "/ColorSpace", "/ProcSet"):
                continue

            if isinstance(v, (g.DictionaryObject, g.ArrayObject, g.IndirectObject, dict, list, tuple)) or hasattr(
                v, "get_object"
            ):
                if _pdf_has_javascript(v, _visited, depth + 1):
                    return True

    elif isinstance(obj, (g.ArrayObject, list, tuple)):
        for item in obj:
            if isinstance(item, (g.DictionaryObject, g.ArrayObject, g.IndirectObject, dict, list, tuple)) or hasattr(
                item, "get_object"
            ):
                if _pdf_has_javascript(item, _visited, depth + 1):
                    return True

    return False
