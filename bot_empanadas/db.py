import json
import os
import random
import re
import string
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash


_SCHEMA_COLUMNS_CACHE = {}
_SENSITIVE_SCHEMA_INITIALIZED = False


def _sensitive_data_key():
    return (os.getenv("SENSITIVE_DATA_KEY", "") or "").strip()


def _sensitive_encryption_enabled():
    return bool(_sensitive_data_key())


def _db_config():
    db_timezone = (os.getenv("DB_TIMEZONE", "America/Chihuahua") or "America/Chihuahua").strip()
    cfg = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "que_chimba"),
        "user": os.getenv("DB_USER", "postgres"),
        "options": f"-c timezone={db_timezone}",
    }
    db_password = os.getenv("DB_PASSWORD")
    if db_password is not None and db_password != "":
        cfg["password"] = db_password
    return cfg


def get_connection():
    try:
        conn = psycopg2.connect(**_db_config())
        _asegurar_seguridad_datos_sensibles(conn)
        return conn
    except Exception as exc:
        raise RuntimeError(f"No se pudo conectar a PostgreSQL: {exc}") from exc


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Tipo no serializable: {type(value)}")


def _to_json_text(payload):
    if payload is None:
        return "{}"
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, default=_json_default)


def _normalizar_texto_busqueda(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tabla_tiene_columna(conn, tabla, columna):
    table_name = str(tabla or "").strip().lower()
    column_name = str(columna or "").strip().lower()
    if not table_name or not column_name:
        return False

    cache_key = (id(conn), table_name)
    cached_columns = _SCHEMA_COLUMNS_CACHE.get(cache_key)
    if cached_columns is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                """,
                (table_name,),
            )
            cached_columns = {str(row[0]).lower() for row in (cur.fetchall() or [])}
            _SCHEMA_COLUMNS_CACHE[cache_key] = cached_columns

    if column_name in cached_columns:
        return True

    # Reintento de seguridad por si la tabla cambio de estructura durante la ejecucion.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            (table_name, column_name),
        )
        exists = cur.fetchone() is not None
    if exists:
        _SCHEMA_COLUMNS_CACHE.setdefault(cache_key, set()).add(column_name)
    return exists


def _tabla_existe(conn, tabla):
    nombre = str(tabla or "").strip().lower()
    if not nombre:
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{nombre}",))
        return cur.fetchone()[0] is not None


def _directorio_documentos_facturas():
    base_dir = Path(__file__).resolve().parent.parent / "documents"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _nombre_archivo_factura(folio_factura, extension):
    folio_safe = str(folio_factura or "").strip().upper().replace(" ", "_").replace("/", "_")
    ext = str(extension or "").strip().lower().lstrip(".")
    if not folio_safe or not ext:
        return None
    return f"factura_{folio_safe}.{ext}"


def _folio_factura_automatico(pedido_id):
    try:
        return f"FAC-AUTO-{int(pedido_id):06d}"
    except Exception:
        return f"FAC-AUTO-{str(pedido_id or '').strip() or '000000'}"


def _obtener_datos_fiscales_por_cliente(conn, cliente_id):
    if not cliente_id:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if _tabla_existe(conn, "datos_fiscales"):
            cur.execute(
                """
                SELECT
                    fiscal_id AS datos_fiscales_id,
                    COALESCE(rfc, '') AS rfc,
                    COALESCE(razon_social, '') AS razon_social,
                    COALESCE(regimen_fiscal, '') AS regimen_fiscal,
                    COALESCE(uso_cfdi, '') AS uso_cfdi,
                    COALESCE(email, '') AS email
                FROM datos_fiscales
                WHERE cliente_id = %s
                ORDER BY fiscal_id DESC
                LIMIT 1
                """,
                (cliente_id,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        if _tabla_existe(conn, "datos_fiscales_clientes"):
            cur.execute(
                """
                SELECT
                    datos_fiscales_id,
                    COALESCE(rfc, '') AS rfc,
                    COALESCE(razon_social, '') AS razon_social,
                    COALESCE(regimen_fiscal, '') AS regimen_fiscal,
                    COALESCE(uso_cfdi, '') AS uso_cfdi,
                    COALESCE(email, '') AS email
                FROM datos_fiscales_clientes
                WHERE cliente_id = %s
                ORDER BY datos_fiscales_id DESC
                LIMIT 1
                """,
                (cliente_id,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

    return None


def _construir_xml_factura_operativa(pedido_id, folio_factura, pedido, cliente, fiscal, items):
    pedido_obj = pedido if isinstance(pedido, dict) else {}
    cliente_obj = cliente if isinstance(cliente, dict) else {}
    fiscal_obj = fiscal if isinstance(fiscal, dict) else {}
    rows = items if isinstance(items, list) else []

    lineas_items = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        cantidad = int(item.get("cantidad") or 0)
        precio = float(item.get("precio_unitario") or item.get("precio_unit") or 0)
        subtotal = float(item.get("subtotal") or (cantidad * precio))
        nombre = str(item.get("producto_nombre") or item.get("nombre") or item.get("producto") or "Producto")
        lineas_items.append(
            "    <item><nombre>{}</nombre><cantidad>{}</cantidad><precio_unitario>{:.2f}</precio_unitario><subtotal>{:.2f}</subtotal></item>".format(
                xml_escape(nombre),
                cantidad,
                precio,
                subtotal,
            )
        )

    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<factura_operativa version="1.0">',
            "  <folio>{}</folio>".format(xml_escape(str(folio_factura or ""))),
            "  <pedido_id>{}</pedido_id>".format(int(pedido_id or 0)),
            "  <fecha_emision>{}</fecha_emision>".format(xml_escape(datetime.utcnow().isoformat() + "Z")),
            "  <total>{:.2f}</total>".format(float(pedido_obj.get("total") or 0)),
            "  <cliente>",
            "    <cliente_id>{}</cliente_id>".format(int(cliente_obj.get("cliente_id") or 0)),
            "    <nombre>{}</nombre>".format(xml_escape(str(cliente_obj.get("nombre") or ""))),
            "    <apellidos>{}</apellidos>".format(xml_escape(str(cliente_obj.get("apellidos") or ""))),
            "    <whatsapp_id>{}</whatsapp_id>".format(xml_escape(str(cliente_obj.get("whatsapp_id") or ""))),
            "  </cliente>",
            "  <fiscal>",
            "    <datos_fiscales_id>{}</datos_fiscales_id>".format(int(fiscal_obj.get("datos_fiscales_id") or 0)),
            "    <rfc>{}</rfc>".format(xml_escape(str(fiscal_obj.get("rfc") or ""))),
            "    <razon_social>{}</razon_social>".format(xml_escape(str(fiscal_obj.get("razon_social") or ""))),
            "    <regimen_fiscal>{}</regimen_fiscal>".format(xml_escape(str(fiscal_obj.get("regimen_fiscal") or ""))),
            "    <uso_cfdi>{}</uso_cfdi>".format(xml_escape(str(fiscal_obj.get("uso_cfdi") or "G01"))),
            "    <email>{}</email>".format(xml_escape(str(fiscal_obj.get("email") or ""))),
            "  </fiscal>",
            "  <items>",
            *lineas_items,
            "  </items>",
            "</factura_operativa>",
        ]
    )


def preparar_factura_automatica_pedido(
    pedido_id,
    actor_usuario="sistema",
    requiere_factura_override=None,
    datos_fiscales_id_override=None,
    force=False,
):
    conn = None
    try:
        pedido_id_int = int(pedido_id or 0)
    except (TypeError, ValueError):
        return {"error": "Pedido invalido para preparar factura."}

    if pedido_id_int < 1:
        return {"error": "Pedido invalido para preparar factura."}

    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM pedidos
                WHERE pedido_id = %s
                LIMIT 1
                """,
                (pedido_id_int,),
            )
            pedido_row = cur.fetchone()
        pedido = dict(pedido_row) if pedido_row else None
        if not pedido:
            return {"error": "Pedido no encontrado."}

        if datos_fiscales_id_override:
            pedido["datos_fiscales_id"] = datos_fiscales_id_override

        if force:
            requiere_factura = True
        elif requiere_factura_override is not None:
            requiere_factura = bool(requiere_factura_override)
        else:
            requiere_factura = bool(pedido.get("requiere_factura")) if "requiere_factura" in pedido else bool(pedido.get("datos_fiscales_id"))

        if not requiere_factura:
            return {
                "prepared": False,
                "ready": False,
                "reason": "no_requiere_factura",
                "message": "El pedido no solicita factura.",
            }

        cliente_id = pedido.get("cliente_id")
        cliente = {}
        if cliente_id:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM clientes
                    WHERE cliente_id = %s
                    LIMIT 1
                    """,
                    (cliente_id,),
                )
                cliente_row = cur.fetchone()
            if cliente_row:
                cliente = dict(cliente_row)

        fiscal_data = None
        if pedido.get("datos_fiscales_id"):
            fiscal_data = obtener_datos_fiscales_por_id(pedido.get("datos_fiscales_id"))
            if not isinstance(fiscal_data, dict) or fiscal_data.get("error"):
                fiscal_data = {
                    "datos_fiscales_id": pedido.get("datos_fiscales_id"),
                    "rfc": "",
                    "razon_social": "",
                    "regimen_fiscal": "",
                    "uso_cfdi": "G01",
                    "email": "",
                }
        if not fiscal_data and cliente_id:
            fiscal_data = _obtener_datos_fiscales_por_cliente(conn, cliente_id)

        if not fiscal_data:
            return {
                "prepared": False,
                "ready": False,
                "reason": "datos_fiscales_incompletos",
                "message": "Pedido con factura solicitada, pero sin datos fiscales completos.",
            }

        folio = _folio_factura_automatico(pedido_id_int)
        invoice_row = registrar_factura_operativa(
            pedido_id=pedido_id_int,
            folio_factura=folio,
            status="emitida",
            notas="Auto-preparada al confirmar pedido con factura solicitada.",
            actor_usuario=(str(actor_usuario or "").strip() or "sistema"),
        )
        if isinstance(invoice_row, dict) and invoice_row.get("error"):
            return {"error": invoice_row.get("error")}

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    dp.detalle_id,
                    dp.producto_id,
                    dp.cantidad,
                    dp.precio_unitario,
                    (dp.cantidad * dp.precio_unitario) AS subtotal,
                    p.nombre AS producto_nombre,
                    NULL::TEXT AS descripcion
                FROM detalle_pedido dp
                LEFT JOIN productos p ON dp.producto_id = p.producto_id
                WHERE dp.pedido_id = %s
                ORDER BY dp.detalle_id ASC
                """,
                (pedido_id_int,),
            )
            item_rows = cur.fetchall() or []
        items = [dict(row) for row in item_rows]

        docs_dir = _directorio_documentos_facturas()
        pdf_path = docs_dir / _nombre_archivo_factura(folio, "pdf")
        xml_path = docs_dir / _nombre_archivo_factura(folio, "xml")

        pdf_ok = False
        pdf_error = None
        try:
            try:
                from services.pdf_service import generar_pdf_factura
            except Exception:
                from bot_empanadas.services.pdf_service import generar_pdf_factura

            pdf_res = generar_pdf_factura(
                pedido_id=pedido_id_int,
                folio_factura=folio,
                datos_cliente={
                    "nombre": cliente.get("nombre", "Cliente"),
                    "apellidos": cliente.get("apellidos", ""),
                    "whatsapp_id": cliente.get("whatsapp_id", ""),
                },
                datos_fiscales={
                    "rfc": fiscal_data.get("rfc", ""),
                    "razon_social": fiscal_data.get("razon_social", ""),
                    "regimen_fiscal": fiscal_data.get("regimen_fiscal", ""),
                    "uso_cfdi": fiscal_data.get("uso_cfdi", "G01"),
                    "email": fiscal_data.get("email", ""),
                },
                items_pedido=items or [],
                total=float(pedido.get("total") or 0),
                output_path=str(pdf_path),
            )
            if not (isinstance(pdf_res, dict) and pdf_res.get("error")) and pdf_path.exists():
                pdf_ok = True
            else:
                pdf_error = (pdf_res or {}).get("error") or "No se pudo generar PDF automatico."
        except Exception as exc:
            pdf_error = str(exc)

        xml_ok = False
        xml_error = None
        try:
            xml_content = _construir_xml_factura_operativa(
                pedido_id=pedido_id_int,
                folio_factura=folio,
                pedido=pedido,
                cliente=cliente,
                fiscal=fiscal_data,
                items=items,
            )
            xml_path.write_text(xml_content, encoding="utf-8")
            xml_ok = xml_path.exists()
        except Exception as exc:
            xml_error = str(exc)

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE facturas_operativas
                SET pdf_ruta = %s,
                    xml_ruta = %s,
                    actualizado_en = NOW()
                WHERE pedido_id = %s
                """,
                (
                    str(pdf_path) if pdf_ok else None,
                    str(xml_path) if xml_ok else None,
                    pedido_id_int,
                ),
            )
        conn.commit()

        combined_error = None
        if not pdf_ok or not xml_ok:
            combined_error = "; ".join(part for part in [pdf_error, xml_error] if part)
        registrar_resultado_envio_factura(
            pedido_id=pedido_id_int,
            envio_estado="pendiente" if (pdf_ok and xml_ok) else "error",
            destino=(cliente.get("whatsapp_id") if isinstance(cliente, dict) else None),
            error_detalle=combined_error,
            marcar_entregada=False,
        )

        return {
            "prepared": True,
            "ready": bool(pdf_ok and xml_ok),
            "folio_factura": folio,
            "pedido_id": pedido_id_int,
            "pdf_ruta": str(pdf_path) if pdf_ok else None,
            "xml_ruta": str(xml_path) if xml_ok else None,
            "error": combined_error,
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _candidatos_documento_factura(folio_factura, extension, ruta_guardada=None):
    ext = str(extension or "").strip().lower().lstrip(".")
    folio_safe = str(folio_factura or "").strip().upper().replace(" ", "_").replace("/", "_")
    if not ext:
        return []

    docs_dir = _directorio_documentos_facturas()
    tmp_dir = Path("/tmp") if os.name != "nt" else Path(os.environ.get("TEMP", "C:\\temp"))
    raw_candidates = []

    if ruta_guardada:
        stored = Path(str(ruta_guardada).strip())
        raw_candidates.append(stored)
        if not stored.is_absolute():
            raw_candidates.append(docs_dir / stored.name)

    if folio_safe:
        raw_candidates.extend([
            docs_dir / f"factura_{folio_safe}.{ext}",
            docs_dir / f"{folio_safe}.{ext}",
            tmp_dir / f"factura_{folio_safe}.{ext}",
            tmp_dir / f"{folio_safe}.{ext}",
        ])

    unique_candidates = []
    seen = set()
    for candidate in raw_candidates:
        candidate_str = str(candidate)
        if candidate_str in seen:
            continue
        seen.add(candidate_str)
        unique_candidates.append(candidate)
    return unique_candidates


def _resolver_documento_factura(folio_factura, extension, ruta_guardada=None):
    candidates = _candidatos_documento_factura(folio_factura, extension, ruta_guardada=ruta_guardada)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    if candidates:
        return str(candidates[0])
    return None


def _describir_documento_factura(folio_factura, extension, ruta_guardada=None):
    resolved_path = _resolver_documento_factura(folio_factura, extension, ruta_guardada=ruta_guardada)
    path_obj = Path(resolved_path) if resolved_path else None
    ready = bool(path_obj and path_obj.exists() and path_obj.is_file())
    filename = path_obj.name if path_obj else _nombre_archivo_factura(folio_factura, extension)
    size_bytes = path_obj.stat().st_size if ready else 0
    return {
        "extension": str(extension or "").strip().lower().lstrip("."),
        "filename": filename,
        "path": str(path_obj) if path_obj else resolved_path,
        "ready": ready,
        "size_bytes": size_bytes,
    }


def _whatsapp_id_parece_real(whatsapp_id):
    digits = re.sub(r"\D", "", str(whatsapp_id or ""))
    if not digits:
        return False
    if digits.startswith("521000") or digits.startswith("520000") or digits.startswith("521999123"):
        return False
    if len(digits) == 10:
        return True
    if len(digits) in {12, 13} and digits.startswith("52"):
        return True
    return False


def _parece_cliente_temporal(whatsapp_id, nombre=None, apellidos=None, total_pedidos=0):
    _ = re.sub(r"\D", "", str(whatsapp_id or ""))
    nombre_norm = _normalizar_texto_busqueda(nombre)
    apellidos_norm = _normalizar_texto_busqueda(apellidos)
    blob = f"{nombre_norm} {apellidos_norm}".strip()

    palabras_temporales = {
        "cliente",
        "confirmar",
        "menu",
        "pedido",
        "evento",
        "test",
        "prueba",
        "temporal",
        "validacion",
        "legacy",
        "sin nombre",
    }
    es_nombre_placeholder = (
        not nombre_norm
        or nombre_norm in palabras_temporales
        or apellidos_norm == "whatsapp"
        or any(token in blob for token in ("test", "prueba", "temporal", "validacion", "whatsapp"))
    )
    return bool(es_nombre_placeholder)


def _asegurar_seguridad_datos_sensibles(conn):
    global _SENSITIVE_SCHEMA_INITIALIZED

    key = _sensitive_data_key()
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION encrypt_sensitive_text(value TEXT)
            RETURNS BYTEA
            LANGUAGE plpgsql
            AS $$
            DECLARE
                k TEXT;
            BEGIN
                k := current_setting('app.sensitive_data_key', true);
                IF value IS NULL OR k IS NULL OR k = '' THEN
                    RETURN NULL;
                END IF;
                RETURN pgp_sym_encrypt(value, k, 'compress-algo=1, cipher-algo=aes256');
            END;
            $$
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION decrypt_sensitive_text(value BYTEA)
            RETURNS TEXT
            LANGUAGE plpgsql
            AS $$
            DECLARE
                k TEXT;
            BEGIN
                k := current_setting('app.sensitive_data_key', true);
                IF value IS NULL OR k IS NULL OR k = '' THEN
                    RETURN NULL;
                END IF;
                RETURN pgp_sym_decrypt(value, k);
            EXCEPTION WHEN OTHERS THEN
                RETURN NULL;
            END;
            $$
            """
        )

        if key:
            cur.execute("SELECT set_config('app.sensitive_data_key', %s, false)", (key,))

    if _SENSITIVE_SCHEMA_INITIALIZED:
        return

    with conn.cursor() as cur:
        cur.execute("ALTER TABLE direcciones_cliente ADD COLUMN IF NOT EXISTS latitud_enc BYTEA")
        cur.execute("ALTER TABLE direcciones_cliente ADD COLUMN IF NOT EXISTS longitud_enc BYTEA")
        cur.execute("ALTER TABLE direcciones_cliente ADD COLUMN IF NOT EXISTS direccion_texto_enc BYTEA")
        cur.execute("ALTER TABLE direcciones_cliente ADD COLUMN IF NOT EXISTS referencia_enc BYTEA")

        cur.execute("ALTER TABLE datos_fiscales ADD COLUMN IF NOT EXISTS rfc_enc BYTEA")
        cur.execute("ALTER TABLE datos_fiscales ADD COLUMN IF NOT EXISTS razon_social_enc BYTEA")
        cur.execute("ALTER TABLE datos_fiscales ADD COLUMN IF NOT EXISTS regimen_fiscal_enc BYTEA")
        cur.execute("ALTER TABLE datos_fiscales ADD COLUMN IF NOT EXISTS uso_cfdi_enc BYTEA")
        cur.execute("ALTER TABLE datos_fiscales ADD COLUMN IF NOT EXISTS email_enc BYTEA")

        cur.execute("ALTER TABLE proveedores ADD COLUMN IF NOT EXISTS email VARCHAR(120)")

        if key:
            cur.execute(
                """
                UPDATE direcciones_cliente
                SET
                    latitud_enc = COALESCE(latitud_enc, encrypt_sensitive_text(latitud::TEXT)),
                    longitud_enc = COALESCE(longitud_enc, encrypt_sensitive_text(longitud::TEXT)),
                    direccion_texto_enc = COALESCE(direccion_texto_enc, encrypt_sensitive_text(direccion_texto)),
                    referencia_enc = COALESCE(referencia_enc, encrypt_sensitive_text(referencia))
                WHERE latitud IS NOT NULL
                   OR longitud IS NOT NULL
                   OR COALESCE(direccion_texto, '') <> ''
                   OR COALESCE(referencia, '') <> ''
                """
            )
            cur.execute(
                """
                UPDATE direcciones_cliente
                SET
                    latitud = CASE WHEN latitud_enc IS NOT NULL THEN NULL ELSE latitud END,
                    longitud = CASE WHEN longitud_enc IS NOT NULL THEN NULL ELSE longitud END,
                    direccion_texto = CASE WHEN direccion_texto_enc IS NOT NULL THEN '' ELSE COALESCE(direccion_texto, '') END,
                    referencia = CASE WHEN referencia_enc IS NOT NULL THEN NULL ELSE referencia END
                """
            )

            cur.execute(
                """
                UPDATE datos_fiscales
                SET
                    rfc_enc = COALESCE(rfc_enc, encrypt_sensitive_text(rfc)),
                    razon_social_enc = COALESCE(razon_social_enc, encrypt_sensitive_text(razon_social)),
                    regimen_fiscal_enc = COALESCE(regimen_fiscal_enc, encrypt_sensitive_text(regimen_fiscal)),
                    uso_cfdi_enc = COALESCE(uso_cfdi_enc, encrypt_sensitive_text(uso_cfdi)),
                    email_enc = COALESCE(email_enc, encrypt_sensitive_text(email))
                WHERE COALESCE(rfc, '') <> ''
                   OR COALESCE(razon_social, '') <> ''
                   OR COALESCE(regimen_fiscal, '') <> ''
                   OR COALESCE(uso_cfdi, '') <> ''
                   OR COALESCE(email, '') <> ''
                """
            )
            cur.execute(
                """
                UPDATE datos_fiscales
                SET
                    rfc = CASE WHEN rfc_enc IS NOT NULL THEN NULL ELSE rfc END,
                    razon_social = CASE WHEN razon_social_enc IS NOT NULL THEN NULL ELSE razon_social END,
                    regimen_fiscal = CASE WHEN regimen_fiscal_enc IS NOT NULL THEN NULL ELSE regimen_fiscal END,
                    uso_cfdi = CASE WHEN uso_cfdi_enc IS NOT NULL THEN NULL ELSE uso_cfdi END,
                    email = CASE WHEN email_enc IS NOT NULL THEN NULL ELSE email END
                """
            )

    conn.commit()
    _SENSITIVE_SCHEMA_INITIALIZED = True


def _direccion_text_expr(alias="dc"):
    return f"COALESCE(decrypt_sensitive_text({alias}.direccion_texto_enc), {alias}.direccion_texto, '')"


ESTADOS_PEDIDO = {"recibido", "en_preparacion", "listo", "en_camino", "entregado", "cancelado"}
ROLES_USUARIO_SISTEMA = {"admin", "cocina", "repartidor"}
TRANSICIONES_PEDIDO_VALIDAS = {
    "recibido": {"en_preparacion", "cancelado"},
    "en_preparacion": {"listo", "cancelado"},
    "listo": {"en_camino", "entregado", "cancelado"},
    "en_camino": {"entregado", "cancelado"},
    "entregado": set(),
    "cancelado": set(),
}


def _normalizar_area_entrega(value):
    return (str(value or "").strip() or None)


def _normalizar_metodo_pago_finanzas(value):
    text = _normalizar_texto_busqueda(value)
    if not text:
        return "sin_definir"
    if text in {"efectivo", "cash"}:
        return "efectivo"
    if text in {"contra_entrega_ficticio", "contra_entrega", "pago_entrega_ficticio", "pago al entregar", "contra entrega"}:
        return "contra_entrega"
    if any(token in text for token in ("mercadopago", "mercado pago")):
        return "mercadopago"
    if any(token in text for token in ("transferencia", "spei", "deposito")):
        return "transferencia"
    if any(token in text for token in ("tarjeta", "credito", "debito", "digital")):
        return "digital"
    return text or "sin_definir"


def _clasificar_turno_operativo(value):
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return "sin_hora"
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return "sin_hora"

    if not isinstance(value, datetime):
        return "sin_hora"

    hour = int(value.hour)
    if 6 <= hour < 14:
        return "manana"
    if 14 <= hour < 20:
        return "tarde"
    return "noche"


def _clasificar_estado_factura_finanzas(requiere_factura, datos_fiscales_id=None, estado_pedido=None, factura_operativa_status=None):
    factura_status = _normalizar_texto_busqueda(factura_operativa_status)
    if factura_status in {"emitida", "entregada"}:
        return factura_status

    if not bool(requiere_factura):
        return "no_requiere"
    if not datos_fiscales_id:
        return "pendiente_datos"

    estado = _normalizar_texto_busqueda(estado_pedido)
    if estado == "entregado":
        return "lista_para_entrega"
    return "lista_para_emision"


def _clasificar_salud_producto_rentabilidad(precio_venta, costo_unitario, calidad_costo=None):
    calidad = _normalizar_texto_busqueda(calidad_costo)
    if calidad == "sin_receta":
        return "sin_receta"
    if calidad in {"sin_costos", "incompleto"}:
        return "sin_costos"

    precio = round(float(precio_venta or 0), 2)
    costo = round(float(costo_unitario or 0), 2)
    if precio <= 0:
        return "sin_precio"

    utilidad = round(precio - costo, 2)
    if utilidad <= 0:
        return "sin_utilidad"

    margen_pct = round((utilidad / precio) * 100, 2) if precio > 0 else 0.0
    if margen_pct < 20:
        return "margen_bajo"
    return "rentable"


def _resumir_coherencia_productos(rows):
    rows = rows if isinstance(rows, list) else []
    resumen = {
        "productos_auditados": len(rows),
        "productos_rentables": 0,
        "productos_sin_receta": 0,
        "productos_sin_costos": 0,
        "productos_sin_utilidad": 0,
        "productos_margen_bajo": 0,
    }
    for row in rows:
        salud = _clasificar_salud_producto_rentabilidad(
            row.get("precio_venta"),
            row.get("costo_estimado_unitario", row.get("costo_receta_actual")),
            row.get("calidad_costo", row.get("salud_rentabilidad")),
        )
        if salud == "sin_receta":
            resumen["productos_sin_receta"] += 1
        elif salud == "sin_costos":
            resumen["productos_sin_costos"] += 1
        elif salud == "sin_utilidad":
            resumen["productos_sin_utilidad"] += 1
        elif salud == "margen_bajo":
            resumen["productos_margen_bajo"] += 1
        elif salud == "rentable":
            resumen["productos_rentables"] += 1
    return resumen


def _evaluar_cobranza_pedido_finanzas(metodo_pago, estado_pedido, total, monto_pagado, estados_pago=""):
    metodo = _normalizar_metodo_pago_finanzas(metodo_pago)
    estado = _normalizar_texto_busqueda(estado_pedido)
    estados = _normalizar_texto_busqueda(estados_pago)
    total_num = round(max(float(total or 0), 0.0), 2)
    pagado_num = round(max(float(monto_pagado or 0), 0.0), 2)

    result = {
        "metodo_pago": metodo,
        "metodo_valido": metodo in {"efectivo", "mercadopago", "transferencia", "digital", "contra_entrega"},
        "monto_validado": 0.0,
        "pendiente": total_num,
        "status": "pendiente",
        "criterio": "sin_validacion",
    }

    if not result["metodo_valido"]:
        result["status"] = "metodo_invalido"
        result["criterio"] = "metodo_no_catalogado"
        return result

    if metodo in {"efectivo", "contra_entrega"}:
        if estado == "entregado":
            result["monto_validado"] = total_num
            result["pendiente"] = 0.0
            result["status"] = "validado"
            result["criterio"] = "cobro_contra_entrega_confirmado"
        elif pagado_num > 0:
            result["monto_validado"] = min(total_num, pagado_num)
            result["pendiente"] = round(max(total_num - result["monto_validado"], 0.0), 2)
            result["status"] = "validado" if result["pendiente"] <= 0.01 else "parcial"
            result["criterio"] = "registro_manual_de_cobro"
        else:
            result["status"] = "pendiente"
            result["criterio"] = "pendiente_de_entrega"
        return result

    result["monto_validado"] = min(total_num, pagado_num)
    result["pendiente"] = round(max(total_num - result["monto_validado"], 0.0), 2)

    estados_aprobados = ("approved", "accredited", "pagado", "paid")
    estados_rechazados = ("rejected", "cancelled", "canceled", "chargeback", "refunded")

    if any(token in estados for token in estados_rechazados) and result["monto_validado"] <= 0.01:
        result["status"] = "rechazado"
        result["criterio"] = "pasarela_rechazada"
    elif result["pendiente"] <= 0.01 and (not estados or any(token in estados for token in estados_aprobados)):
        result["status"] = "validado"
        result["criterio"] = "pasarela_confirmada"
    elif result["monto_validado"] > 0:
        result["status"] = "parcial"
        result["criterio"] = "pago_parcial"
    else:
        result["status"] = "pendiente"
        result["criterio"] = "sin_confirmacion_de_pasarela"

    return result


def _registrar_pago_conciliado_cur(cur, pedido_id, monto, proveedor, referencia=None, detalle=None):
    monto_num = round(max(float(monto or 0), 0.0), 2)
    referencia_final = (str(referencia or "").strip() or f"{str(proveedor or 'manual').upper()}-{pedido_id}")[:120]
    detalle_final = str(detalle or "pago conciliado manualmente al momento de la entrega").strip()

    cur.execute(
        """
        SELECT pago_id
        FROM pagos
        WHERE pedido_id = %s
        ORDER BY pago_id DESC
        LIMIT 1
        """,
        (pedido_id,),
    )
    pago = cur.fetchone()

    if pago and pago.get("pago_id"):
        cur.execute(
            """
            UPDATE pagos
            SET
                monto = %s,
                proveedor = %s,
                estado = 'pagado',
                mp_payment_id = %s,
                mp_status_detail = %s,
                actualizado_en = NOW()
            WHERE pago_id = %s
            """,
            (monto_num, proveedor, referencia_final, detalle_final, pago.get("pago_id")),
        )
        return pago.get("pago_id")

    cur.execute(
        """
        INSERT INTO pagos (
            pedido_id,
            monto,
            proveedor,
            estado,
            mp_payment_id,
            mp_status_detail,
            creado_en,
            actualizado_en
        )
        VALUES (%s, %s, %s, 'pagado', %s, %s, NOW(), NOW())
        RETURNING pago_id
        """,
        (pedido_id, monto_num, proveedor, referencia_final, detalle_final),
    )
    return (cur.fetchone() or {}).get("pago_id")


def _score_area_cercania(area_pedido, area_repartidor):
    pedido = (_normalizar_area_entrega(area_pedido) or "").lower()
    repartidor = (_normalizar_area_entrega(area_repartidor) or "").lower()
    if not pedido or not repartidor:
        return -1

    if pedido == repartidor:
        return 10000

    if pedido.isdigit() and repartidor.isdigit() and len(pedido) == 5 and len(repartidor) == 5:
        return max(0, 8000 - abs(int(pedido) - int(repartidor)))

    common = 0
    for cp, cr in zip(pedido, repartidor):
        if cp != cr:
            break
        common += 1

    return common * 100


def _seleccionar_repartidor_para_area_cur(cur, area_pedido):
    cur.execute(
        """
        SELECT
            u.username,
            u.area_entrega,
            COALESCE(
                (
                    SELECT COUNT(1)
                    FROM asignaciones_reparto ar
                    JOIN pedidos p ON p.pedido_id = ar.pedido_id
                    WHERE ar.repartidor_usuario = u.username
                      AND ar.activo = TRUE
                      AND p.estado IN ('listo', 'en_camino')
                ),
                0
            )::INT AS carga_activa
        FROM usuarios_sistema u
        WHERE u.rol = 'repartidor'
          AND u.activo = TRUE
          AND COALESCE(NULLIF(TRIM(u.area_entrega), ''), '') <> ''
        """
    )
    candidatos = cur.fetchall() or []
    if not candidatos:
        return None

    scoreados = []
    for cand in candidatos:
        score = _score_area_cercania(area_pedido, cand.get("area_entrega"))
        if score < 0:
            continue
        scoreados.append(
            {
                "username": cand.get("username"),
                "area_entrega": cand.get("area_entrega"),
                "carga_activa": int(cand.get("carga_activa") or 0),
                "score_area": int(score),
            }
        )

    if not scoreados:
        return None

    scoreados.sort(key=lambda x: (-x["score_area"], x["carga_activa"], str(x["username"] or "")))
    return scoreados[0]


def _auto_asignar_repartidor_pedido_cur(cur, pedido_id, asignado_por="sistema_auto"):
    direccion_expr = _direccion_text_expr("dc")
    cur.execute(
        """
        SELECT ar.asignacion_id, ar.pedido_id, ar.repartidor_usuario, ar.asignado_por, ar.asignado_en, ar.activo
        FROM asignaciones_reparto ar
        WHERE ar.pedido_id = %s AND ar.activo = TRUE
        LIMIT 1
        """,
        (pedido_id,),
    )
    ya_asignado = cur.fetchone()
    if ya_asignado:
        return ya_asignado

    cur.execute(
        f"""
        SELECT
            p.pedido_id,
            p.estado,
            COALESCE(NULLIF(TRIM(dc.alias), ''), NULLIF(TRIM(dc.codigo_postal), ''), COALESCE(NULLIF(SUBSTRING({direccion_expr} FROM '([0-9]{{5}})'), ''), '00000')) AS area_entrega
        FROM pedidos p
        LEFT JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
        WHERE p.pedido_id = %s
        LIMIT 1
        """,
        (pedido_id,),
    )
    pedido = cur.fetchone()
    if not pedido:
        return None

    estado = (pedido.get("estado") or "").strip().lower()
    if estado not in {"listo", "en_camino"}:
        return None

    seleccionado = _seleccionar_repartidor_para_area_cur(cur, pedido.get("area_entrega"))
    if not seleccionado:
        return None

    cur.execute(
        """
        UPDATE asignaciones_reparto
        SET activo = FALSE
        WHERE pedido_id = %s AND activo = TRUE
        """,
        (pedido_id,),
    )

    cur.execute(
        """
        INSERT INTO asignaciones_reparto (pedido_id, repartidor_usuario, asignado_por, activo)
        VALUES (%s, %s, %s, TRUE)
        RETURNING asignacion_id, pedido_id, repartidor_usuario, asignado_por, asignado_en, activo
        """,
        (pedido_id, seleccionado.get("username"), asignado_por),
    )
    nueva = cur.fetchone()
    if nueva is not None:
        nueva["area_entrega"] = seleccionado.get("area_entrega")
        nueva["score_area"] = seleccionado.get("score_area")
        nueva["carga_activa"] = seleccionado.get("carga_activa")
    return nueva


def _asegurar_tabla_usuarios_sistema(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios_sistema (
                usuario_id BIGSERIAL PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                rol VARCHAR(30) NOT NULL,
                nombre_mostrar VARCHAR(120) NOT NULL,
                telefono VARCHAR(30),
                area_entrega VARCHAR(80),
                activo BOOLEAN NOT NULL DEFAULT TRUE,
                intentos_fallidos SMALLINT NOT NULL DEFAULT 0,
                bloqueado_hasta TIMESTAMP,
                ultimo_login TIMESTAMP,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                actualizado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_usuarios_sistema_rol CHECK (rol IN ('admin', 'cocina', 'repartidor')),
                CONSTRAINT chk_usuarios_sistema_hash_len CHECK (char_length(password_hash) >= 20)
            )
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS intentos_fallidos SMALLINT NOT NULL DEFAULT 0
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMP
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS ultimo_login TIMESTAMP
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMP NOT NULL DEFAULT NOW()
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS area_entrega VARCHAR(80)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usuarios_sistema_rol_activo
                ON usuarios_sistema (rol, activo)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usuarios_sistema_reparto_area
                ON usuarios_sistema (rol, area_entrega)
                WHERE activo = TRUE
            """
        )


def _bootstrap_usuarios_por_rol(conn):
    defaults = {
        "admin": {
            "username": os.getenv("ADMIN_DEFAULT_USERNAME", "admin").strip() or "admin",
            "password": (os.getenv("ADMIN_DEFAULT_PASSWORD", "") or "").strip(),
            "nombre": os.getenv("ADMIN_DEFAULT_NAME", "Administrador"),
        },
        "cocina": {
            "username": os.getenv("COCINA_DEFAULT_USERNAME", "cocina").strip() or "cocina",
            "password": (os.getenv("COCINA_DEFAULT_PASSWORD", "") or "").strip(),
            "nombre": os.getenv("COCINA_DEFAULT_NAME", "Operador Cocina"),
        },
        "repartidor": {
            "username": os.getenv("REPARTIDOR_DEFAULT_USERNAME", "repartidor").strip() or "repartidor",
            "password": (os.getenv("REPARTIDOR_DEFAULT_PASSWORD", "") or "").strip(),
            "nombre": os.getenv("REPARTIDOR_DEFAULT_NAME", "Operador Reparto"),
            "area_entrega": _normalizar_area_entrega(os.getenv("REPARTIDOR_DEFAULT_AREA", "juarez-centro")),
        },
    }

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for rol, data in defaults.items():
            cur.execute(
                """
                SELECT 1
                FROM usuarios_sistema
                WHERE rol = %s AND activo = TRUE
                LIMIT 1
                """,
                (rol,),
            )
            if cur.fetchone():
                continue

            if not data["password"]:
                raise RuntimeError(
                    f"Falta {rol.upper()}_DEFAULT_PASSWORD para crear el usuario inicial de rol '{rol}'."
                )

            cur.execute(
                """
                INSERT INTO usuarios_sistema (username, password_hash, rol, nombre_mostrar, area_entrega, activo)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (username) DO NOTHING
                """,
                (
                    data["username"],
                    generate_password_hash(data["password"]),
                    rol,
                    data["nombre"],
                    data.get("area_entrega") if rol == "repartidor" else None,
                ),
            )


def _asegurar_tabla_auditoria_seguridad(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auditoria_seguridad (
                auditoria_id BIGSERIAL PRIMARY KEY,
                tipo_evento VARCHAR(50) NOT NULL,
                severidad VARCHAR(15) NOT NULL DEFAULT 'info',
                actor_usuario_id BIGINT,
                actor_username VARCHAR(80),
                actor_rol VARCHAR(30),
                objetivo_usuario_id BIGINT,
                objetivo_username VARCHAR(80),
                direccion_ip VARCHAR(64),
                detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_auditoria_seguridad_severidad CHECK (severidad IN ('info', 'warning', 'critical'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_seguridad_creado_en
                ON auditoria_seguridad (creado_en DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_seguridad_tipo_evento
                ON auditoria_seguridad (tipo_evento, creado_en DESC)
            """
        )


def _registrar_auditoria_seguridad_cur(
    cur,
    tipo_evento,
    severidad="info",
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    objetivo_usuario_id=None,
    objetivo_username=None,
    direccion_ip=None,
    detalle=None,
):
    cur.execute(
        """
        INSERT INTO auditoria_seguridad (
            tipo_evento,
            severidad,
            actor_usuario_id,
            actor_username,
            actor_rol,
            objetivo_usuario_id,
            objetivo_username,
            direccion_ip,
            detalle
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            tipo_evento,
            severidad,
            actor_usuario_id,
            actor_username,
            actor_rol,
            objetivo_usuario_id,
            objetivo_username,
            direccion_ip,
            _to_json_text(detalle),
        ),
    )


def registrar_evento_seguridad(
    tipo_evento,
    severidad="info",
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    objetivo_usuario_id=None,
    objetivo_username=None,
    direccion_ip=None,
    detalle=None,
):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_auditoria_seguridad(conn)
        with conn.cursor() as cur:
            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento=tipo_evento,
                severidad=severidad,
                actor_usuario_id=actor_usuario_id,
                actor_username=actor_username,
                actor_rol=actor_rol,
                objetivo_usuario_id=objetivo_usuario_id,
                objetivo_username=objetivo_username,
                direccion_ip=direccion_ip,
                detalle=detalle,
            )
            conn.commit()
            return {"ok": True}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tabla_observabilidad_parser(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS observabilidad_parser_pedidos (
                observacion_id BIGSERIAL PRIMARY KEY,
                tipo_evento VARCHAR(50) NOT NULL,
                cliente_id BIGINT,
                whatsapp_id VARCHAR(40),
                estado_origen VARCHAR(40),
                texto_usuario TEXT NOT NULL,
                confidence_score NUMERIC(5,4) NOT NULL DEFAULT 0,
                parse_mode VARCHAR(40) NOT NULL DEFAULT 'unknown',
                needs_clarification BOOLEAN NOT NULL DEFAULT FALSE,
                needs_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
                items_detectados JSONB NOT NULL DEFAULT '[]'::jsonb,
                signals JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                estado_revision VARCHAR(20) NOT NULL DEFAULT 'nuevo',
                admin_notes TEXT,
                expected_items_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                regla_id BIGINT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute("ALTER TABLE observabilidad_parser_pedidos ADD COLUMN IF NOT EXISTS estado_revision VARCHAR(20) NOT NULL DEFAULT 'nuevo'")
        cur.execute("ALTER TABLE observabilidad_parser_pedidos ADD COLUMN IF NOT EXISTS admin_notes TEXT")
        cur.execute("ALTER TABLE observabilidad_parser_pedidos ADD COLUMN IF NOT EXISTS expected_items_json JSONB NOT NULL DEFAULT '[]'::jsonb")
        cur.execute("ALTER TABLE observabilidad_parser_pedidos ADD COLUMN IF NOT EXISTS regla_id BIGINT")
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_observabilidad_parser_pedidos_created_at
                ON observabilidad_parser_pedidos (created_at DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_observabilidad_parser_pedidos_tipo_evento
                ON observabilidad_parser_pedidos (tipo_evento, created_at DESC)
            """
        )


def _asegurar_tabla_frases_parser_curadas(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS parser_frases_curadas (
                regla_id BIGSERIAL PRIMARY KEY,
                frase_original TEXT NOT NULL,
                frase_normalizada TEXT NOT NULL,
                tipo_match VARCHAR(20) NOT NULL DEFAULT 'exact',
                items_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                needs_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
                needs_clarification BOOLEAN NOT NULL DEFAULT FALSE,
                clarification_message TEXT,
                notas TEXT,
                prioridad INT NOT NULL DEFAULT 100,
                activa BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_parser_frases_curadas_tipo_match CHECK (tipo_match IN ('exact', 'contains'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_parser_frases_curadas_normalizada
                ON parser_frases_curadas (frase_normalizada, activa, prioridad DESC)
            """
        )


def registrar_observacion_parser_pedido(
    tipo_evento,
    cliente_id=None,
    whatsapp_id=None,
    estado_origen=None,
    texto_usuario=None,
    confidence_score: float = 0.0,
    parse_mode="unknown",
    needs_clarification=False,
    needs_confirmation=False,
    items_detectados=None,
    signals=None,
    metadata=None,
):
    conn = None
    try:
        texto = (texto_usuario or "").strip()
        if not texto:
            return {"ok": True, "skipped": True}
        conn = get_connection()
        _asegurar_tabla_observabilidad_parser(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO observabilidad_parser_pedidos (
                    tipo_evento,
                    cliente_id,
                    whatsapp_id,
                    estado_origen,
                    texto_usuario,
                    confidence_score,
                    parse_mode,
                    needs_clarification,
                    needs_confirmation,
                    items_detectados,
                    signals,
                    metadata,
                    expected_items_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
                """,
                (
                    tipo_evento,
                    cliente_id,
                    whatsapp_id,
                    estado_origen,
                    texto,
                    float(confidence_score or 0),
                    parse_mode or "unknown",
                    bool(needs_clarification),
                    bool(needs_confirmation),
                    _to_json_text(items_detectados or []),
                    _to_json_text(signals or []),
                    _to_json_text(metadata or {}),
                    _to_json_text([]),
                ),
            )
            conn.commit()
            return {"ok": True}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_observaciones_parser(limit=80, tipo_evento=None, estado_revision=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_observabilidad_parser(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = []
            params = []
            if tipo_evento:
                where.append("tipo_evento = %s")
                params.append(str(tipo_evento).strip())
            if estado_revision:
                where.append("estado_revision = %s")
                params.append(str(estado_revision).strip())
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            params.append(max(1, min(500, int(limit))))
            cur.execute(
                f"""
                SELECT
                    observacion_id,
                    tipo_evento,
                    cliente_id,
                    whatsapp_id,
                    estado_origen,
                    texto_usuario,
                    confidence_score,
                    parse_mode,
                    needs_clarification,
                    needs_confirmation,
                    items_detectados,
                    signals,
                    metadata,
                    estado_revision,
                    admin_notes,
                    expected_items_json,
                    regla_id,
                    created_at
                FROM observabilidad_parser_pedidos
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_observacion_parser(observacion_id, estado_revision=None, admin_notes=None, expected_items_json=None, regla_id=None):
    conn = None
    try:
        oid = int(observacion_id)
        updates = []
        params = []
        if estado_revision is not None:
            estado = str(estado_revision).strip().lower()
            if estado not in {"nuevo", "en_revision", "resuelto", "descartado"}:
                return {"error": "estado_revision invalido"}
            updates.append("estado_revision = %s")
            params.append(estado)
        if admin_notes is not None:
            updates.append("admin_notes = %s")
            params.append(str(admin_notes or "").strip() or None)
        if expected_items_json is not None:
            updates.append("expected_items_json = %s::jsonb")
            params.append(_to_json_text(expected_items_json or []))
        if regla_id is not None:
            rid = int(regla_id) if regla_id else None
            updates.append("regla_id = %s")
            params.append(rid)
        if not updates:
            return {"error": "No hay campos para actualizar"}
        conn = get_connection()
        _asegurar_tabla_observabilidad_parser(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params.append(oid)
            cur.execute(
                f"""
                UPDATE observabilidad_parser_pedidos
                SET {', '.join(updates)}
                WHERE observacion_id = %s
                RETURNING observacion_id, estado_revision, admin_notes, expected_items_json, regla_id
                """,
                tuple(params),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Observacion no encontrada"}
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_frases_parser_curadas(limit=200, activa=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_frases_parser_curadas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params = []
            where_sql = ""
            if activa is not None:
                where_sql = "WHERE activa = %s"
                params.append(bool(activa))
            params.append(max(1, min(500, int(limit))))
            cur.execute(
                f"""
                SELECT
                    regla_id,
                    frase_original,
                    frase_normalizada,
                    tipo_match,
                    items_json,
                    needs_confirmation,
                    needs_clarification,
                    clarification_message,
                    notas,
                    prioridad,
                    activa,
                    created_at,
                    updated_at
                FROM parser_frases_curadas
                {where_sql}
                ORDER BY activa DESC, prioridad DESC, updated_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_frase_parser_curada(
    frase_original,
    tipo_match="exact",
    items_json=None,
    needs_confirmation=False,
    needs_clarification=False,
    clarification_message=None,
    notas=None,
    prioridad=100,
    activa=True,
):
    conn = None
    try:
        frase = str(frase_original or "").strip()
        if not frase:
            return {"error": "frase_original es obligatoria"}
        tipo = str(tipo_match or "exact").strip().lower()
        if tipo not in {"exact", "contains"}:
            return {"error": "tipo_match invalido"}
        frase_norm = _normalizar_texto_busqueda(frase)
        conn = get_connection()
        _asegurar_tabla_frases_parser_curadas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO parser_frases_curadas (
                    frase_original,
                    frase_normalizada,
                    tipo_match,
                    items_json,
                    needs_confirmation,
                    needs_clarification,
                    clarification_message,
                    notas,
                    prioridad,
                    activa
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                RETURNING regla_id, frase_original, frase_normalizada, tipo_match, items_json,
                          needs_confirmation, needs_clarification, clarification_message,
                          notas, prioridad, activa, created_at, updated_at
                """,
                (
                    frase,
                    frase_norm,
                    tipo,
                    _to_json_text(items_json or []),
                    bool(needs_confirmation),
                    bool(needs_clarification),
                    str(clarification_message or "").strip() or None,
                    str(notas or "").strip() or None,
                    int(prioridad or 100),
                    bool(activa),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_frase_parser_curada(
    regla_id,
    frase_original=None,
    tipo_match=None,
    items_json=None,
    needs_confirmation=None,
    needs_clarification=None,
    clarification_message=None,
    notas=None,
    prioridad=None,
    activa=None,
):
    conn = None
    try:
        rid = int(regla_id)
        updates = ["updated_at = NOW()"]
        params = []
        if frase_original is not None:
            frase = str(frase_original or "").strip()
            if not frase:
                return {"error": "frase_original es obligatoria"}
            updates.append("frase_original = %s")
            params.append(frase)
            updates.append("frase_normalizada = %s")
            params.append(_normalizar_texto_busqueda(frase))
        if tipo_match is not None:
            tipo = str(tipo_match or "").strip().lower()
            if tipo not in {"exact", "contains"}:
                return {"error": "tipo_match invalido"}
            updates.append("tipo_match = %s")
            params.append(tipo)
        if items_json is not None:
            updates.append("items_json = %s::jsonb")
            params.append(_to_json_text(items_json or []))
        if needs_confirmation is not None:
            updates.append("needs_confirmation = %s")
            params.append(bool(needs_confirmation))
        if needs_clarification is not None:
            updates.append("needs_clarification = %s")
            params.append(bool(needs_clarification))
        if clarification_message is not None:
            updates.append("clarification_message = %s")
            params.append(str(clarification_message or "").strip() or None)
        if notas is not None:
            updates.append("notas = %s")
            params.append(str(notas or "").strip() or None)
        if prioridad is not None:
            updates.append("prioridad = %s")
            params.append(int(prioridad or 100))
        if activa is not None:
            updates.append("activa = %s")
            params.append(bool(activa))
        conn = get_connection()
        _asegurar_tabla_frases_parser_curadas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params.append(rid)
            cur.execute(
                f"""
                UPDATE parser_frases_curadas
                SET {', '.join(updates)}
                WHERE regla_id = %s
                RETURNING regla_id, frase_original, frase_normalizada, tipo_match, items_json,
                          needs_confirmation, needs_clarification, clarification_message,
                          notas, prioridad, activa, created_at, updated_at
                """,
                tuple(params),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Regla no encontrada"}
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def buscar_regla_curada_parser(texto_usuario):
    conn = None
    try:
        texto_norm = _normalizar_texto_busqueda(texto_usuario)
        if not texto_norm:
            return None
        conn = get_connection()
        _asegurar_tabla_frases_parser_curadas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    regla_id,
                    frase_original,
                    frase_normalizada,
                    tipo_match,
                    items_json,
                    needs_confirmation,
                    needs_clarification,
                    clarification_message,
                    notas,
                    prioridad,
                    activa,
                    created_at,
                    updated_at
                FROM parser_frases_curadas
                WHERE activa = TRUE
                  AND (
                    (tipo_match = 'exact' AND frase_normalizada = %s)
                    OR (tipo_match = 'contains' AND %s LIKE '%%' || frase_normalizada || '%%')
                  )
                ORDER BY prioridad DESC, updated_at DESC
                LIMIT 1
                """,
                (texto_norm, texto_norm),
            )
            return cur.fetchone()
    except Exception:
        return None
    finally:
        if conn:
            conn.close()


def obtener_auditoria_seguridad(
    limit=50,
    offset=0,
    tipo_evento=None,
    severidad=None,
    actor_username=None,
    fecha_desde=None,
    fecha_hasta=None,
    rango_rapido=None,
):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_auditoria_seguridad(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []

            if tipo_evento:
                filtros.append("tipo_evento = %s")
                params.append(str(tipo_evento).strip())

            if severidad:
                filtros.append("severidad = %s")
                params.append(str(severidad).strip().lower())

            if actor_username:
                filtros.append("LOWER(actor_username) = LOWER(%s)")
                params.append(str(actor_username).strip())

            if fecha_desde:
                filtros.append("creado_en >= %s::date")
                params.append(str(fecha_desde).strip())

            if fecha_hasta:
                filtros.append("creado_en < (%s::date + INTERVAL '1 day')")
                params.append(str(fecha_hasta).strip())

            rango = str(rango_rapido or "").strip().lower()
            if rango == "hoy":
                filtros.append("creado_en::date = CURRENT_DATE")
            elif rango == "7d":
                filtros.append("creado_en >= NOW() - INTERVAL '7 days'")
            elif rango == "30d":
                filtros.append("creado_en >= NOW() - INTERVAL '30 days'")

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            lim = max(1, min(500, int(limit)))
            off = max(0, int(offset or 0))
            params.extend([lim, off])
            cur.execute(
                f"""
                SELECT
                    auditoria_id,
                    tipo_evento,
                    severidad,
                    actor_usuario_id,
                    actor_username,
                    actor_rol,
                    objetivo_usuario_id,
                    objetivo_username,
                    direccion_ip,
                    detalle,
                    creado_en
                FROM auditoria_seguridad
                {where_sql}
                ORDER BY creado_en DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_auditoria_negocio(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auditoria_negocio (
                auditoria_negocio_id BIGSERIAL PRIMARY KEY,
                tabla_objetivo VARCHAR(60) NOT NULL,
                operacion VARCHAR(10) NOT NULL,
                registro_id VARCHAR(120),
                actor_username VARCHAR(80),
                actor_rol VARCHAR(30),
                detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_auditoria_negocio_operacion CHECK (operacion IN ('INSERT', 'UPDATE', 'DELETE'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_negocio_fecha
                ON auditoria_negocio (creado_en DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_negocio_tabla
                ON auditoria_negocio (tabla_objetivo, creado_en DESC)
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION fn_auditoria_negocio_generic()
            RETURNS TRIGGER AS $$
            DECLARE
                actor_name TEXT := NULLIF(current_setting('app.current_user', true), '');
                actor_role TEXT := NULLIF(current_setting('app.current_role', true), '');
                source_row JSONB;
                row_id TEXT;
                payload JSONB;
            BEGIN
                source_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
                row_id := COALESCE(
                    source_row->>'pedido_id',
                    source_row->>'pago_id',
                    source_row->>'compra_id',
                    source_row->>'insumo_id',
                    source_row->>'detalle_id',
                    'N/A'
                );

                IF TG_OP = 'INSERT' THEN
                    payload := jsonb_build_object('new', to_jsonb(NEW));
                ELSIF TG_OP = 'UPDATE' THEN
                    payload := jsonb_build_object('old', to_jsonb(OLD), 'new', to_jsonb(NEW));
                ELSE
                    payload := jsonb_build_object('old', to_jsonb(OLD));
                END IF;

                INSERT INTO auditoria_negocio (tabla_objetivo, operacion, registro_id, actor_username, actor_rol, detalle)
                VALUES (TG_TABLE_NAME, TG_OP, row_id, actor_name, actor_role, payload);

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table_name in ("pedidos", "pagos", "insumos", "compras_insumos"):
            cur.execute(
                f"""
                DROP TRIGGER IF EXISTS trg_auditoria_negocio_{table_name} ON {table_name};
                CREATE TRIGGER trg_auditoria_negocio_{table_name}
                AFTER INSERT OR UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION fn_auditoria_negocio_generic();
                """
            )


def _set_audit_actor(cur, actor_username=None, actor_rol=None):
    cur.execute("SELECT set_config('app.current_user', %s, true)", (str(actor_username or "sistema"),))
    cur.execute("SELECT set_config('app.current_role', %s, true)", (str(actor_rol or "sistema"),))


def obtener_auditoria_negocio(
    limit=50,
    offset=0,
    tabla_objetivo=None,
    actor_username=None,
    fecha_desde=None,
    fecha_hasta=None,
    rango_rapido=None,
):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_compras_insumos(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []

            if tabla_objetivo:
                filtros.append("tabla_objetivo = %s")
                params.append(str(tabla_objetivo).strip().lower())

            if actor_username:
                filtros.append("LOWER(actor_username) = LOWER(%s)")
                params.append(str(actor_username).strip())

            if fecha_desde:
                filtros.append("creado_en >= %s::date")
                params.append(str(fecha_desde).strip())

            if fecha_hasta:
                filtros.append("creado_en < (%s::date + INTERVAL '1 day')")
                params.append(str(fecha_hasta).strip())

            rango = str(rango_rapido or "").strip().lower()
            if rango == "hoy":
                filtros.append("creado_en::date = CURRENT_DATE")
            elif rango == "7d":
                filtros.append("creado_en >= NOW() - INTERVAL '7 days'")
            elif rango == "30d":
                filtros.append("creado_en >= NOW() - INTERVAL '30 days'")

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            lim = max(1, min(500, int(limit)))
            off = max(0, int(offset or 0))
            params.extend([lim, off])
            cur.execute(
                f"""
                SELECT
                    auditoria_negocio_id,
                    tabla_objetivo,
                    operacion,
                    registro_id,
                    actor_username,
                    actor_rol,
                    detalle,
                    creado_en
                FROM auditoria_negocio
                {where_sql}
                ORDER BY creado_en DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def autenticar_usuario(username, password, direccion_ip=None):
    conn = None
    try:
        usuario = (username or "").strip()
        secret = password or ""
        if not usuario or not secret:
            return {"error": "Credenciales invalidas", "status": 401}

        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _asegurar_tabla_auditoria_seguridad(conn)
        _bootstrap_usuarios_por_rol(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    usuario_id,
                    username,
                    password_hash,
                    rol,
                    nombre_mostrar,
                    area_entrega,
                    activo,
                    intentos_fallidos,
                    bloqueado_hasta
                FROM usuarios_sistema
                WHERE LOWER(username) = LOWER(%s)
                LIMIT 1
                """,
                (usuario,),
            )
            row = cur.fetchone()

            if not row:
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_failed",
                    severidad="warning",
                    actor_username=usuario,
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "usuario_no_encontrado"},
                )
                conn.commit()
                return {"error": "Credenciales invalidas", "status": 401}

            if not row.get("activo"):
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_blocked",
                    severidad="warning",
                    actor_usuario_id=row.get("usuario_id"),
                    actor_username=row.get("username"),
                    actor_rol=row.get("rol"),
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "usuario_inactivo"},
                )
                conn.commit()
                return {"error": "Usuario inactivo", "status": 403}

            bloqueado_hasta = row.get("bloqueado_hasta")
            if bloqueado_hasta and bloqueado_hasta > datetime.now():
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_blocked",
                    severidad="warning",
                    actor_usuario_id=row.get("usuario_id"),
                    actor_username=row.get("username"),
                    actor_rol=row.get("rol"),
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "bloqueo_temporal", "bloqueado_hasta": bloqueado_hasta.isoformat()},
                )
                conn.commit()
                return {"error": "Usuario bloqueado temporalmente", "status": 423}

            if not check_password_hash(row["password_hash"], secret):
                cur.execute(
                    """
                    UPDATE usuarios_sistema
                    SET
                        intentos_fallidos = CASE
                            WHEN intentos_fallidos + 1 >= 5 THEN 0
                            ELSE intentos_fallidos + 1
                        END,
                        bloqueado_hasta = CASE
                            WHEN intentos_fallidos + 1 >= 5 THEN NOW() + INTERVAL '15 minutes'
                            ELSE bloqueado_hasta
                        END,
                        actualizado_en = NOW()
                    WHERE usuario_id = %s
                    """,
                    (row["usuario_id"],),
                )
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_failed",
                    severidad="warning",
                    actor_usuario_id=row.get("usuario_id"),
                    actor_username=row.get("username"),
                    actor_rol=row.get("rol"),
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "password_incorrecto"},
                )
                conn.commit()
                return {"error": "Credenciales invalidas", "status": 401}

            cur.execute(
                """
                UPDATE usuarios_sistema
                SET
                    ultimo_login = NOW(),
                    intentos_fallidos = 0,
                    bloqueado_hasta = NULL,
                    actualizado_en = NOW()
                WHERE usuario_id = %s
                """,
                (row["usuario_id"],),
            )
            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento="login_success",
                severidad="info",
                actor_usuario_id=row.get("usuario_id"),
                actor_username=row.get("username"),
                actor_rol=row.get("rol"),
                direccion_ip=direccion_ip,
            )
            conn.commit()
            return {
                "usuario_id": row["usuario_id"],
                "username": row["username"],
                "rol": row["rol"],
                "nombre_mostrar": row["nombre_mostrar"],
                "area_entrega": row.get("area_entrega"),
            }
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc), "status": 500}
    finally:
        if conn:
            conn.close()


def obtener_usuarios_sistema(rol=None, area_entrega=None, busqueda=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _bootstrap_usuarios_por_rol(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []

            rol_val = (rol or "").strip().lower()
            if rol_val:
                filtros.append("rol = %s")
                params.append(rol_val)

            area = _normalizar_area_entrega(area_entrega)
            if area:
                filtros.append("LOWER(COALESCE(area_entrega, '')) = LOWER(%s)")
                params.append(area)

            busqueda_val = (busqueda or "").strip().lower()
            if busqueda_val:
                filtros.append("(LOWER(username) LIKE %s OR LOWER(COALESCE(nombre_mostrar, '')) LIKE %s)")
                params.append("%" + busqueda_val + "%")
                params.append("%" + busqueda_val + "%")

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            cur.execute(
                f"""
                SELECT
                    usuario_id,
                    username,
                    rol,
                    nombre_mostrar,
                    telefono,
                    area_entrega,
                    activo,
                    ultimo_login,
                    creado_en,
                    actualizado_en
                FROM usuarios_sistema
                {where_sql}
                ORDER BY rol, username
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_usuario_sistema(
    username,
    password,
    rol,
    nombre_mostrar,
    telefono=None,
    area_entrega=None,
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    direccion_ip=None,
):
    conn = None
    try:
        usuario = (username or "").strip()
        secret = password or ""
        rol_val = (rol or "").strip().lower()
        nombre = (nombre_mostrar or "").strip()
        tel = (telefono or "").strip() or None
        area = _normalizar_area_entrega(area_entrega)

        if not usuario or not nombre:
            return {"error": "username y nombre_mostrar son obligatorios"}
        if len(secret) < 8:
            return {"error": "La contrasena debe tener al menos 8 caracteres"}
        if rol_val not in ROLES_USUARIO_SISTEMA:
            return {"error": "Rol invalido"}
        if rol_val == "repartidor" and not area:
            return {"error": "Para rol repartidor debes definir area_entrega"}
        if rol_val != "repartidor":
            area = None

        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _asegurar_tabla_auditoria_seguridad(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO usuarios_sistema
                    (username, password_hash, rol, nombre_mostrar, telefono, area_entrega, activo)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                RETURNING
                    usuario_id,
                    username,
                    rol,
                    nombre_mostrar,
                    telefono,
                    area_entrega,
                    activo,
                    ultimo_login,
                    creado_en,
                    actualizado_en
                """,
                (usuario, generate_password_hash(secret), rol_val, nombre, tel, area),
            )
            row = cur.fetchone()
            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento="user_created",
                severidad="info",
                actor_usuario_id=actor_usuario_id,
                actor_username=actor_username,
                actor_rol=actor_rol,
                objetivo_usuario_id=row.get("usuario_id"),
                objetivo_username=row.get("username"),
                direccion_ip=direccion_ip,
                detalle={
                    "rol": row.get("rol"),
                    "telefono": row.get("telefono"),
                    "area_entrega": row.get("area_entrega"),
                },
            )
            conn.commit()
            return row
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        return {"error": "El username ya existe"}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_usuario_sistema(
    usuario_id,
    rol=None,
    nombre_mostrar=None,
    telefono=None,
    area_entrega=None,
    activo=None,
    nueva_password=None,
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    direccion_ip=None,
):
    conn = None
    try:
        user_id = int(usuario_id)
        cambios = []
        params = []
        detalle_auditoria = {}
        rol_objetivo = None

        if rol is not None:
            rol_val = str(rol).strip().lower()
            if rol_val not in ROLES_USUARIO_SISTEMA:
                return {"error": "Rol invalido"}
            cambios.append("rol = %s")
            params.append(rol_val)
            detalle_auditoria["rol"] = rol_val
            rol_objetivo = rol_val

        if nombre_mostrar is not None:
            nombre = str(nombre_mostrar).strip()
            if not nombre:
                return {"error": "nombre_mostrar no puede ser vacio"}
            cambios.append("nombre_mostrar = %s")
            params.append(nombre)
            detalle_auditoria["nombre_mostrar"] = nombre

        if email is not None:
            email_val = str(email).strip() or None
            cambios.append("email = %s")
            params.append(email_val)
            detalle_auditoria["email"] = email_val

        if telefono is not None:
            tel = str(telefono).strip() or None
            cambios.append("telefono = %s")
            params.append(tel)
            detalle_auditoria["telefono"] = tel

        if area_entrega is not None:
            area = _normalizar_area_entrega(area_entrega)
            cambios.append("area_entrega = %s")
            params.append(area)
            detalle_auditoria["area_entrega"] = area

        if activo is not None:
            cambios.append("activo = %s")
            params.append(bool(activo))
            detalle_auditoria["activo"] = bool(activo)

        if nueva_password is not None:
            secret = str(nueva_password)
            if len(secret) < 8:
                return {"error": "La contrasena debe tener al menos 8 caracteres"}
            cambios.append("password_hash = %s")
            params.append(generate_password_hash(secret))
            cambios.append("intentos_fallidos = 0")
            cambios.append("bloqueado_hasta = NULL")
            detalle_auditoria["password_reset"] = True

        if not cambios:
            return {"error": "No hay campos para actualizar"}

        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _asegurar_tabla_auditoria_seguridad(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if rol_objetivo is None:
                cur.execute(
                    """
                    SELECT rol
                    FROM usuarios_sistema
                    WHERE usuario_id = %s
                    LIMIT 1
                    """,
                    (user_id,),
                )
                existente = cur.fetchone()
                if not existente:
                    return {"error": "Usuario no encontrado"}
                rol_objetivo = existente.get("rol")

            if rol_objetivo != "repartidor":
                cambios.append("area_entrega = NULL")
                detalle_auditoria["area_entrega"] = None
            elif "area_entrega" in detalle_auditoria and not detalle_auditoria.get("area_entrega"):
                return {"error": "Para rol repartidor debes definir area_entrega"}

            query = f"""
                UPDATE usuarios_sistema
                SET
                    {", ".join(cambios)},
                    actualizado_en = NOW()
                WHERE usuario_id = %s
                RETURNING
                    usuario_id,
                    username,
                    rol,
                    nombre_mostrar,
                    telefono,
                    area_entrega,
                    activo,
                    ultimo_login,
                    creado_en,
                    actualizado_en
            """
            params.append(user_id)
            cur.execute(query, tuple(params))
            row = cur.fetchone()
            if not row:
                return {"error": "Usuario no encontrado"}
            tipo_evento = "user_updated"
            severidad = "info"
            if detalle_auditoria.get("password_reset"):
                tipo_evento = "user_password_reset"
            elif "activo" in detalle_auditoria:
                tipo_evento = "user_activated" if detalle_auditoria["activo"] else "user_deactivated"
                severidad = "warning" if not detalle_auditoria["activo"] else "info"

            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento=tipo_evento,
                severidad=severidad,
                actor_usuario_id=actor_usuario_id,
                actor_username=actor_username,
                actor_rol=actor_rol,
                objetivo_usuario_id=row.get("usuario_id"),
                objetivo_username=row.get("username"),
                direccion_ip=direccion_ip,
                detalle=detalle_auditoria,
            )
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tablas_operacion_pedidos(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE pedidos
            ADD COLUMN IF NOT EXISTS codigo_entrega VARCHAR(12)
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_codigo_entrega
                ON pedidos(codigo_entrega)
                WHERE codigo_entrega IS NOT NULL
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS asignaciones_reparto (
                asignacion_id BIGSERIAL PRIMARY KEY,
                pedido_id BIGINT NOT NULL REFERENCES pedidos(pedido_id),
                repartidor_usuario VARCHAR(80) NOT NULL,
                asignado_por VARCHAR(80),
                asignado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                activo BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_asignaciones_reparto_pedido_activo
                ON asignaciones_reparto(pedido_id)
                WHERE activo = TRUE
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bitacora_estado_pedidos (
                bitacora_id BIGSERIAL PRIMARY KEY,
                pedido_id BIGINT NOT NULL REFERENCES pedidos(pedido_id),
                estado_anterior VARCHAR(30),
                estado_nuevo VARCHAR(30) NOT NULL,
                actor_usuario VARCHAR(80),
                rol_actor VARCHAR(30),
                motivo TEXT,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bitacora_estado_pedidos_pedido
                ON bitacora_estado_pedidos (pedido_id, creado_en DESC)
            """
        )


def _registrar_bitacora_estado(cur, pedido_id, estado_anterior, estado_nuevo, actor_usuario=None, rol_actor=None, motivo=None):
    cur.execute(
        """
        INSERT INTO bitacora_estado_pedidos
            (pedido_id, estado_anterior, estado_nuevo, actor_usuario, rol_actor, motivo)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (pedido_id, estado_anterior, estado_nuevo, actor_usuario, rol_actor, motivo),
    )


def _asegurar_tabla_facturas_operativas(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS facturas_operativas (
                factura_op_id BIGSERIAL PRIMARY KEY,
                pedido_id BIGINT NOT NULL REFERENCES pedidos(pedido_id),
                datos_fiscales_id BIGINT,
                folio_factura VARCHAR(80) NOT NULL,
                estado VARCHAR(20) NOT NULL DEFAULT 'emitida',
                email_destino VARCHAR(255),
                pdf_ruta TEXT,
                xml_ruta TEXT,
                notas TEXT,
                emitida_por VARCHAR(80),
                emitida_en TIMESTAMP NOT NULL DEFAULT NOW(),
                entregada_en TIMESTAMP,
                ultimo_envio_estado VARCHAR(20),
                ultimo_envio_error TEXT,
                ultimo_envio_en TIMESTAMP,
                ultimo_envio_destino VARCHAR(120),
                actualizado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT ux_facturas_operativas_pedido UNIQUE (pedido_id),
                CONSTRAINT chk_facturas_operativas_estado CHECK (estado IN ('emitida', 'entregada'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_facturas_operativas_estado
                ON facturas_operativas (estado, emitida_en DESC)
            """
        )
        cur.execute("ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS pdf_ruta TEXT")
        cur.execute("ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS xml_ruta TEXT")
        cur.execute("ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS ultimo_envio_estado VARCHAR(20)")
        cur.execute("ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS ultimo_envio_error TEXT")
        cur.execute("ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS ultimo_envio_en TIMESTAMP")
        cur.execute("ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS ultimo_envio_destino VARCHAR(120)")


def _generar_codigo_entrega_db(cur, length=6):
    chars = string.ascii_uppercase + string.digits
    for _ in range(40):
        code = "".join(random.choices(chars, k=length))
        cur.execute("SELECT 1 FROM pedidos WHERE codigo_entrega = %s LIMIT 1", (code,))
        if not cur.fetchone():
            return code
    return "".join(random.choices(chars, k=length))


def obtener_productos(solo_pedibles=False):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if solo_pedibles:
                cur.execute(
                    """
                    SELECT p.producto_id, p.nombre, p.variante, p.precio, p.activo
                    FROM productos p
                    WHERE p.activo = TRUE
                      AND EXISTS (
                        SELECT 1
                        FROM recetas_producto_insumo r
                        WHERE r.producto_id = p.producto_id
                          AND r.activo = TRUE
                    )
                    ORDER BY p.nombre, p.variante
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT producto_id, nombre, variante, precio, activo
                    FROM productos
                    WHERE activo = TRUE
                    ORDER BY nombre, variante
                    """
                )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_productos_sin_receta():
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT p.producto_id, p.nombre, p.variante, p.precio, p.activo
                FROM productos p
                WHERE p.activo = TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM recetas_producto_insumo r
                    WHERE r.producto_id = p.producto_id
                      AND r.activo = TRUE
                  )
                ORDER BY p.nombre, p.variante
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_o_crear_cliente(whatsapp_id):
    conn = None
    try:
        conn = get_connection()
        _asegurar_columnas_clientes_y_direcciones(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT cliente_id, whatsapp_id, nombre, apellidos, genero_trato
                FROM clientes
                WHERE whatsapp_id = %s
                LIMIT 1
                """,
                (whatsapp_id,),
            )
            cliente = cur.fetchone()
            if cliente:
                conn.commit()
                return cliente

            cur.execute(
                """
                INSERT INTO clientes (whatsapp_id, nombre, apellidos, genero_trato)
                VALUES (%s, %s, %s, %s)
                RETURNING cliente_id, whatsapp_id, nombre, apellidos, genero_trato
                """,
                (whatsapp_id, "Cliente", "WhatsApp", "neutro"),
            )
            nuevo = cur.fetchone()
            conn.commit()
            return nuevo
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_columnas_clientes_y_direcciones(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE clientes
            ADD COLUMN IF NOT EXISTS genero_trato VARCHAR(10) NOT NULL DEFAULT 'neutro'
            """
        )
        cur.execute(
            """
            ALTER TABLE direcciones_cliente
            ADD COLUMN IF NOT EXISTS codigo_postal VARCHAR(5)
            """
        )


def guardar_direccion_cliente(
    cliente_id,
    lat=None,
    lng=None,
    alias=None,
    direccion_texto=None,
    codigo_postal=None,
    referencia=None,
    principal=True,
):
    conn = None
    try:
        conn = get_connection()
        _asegurar_columnas_clientes_y_direcciones(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if _sensitive_encryption_enabled():
                cur.execute(
                    """
                    INSERT INTO direcciones_cliente (
                        cliente_id,
                        latitud,
                        longitud,
                        alias,
                        direccion_texto,
                        codigo_postal,
                        referencia,
                        principal,
                        actualizado_en,
                        latitud_enc,
                        longitud_enc,
                        direccion_texto_enc,
                        referencia_enc
                    )
                    VALUES (
                        %s,
                        NULL,
                        NULL,
                        %s,
                        '',
                        %s,
                        NULL,
                        %s,
                        NOW(),
                        encrypt_sensitive_text(%s::TEXT),
                        encrypt_sensitive_text(%s::TEXT),
                        encrypt_sensitive_text(%s),
                        encrypt_sensitive_text(%s)
                    )
                    RETURNING direccion_id
                    """,
                    (
                        cliente_id,
                        alias,
                        codigo_postal,
                        bool(principal),
                        None if lat is None else str(lat),
                        None if lng is None else str(lng),
                        direccion_texto,
                        referencia,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO direcciones_cliente (
                        cliente_id,
                        latitud,
                        longitud,
                        alias,
                        direccion_texto,
                        codigo_postal,
                        referencia,
                        principal,
                        actualizado_en
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING direccion_id
                    """,
                    (
                        cliente_id,
                        lat,
                        lng,
                        alias,
                        direccion_texto,
                        codigo_postal,
                        referencia,
                        bool(principal),
                    ),
                )

            row = cur.fetchone() or {}
            conn.commit()
            return row.get("direccion_id")
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _guardar_datos_fiscales_cliente_cur(cur, cliente_id, datos_fiscales):
    if _sensitive_encryption_enabled():
        cur.execute(
            """
            INSERT INTO datos_fiscales (
                cliente_id,
                rfc,
                razon_social,
                regimen_fiscal,
                uso_cfdi,
                email,
                actualizado_en,
                rfc_enc,
                razon_social_enc,
                regimen_fiscal_enc,
                uso_cfdi_enc,
                email_enc
            )
            VALUES (
                %s,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NOW(),
                encrypt_sensitive_text(%s),
                encrypt_sensitive_text(%s),
                encrypt_sensitive_text(%s),
                encrypt_sensitive_text(%s),
                encrypt_sensitive_text(%s)
            )
            RETURNING fiscal_id
            """,
            (
                cliente_id,
                datos_fiscales.get("rfc"),
                datos_fiscales.get("razon_social"),
                datos_fiscales.get("regimen_fiscal"),
                datos_fiscales.get("uso_cfdi"),
                datos_fiscales.get("email"),
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO datos_fiscales (cliente_id, rfc, razon_social, regimen_fiscal, uso_cfdi, email, actualizado_en)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING fiscal_id
            """,
            (
                cliente_id,
                datos_fiscales.get("rfc"),
                datos_fiscales.get("razon_social"),
                datos_fiscales.get("regimen_fiscal"),
                datos_fiscales.get("uso_cfdi"),
                datos_fiscales.get("email"),
            ),
        )

    return (cur.fetchone() or {}).get("fiscal_id")


def guardar_datos_fiscales_cliente(cliente_id, datos_fiscales):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            fiscal_id = _guardar_datos_fiscales_cliente_cur(cur, cliente_id=cliente_id, datos_fiscales=datos_fiscales or {})
        conn.commit()
        return fiscal_id
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_cliente_basico(cliente_id, nombre=None, apellidos=None, genero_trato=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_columnas_clientes_y_direcciones(conn)
        updates = []
        params = []

        if nombre is not None:
            nombre_clean = str(nombre).strip()
            if nombre_clean:
                updates.append("nombre = %s")
                params.append(nombre_clean)

        if apellidos is not None:
            apellidos_clean = str(apellidos).strip()
            updates.append("apellidos = %s")
            params.append(apellidos_clean)

        if genero_trato is not None:
            genero = str(genero_trato).strip().lower()
            if genero in {"hombre", "mujer", "neutro"}:
                updates.append("genero_trato = %s")
                params.append(genero)

        if not updates:
            return {"ok": True, "actualizado": False}

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params.append(int(cliente_id))
            cur.execute(
                f"""
                UPDATE clientes
                SET {', '.join(updates)}
                WHERE cliente_id = %s
                RETURNING cliente_id, whatsapp_id, nombre, apellidos, genero_trato
                """,
                tuple(params),
            )
            row = cur.fetchone()
        conn.commit()
        return row if row else {"error": "Cliente no encontrado"}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def limpiar_clientes_temporales():
    conn = None
    try:
        conn = get_connection()
        _asegurar_columnas_clientes_y_direcciones(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.cliente_id,
                    c.whatsapp_id,
                    c.nombre,
                    c.apellidos,
                    COUNT(p.pedido_id) FILTER (WHERE p.estado <> 'cancelado')::INT AS total_pedidos
                FROM clientes c
                LEFT JOIN pedidos p ON p.cliente_id = c.cliente_id
                GROUP BY c.cliente_id, c.whatsapp_id, c.nombre, c.apellidos
                ORDER BY c.cliente_id DESC
                """
            )
            rows = cur.fetchall() or []

            eliminar_ids = []
            normalizar_ids = []
            normalizar_whatsapp = []

            for row in rows:
                cliente_id = int(row.get("cliente_id") or 0)
                whatsapp_id = row.get("whatsapp_id")
                nombre = row.get("nombre")
                apellidos = row.get("apellidos")
                total_pedidos = int(row.get("total_pedidos") or 0)
                if not _parece_cliente_temporal(whatsapp_id, nombre, apellidos, total_pedidos=total_pedidos):
                    continue

                blob = _normalizar_texto_busqueda(f"{nombre or ''} {apellidos or ''}")
                if (not _whatsapp_id_parece_real(whatsapp_id)) or any(token in blob for token in ("validacion", "test", "prueba", "legacy")):
                    eliminar_ids.append(cliente_id)
                    if whatsapp_id:
                        normalizar_whatsapp.append(str(whatsapp_id))
                else:
                    normalizar_ids.append(cliente_id)

            pedido_ids = []
            if eliminar_ids:
                cur.execute(
                    "SELECT pedido_id FROM pedidos WHERE cliente_id = ANY(%s)",
                    (eliminar_ids,),
                )
                pedido_ids = [
                    int((r or {}).get("pedido_id") or 0)
                    for r in (cur.fetchall() or [])
                    if int((r or {}).get("pedido_id") or 0) > 0
                ]

                direccion_ids = []
                fiscal_ids = []
                if _tabla_existe(conn, "direcciones_cliente"):
                    cur.execute("SELECT direccion_id FROM direcciones_cliente WHERE cliente_id = ANY(%s)", (eliminar_ids,))
                    direccion_ids = [
                        int((r or {}).get("direccion_id") or 0)
                        for r in (cur.fetchall() or [])
                        if int((r or {}).get("direccion_id") or 0) > 0
                    ]
                if _tabla_existe(conn, "datos_fiscales"):
                    cur.execute("SELECT fiscal_id FROM datos_fiscales WHERE cliente_id = ANY(%s)", (eliminar_ids,))
                    fiscal_ids = [
                        int((r or {}).get("fiscal_id") or 0)
                        for r in (cur.fetchall() or [])
                        if int((r or {}).get("fiscal_id") or 0) > 0
                    ]

                if direccion_ids and _tabla_existe(conn, "pedidos") and _tabla_tiene_columna(conn, "pedidos", "direccion_id"):
                    cur.execute("UPDATE pedidos SET direccion_id = NULL WHERE direccion_id = ANY(%s)", (direccion_ids,))
                if fiscal_ids and _tabla_existe(conn, "pedidos") and _tabla_tiene_columna(conn, "pedidos", "datos_fiscales_id"):
                    cur.execute("UPDATE pedidos SET datos_fiscales_id = NULL WHERE datos_fiscales_id = ANY(%s)", (fiscal_ids,))

                if pedido_ids and _tabla_existe(conn, "facturas_operativas"):
                    cur.execute("DELETE FROM facturas_operativas WHERE pedido_id = ANY(%s)", (pedido_ids,))
                if pedido_ids and _tabla_existe(conn, "pagos"):
                    cur.execute("DELETE FROM pagos WHERE pedido_id = ANY(%s)", (pedido_ids,))
                if pedido_ids and _tabla_existe(conn, "detalle_pedido"):
                    cur.execute("DELETE FROM detalle_pedido WHERE pedido_id = ANY(%s)", (pedido_ids,))
                if pedido_ids and _tabla_existe(conn, "bitacora_estado_pedidos"):
                    cur.execute("DELETE FROM bitacora_estado_pedidos WHERE pedido_id = ANY(%s)", (pedido_ids,))
                if pedido_ids and _tabla_existe(conn, "asignaciones_reparto"):
                    cur.execute("DELETE FROM asignaciones_reparto WHERE pedido_id = ANY(%s)", (pedido_ids,))
                if _tabla_existe(conn, "pedidos"):
                    cur.execute("DELETE FROM pedidos WHERE cliente_id = ANY(%s)", (eliminar_ids,))
                if _tabla_existe(conn, "datos_fiscales"):
                    cur.execute("DELETE FROM datos_fiscales WHERE cliente_id = ANY(%s)", (eliminar_ids,))
                if _tabla_existe(conn, "direcciones_cliente"):
                    cur.execute("DELETE FROM direcciones_cliente WHERE cliente_id = ANY(%s)", (eliminar_ids,))
                if normalizar_whatsapp and _tabla_existe(conn, "sesiones_bot"):
                    cur.execute("DELETE FROM sesiones_bot WHERE whatsapp_id = ANY(%s)", (normalizar_whatsapp,))
                cur.execute("DELETE FROM clientes WHERE cliente_id = ANY(%s)", (eliminar_ids,))

            if normalizar_ids:
                cur.execute(
                    """
                    UPDATE clientes
                    SET nombre = '',
                        apellidos = '',
                        genero_trato = 'neutro'
                    WHERE cliente_id = ANY(%s)
                    """,
                    (normalizar_ids,),
                )

        conn.commit()
        return {
            "eliminados": len(eliminar_ids),
            "normalizados": len(normalizar_ids),
            "pedidos_eliminados": len(pedido_ids),
            "clientes_conservados": max(len(rows) - len(eliminar_ids), 0),
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_pedido(cliente_id, items, direccion_id, metodo_pago, actor_usuario="sistema", actor_rol="bot"):
    conn = None
    try:
        if not items:
            return {"error": "El pedido debe incluir al menos un item."}

        items_normalizados = []

        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_tablas_inventario_real(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for item in items:
                producto_id = int(item.get("producto_id") or 0)
                cantidad = int(item.get("cantidad") or 0)
                if producto_id <= 0:
                    return {"error": "Cada item requiere producto_id valido."}
                if cantidad <= 0:
                    return {"error": f"Cantidad invalida para producto_id={producto_id}."}

                cur.execute(
                    """
                    SELECT producto_id, nombre, variante, precio, activo
                    FROM productos
                    WHERE producto_id = %s
                    LIMIT 1
                    """,
                    (producto_id,),
                )
                producto = cur.fetchone()
                if not producto:
                    return {"error": f"Producto no encontrado: producto_id={producto_id}."}
                if not producto.get("activo"):
                    return {"error": f"Producto inactivo: {producto.get('nombre')} ({producto_id})."}

                precio_item = item.get("precio_unitario")
                precio_unitario = float(precio_item) if precio_item not in (None, "") else float(producto.get("precio") or 0)
                if precio_unitario <= 0:
                    return {"error": f"Precio invalido para producto_id={producto_id}."}

                items_normalizados.append(
                    {
                        "producto_id": producto_id,
                        "cantidad": cantidad,
                        "precio_unitario": precio_unitario,
                        "producto": producto.get("nombre"),
                        "variante": producto.get("variante"),
                    }
                )

            total = sum(float(item["cantidad"]) * float(item["precio_unitario"]) for item in items_normalizados)
            has_codigo = _tabla_tiene_columna(conn, "pedidos", "codigo_entrega")
            codigo_entrega = _generar_codigo_entrega_db(cur) if has_codigo else None

            _set_audit_actor(cur, actor_username=actor_usuario, actor_rol=actor_rol)
            if has_codigo:
                cur.execute(
                    """
                    INSERT INTO pedidos (cliente_id, direccion_id, metodo_pago, total, estado, codigo_entrega)
                    VALUES (%s, %s, %s, %s, 'recibido', %s)
                    RETURNING pedido_id, cliente_id, direccion_id, metodo_pago, total, estado, creado_en, codigo_entrega
                    """,
                    (cliente_id, direccion_id, metodo_pago, total, codigo_entrega),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO pedidos (cliente_id, direccion_id, metodo_pago, total, estado)
                    VALUES (%s, %s, %s, %s, 'recibido')
                    RETURNING pedido_id, cliente_id, direccion_id, metodo_pago, total, estado, creado_en
                    """,
                    (cliente_id, direccion_id, metodo_pago, total),
                )
            pedido = cur.fetchone()

            for item in items_normalizados:
                cur.execute(
                    """
                    INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio_unitario)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        pedido["pedido_id"],
                        item.get("producto_id"),
                        item.get("cantidad", 1),
                        item.get("precio_unitario", 0),
                    ),
                )

            consumo = _descontar_inventario_por_pedido(
                cur,
                pedido_id=pedido["pedido_id"],
                items=items_normalizados,
                actor_usuario=actor_usuario,
                actor_rol=actor_rol,
            )
            if isinstance(consumo, dict) and consumo.get("error"):
                return consumo

            _registrar_bitacora_estado(
                cur,
                pedido_id=pedido["pedido_id"],
                estado_anterior=None,
                estado_nuevo="recibido",
                actor_usuario=actor_usuario,
                rol_actor=actor_rol,
                motivo="Pedido creado",
            )

            conn.commit()
            pedido["items"] = items_normalizados
            pedido["movimientos_inventario"] = consumo.get("movimientos", [])
            return pedido
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_pedido_completo(cliente_id, datos_temp):
    """
    Crea el pedido completo en una sola transaccion.

    Flujo esperado:
      1) Verificar stock por item usando verificar_stock_suficiente(producto_id, cantidad)
      2) Insertar pedido principal
      3) Insertar detalle_pedido (el trigger descuenta inventario automaticamente)
      4) Vincular pago pendiente (si aplica)
      5) Incrementar total_compras del cliente (si la columna existe)
      6) Limpiar sesion del cliente (si existe por whatsapp_id)
      7) Commit
    """
    conn = None
    try:
        datos = datos_temp if isinstance(datos_temp, dict) else {}
        items = datos.get("items") or []
        if not isinstance(items, list) or not items:
            return {"error": "No hay items en datos_temp para crear el pedido."}

        conn = get_connection()

        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_tablas_inventario_real(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Paso 1: validar stock por cada item antes de insertar.
            for item in items:
                producto_id = int(item.get("producto_id") or 0)
                cantidad = int(item.get("cantidad") or 0)
                if producto_id <= 0 or cantidad <= 0:
                    raise RuntimeError("Item invalido en carrito: producto_id/cantidad requeridos.")

                cur.execute(
                    "SELECT verificar_stock_suficiente(%s, %s) AS ok",
                    (producto_id, cantidad),
                )
                row_ok = cur.fetchone() or {}
                if not bool(row_ok.get("ok")):
                    raise RuntimeError(f"Stock insuficiente para producto_id={producto_id}.")

            # Preparar campos base del pedido.
            total = float(datos.get("total") or 0)
            if total <= 0:
                total = sum(float(item.get("precio_unit") or item.get("precio_unitario") or 0) * int(item.get("cantidad") or 0) for item in items)

            metodo_entrega = str(datos.get("metodo_entrega") or datos.get("entrega") or "recoger_tienda")
            metodo_pago = str(datos.get("metodo_pago") or datos.get("pago") or "efectivo")
            requiere_factura = bool(datos.get("factura") if "factura" in datos else datos.get("requiere_factura"))
            direccion_id = datos.get("direccion_id")
            datos_fiscales_id = datos.get("datos_fiscales_id")

            # Si requiere factura y no hay fiscal_id, intentamos crearlo desde datos_fiscales temporal.
            if requiere_factura and not datos_fiscales_id:
                datos_fiscales = datos.get("datos_fiscales") if isinstance(datos.get("datos_fiscales"), dict) else {}
                if datos_fiscales:
                    datos_fiscales_id = _guardar_datos_fiscales_cliente_cur(
                        cur,
                        cliente_id=cliente_id,
                        datos_fiscales=datos_fiscales,
                    )

            # Generar codigo en SQL (fallback a helper Python si no existe funcion SQL).
            try:
                cur.execute("SELECT generar_codigo_entrega() AS codigo")
                codigo_entrega = (cur.fetchone() or {}).get("codigo")
            except Exception:
                codigo_entrega = _generar_codigo_entrega_db(cur)

            cols_pedidos = {
                "tipo": _tabla_tiene_columna(conn, "pedidos", "tipo"),
                "metodo_entrega": _tabla_tiene_columna(conn, "pedidos", "metodo_entrega"),
                "metodo_pago": _tabla_tiene_columna(conn, "pedidos", "metodo_pago"),
                "requiere_factura": _tabla_tiene_columna(conn, "pedidos", "requiere_factura"),
                "datos_fiscales_id": _tabla_tiene_columna(conn, "pedidos", "datos_fiscales_id"),
                "direccion_id": _tabla_tiene_columna(conn, "pedidos", "direccion_id"),
                "codigo_entrega": _tabla_tiene_columna(conn, "pedidos", "codigo_entrega"),
                "creado_en": _tabla_tiene_columna(conn, "pedidos", "creado_en"),
            }

            fields = ["cliente_id", "estado", "total"]
            values = [cliente_id, "recibido", total]
            placeholders = ["%s", "%s", "%s"]

            if cols_pedidos["tipo"]:
                fields.append("tipo")
                values.append("orden")
                placeholders.append("%s")
            if cols_pedidos["metodo_entrega"]:
                fields.append("metodo_entrega")
                values.append(metodo_entrega)
                placeholders.append("%s")
            if cols_pedidos["metodo_pago"]:
                fields.append("metodo_pago")
                values.append(metodo_pago)
                placeholders.append("%s")
            if cols_pedidos["requiere_factura"]:
                fields.append("requiere_factura")
                values.append(requiere_factura)
                placeholders.append("%s")
            if cols_pedidos["datos_fiscales_id"]:
                fields.append("datos_fiscales_id")
                values.append(datos_fiscales_id)
                placeholders.append("%s")
            if cols_pedidos["direccion_id"]:
                fields.append("direccion_id")
                values.append(direccion_id)
                placeholders.append("%s")
            if cols_pedidos["codigo_entrega"]:
                fields.append("codigo_entrega")
                values.append(codigo_entrega)
                placeholders.append("%s")
            if cols_pedidos["creado_en"]:
                fields.append("creado_en")
                # Usar hora de BD evita desfase UTC/local en reportes por fecha.
                placeholders.append("NOW()")

            # Paso 2: pedido principal.
            cur.execute(
                f"INSERT INTO pedidos ({', '.join(fields)}) VALUES ({', '.join(placeholders)}) RETURNING pedido_id",
                tuple(values),
            )
            pedido_id = int((cur.fetchone() or {}).get("pedido_id") or 0)
            if pedido_id <= 0:
                raise RuntimeError("No se pudo crear pedido en tabla pedidos.")

            # Paso 3: detalle por item (trigger SQL maneja inventario).
            for item in items:
                producto_id = int(item.get("producto_id") or 0)
                cantidad = int(item.get("cantidad") or 0)
                precio_unitario = float(item.get("precio_unit") or item.get("precio_unitario") or 0)
                cur.execute(
                    """
                    INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio_unitario)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (pedido_id, producto_id, cantidad, precio_unitario),
                )

            # Paso 3b: registrar bitacora de consumo de inventario.
            # Si existe trigger SQL de descuento, solo registramos movimientos.
            actor_usuario = (str(datos.get("actor_usuario") or "") or "bot").strip() or "bot"
            actor_rol = (str(datos.get("actor_rol") or "") or "bot").strip() or "bot"
            trigger_descuenta = _detalle_pedido_tiene_trigger_descuento(cur)
            consumo = _descontar_inventario_por_pedido(
                cur,
                pedido_id=pedido_id,
                items=items,
                actor_usuario=actor_usuario,
                actor_rol=actor_rol,
                actualizar_stock=not trigger_descuenta,
            )
            if isinstance(consumo, dict) and consumo.get("error"):
                raise RuntimeError(consumo.get("error"))

            # Paso 4: vincular pago pendiente si fue tarjeta.
            if metodo_pago in {"tarjeta", "mercadopago"}:
                mp_ref = (str(datos.get("mp_ref") or "")).strip()
                if mp_ref:
                    has_ref_externa = _tabla_tiene_columna(conn, "pagos", "referencia_externa")
                    has_mp_preference = _tabla_tiene_columna(conn, "pagos", "mp_preference_id")
                    if has_ref_externa:
                        cur.execute(
                            "UPDATE pagos SET pedido_id = %s WHERE referencia_externa = %s",
                            (pedido_id, mp_ref),
                        )
                    elif has_mp_preference:
                        cur.execute(
                            "UPDATE pagos SET pedido_id = %s WHERE mp_preference_id = %s",
                            (pedido_id, mp_ref),
                        )

            # Paso 5: contador de compras del cliente (si existe la columna).
            if _tabla_tiene_columna(conn, "clientes", "total_compras"):
                cur.execute(
                    "UPDATE clientes SET total_compras = COALESCE(total_compras, 0) + 1 WHERE cliente_id = %s",
                    (cliente_id,),
                )

            # Paso 6: limpiar sesion de este cliente por whatsapp_id.
            cur.execute("SELECT whatsapp_id FROM clientes WHERE cliente_id = %s LIMIT 1", (cliente_id,))
            row_cli = cur.fetchone() or {}
            whatsapp_id = row_cli.get("whatsapp_id")
            if whatsapp_id:
                cur.execute(
                    "UPDATE sesiones_bot SET estado = 'completado', datos_temp = '{}'::jsonb WHERE whatsapp_id = %s",
                    (whatsapp_id,),
                )

        # Paso 8: commit.
        conn.commit()
        factura_preparacion = None
        if bool(requiere_factura):
            factura_preparacion = preparar_factura_automatica_pedido(
                pedido_id=pedido_id,
                actor_usuario=actor_usuario,
                requiere_factura_override=requiere_factura,
                datos_fiscales_id_override=datos_fiscales_id,
            )
        return {
            "pedido_id": pedido_id,
            "codigo_entrega": codigo_entrega,
            "total": round(float(total), 2),
            "movimientos_inventario": (consumo or {}).get("movimientos", []),
            "factura_preparacion": factura_preparacion,
        }

    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def actualizar_estado_pedido(pedido_id, nuevo_estado, actor_usuario=None, rol_actor=None, motivo=None):
    conn = None
    try:
        nuevo = (nuevo_estado or "").strip().lower()
        if nuevo not in ESTADOS_PEDIDO:
            return {"error": "Estado no valido."}

        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _set_audit_actor(cur, actor_username=actor_usuario, actor_rol=rol_actor)
            cur.execute(
                """
                SELECT pedido_id, estado, creado_en
                FROM pedidos
                WHERE pedido_id = %s
                LIMIT 1
                """,
                (pedido_id,),
            )
            actual = cur.fetchone()
            if not actual:
                return {"error": "Pedido no encontrado."}

            estado_actual = (actual.get("estado") or "").strip().lower()
            if estado_actual == nuevo:
                return {
                    "pedido_id": actual["pedido_id"],
                    "estado": actual["estado"],
                    "creado_en": actual["creado_en"],
                }

            permitidos = TRANSICIONES_PEDIDO_VALIDAS.get(estado_actual, set())
            if nuevo not in permitidos:
                return {
                    "error": f"Transicion no permitida: {estado_actual} -> {nuevo}."
                }

            cur.execute(
                """
                UPDATE pedidos
                SET estado = %s
                WHERE pedido_id = %s
                RETURNING pedido_id, estado, creado_en
                """,
                (nuevo, pedido_id),
            )
            actualizado = cur.fetchone()

            _registrar_bitacora_estado(
                cur,
                pedido_id=pedido_id,
                estado_anterior=estado_actual,
                estado_nuevo=nuevo,
                actor_usuario=actor_usuario,
                rol_actor=rol_actor,
                motivo=motivo,
            )

            asignacion_auto = None
            if nuevo in {"listo", "en_camino"}:
                _asegurar_tabla_usuarios_sistema(conn)
                asignacion_auto = _auto_asignar_repartidor_pedido_cur(
                    cur,
                    pedido_id=pedido_id,
                    asignado_por=actor_usuario or "sistema_auto",
                )

            if nuevo in {"entregado", "cancelado"}:
                cur.execute(
                    """
                    UPDATE asignaciones_reparto
                    SET activo = FALSE
                    WHERE pedido_id = %s AND activo = TRUE
                    """,
                    (pedido_id,),
                )

            conn.commit()
            if asignacion_auto:
                actualizado["asignacion_reparto"] = asignacion_auto
            return actualizado
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_pedidos_por_estado(estado):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    p.pedido_id,
                    p.estado,
                    p.total,
                    p.creado_en,
                    c.cliente_id,
                    c.whatsapp_id,
                    c.nombre,
                    c.apellidos
                FROM pedidos p
                JOIN clientes c ON c.cliente_id = p.cliente_id
                WHERE p.estado = %s
                ORDER BY p.creado_en DESC
                """,
                (estado,),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_pedidos(
    estado=None,
    fecha=None,
    fecha_desde=None,
    fecha_hasta=None,
    busqueda=None,
    limit=None,
    offset=0,
):
    conn = None
    try:
        conn = get_connection()
        clauses = []
        params = []

        if estado:
            if isinstance(estado, (list, tuple, set)):
                estados = [str(e).strip() for e in estado if str(e).strip()]
                if estados:
                    placeholders = ", ".join(["%s"] * len(estados))
                    clauses.append(f"p.estado IN ({placeholders})")
                    params.extend(estados)
            else:
                clauses.append("p.estado = %s")
                params.append(estado)

        if fecha == "hoy":
            clauses.append("p.creado_en::date = CURRENT_DATE")

        if fecha_desde:
            clauses.append("p.creado_en >= %s::date")
            params.append(str(fecha_desde).strip())

        if fecha_hasta:
            clauses.append("p.creado_en < (%s::date + INTERVAL '1 day')")
            params.append(str(fecha_hasta).strip())

        direccion_expr = _direccion_text_expr("dc")

        search = str(busqueda or "").strip()
        if search:
            clauses.append(
                f"""
                (
                    CAST(p.pedido_id AS TEXT) ILIKE %s
                    OR COALESCE(c.whatsapp_id, '') ILIKE %s
                    OR COALESCE(c.nombre, '') ILIKE %s
                    OR COALESCE(c.apellidos, '') ILIKE %s
                    OR COALESCE({direccion_expr}, '') ILIKE %s
                )
                """
            )
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern, pattern, pattern])

        where_sql = ""
        if clauses:
            where_sql = "WHERE " + " AND ".join(clauses)

        limit_sql = ""
        if limit is not None:
            lim = max(1, min(500, int(limit)))
            off = max(0, int(offset or 0))
            limit_sql = " LIMIT %s OFFSET %s"
            params.extend([lim, off])

        query = f"""
            SELECT
                p.pedido_id,
                p.estado,
                p.total,
                p.creado_en,
                c.cliente_id,
                c.whatsapp_id,
                c.nombre,
                c.apellidos,
                COALESCE(NULLIF(MAX({direccion_expr}), ''), 'Sin direccion') AS direccion_entrega,
                COALESCE(NULLIF(SUBSTRING(MAX({direccion_expr}) FROM '([0-9]{{5}})'), ''), '00000') AS codigo_postal,
                COALESCE(SUM(dp.cantidad), 0)::INT AS cantidad_total,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'detalle_id', dp.detalle_id,
                            'producto_id', dp.producto_id,
                            'producto', COALESCE(pr.nombre, 'Producto'),
                            'variante', COALESCE(pr.variante, ''),
                            'cantidad', dp.cantidad,
                            'precio_unitario', dp.precio_unitario
                        )
                    ) FILTER (WHERE dp.detalle_id IS NOT NULL),
                    '[]'::json
                ) AS items
            FROM pedidos p
            JOIN clientes c ON c.cliente_id = p.cliente_id
            LEFT JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
            LEFT JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
            LEFT JOIN productos pr ON pr.producto_id = dp.producto_id
            {where_sql}
            GROUP BY p.pedido_id, p.estado, p.total, p.creado_en, c.cliente_id, c.whatsapp_id, c.nombre, c.apellidos
            ORDER BY p.creado_en DESC
            {limit_sql}
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def confirmar_entrega_pedido(pedido_id, codigo_entrega=None, numero_confirmacion_pago=None, actor_usuario=None, rol_actor=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_auditoria_negocio(conn)
        has_codigo = _tabla_tiene_columna(conn, "pedidos", "codigo_entrega")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _set_audit_actor(
                cur,
                actor_username=actor_usuario or "repartidor",
                actor_rol=rol_actor or "repartidor",
            )
            if has_codigo:
                cur.execute(
                    """
                    SELECT pedido_id, estado, codigo_entrega, COALESCE(metodo_pago, 'efectivo') AS metodo_pago, total
                    FROM pedidos
                    WHERE pedido_id = %s
                    LIMIT 1
                    """,
                    (pedido_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT pedido_id, estado, COALESCE(metodo_pago, 'efectivo') AS metodo_pago, total
                    FROM pedidos
                    WHERE pedido_id = %s
                    LIMIT 1
                    """,
                    (pedido_id,),
                )

            row = cur.fetchone()
            if not row:
                return {"error": "Pedido no encontrado."}

            estado_actual = (row.get("estado") or "").strip().lower()
            if estado_actual not in {"listo", "en_camino"}:
                return {"error": "Solo se puede confirmar entrega para pedidos en estado listo o en_camino."}

            codigo_in = (codigo_entrega or "").strip().upper()
            if not codigo_in:
                return {"error": "Debes ingresar el codigo de entrega para liberar el pedido."}

            if not has_codigo:
                return {"error": "La base de datos no tiene columna codigo_entrega. Ejecuta migracion/arranque nuevamente."}

            codigo_db = (row.get("codigo_entrega") or "").strip().upper()
            if not codigo_db:
                return {"error": "Este pedido no tiene codigo de entrega asignado. Reenvia o genera un codigo primero."}

            if codigo_db != codigo_in:
                return {"error": "Codigo de entrega incorrecto."}

            metodo_pago = (row.get("metodo_pago") or "efectivo").strip().lower()
            metodo_pago_contra = metodo_pago in {"contra_entrega_ficticio", "contra_entrega", "pago_entrega_ficticio"}
            confirmacion_pago = None
            monto = float(row.get("total") or 0)

            # En pago contra entrega (demo), exigimos folio de confirmacion antes de liberar.
            if metodo_pago_contra:
                confirmacion_pago = (numero_confirmacion_pago or "").strip().upper()
                # Conservamos compatibilidad retro pasando el folio por codigo_entrega cuando venga con prefijo.
                # El API envia este dato en el campo dedicado, pero este fallback evita ruptura de clientes viejos.
                if codigo_in.startswith("PAY-"):
                    confirmacion_pago = codigo_in

                if not confirmacion_pago:
                    return {"error": "Debes registrar numero de confirmacion de pago para liberar el pedido contra entrega."}

                _registrar_pago_conciliado_cur(
                    cur,
                    pedido_id=pedido_id,
                    monto=monto,
                    proveedor="contra_entrega_ficticio",
                    referencia=confirmacion_pago,
                    detalle="pago confirmado al entregar (demo)",
                )
            elif metodo_pago == "efectivo":
                _registrar_pago_conciliado_cur(
                    cur,
                    pedido_id=pedido_id,
                    monto=monto,
                    proveedor="efectivo",
                    referencia=f"CASH-{pedido_id}-{codigo_db or codigo_in}",
                    detalle="cobro en efectivo validado al momento de la entrega",
                )

            cur.execute(
                """
                UPDATE pedidos
                SET estado = 'entregado'
                WHERE pedido_id = %s
                  AND estado IN ('listo', 'en_camino')
                RETURNING pedido_id, estado, creado_en
                """,
                (pedido_id,),
            )
            updated = cur.fetchone()
            if not updated:
                return {"error": "No se pudo liberar el pedido desde el estado actual."}

            _registrar_bitacora_estado(
                cur,
                pedido_id=pedido_id,
                estado_anterior=estado_actual,
                estado_nuevo="entregado",
                actor_usuario=actor_usuario or "repartidor",
                rol_actor=rol_actor or "repartidor",
                motivo="Confirmacion de entrega con codigo",
            )

            cur.execute(
                """
                UPDATE asignaciones_reparto
                SET activo = FALSE
                WHERE pedido_id = %s AND activo = TRUE
                """,
                (pedido_id,),
            )
            conn.commit()
            if confirmacion_pago:
                updated["confirmacion_pago"] = confirmacion_pago
            return updated
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_o_generar_codigo_entrega_pedido(pedido_id):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT pedido_id, codigo_entrega
                FROM pedidos
                WHERE pedido_id = %s
                LIMIT 1
                """,
                (pedido_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Pedido no encontrado."}

            codigo = (row.get("codigo_entrega") or "").strip().upper()
            if not codigo:
                codigo = _generar_codigo_entrega_db(cur)
                cur.execute(
                    """
                    UPDATE pedidos
                    SET codigo_entrega = %s
                    WHERE pedido_id = %s
                    """,
                    (codigo, pedido_id),
                )

            conn.commit()
            return {"pedido_id": pedido_id, "codigo_entrega": codigo}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_destino_whatsapp_por_pedido(pedido_id):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT p.pedido_id, c.whatsapp_id
                FROM pedidos p
                JOIN clientes c ON c.cliente_id = p.cliente_id
                WHERE p.pedido_id = %s
                LIMIT 1
                """,
                (pedido_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Pedido no encontrado."}

            whatsapp_id = (row.get("whatsapp_id") or "").strip()
            if not whatsapp_id:
                return {"error": "El pedido no tiene WhatsApp asociado."}

            return {"pedido_id": row.get("pedido_id"), "whatsapp_id": whatsapp_id}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def asignar_pedido_repartidor(pedido_id, repartidor_usuario, asignado_por=None):
    conn = None
    try:
        if not repartidor_usuario:
            return {"error": "repartidor_usuario es obligatorio."}

        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)

        direccion_expr = _direccion_text_expr("dc")
        area_expr = f"COALESCE(NULLIF(TRIM(dc.alias), ''), NULLIF(TRIM(dc.codigo_postal), ''), COALESCE(NULLIF(SUBSTRING({direccion_expr} FROM '([0-9]{{5}})'), ''), '00000'))"

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    p.pedido_id,
                    p.estado,
                    {area_expr} AS area_entrega
                FROM pedidos p
                LEFT JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
                WHERE p.pedido_id = %s
                LIMIT 1
                """,
                (pedido_id,),
            )
            pedido = cur.fetchone()
            if not pedido:
                return {"error": "Pedido no encontrado."}

            if (pedido.get("estado") or "").strip().lower() not in {"listo", "en_camino"}:
                return {"error": "Solo se pueden asignar pedidos en estado listo o en_camino."}

            cur.execute(
                """
                SELECT usuario_id, username, rol, activo, area_entrega
                FROM usuarios_sistema
                WHERE LOWER(username) = LOWER(%s)
                LIMIT 1
                """,
                (repartidor_usuario,),
            )
            repartidor = cur.fetchone()
            if not repartidor:
                return {"error": "Repartidor no encontrado."}
            if not repartidor.get("activo"):
                return {"error": "El repartidor esta inactivo."}
            if (repartidor.get("rol") or "").strip().lower() != "repartidor":
                return {"error": "El usuario indicado no tiene rol repartidor."}

            area_pedido = _normalizar_area_entrega(pedido.get("area_entrega"))
            area_repartidor = _normalizar_area_entrega(repartidor.get("area_entrega"))
            if not area_repartidor:
                return {"error": "El repartidor no tiene area_entrega configurada."}
            if area_pedido and area_repartidor.lower() != area_pedido.lower():
                return {"error": f"El pedido pertenece al area '{area_pedido}' y el repartidor cubre '{area_repartidor}'."}

            cur.execute(
                """
                UPDATE asignaciones_reparto
                SET activo = FALSE
                WHERE pedido_id = %s AND activo = TRUE
                """,
                (pedido_id,),
            )

            cur.execute(
                """
                INSERT INTO asignaciones_reparto (pedido_id, repartidor_usuario, asignado_por, activo)
                VALUES (%s, %s, %s, TRUE)
                RETURNING asignacion_id, pedido_id, repartidor_usuario, asignado_por, asignado_en, activo
                """,
                (pedido_id, repartidor.get("username"), asignado_por),
            )
            row = cur.fetchone()
            if row is not None:
                row["area_entrega"] = area_repartidor
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_pedidos_repartidor(repartidor_usuario=None, area_entrega=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)

        params = ["listo", "en_camino"]  # type: list[object]
        direccion_expr = _direccion_text_expr("dc")
        area_expr = f"COALESCE(NULLIF(TRIM(dc.alias), ''), NULLIF(TRIM(dc.codigo_postal), ''), COALESCE(NULLIF(SUBSTRING({direccion_expr} FROM '([0-9]{{5}})'), ''), '00000'))"
        where_assignment = ""
        area_filter = _normalizar_area_entrega(area_entrega)
        if repartidor_usuario:
            where_assignment = f"""
            AND (
                ar.repartidor_usuario = %s
                OR (
                    ar.repartidor_usuario IS NULL
                    AND (%s IS NULL OR LOWER({area_expr}) = LOWER(%s))
                )
            )
            """
            params.append(repartidor_usuario)
            params.append(area_filter)
            params.append(area_filter)

        query = f"""
            SELECT
                p.pedido_id,
                p.estado,
                p.total,
                COALESCE(p.metodo_pago, 'efectivo') AS metodo_pago,
                p.creado_en,
                c.nombre,
                c.apellidos,
                c.whatsapp_id,
                COALESCE(NULLIF(MAX({direccion_expr}), ''), 'Sin direccion') AS direccion_entrega,
                COALESCE(NULLIF(SUBSTRING(MAX({direccion_expr}) FROM '([0-9]{{5}})'), ''), '00000') AS codigo_postal,
                MAX({area_expr}) AS area_entrega,
                ar.repartidor_usuario,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'producto', COALESCE(pr.nombre, 'Producto'),
                            'variante', COALESCE(pr.variante, ''),
                            'cantidad', dp.cantidad
                        )
                    ) FILTER (WHERE dp.detalle_id IS NOT NULL),
                    '[]'::json
                ) AS items
            FROM pedidos p
            JOIN clientes c ON c.cliente_id = p.cliente_id
            LEFT JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
            LEFT JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
            LEFT JOIN productos pr ON pr.producto_id = dp.producto_id
            LEFT JOIN asignaciones_reparto ar ON ar.pedido_id = p.pedido_id AND ar.activo = TRUE
            WHERE p.estado IN (%s, %s)
            {where_assignment}
            GROUP BY p.pedido_id, p.estado, p.total, p.metodo_pago, p.creado_en, c.nombre, c.apellidos, c.whatsapp_id, ar.repartidor_usuario
            ORDER BY p.creado_en ASC
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_bitacora_pedido(pedido_id, limit=50):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT bitacora_id, pedido_id, estado_anterior, estado_nuevo, actor_usuario, rol_actor, motivo, creado_en
                FROM bitacora_estado_pedidos
                WHERE pedido_id = %s
                ORDER BY creado_en DESC
                LIMIT %s
                """,
                (pedido_id, int(limit)),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_ventas_diarias():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR(DATE_TRUNC('hour', p.creado_en), 'HH24:00') AS etiqueta,
                    COUNT(*)::INT AS pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
                FROM pedidos p
                WHERE p.estado <> 'cancelado'
                  AND p.creado_en::date = CURRENT_DATE
                GROUP BY DATE_TRUNC('hour', p.creado_en)
                ORDER BY DATE_TRUNC('hour', p.creado_en)
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_ventas_mensuales():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR(DATE_TRUNC('day', p.creado_en), 'YYYY-MM-DD') AS etiqueta,
                    COUNT(*)::INT AS pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
                FROM pedidos p
                WHERE p.estado <> 'cancelado'
                  AND DATE_TRUNC('month', p.creado_en) = DATE_TRUNC('month', CURRENT_DATE)
                GROUP BY DATE_TRUNC('day', p.creado_en)
                ORDER BY DATE_TRUNC('day', p.creado_en)
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_ventas_anuales():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR(DATE_TRUNC('month', p.creado_en), 'YYYY-MM') AS etiqueta,
                    COUNT(*)::INT AS pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
                FROM pedidos p
                WHERE p.estado <> 'cancelado'
                  AND DATE_TRUNC('year', p.creado_en) = DATE_TRUNC('year', CURRENT_DATE)
                GROUP BY DATE_TRUNC('month', p.creado_en)
                ORDER BY DATE_TRUNC('month', p.creado_en)
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_kpis_ventas_periodo():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH base AS (
                    SELECT
                        p.pedido_id,
                        p.cliente_id,
                        p.total,
                        p.creado_en
                    FROM pedidos p
                    WHERE p.estado <> 'cancelado'
                ),
                day_current AS (
                    SELECT
                        COALESCE(SUM(total), 0)::NUMERIC(12,2) AS ventas,
                        COUNT(*)::INT AS pedidos,
                        COUNT(DISTINCT cliente_id)::INT AS clientes
                    FROM base
                    WHERE creado_en::date = CURRENT_DATE
                ),
                day_prev AS (
                    SELECT
                        COALESCE(SUM(total), 0)::NUMERIC(12,2) AS ventas
                    FROM base
                    WHERE creado_en::date = (CURRENT_DATE - INTERVAL '1 day')::date
                ),
                month_current AS (
                    SELECT
                        COALESCE(SUM(total), 0)::NUMERIC(12,2) AS ventas,
                        COUNT(*)::INT AS pedidos,
                        COUNT(DISTINCT cliente_id)::INT AS clientes
                    FROM base
                    WHERE DATE_TRUNC('month', creado_en) = DATE_TRUNC('month', CURRENT_DATE)
                ),
                month_prev AS (
                    SELECT
                        COALESCE(SUM(total), 0)::NUMERIC(12,2) AS ventas
                    FROM base
                    WHERE DATE_TRUNC('month', creado_en) = DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
                ),
                year_current AS (
                    SELECT
                        COALESCE(SUM(total), 0)::NUMERIC(12,2) AS ventas,
                        COUNT(*)::INT AS pedidos,
                        COUNT(DISTINCT cliente_id)::INT AS clientes
                    FROM base
                    WHERE DATE_TRUNC('year', creado_en) = DATE_TRUNC('year', CURRENT_DATE)
                ),
                year_prev AS (
                    SELECT
                        COALESCE(SUM(total), 0)::NUMERIC(12,2) AS ventas
                    FROM base
                    WHERE DATE_TRUNC('year', creado_en) = DATE_TRUNC('year', CURRENT_DATE - INTERVAL '1 year')
                )
                SELECT
                    dc.ventas AS dia_ventas,
                    dc.pedidos AS dia_pedidos,
                    dc.clientes AS dia_clientes,
                    dp.ventas AS dia_prev_ventas,
                    mc.ventas AS mes_ventas,
                    mc.pedidos AS mes_pedidos,
                    mc.clientes AS mes_clientes,
                    mp.ventas AS mes_prev_ventas,
                    yc.ventas AS ano_ventas,
                    yc.pedidos AS ano_pedidos,
                    yc.clientes AS ano_clientes,
                    yp.ventas AS ano_prev_ventas
                FROM day_current dc
                CROSS JOIN day_prev dp
                CROSS JOIN month_current mc
                CROSS JOIN month_prev mp
                CROSS JOIN year_current yc
                CROSS JOIN year_prev yp
                """
            )
            row = cur.fetchone() or {}

            def _to_float(v):
                return float(v or 0)

            def _to_int(v):
                return int(v or 0)

            def _growth(current, previous):
                if previous and previous > 0:
                    return round(((current - previous) / previous) * 100, 2)
                return 0.0

            def _pack(prefix):
                ventas = _to_float(row.get(f"{prefix}_ventas"))
                pedidos = _to_int(row.get(f"{prefix}_pedidos"))
                clientes = _to_int(row.get(f"{prefix}_clientes"))
                prev_ventas = _to_float(row.get(f"{prefix}_prev_ventas"))
                ticket = round((ventas / pedidos), 2) if pedidos > 0 else 0.0
                return {
                    "ventas": round(ventas, 2),
                    "pedidos": pedidos,
                    "clientes": clientes,
                    "ticket_promedio": ticket,
                    "crecimiento_pct": _growth(ventas, prev_ventas),
                }

            return {
                "dia": _pack("dia"),
                "mes": _pack("mes"),
                "ano": _pack("ano"),
            }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_reporte_ventas_profesional(periodo="dia", fecha_base=None, busqueda=None, limit=300):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_tablas_inventario_real(conn)
        _asegurar_tabla_compras_insumos(conn)
        has_metodo_pago = _tabla_tiene_columna(conn, "pedidos", "metodo_pago")
        has_metodo_entrega = _tabla_tiene_columna(conn, "pedidos", "metodo_entrega")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = ["p.estado <> 'cancelado'"]
            params = []

            periodo_norm = str(periodo or "dia").strip().lower()
            if periodo_norm not in {"dia", "semana", "mes", "ano"}:
                periodo_norm = "dia"

            fecha_ref = str(fecha_base or "").strip()
            if fecha_ref:
                params.append(fecha_ref)
                if periodo_norm == "dia":
                    filtros.append("p.creado_en::date = %s::date")
                elif periodo_norm == "semana":
                    filtros.append(
                        """
                        p.creado_en >= DATE_TRUNC('week', %s::date)
                        AND p.creado_en < (DATE_TRUNC('week', %s::date) + INTERVAL '7 day')
                        """
                    )
                    params.append(fecha_ref)
                elif periodo_norm == "mes":
                    filtros.append(
                        """
                        p.creado_en >= DATE_TRUNC('month', %s::date)
                        AND p.creado_en < (DATE_TRUNC('month', %s::date) + INTERVAL '1 month')
                        """
                    )
                    params.append(fecha_ref)
                else:
                    filtros.append(
                        """
                        p.creado_en >= DATE_TRUNC('year', %s::date)
                        AND p.creado_en < (DATE_TRUNC('year', %s::date) + INTERVAL '1 year')
                        """
                    )
                    params.append(fecha_ref)
            else:
                if periodo_norm == "dia":
                    filtros.append("p.creado_en::date = CURRENT_DATE")
                elif periodo_norm == "semana":
                    filtros.append(
                        """
                        p.creado_en >= DATE_TRUNC('week', CURRENT_DATE)
                        AND p.creado_en < (DATE_TRUNC('week', CURRENT_DATE) + INTERVAL '7 day')
                        """
                    )
                elif periodo_norm == "mes":
                    filtros.append("DATE_TRUNC('month', p.creado_en) = DATE_TRUNC('month', CURRENT_DATE)")
                else:
                    filtros.append("DATE_TRUNC('year', p.creado_en) = DATE_TRUNC('year', CURRENT_DATE)")

            q = str(busqueda or "").strip()
            if q:
                pattern = f"%{q}%"
                filtros.append(
                    """
                    (
                        CAST(p.pedido_id AS TEXT) ILIKE %s
                        OR COALESCE(c.nombre, '') ILIKE %s
                        OR COALESCE(c.apellidos, '') ILIKE %s
                        OR COALESCE(c.whatsapp_id, '') ILIKE %s
                    )
                    """
                )
                params.extend([pattern, pattern, pattern, pattern])

            where_sql = "WHERE " + " AND ".join(filtros)
            metodo_pago_sql = "COALESCE(p.metodo_pago, '-')" if has_metodo_pago else "'-'"
            metodo_entrega_sql = "COALESCE(p.metodo_entrega, '-')" if has_metodo_entrega else "'-'"
            group_cols = [
                "p.pedido_id",
                "p.creado_en",
                "p.estado",
                "p.total",
                "c.cliente_id",
                "c.nombre",
                "c.apellidos",
                "c.whatsapp_id",
            ]
            if has_metodo_pago:
                group_cols.append("COALESCE(p.metodo_pago, '-')")
            if has_metodo_entrega:
                group_cols.append("COALESCE(p.metodo_entrega, '-')")
            group_cols.extend([
                "et.ts_listo",
                "et.ts_entregado",
            ])
            group_by_sql = ",\n                    ".join(group_cols)

            lim = max(1, min(1000, int(limit or 300)))
            params.append(lim)

            cur.execute(
                f"""
                WITH estado_times AS (
                    SELECT
                        b.pedido_id,
                        MIN(CASE WHEN b.estado_nuevo IN ('listo', 'en_camino', 'entregado') THEN b.creado_en END) AS ts_listo,
                        MIN(CASE WHEN b.estado_nuevo = 'entregado' THEN b.creado_en END) AS ts_entregado
                    FROM bitacora_estado_pedidos b
                    GROUP BY b.pedido_id
                ),
                costo_insumo AS (
                    SELECT DISTINCT ON (c.insumo_id)
                        c.insumo_id,
                        COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                    FROM compras_insumos c
                    WHERE c.costo_total IS NOT NULL
                      AND c.cantidad > 0
                    ORDER BY c.insumo_id, c.creado_en DESC
                ),
                costo_producto AS (
                    SELECT
                        r.producto_id,
                        COALESCE(SUM(r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)::NUMERIC(12,4) AS costo_unitario_producto
                    FROM recetas_producto_insumo r
                    LEFT JOIN costo_insumo ci ON ci.insumo_id = r.insumo_id
                    WHERE r.activo = TRUE
                    GROUP BY r.producto_id
                )
                SELECT
                    p.pedido_id,
                    p.creado_en,
                    p.estado,
                    p.total::NUMERIC(12,2) AS total,
                    c.cliente_id,
                    COALESCE(NULLIF(TRIM(c.nombre || ' ' || COALESCE(c.apellidos, '')), ''), 'Cliente') AS cliente,
                    COALESCE(c.whatsapp_id, '-') AS whatsapp_id,
                    {metodo_pago_sql} AS metodo_pago,
                    {metodo_entrega_sql} AS metodo_entrega,
                    COALESCE(SUM(dp.cantidad), 0)::INT AS piezas,
                    COALESCE(
                        STRING_AGG(
                            (COALESCE(pr.nombre, 'Producto') ||
                             CASE WHEN COALESCE(pr.variante, '') <> '' THEN ' ' || pr.variante ELSE '' END ||
                             ' x' || COALESCE(dp.cantidad, 0)::TEXT),
                            ', ' ORDER BY dp.detalle_id
                        ),
                        '-'
                    ) AS productos,
                    COALESCE(SUM(dp.cantidad * COALESCE(cp.costo_unitario_producto, 0)), 0)::NUMERIC(12,2) AS costo_estimado,
                    (p.total - COALESCE(SUM(dp.cantidad * COALESCE(cp.costo_unitario_producto, 0)), 0))::NUMERIC(12,2) AS utilidad_estimada,
                    CASE
                        WHEN p.total > 0 THEN ((p.total - COALESCE(SUM(dp.cantidad * COALESCE(cp.costo_unitario_producto, 0)), 0)) / p.total) * 100
                        ELSE 0
                    END::NUMERIC(12,2) AS margen_estimado_pct,
                    ROUND(EXTRACT(EPOCH FROM (et.ts_listo - p.creado_en)) / 60.0, 2) AS rapidez_preparacion_min,
                    ROUND(EXTRACT(EPOCH FROM (et.ts_entregado - p.creado_en)) / 60.0, 2) AS rapidez_entrega_min
                FROM pedidos p
                JOIN clientes c ON c.cliente_id = p.cliente_id
                LEFT JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
                LEFT JOIN productos pr ON pr.producto_id = dp.producto_id
                LEFT JOIN costo_producto cp ON cp.producto_id = dp.producto_id
                LEFT JOIN estado_times et ON et.pedido_id = p.pedido_id
                {where_sql}
                GROUP BY
                    {group_by_sql}
                ORDER BY p.creado_en DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []

            total_ventas = round(sum(float(r.get("total") or 0) for r in rows), 2)
            total_pedidos = len(rows)
            ticket_promedio = round((total_ventas / total_pedidos), 2) if total_pedidos > 0 else 0.0
            clientes_unicos = len({int(r.get("cliente_id") or 0) for r in rows if int(r.get("cliente_id") or 0) > 0})
            costo_estimado_total = round(sum(float(r.get("costo_estimado") or 0) for r in rows), 2)
            utilidad_estimada_total = round(total_ventas - costo_estimado_total, 2)
            margen_estimado_pct = round((utilidad_estimada_total / total_ventas) * 100, 2) if total_ventas > 0 else 0.0
            reserva_impuestos_pct = 16.0
            reserva_impuestos_monto = round((total_ventas * reserva_impuestos_pct) / 100, 2)
            utilidad_neta_estimada = round(utilidad_estimada_total - reserva_impuestos_monto, 2)

            prep_vals = [float(r.get("rapidez_preparacion_min")) for r in rows if r.get("rapidez_preparacion_min") is not None]
            entrega_vals = [float(r.get("rapidez_entrega_min")) for r in rows if r.get("rapidez_entrega_min") is not None]
            rapidez_prep_promedio = round(sum(prep_vals) / len(prep_vals), 2) if prep_vals else None
            rapidez_entrega_promedio = round(sum(entrega_vals) / len(entrega_vals), 2) if entrega_vals else None

            return {
                "periodo": periodo_norm,
                "fecha_base": fecha_ref or None,
                "resumen": {
                    "ventas": total_ventas,
                    "pedidos": total_pedidos,
                    "ticket_promedio": ticket_promedio,
                    "clientes_unicos": clientes_unicos,
                    "costo_estimado_total": costo_estimado_total,
                    "utilidad_estimada_total": utilidad_estimada_total,
                    "reserva_impuestos_pct": reserva_impuestos_pct,
                    "reserva_impuestos_monto": reserva_impuestos_monto,
                    "utilidad_neta_estimada": utilidad_neta_estimada,
                    "margen_estimado_pct": margen_estimado_pct,
                    "rapidez_preparacion_promedio_min": rapidez_prep_promedio,
                    "rapidez_entrega_promedio_min": rapidez_entrega_promedio,
                },
                "rows": rows,
            }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_rentabilidad_productos(limit=30):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        _asegurar_tabla_compras_insumos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH costo_insumo AS (
                    SELECT DISTINCT ON (c.insumo_id)
                        c.insumo_id,
                        COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                    FROM compras_insumos c
                    WHERE c.costo_total IS NOT NULL
                      AND c.cantidad > 0
                    ORDER BY c.insumo_id, c.creado_en DESC
                )
                SELECT
                    p.producto_id,
                    p.nombre,
                    p.variante,
                    p.precio::NUMERIC(10,2) AS precio_venta,
                    COALESCE(p.costo_referencia, 0)::NUMERIC(10,2) AS costo_referencia,
                    GREATEST(
                        COALESCE(p.costo_referencia, 0),
                        COALESCE(SUM(r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)
                    )::NUMERIC(12,4) AS costo_estimado_unitario,
                    (
                        p.precio - GREATEST(
                            COALESCE(p.costo_referencia, 0),
                            COALESCE(SUM(r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)
                        )
                    )::NUMERIC(12,4) AS margen_unitario,
                    CASE
                        WHEN p.precio > 0 THEN ((p.precio - GREATEST(
                            COALESCE(p.costo_referencia, 0),
                            COALESCE(SUM(r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)
                        )) / p.precio) * 100
                        ELSE 0
                    END::NUMERIC(8,2) AS margen_pct,
                    COUNT(r.insumo_id)::INT AS componentes_activos,
                    COUNT(ci.insumo_id)::INT AS componentes_con_costo,
                    GREATEST(COUNT(r.insumo_id) - COUNT(ci.insumo_id), 0)::INT AS componentes_sin_costo,
                    CASE
                        WHEN COUNT(r.insumo_id) = 0 THEN 'sin_receta'
                        WHEN COUNT(ci.insumo_id) = 0 THEN 'sin_costos'
                        WHEN COUNT(ci.insumo_id) = COUNT(r.insumo_id) THEN 'completo'
                        ELSE 'incompleto'
                    END AS calidad_costo
                FROM productos p
                LEFT JOIN recetas_producto_insumo r
                    ON r.producto_id = p.producto_id
                   AND r.activo = TRUE
                LEFT JOIN costo_insumo ci
                    ON ci.insumo_id = r.insumo_id
                WHERE p.activo = TRUE
                GROUP BY p.producto_id, p.nombre, p.variante, p.precio, p.costo_referencia
                ORDER BY margen_unitario DESC, p.nombre, p.variante
                LIMIT %s
                """,
                (int(limit),),
            )
            rows = cur.fetchall() or []
            for row in rows:
                precio = round(float(row.get("precio_venta") or 0), 2)
                costo = round(float(row.get("costo_estimado_unitario") or 0), 2)
                row["utilidad_unitaria"] = round(float(row.get("margen_unitario") or 0), 2)
                row["salud_rentabilidad"] = _clasificar_salud_producto_rentabilidad(
                    precio,
                    costo,
                    row.get("calidad_costo"),
                )
            return rows
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_diagnostico_costos_receta(limit=200):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        _asegurar_tabla_compras_insumos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH costo_insumo AS (
                    SELECT DISTINCT ON (c.insumo_id)
                        c.insumo_id,
                        COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                    FROM compras_insumos c
                    WHERE c.costo_total IS NOT NULL
                      AND c.cantidad > 0
                    ORDER BY c.insumo_id, c.creado_en DESC
                )
                SELECT
                    p.producto_id,
                    p.nombre,
                    p.variante,
                    COUNT(r.insumo_id)::INT AS componentes_activos,
                    COUNT(ci.insumo_id)::INT AS componentes_con_costo,
                    GREATEST(COUNT(r.insumo_id) - COUNT(ci.insumo_id), 0)::INT AS componentes_sin_costo,
                    ARRAY_REMOVE(
                        ARRAY_AGG(i.nombre ORDER BY i.nombre)
                            FILTER (WHERE r.insumo_id IS NOT NULL AND ci.insumo_id IS NULL),
                        NULL
                    ) AS insumos_sin_costo
                    ,
                    COALESCE(
                        JSON_AGG(
                            JSON_BUILD_OBJECT(
                                'insumo_id', i.insumo_id,
                                'nombre', i.nombre
                            )
                            ORDER BY i.nombre
                        ) FILTER (WHERE r.insumo_id IS NOT NULL AND ci.insumo_id IS NULL),
                        '[]'::json
                    ) AS insumos_sin_costo_detalle
                FROM productos p
                LEFT JOIN recetas_producto_insumo r
                    ON r.producto_id = p.producto_id
                   AND r.activo = TRUE
                LEFT JOIN insumos i
                    ON i.insumo_id = r.insumo_id
                LEFT JOIN costo_insumo ci
                    ON ci.insumo_id = r.insumo_id
                WHERE p.activo = TRUE
                GROUP BY p.producto_id, p.nombre, p.variante
                HAVING COUNT(r.insumo_id) > 0
                   AND COUNT(ci.insumo_id) < COUNT(r.insumo_id)
                ORDER BY componentes_sin_costo DESC, p.nombre, p.variante
                LIMIT %s
                """,
                (int(limit),),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def registrar_factura_operativa(pedido_id=None, folio_factura=None, status="emitida", notas=None, actor_usuario=None, pdf_ruta=None, xml_ruta=None):
    try:
        pedido_id_int = int(pedido_id or 0)
    except (TypeError, ValueError):
        return {"error": "Pedido invalido para registrar factura."}

    folio = str(folio_factura or "").strip().upper()
    if not folio:
        return {"error": "Debes capturar el folio de factura."}

    estado_factura = _normalizar_texto_busqueda(status)
    if estado_factura not in {"emitida", "entregada"}:
        return {"error": "Estado de factura invalido. Usa emitida o entregada."}

    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)
        has_requiere_factura = _tabla_tiene_columna(conn, "pedidos", "requiere_factura")
        has_datos_fiscales_id = _tabla_tiene_columna(conn, "pedidos", "datos_fiscales_id")

        requiere_factura_sql = "COALESCE(p.requiere_factura, FALSE)" if has_requiere_factura else "TRUE"
        datos_fiscales_sql = "p.datos_fiscales_id" if has_datos_fiscales_id else "NULL"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    p.pedido_id,
                    p.cliente_id,
                    {requiere_factura_sql} AS requiere_factura,
                    {datos_fiscales_sql} AS datos_fiscales_id,
                    c.whatsapp_id,
                    NULL::VARCHAR AS email_destino
                FROM pedidos p
                LEFT JOIN clientes c ON c.cliente_id = p.cliente_id
                WHERE p.pedido_id = %s
                LIMIT 1
                """,
                (pedido_id_int,),
            )
            pedido = cur.fetchone()
            if not pedido:
                return {"error": "Pedido no encontrado para factura."}
            if has_requiere_factura and not bool(pedido.get("requiere_factura")):
                return {"error": "Este pedido no requiere factura."}

            if not pedido.get("datos_fiscales_id") and pedido.get("cliente_id"):
                if _tabla_existe(conn, "datos_fiscales"):
                    cur.execute(
                        """
                        SELECT fiscal_id AS datos_fiscales_id, COALESCE(email, '') AS email_destino
                        FROM datos_fiscales
                        WHERE cliente_id = %s
                        ORDER BY fiscal_id DESC
                        LIMIT 1
                        """,
                        (pedido.get("cliente_id"),),
                    )
                    fiscal_row = cur.fetchone()
                    if fiscal_row:
                        pedido["datos_fiscales_id"] = fiscal_row.get("datos_fiscales_id")
                        pedido["email_destino"] = fiscal_row.get("email_destino")
                elif _tabla_existe(conn, "datos_fiscales_clientes"):
                    cur.execute(
                        """
                        SELECT datos_fiscales_id, COALESCE(email, '') AS email_destino
                        FROM datos_fiscales_clientes
                        WHERE cliente_id = %s
                        ORDER BY datos_fiscales_id DESC
                        LIMIT 1
                        """,
                        (pedido.get("cliente_id"),),
                    )
                    fiscal_row = cur.fetchone()
                    if fiscal_row:
                        pedido["datos_fiscales_id"] = fiscal_row.get("datos_fiscales_id")
                        pedido["email_destino"] = fiscal_row.get("email_destino")

            if has_requiere_factura and has_datos_fiscales_id and not pedido.get("datos_fiscales_id"):
                return {"error": "El pedido no tiene datos fiscales completos."}

            email_destino = (str(pedido.get("email_destino") or "").strip().lower() or None)
            cur.execute(
                """
                INSERT INTO facturas_operativas (
                    pedido_id,
                    datos_fiscales_id,
                    folio_factura,
                    estado,
                    email_destino,
                    pdf_ruta,
                    xml_ruta,
                    notas,
                    emitida_por,
                    emitida_en,
                    entregada_en,
                    actualizado_en
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), CASE WHEN %s = 'entregada' THEN NOW() ELSE NULL END, NOW())
                ON CONFLICT (pedido_id)
                DO UPDATE SET
                    datos_fiscales_id = EXCLUDED.datos_fiscales_id,
                    folio_factura = EXCLUDED.folio_factura,
                    estado = EXCLUDED.estado,
                    email_destino = EXCLUDED.email_destino,
                    pdf_ruta = COALESCE(EXCLUDED.pdf_ruta, facturas_operativas.pdf_ruta),
                    xml_ruta = COALESCE(EXCLUDED.xml_ruta, facturas_operativas.xml_ruta),
                    notas = EXCLUDED.notas,
                    emitida_por = EXCLUDED.emitida_por,
                    entregada_en = CASE WHEN EXCLUDED.estado = 'entregada' THEN NOW() ELSE facturas_operativas.entregada_en END,
                    actualizado_en = NOW()
                RETURNING factura_op_id, pedido_id, datos_fiscales_id, folio_factura, estado, email_destino,
                          pdf_ruta, xml_ruta, ultimo_envio_estado, ultimo_envio_error, ultimo_envio_en, ultimo_envio_destino,
                          notas, emitida_por, emitida_en, entregada_en, actualizado_en
                """,
                (
                    pedido_id_int,
                    pedido.get("datos_fiscales_id"),
                    folio,
                    estado_factura,
                    email_destino,
                    (str(pdf_ruta).strip() if pdf_ruta else None),
                    (str(xml_ruta).strip() if xml_ruta else None),
                    (str(notas or "").strip() or None),
                    (str(actor_usuario or "").strip() or "admin"),
                    estado_factura,
                ),
            )
            row = cur.fetchone() or {}
            row["whatsapp_id"] = pedido.get("whatsapp_id")
        conn.commit()
        return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def registrar_auditoria_factura(pedido_id, evento_tipo, detalles=None, actor_username=None, actor_rol=None):
    """Registra evento de auditoría para seguimiento de facturas.
    
    Args:
        pedido_id: ID del pedido afectado
        evento_tipo: Tipo de evento (solicitud_datos, datos_guardados, factura_emitida, 
                     factura_entregada, notificacion_enviada, notificacion_fallida)
        detalles: Dict con información adicional del evento
        actor_username: Usuario que causó el evento
        actor_rol: Rol del usuario (admin, bot, sistema)
    
    Returns:
        Dict con id_auditoria o error
    """
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)
        
        # Asegurar tabla de auditoría de facturas
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auditoria_facturas (
                    auditoria_id BIGSERIAL PRIMARY KEY,
                    pedido_id BIGINT NOT NULL REFERENCES pedidos(pedido_id),
                    evento_tipo VARCHAR(50) NOT NULL,
                    actor_username VARCHAR(80),
                    actor_rol VARCHAR(30),
                    detalles JSONB NOT NULL DEFAULT '{}'::jsonb,
                    creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                    ip_origen VARCHAR(45),
                    CONSTRAINT chk_auditoria_facturas_evento CHECK (
                        evento_tipo IN (
                            'solicitud_datos', 'datos_guardados', 'validacion_fallida',
                            'factura_emitida', 'factura_entregada', 'factura_cancelada',
                            'notificacion_whatsapp_enviada', 'notificacion_whatsapp_fallida',
                            'notificacion_email_enviada', 'notificacion_email_fallida',
                            'pdf_generado', 'pdf_fallido'
                        )
                    )
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_auditoria_facturas_pedido
                ON auditoria_facturas (pedido_id, creado_en DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_auditoria_facturas_evento
                ON auditoria_facturas (evento_tipo, creado_en DESC)
            """)
        
        # Registrar evento
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            detalles_json = json.dumps(detalles or {})
            cur.execute("""
                INSERT INTO auditoria_facturas (pedido_id, evento_tipo, actor_username, actor_rol, detalles)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING auditoria_id, pedido_id, evento_tipo, creado_en
            """, (pedido_id, evento_tipo, actor_username, actor_rol, detalles_json))
            row = cur.fetchone() or {}
        
        conn.commit()
        return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_historial_factura(pedido_id):
    """Obtiene historial completo de auditoría de una factura.
    
    Args:
        pedido_id: ID del pedido
    
    Returns:
        List de eventos ordenados por fecha
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    auditoria_id,
                    evento_tipo,
                    actor_username,
                    actor_rol,
                    detalles,
                    creado_en
                FROM auditoria_facturas
                WHERE pedido_id = %s
                ORDER BY creado_en DESC
                LIMIT 50
            """, (pedido_id,))
            return cur.fetchall() or []
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_documentos_factura(pedido_id, pdf_ruta=None, xml_ruta=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE facturas_operativas
                SET pdf_ruta = %s,
                    xml_ruta = %s,
                    actualizado_en = NOW()
                WHERE pedido_id = %s
                RETURNING factura_op_id, pedido_id, folio_factura, estado, email_destino, pdf_ruta, xml_ruta,
                          ultimo_envio_estado, ultimo_envio_error, ultimo_envio_en, ultimo_envio_destino,
                          notas, emitida_por, emitida_en, entregada_en, actualizado_en
                """,
                (
                    (str(pdf_ruta).strip() if pdf_ruta else None),
                    (str(xml_ruta).strip() if xml_ruta else None),
                    pedido_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return row or {"error": "Factura no encontrada."}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def registrar_resultado_envio_factura(pedido_id, envio_estado, destino=None, error_detalle=None, marcar_entregada=False):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)
        envio = _normalizar_texto_busqueda(envio_estado)
        if envio not in {"pendiente", "enviado", "error"}:
            envio = "pendiente"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE facturas_operativas
                SET ultimo_envio_estado = %s,
                    ultimo_envio_error = %s,
                    ultimo_envio_destino = %s,
                    ultimo_envio_en = NOW(),
                    estado = CASE WHEN %s THEN 'entregada' ELSE estado END,
                    entregada_en = CASE WHEN %s THEN COALESCE(entregada_en, NOW()) ELSE entregada_en END,
                    actualizado_en = NOW()
                WHERE pedido_id = %s
                RETURNING factura_op_id, pedido_id, folio_factura, estado, email_destino, pdf_ruta, xml_ruta,
                          ultimo_envio_estado, ultimo_envio_error, ultimo_envio_en, ultimo_envio_destino,
                          notas, emitida_por, emitida_en, entregada_en, actualizado_en
                """,
                (
                    envio,
                    (str(error_detalle).strip() if error_detalle else None),
                    (str(destino).strip() if destino else None),
                    bool(marcar_entregada),
                    bool(marcar_entregada),
                    pedido_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return row or {"error": "Factura no encontrada."}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_panel_facturas(busqueda=None, estado=None, envio=None, limit=200):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)

        search = (busqueda or "").strip() or None
        search_pedido_id = int(search) if search and search.isdigit() else None
        estado_norm = _normalizar_texto_busqueda(estado)
        envio_norm = _normalizar_texto_busqueda(envio)
        limit_int = max(1, min(500, int(limit or 200)))

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    fo.factura_op_id,
                    fo.pedido_id,
                    fo.datos_fiscales_id,
                    fo.folio_factura,
                    fo.estado,
                    fo.email_destino,
                    fo.pdf_ruta,
                    fo.xml_ruta,
                    fo.notas,
                    fo.emitida_por,
                    fo.emitida_en,
                    fo.entregada_en,
                    fo.ultimo_envio_estado,
                    fo.ultimo_envio_error,
                    fo.ultimo_envio_en,
                    fo.ultimo_envio_destino,
                    fo.actualizado_en,
                    p.estado AS estado_pedido,
                    p.total,
                    p.metodo_pago,
                    p.creado_en,
                    c.whatsapp_id,
                    COALESCE(NULLIF(TRIM(c.nombre), ''), 'Cliente') AS cliente_nombre,
                    COALESCE(NULLIF(TRIM(c.apellidos), ''), '') AS cliente_apellidos
                FROM facturas_operativas fo
                LEFT JOIN pedidos p ON p.pedido_id = fo.pedido_id
                LEFT JOIN clientes c ON c.cliente_id = p.cliente_id
                WHERE (
                    %s IS NULL
                    OR (%s IS NOT NULL AND fo.pedido_id = %s)
                    OR (
                        %s IS NULL AND (
                            COALESCE(fo.folio_factura, '') ILIKE %s
                            OR COALESCE(c.nombre, '') ILIKE %s
                            OR COALESCE(c.apellidos, '') ILIKE %s
                            OR COALESCE(c.whatsapp_id, '') ILIKE %s
                        )
                    )
                )
                ORDER BY COALESCE(fo.actualizado_en, fo.emitida_en) DESC, fo.factura_op_id DESC
                LIMIT %s
                """,
                (
                    search,
                    search_pedido_id,
                    search_pedido_id,
                    search_pedido_id,
                    f"%{search}%" if search else None,
                    f"%{search}%" if search else None,
                    f"%{search}%" if search else None,
                    f"%{search}%" if search else None,
                    limit_int,
                ),
            )
            rows = cur.fetchall() or []

        if search_pedido_id and not any(int(row.get("pedido_id") or 0) == search_pedido_id for row in rows):
            pedido = obtener_pedido_por_id(search_pedido_id)
            if isinstance(pedido, dict) and not pedido.get("error"):
                cliente = obtener_cliente_por_id(pedido.get("cliente_id")) if pedido.get("cliente_id") else {}
                if not isinstance(cliente, dict) or cliente.get("error"):
                    cliente = {}
                fiscal_data = _obtener_datos_fiscales_por_cliente(conn, pedido.get("cliente_id")) if pedido.get("cliente_id") else None
                rows.append(
                    {
                        "factura_op_id": None,
                        "pedido_id": pedido.get("pedido_id"),
                        "datos_fiscales_id": (fiscal_data or {}).get("datos_fiscales_id") if isinstance(fiscal_data, dict) else None,
                        "folio_factura": None,
                        "estado": "pendiente_preparacion",
                        "email_destino": (fiscal_data or {}).get("email") if isinstance(fiscal_data, dict) else None,
                        "pdf_ruta": None,
                        "xml_ruta": None,
                        "notas": "Pedido localizado sin factura operativa generada. Requiere reparación desde panel.",
                        "emitida_por": None,
                        "emitida_en": None,
                        "entregada_en": None,
                        "ultimo_envio_estado": "pendiente",
                        "ultimo_envio_error": None,
                        "ultimo_envio_en": None,
                        "ultimo_envio_destino": None,
                        "actualizado_en": pedido.get("creado_en"),
                        "estado_pedido": pedido.get("estado"),
                        "total": pedido.get("total"),
                        "metodo_pago": pedido.get("metodo_pago"),
                        "creado_en": pedido.get("creado_en"),
                        "whatsapp_id": cliente.get("whatsapp_id"),
                        "cliente_nombre": cliente.get("nombre") or "Cliente",
                        "cliente_apellidos": cliente.get("apellidos") or "",
                    }
                )

        items = []
        for row in rows:
            invoice_state = _normalizar_texto_busqueda(row.get("estado")) or "emitida"
            send_state = _normalizar_texto_busqueda(row.get("ultimo_envio_estado")) or "pendiente"
            if send_state not in {"pendiente", "enviado", "error"}:
                send_state = "pendiente"

            pdf_info = _describir_documento_factura(row.get("folio_factura"), "pdf", ruta_guardada=row.get("pdf_ruta"))
            xml_info = _describir_documento_factura(row.get("folio_factura"), "xml", ruta_guardada=row.get("xml_ruta"))
            docs_ready = bool(pdf_info.get("ready") and xml_info.get("ready"))
            can_send = docs_ready and bool((row.get("whatsapp_id") or "").strip())

            view = {
                "factura_op_id": row.get("factura_op_id"),
                "pedido_id": row.get("pedido_id"),
                "folio_factura": row.get("folio_factura"),
                "estado": invoice_state,
                "estado_pedido": _normalizar_texto_busqueda(row.get("estado_pedido")) or None,
                "cliente": " ".join(part for part in [row.get("cliente_nombre"), row.get("cliente_apellidos")] if part).strip() or "Cliente",
                "whatsapp_id": row.get("whatsapp_id") or None,
                "email_destino": row.get("email_destino") or None,
                "metodo_pago": row.get("metodo_pago") or None,
                "total": round(float(row.get("total") or 0), 2),
                "emitida_por": row.get("emitida_por") or None,
                "emitida_en": row.get("emitida_en"),
                "entregada_en": row.get("entregada_en"),
                "actualizado_en": row.get("actualizado_en"),
                "ultimo_envio_estado": send_state,
                "ultimo_envio_error": row.get("ultimo_envio_error") or None,
                "ultimo_envio_en": row.get("ultimo_envio_en"),
                "ultimo_envio_destino": row.get("ultimo_envio_destino") or None,
                "notas": row.get("notas") or None,
                "documentos": {
                    "pdf": pdf_info,
                    "xml": xml_info,
                    "listos": docs_ready,
                },
                "can_send": can_send,
            }

            if estado_norm and invoice_state != estado_norm:
                continue
            if envio_norm == "por_enviar" and (send_state == "enviado" or not can_send):
                continue
            if envio_norm == "enviado" and send_state != "enviado":
                continue
            if envio_norm == "error" and send_state != "error":
                continue
            if envio_norm == "sin_documentos" and docs_ready:
                continue

            items.append(view)

        summary = {
            "total": len(items),
            "emitidas": sum(1 for item in items if item.get("estado") == "emitida"),
            "entregadas": sum(1 for item in items if item.get("estado") == "entregada"),
            "listas_para_envio": sum(1 for item in items if item.get("can_send") and item.get("ultimo_envio_estado") != "enviado"),
            "enviadas": sum(1 for item in items if item.get("ultimo_envio_estado") == "enviado"),
            "con_error": sum(1 for item in items if item.get("ultimo_envio_estado") == "error"),
            "sin_documentos": sum(1 for item in items if not item.get("documentos", {}).get("listos")),
        }
        return {"summary": summary, "rows": items}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_preview_factura(pedido_id):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    fo.factura_op_id,
                    fo.pedido_id,
                    fo.datos_fiscales_id,
                    fo.folio_factura,
                    fo.estado,
                    fo.email_destino,
                    fo.pdf_ruta,
                    fo.xml_ruta,
                    fo.notas,
                    fo.emitida_por,
                    fo.emitida_en,
                    fo.entregada_en,
                    fo.ultimo_envio_estado,
                    fo.ultimo_envio_error,
                    fo.ultimo_envio_en,
                    fo.ultimo_envio_destino,
                    fo.actualizado_en,
                    p.estado AS estado_pedido,
                    p.total,
                    p.metodo_pago,
                    p.creado_en,
                    p.cliente_id,
                    c.whatsapp_id,
                    COALESCE(NULLIF(TRIM(c.nombre), ''), 'Cliente') AS cliente_nombre,
                    COALESCE(NULLIF(TRIM(c.apellidos), ''), '') AS cliente_apellidos
                FROM facturas_operativas fo
                LEFT JOIN pedidos p ON p.pedido_id = fo.pedido_id
                LEFT JOIN clientes c ON c.cliente_id = p.cliente_id
                WHERE fo.pedido_id = %s
                LIMIT 1
                """,
                (pedido_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"error": "Factura no encontrada."}

        pdf_info = _describir_documento_factura(row.get("folio_factura"), "pdf", ruta_guardada=row.get("pdf_ruta"))
        xml_info = _describir_documento_factura(row.get("folio_factura"), "xml", ruta_guardada=row.get("xml_ruta"))

        xml_excerpt = None
        xml_path = xml_info.get("path")
        if xml_info.get("ready") and xml_path:
            try:
                xml_excerpt = Path(xml_path).read_text(encoding="utf-8", errors="ignore")[:4000]
            except Exception:
                xml_excerpt = None

        items = obtener_items_pedido(pedido_id)
        historial = obtener_historial_factura(pedido_id)

        return {
            "factura_op_id": row.get("factura_op_id"),
            "pedido_id": row.get("pedido_id"),
            "folio_factura": row.get("folio_factura"),
            "estado": _normalizar_texto_busqueda(row.get("estado")) or "emitida",
            "estado_pedido": _normalizar_texto_busqueda(row.get("estado_pedido")) or None,
            "cliente": " ".join(part for part in [row.get("cliente_nombre"), row.get("cliente_apellidos")] if part).strip() or "Cliente",
            "cliente_id": row.get("cliente_id"),
            "whatsapp_id": row.get("whatsapp_id") or None,
            "email_destino": row.get("email_destino") or None,
            "metodo_pago": row.get("metodo_pago") or None,
            "total": round(float(row.get("total") or 0), 2),
            "emitida_por": row.get("emitida_por") or None,
            "emitida_en": row.get("emitida_en"),
            "entregada_en": row.get("entregada_en"),
            "actualizado_en": row.get("actualizado_en"),
            "ultimo_envio_estado": _normalizar_texto_busqueda(row.get("ultimo_envio_estado")) or "pendiente",
            "ultimo_envio_error": row.get("ultimo_envio_error") or None,
            "ultimo_envio_en": row.get("ultimo_envio_en"),
            "ultimo_envio_destino": row.get("ultimo_envio_destino") or None,
            "notas": row.get("notas") or None,
            "documentos": {
                "pdf": pdf_info,
                "xml": dict(xml_info, preview_excerpt=xml_excerpt),
                "listos": bool(pdf_info.get("ready") and xml_info.get("ready")),
            },
            "items": items if isinstance(items, list) else [],
            "historial": historial if isinstance(historial, list) else [],
            "can_send": bool(pdf_info.get("ready") and xml_info.get("ready") and (row.get("whatsapp_id") or "").strip()),
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_pedido_por_id(pedido_id):
    """Obtiene datos completos de un pedido.
    
    Args:
        pedido_id: ID del pedido
    
    Returns:
        Dict con datos del pedido o {"error": msg}
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM pedidos
                WHERE pedido_id = %s
                LIMIT 1
            """, (pedido_id,))
            row = cur.fetchone()
            return dict(row) if row else {"error": "Pedido no encontrado"}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_cliente_por_id(cliente_id):
    """Obtiene datos de un cliente.
    
    Args:
        cliente_id: ID del cliente
    
    Returns:
        Dict con datos del cliente o {"error": msg}
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM clientes
                WHERE cliente_id = %s
                LIMIT 1
            """, (cliente_id,))
            row = cur.fetchone()
            return dict(row) if row else {"error": "Cliente no encontrado"}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_datos_fiscales_por_id(datos_fiscales_id):
    """Obtiene datos fiscales/CFDI de un cliente.
    
    Args:
        datos_fiscales_id: ID del registro de datos fiscales
    
    Returns:
        Dict con datos fiscales o {"error": msg}
    """
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_datos_fiscales(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM datos_fiscales_clientes
                WHERE datos_fiscales_id = %s
                LIMIT 1
            """, (datos_fiscales_id,))
            row = cur.fetchone()
            return dict(row) if row else {"error": "Datos fiscales no encontrados"}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_items_pedido(pedido_id):
    """Obtiene los items (productos) de un pedido.
    
    Args:
        pedido_id: ID del pedido
    
    Returns:
        List de items o {"error": msg}
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    dp.detalle_id,
                    dp.producto_id,
                    dp.cantidad,
                    dp.precio_unitario,
                    (dp.cantidad * dp.precio_unitario) AS subtotal,
                    p.nombre as producto_nombre,
                    NULL::TEXT AS descripcion
                FROM detalle_pedido dp
                LEFT JOIN productos p ON dp.producto_id = p.producto_id
                WHERE dp.pedido_id = %s
                ORDER BY dp.detalle_id ASC
            """, (pedido_id,))
            return cur.fetchall() or []
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def reparar_factura_pedido(pedido_id, actor_usuario="admin"):
    conn = None
    try:
        pedido_id_int = int(pedido_id or 0)
    except (TypeError, ValueError):
        return {"error": "Pedido invalido para reparar factura."}

    if pedido_id_int < 1:
        return {"error": "Pedido invalido para reparar factura."}

    try:
        conn = get_connection()
        _asegurar_tabla_facturas_operativas(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT pedido_id, folio_factura, estado, pdf_ruta, xml_ruta
                FROM facturas_operativas
                WHERE pedido_id = %s
                LIMIT 1
                """,
                (pedido_id_int,),
            )
            row = cur.fetchone()

        if not row:
            folio = _folio_factura_automatico(pedido_id_int)
            creado = registrar_factura_operativa(
                pedido_id=pedido_id_int,
                folio_factura=folio,
                status="emitida",
                notas="Reparacion de factura desde panel admin.",
                actor_usuario=actor_usuario,
            )
            if isinstance(creado, dict) and creado.get("error"):
                return creado
            row = creado

        folio_factura = str((row or {}).get("folio_factura") or "").strip()
        if not folio_factura:
            folio_factura = _folio_factura_automatico(pedido_id_int)
            actualizado = registrar_factura_operativa(
                pedido_id=pedido_id_int,
                folio_factura=folio_factura,
                status="emitida",
                notas="Reparacion de folio faltante.",
                actor_usuario=actor_usuario,
            )
            if isinstance(actualizado, dict) and actualizado.get("error"):
                return actualizado

        pedido = obtener_pedido_por_id(pedido_id_int)
        if not isinstance(pedido, dict) or pedido.get("error"):
            return {"error": (pedido or {}).get("error") or "Pedido no encontrado."}

        cliente = obtener_cliente_por_id(pedido.get("cliente_id")) if pedido.get("cliente_id") else {}
        if not isinstance(cliente, dict) or cliente.get("error"):
            cliente = {}

        fiscal = _obtener_datos_fiscales_por_cliente(conn, pedido.get("cliente_id")) if pedido.get("cliente_id") else None
        if not isinstance(fiscal, dict):
            fiscal = {
                "rfc": "",
                "razon_social": "",
                "regimen_fiscal": "",
                "uso_cfdi": "G01",
                "email": "",
            }

        items = obtener_items_pedido(pedido_id_int)
        if not isinstance(items, list):
            items = []

        docs_dir = _directorio_documentos_facturas()
        pdf_path = docs_dir / _nombre_archivo_factura(folio_factura, "pdf")
        xml_path = docs_dir / _nombre_archivo_factura(folio_factura, "xml")

        pdf_ok = False
        pdf_error = None
        try:
            try:
                from services.pdf_service import generar_pdf_factura
            except Exception:
                from bot_empanadas.services.pdf_service import generar_pdf_factura

            pdf_res = generar_pdf_factura(
                pedido_id=pedido_id_int,
                folio_factura=folio_factura,
                datos_cliente={
                    "nombre": cliente.get("nombre", "Cliente"),
                    "apellidos": cliente.get("apellidos", ""),
                    "whatsapp_id": cliente.get("whatsapp_id", ""),
                },
                datos_fiscales={
                    "rfc": fiscal.get("rfc", ""),
                    "razon_social": fiscal.get("razon_social", ""),
                    "regimen_fiscal": fiscal.get("regimen_fiscal", ""),
                    "uso_cfdi": fiscal.get("uso_cfdi", "G01"),
                    "email": fiscal.get("email", ""),
                },
                items_pedido=items,
                total=float(pedido.get("total") or 0),
                output_path=str(pdf_path),
            )
            if not (isinstance(pdf_res, dict) and pdf_res.get("error")) and pdf_path.exists():
                pdf_ok = True
            else:
                pdf_error = (pdf_res or {}).get("error") or "No se pudo generar PDF en reparación."
        except Exception as exc:
            pdf_error = str(exc)

        xml_ok = False
        xml_error = None
        try:
            xml_content = _construir_xml_factura_operativa(
                pedido_id=pedido_id_int,
                folio_factura=folio_factura,
                pedido=pedido,
                cliente=cliente,
                fiscal=fiscal,
                items=items,
            )
            xml_path.write_text(xml_content, encoding="utf-8")
            xml_ok = xml_path.exists()
        except Exception as exc:
            xml_error = str(exc)

        actualizar_documentos_factura(
            pedido_id=pedido_id_int,
            pdf_ruta=str(pdf_path) if pdf_ok else None,
            xml_ruta=str(xml_path) if xml_ok else None,
        )

        return {
            "prepared": bool(pdf_ok or xml_ok),
            "ready": bool(pdf_ok and xml_ok),
            "pedido_id": pedido_id_int,
            "folio_factura": folio_factura,
            "pdf_path": str(pdf_path),
            "xml_path": str(xml_path),
            "pdf_ready": pdf_ok,
            "xml_ready": xml_ok,
            "errors": [err for err in [pdf_error, xml_error] if err],
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_auditoria_financiera(fecha_base=None, limit=50):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_tablas_inventario_real(conn)
        _asegurar_tabla_compras_insumos(conn)
        _asegurar_tabla_facturas_operativas(conn)

        has_requiere_factura = _tabla_tiene_columna(conn, "pedidos", "requiere_factura")
        has_datos_fiscales_id = _tabla_tiene_columna(conn, "pedidos", "datos_fiscales_id")

        fecha_ref = str(fecha_base or "").strip() or None
        limit_int = max(1, min(300, int(limit or 50)))

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH compras_norm AS (
                    SELECT
                        c.insumo_id,
                        COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario,
                        c.creado_en
                    FROM compras_insumos c
                    WHERE c.costo_total IS NOT NULL
                      AND c.cantidad > 0
                ),
                costo_ultimo AS (
                    SELECT DISTINCT ON (cn.insumo_id)
                        cn.insumo_id,
                        cn.costo_unitario AS costo_unitario_ultimo,
                        cn.creado_en AS compra_ultima_en
                    FROM compras_norm cn
                    ORDER BY cn.insumo_id, cn.creado_en DESC
                ),
                costo_promedio AS (
                    SELECT
                        cn.insumo_id,
                        AVG(cn.costo_unitario)::NUMERIC(12,4) AS costo_unitario_promedio,
                        COUNT(*)::INT AS compras_reales
                    FROM compras_norm cn
                    WHERE cn.creado_en >= (CURRENT_DATE - INTERVAL '60 day')
                    GROUP BY cn.insumo_id
                )
                SELECT
                    p.producto_id,
                    p.nombre,
                    p.variante,
                    p.precio::NUMERIC(10,2) AS precio_venta,
                    COALESCE(p.costo_referencia, 0)::NUMERIC(10,2) AS costo_referencia,
                    GREATEST(
                        COALESCE(p.costo_referencia, 0),
                        COALESCE(SUM(r.cantidad_por_unidad * COALESCE(cu.costo_unitario_ultimo, 0)), 0)
                    )::NUMERIC(12,4) AS costo_receta_actual,
                    GREATEST(
                        COALESCE(p.costo_referencia, 0),
                        COALESCE(SUM(r.cantidad_por_unidad * COALESCE(cp.costo_unitario_promedio, cu.costo_unitario_ultimo, 0)), 0)
                    )::NUMERIC(12,4) AS costo_receta_promedio,
                    COUNT(r.insumo_id)::INT AS componentes_activos,
                    GREATEST(COUNT(r.insumo_id) - COUNT(cu.insumo_id), 0)::INT AS componentes_sin_costo,
                    COUNT(cp.insumo_id)::INT AS insumos_con_historial
                FROM productos p
                LEFT JOIN recetas_producto_insumo r
                    ON r.producto_id = p.producto_id
                   AND r.activo = TRUE
                LEFT JOIN costo_ultimo cu
                    ON cu.insumo_id = r.insumo_id
                LEFT JOIN costo_promedio cp
                    ON cp.insumo_id = r.insumo_id
                WHERE p.activo = TRUE
                GROUP BY p.producto_id, p.nombre, p.variante, p.precio, p.costo_referencia
                ORDER BY ABS(
                    COALESCE(SUM(r.cantidad_por_unidad * COALESCE(cu.costo_unitario_ultimo, 0)), 0)
                    -
                    COALESCE(SUM(r.cantidad_por_unidad * COALESCE(cp.costo_unitario_promedio, cu.costo_unitario_ultimo, 0)), 0)
                ) DESC, p.nombre, p.variante
                LIMIT %s
                """,
                (limit_int,),
            )
            costos_rows_raw = cur.fetchall() or []

            factura_sql = "COALESCE(p.requiere_factura, FALSE)" if has_requiere_factura else "FALSE"
            datos_fiscales_sql = "p.datos_fiscales_id" if has_datos_fiscales_id else "NULL"
            params = []
            if fecha_ref:
                where_fecha = "p.creado_en::date = %s::date"
                params.append(fecha_ref)
            else:
                where_fecha = "p.creado_en::date = CURRENT_DATE"

            cur.execute(
                f"""
                WITH pagos_resumen AS (
                    SELECT
                        pg.pedido_id,
                        COALESCE(SUM(CASE WHEN LOWER(COALESCE(pg.estado, '')) IN ('pagado', 'approved', 'accredited') THEN pg.monto ELSE 0 END), 0)::NUMERIC(12,2) AS monto_pagado,
                        COALESCE(SUM(pg.monto), 0)::NUMERIC(12,2) AS monto_registrado,
                        STRING_AGG(DISTINCT COALESCE(pg.estado, 'pendiente'), ', ' ORDER BY COALESCE(pg.estado, 'pendiente')) AS estados_pago,
                        STRING_AGG(DISTINCT COALESCE(pg.proveedor, '-'), ', ' ORDER BY COALESCE(pg.proveedor, '-')) AS proveedores_pago
                    FROM pagos pg
                    GROUP BY pg.pedido_id
                )
                SELECT
                    p.pedido_id,
                    p.creado_en,
                    p.estado,
                    COALESCE(p.total, 0)::NUMERIC(12,2) AS total,
                    COALESCE(p.metodo_pago, '') AS metodo_pago,
                    {factura_sql} AS requiere_factura,
                    {datos_fiscales_sql} AS datos_fiscales_id,
                    COALESCE(pr.monto_pagado, 0)::NUMERIC(12,2) AS monto_pagado,
                    COALESCE(pr.monto_registrado, 0)::NUMERIC(12,2) AS monto_registrado,
                    COALESCE(pr.estados_pago, '') AS estados_pago,
                    COALESCE(pr.proveedores_pago, '') AS proveedores_pago,
                    COALESCE(fo.estado, '') AS factura_operativa_status,
                    COALESCE(fo.folio_factura, '') AS folio_factura,
                    COALESCE(fo.email_destino, '') AS factura_email
                FROM pedidos p
                LEFT JOIN pagos_resumen pr ON pr.pedido_id = p.pedido_id
                LEFT JOIN facturas_operativas fo ON fo.pedido_id = p.pedido_id
                WHERE p.estado <> 'cancelado'
                  AND {where_fecha}
                ORDER BY p.creado_en DESC
                LIMIT %s
                """,
                tuple(params + [max(limit_int * 10, 200)]),
            )
            pedidos_rows = cur.fetchall() or []

        costos_rows = []
        costos_alerta = 0
        desviaciones = []
        for row in costos_rows_raw:
            precio = round(float(row.get("precio_venta") or 0), 2)
            actual = round(float(row.get("costo_receta_actual") or 0), 4)
            promedio = round(float(row.get("costo_receta_promedio") or 0), 4)
            componentes = int(row.get("componentes_activos") or 0)
            sin_costo = int(row.get("componentes_sin_costo") or 0)
            desviacion_mxn = round(actual - promedio, 4)
            desviacion_pct = round(((desviacion_mxn / promedio) * 100), 2) if promedio > 0 else 0.0
            margen_pct = round(((precio - actual) / precio) * 100, 2) if precio > 0 else 0.0
            utilidad_unitaria = round(precio - actual, 2)

            calidad_costo = "completo"
            if componentes <= 0:
                calidad_costo = "sin_receta"
            elif sin_costo > 0:
                calidad_costo = "sin_costos"

            salud = _clasificar_salud_producto_rentabilidad(precio, actual, calidad_costo)

            alerta = "ok"
            if salud == "sin_receta":
                alerta = "sin_receta"
            elif salud == "sin_costos":
                alerta = "faltan_costos"
            elif salud == "sin_utilidad":
                alerta = "sin_utilidad"
            elif salud == "margen_bajo":
                alerta = "margen_riesgo"
            elif abs(desviacion_pct) >= 20:
                alerta = "desviacion_alta"

            if alerta != "ok":
                costos_alerta += 1
            desviaciones.append(abs(desviacion_pct))

            costos_rows.append({
                "producto_id": row.get("producto_id"),
                "nombre": row.get("nombre"),
                "variante": row.get("variante"),
                "precio_venta": precio,
                "costo_receta_actual": actual,
                "costo_receta_promedio": promedio,
                "utilidad_unitaria": utilidad_unitaria,
                "desviacion_mxn": round(desviacion_mxn, 2),
                "desviacion_pct": desviacion_pct,
                "margen_pct": margen_pct,
                "componentes_activos": componentes,
                "componentes_sin_costo": sin_costo,
                "salud_rentabilidad": salud,
                "calidad_costo": calidad_costo,
                "alerta": alerta,
            })

        pagos_rows = []
        corte_map = {
            "manana": {"turno": "manana", "label": "Mañana", "pedidos": 0, "ventas": 0.0, "efectivo": 0.0, "digital": 0.0, "contra_entrega": 0.0, "facturas": 0, "cobranzas_validadas": 0.0, "por_validar": 0.0},
            "tarde": {"turno": "tarde", "label": "Tarde", "pedidos": 0, "ventas": 0.0, "efectivo": 0.0, "digital": 0.0, "contra_entrega": 0.0, "facturas": 0, "cobranzas_validadas": 0.0, "por_validar": 0.0},
            "noche": {"turno": "noche", "label": "Noche", "pedidos": 0, "ventas": 0.0, "efectivo": 0.0, "digital": 0.0, "contra_entrega": 0.0, "facturas": 0, "cobranzas_validadas": 0.0, "por_validar": 0.0},
        }
        pagos_map = {}

        total_ventas = 0.0
        total_validado = 0.0
        total_pendiente = 0.0
        pagos_conciliados = 0
        pagos_inconsistentes = 0
        facturas_solicitadas = 0
        facturas_listas = 0
        facturas_pendientes = 0
        facturas_emitidas = 0
        facturas_entregadas = 0
        metodos_invalidos = 0

        for row in pedidos_rows:
            total = round(float(row.get("total") or 0), 2)
            monto_pagado = round(float(row.get("monto_pagado") or 0), 2)
            metodo = _normalizar_metodo_pago_finanzas(row.get("metodo_pago"))
            estado = str(row.get("estado") or "").strip().lower()
            requiere_factura = bool(row.get("requiere_factura"))
            turno = _clasificar_turno_operativo(row.get("creado_en"))
            if turno not in corte_map:
                turno = "noche"

            factura_status = _clasificar_estado_factura_finanzas(
                requiere_factura=requiere_factura,
                datos_fiscales_id=row.get("datos_fiscales_id"),
                estado_pedido=estado,
                factura_operativa_status=row.get("factura_operativa_status"),
            )
            factura_en_flujo = requiere_factura or factura_status in {"emitida", "entregada", "lista_para_emision", "lista_para_entrega", "pendiente_datos"}
            if factura_en_flujo:
                facturas_solicitadas += 1
                if factura_status in {"lista_para_emision", "lista_para_entrega", "emitida", "entregada"}:
                    facturas_listas += 1
                else:
                    facturas_pendientes += 1
                if factura_status == "emitida":
                    facturas_emitidas += 1
                if factura_status == "entregada":
                    facturas_entregadas += 1

            cobranza = _evaluar_cobranza_pedido_finanzas(
                metodo_pago=metodo,
                estado_pedido=estado,
                total=total,
                monto_pagado=monto_pagado,
                estados_pago=row.get("estados_pago") or "",
            )
            valido = bool(cobranza.get("metodo_valido"))
            if not valido:
                metodos_invalidos += 1

            monto_validado = round(float(cobranza.get("monto_validado") or 0), 2)
            pendiente = round(float(cobranza.get("pendiente") or 0), 2)
            status_cobranza = str(cobranza.get("status") or "pendiente")
            criterio_cobranza = str(cobranza.get("criterio") or "sin_validacion")

            if status_cobranza == "validado":
                pagos_conciliados += 1
            else:
                pagos_inconsistentes += 1

            total_ventas += total
            total_validado += monto_validado
            total_pendiente += pendiente

            by_method = pagos_map.setdefault(metodo, {
                "metodo_pago": metodo,
                "pedidos": 0,
                "ventas": 0.0,
                "monto_validado": 0.0,
                "por_validar": 0.0,
                "facturas_solicitadas": 0,
                "metodos_invalidos": 0,
                "cobranzas_conciliadas": 0,
                "cobranzas_parciales": 0,
                "cobranzas_pendientes": 0,
            })
            by_method["pedidos"] += 1
            by_method["ventas"] = round(by_method["ventas"] + total, 2)
            by_method["monto_validado"] = round(by_method["monto_validado"] + monto_validado, 2)
            by_method["por_validar"] = round(by_method["por_validar"] + pendiente, 2)
            by_method["facturas_solicitadas"] += 1 if factura_en_flujo else 0
            by_method["metodos_invalidos"] += 0 if valido else 1
            if status_cobranza == "validado":
                by_method["cobranzas_conciliadas"] += 1
            elif status_cobranza == "parcial":
                by_method["cobranzas_parciales"] += 1
            else:
                by_method["cobranzas_pendientes"] += 1

            corte = corte_map[turno]
            corte["pedidos"] += 1
            corte["ventas"] = round(corte["ventas"] + total, 2)
            corte["cobranzas_validadas"] = round(corte["cobranzas_validadas"] + monto_validado, 2)
            corte["por_validar"] = round(corte["por_validar"] + pendiente, 2)
            corte["facturas"] += 1 if factura_en_flujo else 0

            if metodo == "efectivo":
                corte["efectivo"] = round(corte["efectivo"] + (total if estado == "entregado" else 0), 2)
            elif metodo == "contra_entrega":
                corte["contra_entrega"] = round(corte["contra_entrega"] + (total if estado == "entregado" else 0), 2)
            else:
                corte["digital"] = round(corte["digital"] + monto_validado, 2)

            pagos_rows.append({
                "pedido_id": row.get("pedido_id"),
                "metodo_pago": metodo,
                "estado": estado,
                "total": total,
                "monto_pagado": monto_pagado,
                "monto_validado": monto_validado,
                "pendiente": pendiente,
                "factura_status": factura_status,
                "folio_factura": row.get("folio_factura") or None,
                "factura_email": row.get("factura_email") or None,
                "status_cobranza": status_cobranza,
                "criterio_cobranza": criterio_cobranza,
                "metodo_valido": valido,
                "proveedores_pago": row.get("proveedores_pago") or "-",
                "estados_pago": row.get("estados_pago") or "-",
            })

        pagos_by_method_rows = []
        for key in ("efectivo", "mercadopago", "transferencia", "digital", "contra_entrega", "sin_definir"):
            if key in pagos_map:
                pagos_by_method_rows.append(pagos_map[key])
        for key, value in pagos_map.items():
            if key not in {"efectivo", "mercadopago", "transferencia", "digital", "contra_entrega", "sin_definir"}:
                pagos_by_method_rows.append(value)

        corte_rows = []
        for key in ("manana", "tarde", "noche"):
            row = corte_map[key]
            pedidos = int(row.get("pedidos") or 0)
            row["ticket_promedio"] = round((float(row.get("ventas") or 0) / pedidos), 2) if pedidos > 0 else 0.0
            row["efectivo_sistema"] = round(float(row.get("efectivo") or 0) + float(row.get("contra_entrega") or 0), 2)
            row["digital_sistema"] = round(float(row.get("digital") or 0), 2)
            corte_rows.append(row)

        coherencia_productos = _resumir_coherencia_productos(costos_rows)

        return {
            "fecha_base": fecha_ref or datetime.now().strftime("%Y-%m-%d"),
            "costos": {
                "resumen": {
                    "productos_auditados": len(costos_rows),
                    "productos_con_alerta": costos_alerta,
                    "desviacion_promedio_pct": round(sum(desviaciones) / len(desviaciones), 2) if desviaciones else 0.0,
                    "productos_rentables": coherencia_productos.get("productos_rentables", 0),
                    "productos_sin_receta": coherencia_productos.get("productos_sin_receta", 0),
                    "productos_sin_costos": coherencia_productos.get("productos_sin_costos", 0),
                    "productos_sin_utilidad": coherencia_productos.get("productos_sin_utilidad", 0),
                    "productos_margen_bajo": coherencia_productos.get("productos_margen_bajo", 0),
                },
                "rows": costos_rows,
            },
            "facturacion_pagos": {
                "resumen": {
                    "pedidos": len(pedidos_rows),
                    "ventas": round(total_ventas, 2),
                    "monto_validado": round(total_validado, 2),
                    "monto_pendiente": round(total_pendiente, 2),
                    "pagos_conciliados": pagos_conciliados,
                    "pagos_inconsistentes": pagos_inconsistentes,
                    "facturas_solicitadas": facturas_solicitadas,
                    "facturas_listas": facturas_listas,
                    "facturas_pendientes": facturas_pendientes,
                    "facturas_emitidas": facturas_emitidas,
                    "facturas_entregadas": facturas_entregadas,
                    "metodos_invalidos": metodos_invalidos,
                    "efectivo_conciliado": round(float((pagos_map.get("efectivo") or {}).get("monto_validado") or 0), 2),
                    "tarjeta_digital_conciliado": round(sum(float((pagos_map.get(k) or {}).get("monto_validado") or 0) for k in ("mercadopago", "digital", "transferencia")), 2),
                },
                "rows": pagos_by_method_rows,
                "detalle": pagos_rows,
            },
            "corte_caja": {
                "resumen": {
                    "turnos": len(corte_rows),
                    "ventas": round(total_ventas, 2),
                    "cobranzas_validadas": round(total_validado, 2),
                    "por_validar": round(total_pendiente, 2),
                    "efectivo_estimado": round(sum(float(r.get("efectivo") or 0) for r in corte_rows), 2),
                    "digital_estimado": round(sum(float(r.get("digital") or 0) for r in corte_rows), 2),
                },
                "rows": corte_rows,
            },
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_top_clientes(limit=20):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.cliente_id,
                    c.whatsapp_id,
                    c.nombre,
                    c.apellidos,
                    COUNT(p.pedido_id)::INT AS total_pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS monto_total_comprado,
                    MAX(p.creado_en) AS ultima_compra
                FROM clientes c
                JOIN pedidos p ON p.cliente_id = c.cliente_id
                WHERE p.estado <> 'cancelado'
                GROUP BY c.cliente_id, c.whatsapp_id, c.nombre, c.apellidos
                ORDER BY monto_total_comprado DESC, total_pedidos DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_contexto_cliente(cliente_id):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            has_metodo_entrega = _tabla_tiene_columna(conn, "pedidos", "metodo_entrega")

            cur.execute(
                """
                SELECT cliente_id, whatsapp_id, nombre, apellidos
                FROM clientes
                WHERE cliente_id = %s
                LIMIT 1
                """,
                (int(cliente_id),),
            )
            cliente = cur.fetchone()
            if not cliente:
                return {"error": "Cliente no encontrado"}

            if has_metodo_entrega:
                cur.execute(
                    """
                    SELECT p.pedido_id, p.total, p.metodo_entrega, p.creado_en
                    FROM pedidos p
                    WHERE p.cliente_id = %s
                      AND p.estado <> 'cancelado'
                    ORDER BY p.creado_en DESC, p.pedido_id DESC
                    LIMIT 1
                    """,
                    (int(cliente_id),),
                )
            else:
                cur.execute(
                    """
                    SELECT p.pedido_id, p.total, NULL::TEXT AS metodo_entrega, p.creado_en
                    FROM pedidos p
                    WHERE p.cliente_id = %s
                      AND p.estado <> 'cancelado'
                    ORDER BY p.creado_en DESC, p.pedido_id DESC
                    LIMIT 1
                    """,
                    (int(cliente_id),),
                )
            ultimo_pedido = cur.fetchone()

            ultimo_items = []
            if ultimo_pedido:
                cur.execute(
                    """
                    SELECT
                        d.producto_id,
                        d.cantidad,
                        d.precio_unitario,
                        p.nombre,
                        p.variante
                    FROM detalle_pedido d
                    LEFT JOIN productos p ON p.producto_id = d.producto_id
                    WHERE d.pedido_id = %s
                    ORDER BY d.detalle_id ASC
                    """,
                    (int(ultimo_pedido["pedido_id"]),),
                )
                for row in cur.fetchall() or []:
                    ultimo_items.append(
                        {
                            "producto_id": int(row.get("producto_id") or 0),
                            "cantidad": int(row.get("cantidad") or 0),
                            "precio_unit": float(row.get("precio_unitario") or 0),
                            "nombre": row.get("nombre"),
                            "variante": row.get("variante"),
                        }
                    )

            direccion_expr = _direccion_text_expr("dc")

            if has_metodo_entrega:
                cur.execute(
                    f"""
                    SELECT dc.direccion_id, {direccion_expr} AS direccion_texto, dc.codigo_postal
                    FROM pedidos p
                    JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
                    WHERE p.cliente_id = %s
                      AND p.estado <> 'cancelado'
                      AND p.direccion_id IS NOT NULL
                      AND p.metodo_entrega = 'domicilio'
                    ORDER BY p.creado_en DESC, p.pedido_id DESC
                    LIMIT 1
                    """,
                    (int(cliente_id),),
                )
            else:
                cur.execute(
                    f"""
                    SELECT dc.direccion_id, {direccion_expr} AS direccion_texto, dc.codigo_postal
                    FROM pedidos p
                    JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
                    WHERE p.cliente_id = %s
                      AND p.estado <> 'cancelado'
                      AND p.direccion_id IS NOT NULL
                    ORDER BY p.creado_en DESC, p.pedido_id DESC
                    LIMIT 1
                    """,
                    (int(cliente_id),),
                )
            ultima_direccion = cur.fetchone()

            return {
                "cliente_id": int(cliente.get("cliente_id") or 0),
                "whatsapp_id": cliente.get("whatsapp_id"),
                "nombre": cliente.get("nombre"),
                "apellidos": cliente.get("apellidos"),
                "ultimo_pedido_id": int(ultimo_pedido.get("pedido_id") or 0) if ultimo_pedido else None,
                "ultimo_total": float(ultimo_pedido.get("total") or 0) if ultimo_pedido else 0,
                "ultimo_metodo_entrega": (ultimo_pedido.get("metodo_entrega") if ultimo_pedido else None),
                "ultimo_items": [i for i in ultimo_items if int(i.get("cantidad") or 0) > 0],
                "ultima_direccion": {
                    "direccion_id": int(ultima_direccion.get("direccion_id") or 0),
                    "direccion_texto": (ultima_direccion.get("direccion_texto") or "").strip(),
                    "codigo_postal": (ultima_direccion.get("codigo_postal") or "").strip(),
                }
                if ultima_direccion
                else None,
            }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_alertas_inventario():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    i.insumo_id,
                    i.nombre,
                    i.unidad_medida,
                    i.stock_actual,
                    i.stock_minimo,
                    (i.stock_minimo - i.stock_actual)::NUMERIC(10,3) AS faltante,
                    pv.nombre AS proveedor,
                    pv.email AS proveedor_email
                FROM insumos i
                LEFT JOIN proveedores pv ON pv.proveedor_id = i.proveedor_id
                WHERE i.stock_actual < i.stock_minimo
                ORDER BY faltante DESC, i.nombre
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_inventario(texto=None, estado_stock=None, proveedor=None, limit=None, offset=0):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []

            search = str(texto or "").strip()
            if search:
                pattern = f"%{search}%"
                filtros.append(
                    """
                    (
                        COALESCE(i.nombre, '') ILIKE %s
                        OR COALESCE(i.unidad_medida, '') ILIKE %s
                        OR COALESCE(pv.nombre, '') ILIKE %s
                        OR COALESCE(pv.email, '') ILIKE %s
                    )
                    """
                )
                params.extend([pattern, pattern, pattern, pattern])

            prov = str(proveedor or "").strip()
            if prov:
                filtros.append("(COALESCE(pv.nombre, '') ILIKE %s OR COALESCE(pv.email, '') ILIKE %s)")
                params.extend([f"%{prov}%", f"%{prov}%"])

            estado = str(estado_stock or "").strip().lower()
            if estado == "bajo":
                filtros.append("i.stock_actual < i.stock_minimo")
            elif estado == "normal":
                filtros.append("i.stock_actual >= i.stock_minimo")
            elif estado == "sobre":
                filtros.append("i.stock_actual >= (i.stock_minimo * 1.5)")

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            limit_sql = ""
            if limit is not None:
                lim = max(1, min(500, int(limit)))
                off = max(0, int(offset or 0))
                limit_sql = " LIMIT %s OFFSET %s"
                params.extend([lim, off])

            cur.execute(
                f"""
                SELECT
                    i.insumo_id,
                    i.nombre,
                    i.unidad_medida,
                    i.stock_actual,
                    i.stock_minimo,
                    (i.stock_actual - i.stock_minimo)::NUMERIC(12,3) AS margen_stock,
                    pv.nombre AS proveedor,
                    pv.email AS proveedor_email
                FROM insumos i
                LEFT JOIN proveedores pv ON pv.proveedor_id = i.proveedor_id
                {where_sql}
                ORDER BY i.nombre
                {limit_sql}
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tabla_compras_insumos(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS compras_insumos (
                compra_id BIGSERIAL PRIMARY KEY,
                insumo_id BIGINT NOT NULL REFERENCES insumos(insumo_id),
                cantidad NUMERIC(12,3) NOT NULL,
                costo_total NUMERIC(10,2),
                proveedor VARCHAR(120),
                creado_por VARCHAR(80),
                creado_en TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_compras_insumos_insumo_id
                ON compras_insumos (insumo_id)
            """
        )


def _obtener_o_crear_proveedor(cur, nombre_proveedor):
    if not nombre_proveedor:
        return None

    cur.execute(
        """
        SELECT proveedor_id
        FROM proveedores
        WHERE LOWER(nombre) = LOWER(%s)
        LIMIT 1
        """,
        (nombre_proveedor,),
    )
    row = cur.fetchone()
    if row:
        return row["proveedor_id"] if isinstance(row, dict) else row[0]

    cur.execute(
        """
        INSERT INTO proveedores (nombre)
        VALUES (%s)
        RETURNING proveedor_id
        """,
        (nombre_proveedor,),
    )
    created = cur.fetchone()
    return created["proveedor_id"] if isinstance(created, dict) else created[0]


def _asegurar_tablas_inventario_real(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS costo_referencia NUMERIC(10,2) NOT NULL DEFAULT 0
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS recetas_producto_insumo (
                receta_id BIGSERIAL PRIMARY KEY,
                producto_id BIGINT NOT NULL REFERENCES productos(producto_id),
                insumo_id BIGINT NOT NULL REFERENCES insumos(insumo_id),
                cantidad_por_unidad NUMERIC(12,3) NOT NULL,
                activo BOOLEAN NOT NULL DEFAULT TRUE,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                actualizado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_recetas_cantidad_pos CHECK (cantidad_por_unidad > 0)
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_recetas_producto_insumo_activo
                ON recetas_producto_insumo (producto_id, insumo_id)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS movimientos_inventario (
                movimiento_id BIGSERIAL PRIMARY KEY,
                insumo_id BIGINT NOT NULL REFERENCES insumos(insumo_id),
                tipo VARCHAR(30) NOT NULL,
                cantidad_movimiento NUMERIC(12,3) NOT NULL,
                stock_antes NUMERIC(12,3) NOT NULL,
                stock_despues NUMERIC(12,3) NOT NULL,
                referencia_tipo VARCHAR(30),
                referencia_id BIGINT,
                detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
                actor_username VARCHAR(80),
                actor_rol VARCHAR(30),
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_movimientos_tipo CHECK (tipo IN ('compra', 'consumo_pedido', 'ajuste_entrada', 'ajuste_salida'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_movimientos_inventario_insumo
                ON movimientos_inventario (insumo_id, creado_en DESC)
            """
        )


def _registrar_movimiento_inventario_cur(
    cur,
    insumo_id,
    tipo,
    cantidad_movimiento,
    stock_antes,
    stock_despues,
    referencia_tipo=None,
    referencia_id=None,
    detalle=None,
    actor_username=None,
    actor_rol=None,
):
    cur.execute(
        """
        INSERT INTO movimientos_inventario (
            insumo_id,
            tipo,
            cantidad_movimiento,
            stock_antes,
            stock_despues,
            referencia_tipo,
            referencia_id,
            detalle,
            actor_username,
            actor_rol
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        """,
        (
            insumo_id,
            tipo,
            cantidad_movimiento,
            stock_antes,
            stock_despues,
            referencia_tipo,
            referencia_id,
            _to_json_text(detalle),
            actor_username,
            actor_rol,
        ),
    )


def _detalle_pedido_tiene_trigger_descuento(cur):
    cur.execute(
        """
        SELECT 1
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        WHERE c.relname = 'detalle_pedido'
          AND NOT t.tgisinternal
          AND (
                t.tgname = 'trg_descontar_insumos_detalle_pedido'
                OR t.tgname ILIKE '%descontar%insumo%'
                OR t.tgname ILIKE '%consumo%inventario%'
          )
        LIMIT 1
        """
    )
    return cur.fetchone() is not None


def _descontar_inventario_por_pedido(cur, pedido_id, items, actor_usuario=None, actor_rol=None, actualizar_stock=True):
    requeridos = {}
    faltan_recetas = []

    for item in items:
        producto_id = int(item["producto_id"])
        cantidad_pedido = float(item["cantidad"])
        cur.execute(
            """
            SELECT
                r.insumo_id,
                r.cantidad_por_unidad,
                i.nombre AS insumo_nombre,
                i.unidad_medida
            FROM recetas_producto_insumo r
            JOIN insumos i ON i.insumo_id = r.insumo_id
            WHERE r.producto_id = %s AND r.activo = TRUE
            """,
            (producto_id,),
        )
        componentes = cur.fetchall() or []
        if not componentes:
            faltan_recetas.append(str(producto_id))
            continue

        for comp in componentes:
            insumo_id = int(comp["insumo_id"])
            qty = float(comp["cantidad_por_unidad"]) * cantidad_pedido
            if insumo_id not in requeridos:
                requeridos[insumo_id] = {
                    "cantidad": 0.0,
                    "insumo_nombre": comp["insumo_nombre"],
                    "unidad_medida": comp["unidad_medida"],
                }
            requeridos[insumo_id]["cantidad"] += qty

    if faltan_recetas:
        return {"error": f"No hay receta configurada para producto_id: {', '.join(faltan_recetas)}"}

    if not requeridos:
        return {"ok": True, "movimientos": []}

    ids = list(requeridos.keys())
    placeholders = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"""
        SELECT insumo_id, nombre, unidad_medida, stock_actual
        FROM insumos
        WHERE insumo_id IN ({placeholders})
        FOR UPDATE
        """,
        tuple(ids),
    )
    stocks = {int(row["insumo_id"]): row for row in (cur.fetchall() or [])}

    faltantes = []
    for insumo_id, req in requeridos.items():
        row = stocks.get(insumo_id)
        if not row:
            faltantes.append(f"insumo_id={insumo_id} no existe")
            continue
        disponible = float(row["stock_actual"])
        requerido = float(req["cantidad"])
        if actualizar_stock and disponible < requerido:
            faltantes.append(
                f"{row['nombre']}: disponible={disponible:.3f} {row['unidad_medida']} / requerido={requerido:.3f} {row['unidad_medida']}"
            )

    if faltantes:
        return {"error": "Stock insuficiente para surtir pedido. " + " | ".join(faltantes)}

    movimientos = []
    for insumo_id, req in requeridos.items():
        row = stocks[insumo_id]
        qty = float(req["cantidad"])
        stock_actual = float(row["stock_actual"])

        if actualizar_stock:
            stock_antes = stock_actual
            stock_despues = stock_antes - qty

            cur.execute(
                """
                UPDATE insumos
                SET stock_actual = %s
                WHERE insumo_id = %s
                """,
                (stock_despues, insumo_id),
            )
        else:
            # Modo bitacora: el trigger SQL ya desconto existencias.
            stock_despues = stock_actual
            stock_antes = stock_despues + qty

        _registrar_movimiento_inventario_cur(
            cur,
            insumo_id=insumo_id,
            tipo="consumo_pedido",
            cantidad_movimiento=-qty,
            stock_antes=stock_antes,
            stock_despues=stock_despues,
            referencia_tipo="pedido",
            referencia_id=pedido_id,
            detalle={"pedido_id": pedido_id},
            actor_username=actor_usuario,
            actor_rol=actor_rol,
        )
        movimientos.append(
            {
                "insumo_id": insumo_id,
                "insumo": row["nombre"],
                "consumo": qty,
                "stock_despues": stock_despues,
                "unidad_medida": row["unidad_medida"],
            }
        )

    return {"ok": True, "movimientos": movimientos}


def registrar_compra_insumo(
    insumo,
    cantidad,
    proveedor=None,
    costo_total=None,
    creado_por=None,
    actor_rol="admin",
    confirmar_unidad_base=False,
):
    conn = None
    try:
        nombre_insumo = (insumo or "").strip()
        if not nombre_insumo:
            return {"error": "El nombre del insumo es obligatorio."}

        qty = float(cantidad or 0)
        if qty <= 0:
            return {"error": "La cantidad debe ser mayor a 0."}

        proveedor_nombre = (proveedor or "").strip() or None

        conn = get_connection()
        _asegurar_tabla_compras_insumos(conn)
        _asegurar_tablas_inventario_real(conn)
        _asegurar_auditoria_negocio(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _set_audit_actor(cur, actor_username=creado_por, actor_rol=actor_rol)
            proveedor_id = _obtener_o_crear_proveedor(cur, proveedor_nombre)

            cur.execute(
                """
                SELECT insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                FROM insumos
                WHERE LOWER(nombre) = LOWER(%s)
                LIMIT 1
                """,
                (nombre_insumo,),
            )
            insumo_row = cur.fetchone()
            insumo_existente = bool(insumo_row)

            if not insumo_row:
                stock_antes = 0.0
                cur.execute(
                    """
                    INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (nombre_insumo, "pieza", qty, 10, proveedor_id),
                )
                insumo_row = cur.fetchone()
            else:
                stock_antes = float(insumo_row["stock_actual"])

            unidad_medida = str(insumo_row.get("unidad_medida") or "").strip().lower()
            if unidad_medida in {"g", "ml"} and abs(qty - 1.0) < 1e-9 and not bool(confirmar_unidad_base):
                return {
                    "error": (
                        "Cantidad 1 detectada para un insumo en g/ml. "
                        "Si compraste 1 kg o 1 L, captura 1000 en cantidad. "
                        "Si realmente es 1 g/ml, confirma el registro con confirmar_unidad_base=true."
                    )
                }

            if insumo_existente:
                cur.execute(
                    """
                    UPDATE insumos
                    SET
                        stock_actual = stock_actual + %s,
                        proveedor_id = COALESCE(%s, proveedor_id)
                    WHERE insumo_id = %s
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (qty, proveedor_id, insumo_row["insumo_id"]),
                )
                insumo_row = cur.fetchone()

            cur.execute(
                """
                INSERT INTO compras_insumos (insumo_id, cantidad, costo_total, proveedor, creado_por)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING compra_id, insumo_id, cantidad, costo_total, proveedor, creado_por, creado_en
                """,
                (
                    insumo_row["insumo_id"],
                    qty,
                    costo_total,
                    proveedor_nombre,
                    creado_por,
                ),
            )
            compra = cur.fetchone()

            _registrar_movimiento_inventario_cur(
                cur,
                insumo_id=insumo_row["insumo_id"],
                tipo="compra",
                cantidad_movimiento=qty,
                stock_antes=stock_antes,
                stock_despues=float(insumo_row["stock_actual"]),
                referencia_tipo="compra_insumo",
                referencia_id=compra["compra_id"],
                detalle={
                    "proveedor": proveedor_nombre,
                    "costo_total": costo_total,
                },
                actor_username=creado_por,
                actor_rol=actor_rol,
            )

            conn.commit()
            return {
                "compra": compra,
                "insumo": insumo_row,
            }
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_compras_insumos(limit=30):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_compras_insumos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.compra_id,
                    c.insumo_id,
                    i.nombre AS insumo,
                    c.cantidad,
                    c.costo_total,
                    c.proveedor,
                    c.creado_por,
                    c.creado_en
                FROM compras_insumos c
                JOIN insumos i ON i.insumo_id = c.insumo_id
                ORDER BY c.creado_en DESC
                LIMIT %s
                """,
                (int(limit),),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_producto_manual(nombre, variante, precio, costo_referencia=None, activo=True):
    conn = None
    try:
        nom = (nombre or "").strip()
        var = (variante or "").strip()
        pre = float(precio or 0)
        costo_ref = float(costo_referencia or 0)
        if not nom:
            return {"error": "nombre es obligatorio"}
        if pre <= 0:
            return {"error": "precio debe ser mayor a 0"}
        if costo_ref < 0:
            return {"error": "costo_referencia no puede ser negativo"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT producto_id
                FROM productos
                WHERE LOWER(nombre) = LOWER(%s)
                  AND LOWER(COALESCE(variante, '')) = LOWER(%s)
                LIMIT 1
                """,
                (nom, var),
            )
            existe = cur.fetchone()

            if existe:
                cur.execute(
                    """
                    UPDATE productos
                    SET precio = %s, costo_referencia = %s, activo = %s
                    WHERE producto_id = %s
                    RETURNING producto_id, nombre, variante, precio, costo_referencia, activo
                    """,
                    (pre, costo_ref, bool(activo), existe["producto_id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO productos (nombre, variante, precio, costo_referencia, activo)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING producto_id, nombre, variante, precio, costo_referencia, activo
                    """,
                    (nom, var, pre, costo_ref, bool(activo)),
                )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_productos_admin(limit=200):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    p.producto_id,
                    p.nombre,
                    p.variante,
                    p.precio,
                    COALESCE(p.costo_referencia, 0)::NUMERIC(10,2) AS costo_referencia,
                    p.activo,
                    COUNT(r.receta_id) FILTER (WHERE r.activo = TRUE)::INT AS componentes_activos,
                    CASE WHEN COUNT(r.receta_id) FILTER (WHERE r.activo = TRUE) > 0 THEN TRUE ELSE FALSE END AS tiene_receta_activa
                FROM productos p
                LEFT JOIN recetas_producto_insumo r ON r.producto_id = p.producto_id
                GROUP BY p.producto_id, p.nombre, p.variante, p.precio, p.costo_referencia, p.activo
                ORDER BY p.activo DESC, p.nombre, p.variante
                LIMIT %s
                """,
                (int(limit),),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_producto_admin(producto_id, nombre=None, variante=None, precio=None, costo_referencia=None, activo=None):
    conn = None
    try:
        pid = int(producto_id)
        updates = []
        params = []

        if nombre is not None:
            nom = str(nombre).strip()
            if not nom:
                return {"error": "nombre es obligatorio"}
            updates.append("nombre = %s")
            params.append(nom)

        if variante is not None:
            updates.append("variante = %s")
            params.append(str(variante).strip())

        if precio is not None:
            pre = float(precio)
            if pre <= 0:
                return {"error": "precio debe ser mayor a 0"}
            updates.append("precio = %s")
            params.append(pre)

        if costo_referencia is not None:
            costo_ref = float(costo_referencia or 0)
            if costo_ref < 0:
                return {"error": "costo_referencia no puede ser negativo"}
            updates.append("costo_referencia = %s")
            params.append(costo_ref)

        if activo is not None:
            updates.append("activo = %s")
            params.append(bool(activo))

        if not updates:
            return {"error": "No hay campos para actualizar"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params.append(pid)
            cur.execute(
                f"""
                UPDATE productos
                SET {', '.join(updates)}
                WHERE producto_id = %s
                RETURNING producto_id, nombre, variante, precio, costo_referencia, activo
                """,
                tuple(params),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Producto no encontrado"}
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_insumo_manual(nombre, unidad_medida, stock_minimo=0, stock_inicial=0, proveedor=None, actor_username=None, actor_rol="admin"):
    conn = None
    try:
        nom = (nombre or "").strip()
        unidad = (unidad_medida or "").strip()
        minimo = float(stock_minimo or 0)
        inicial = float(stock_inicial or 0)
        proveedor_nombre = (proveedor or "").strip() or None

        if not nom:
            return {"error": "nombre es obligatorio"}
        if not unidad:
            return {"error": "unidad_medida es obligatoria"}
        if minimo < 0 or inicial < 0:
            return {"error": "stock_minimo y stock_inicial no pueden ser negativos"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            proveedor_id = _obtener_o_crear_proveedor(cur, proveedor_nombre)

            cur.execute(
                """
                SELECT insumo_id, stock_actual
                FROM insumos
                WHERE LOWER(nombre) = LOWER(%s)
                LIMIT 1
                """,
                (nom,),
            )
            existe = cur.fetchone()

            if existe:
                cur.execute(
                    """
                    UPDATE insumos
                    SET unidad_medida = %s,
                        stock_minimo = %s,
                        proveedor_id = COALESCE(%s, proveedor_id)
                    WHERE insumo_id = %s
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (unidad, minimo, proveedor_id, existe["insumo_id"]),
                )
                row = cur.fetchone()
            else:
                cur.execute(
                    """
                    INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (nom, unidad, inicial, minimo, proveedor_id),
                )
                row = cur.fetchone()
                if inicial > 0:
                    _registrar_movimiento_inventario_cur(
                        cur,
                        insumo_id=row["insumo_id"],
                        tipo="ajuste_entrada",
                        cantidad_movimiento=inicial,
                        stock_antes=0,
                        stock_despues=float(row["stock_actual"]),
                        referencia_tipo="alta_insumo",
                        referencia_id=row["insumo_id"],
                        detalle={"motivo": "stock inicial"},
                        actor_username=actor_username,
                        actor_rol=actor_rol,
                    )

            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_insumo_admin(insumo_id, unidad_medida=None, stock_minimo=None, proveedor=None):
    conn = None
    try:
        iid = int(insumo_id)
        updates = []
        params = []
        proveedor_nombre = (proveedor or "").strip() or None

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            proveedor_id = _obtener_o_crear_proveedor(cur, proveedor_nombre)

            if unidad_medida is not None:
                unidad = str(unidad_medida).strip()
                if not unidad:
                    return {"error": "unidad_medida es obligatoria"}
                updates.append("unidad_medida = %s")
                params.append(unidad)

            if stock_minimo is not None:
                minimo = float(stock_minimo)
                if minimo < 0:
                    return {"error": "stock_minimo no puede ser negativo"}
                updates.append("stock_minimo = %s")
                params.append(minimo)

            if proveedor is not None:
                updates.append("proveedor_id = %s")
                params.append(proveedor_id)

            if not updates:
                return {"error": "No hay campos para actualizar"}

            params.append(iid)
            cur.execute(
                f"""
                UPDATE insumos
                SET {', '.join(updates)}
                WHERE insumo_id = %s
                RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                """,
                tuple(params),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Insumo no encontrado"}
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def ajustar_stock_insumo(insumo_id, cantidad_ajuste, motivo=None, actor_username=None, actor_rol="admin"):
    conn = None
    try:
        iid = int(insumo_id)
        ajuste = float(cantidad_ajuste or 0)
        if ajuste == 0:
            return {"error": "cantidad_ajuste no puede ser 0"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT insumo_id, nombre, unidad_medida, stock_actual, stock_minimo
                FROM insumos
                WHERE insumo_id = %s
                FOR UPDATE
                """,
                (iid,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Insumo no encontrado"}

            stock_antes = float(row["stock_actual"])
            stock_despues = stock_antes + ajuste
            if stock_despues < 0:
                return {"error": f"Ajuste invalido: el stock de {row['nombre']} no puede quedar negativo."}

            cur.execute(
                """
                UPDATE insumos
                SET stock_actual = %s
                WHERE insumo_id = %s
                RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo
                """,
                (stock_despues, iid),
            )
            updated = cur.fetchone()

            _registrar_movimiento_inventario_cur(
                cur,
                insumo_id=iid,
                tipo="ajuste_entrada" if ajuste > 0 else "ajuste_salida",
                cantidad_movimiento=ajuste,
                stock_antes=stock_antes,
                stock_despues=stock_despues,
                referencia_tipo="ajuste_manual",
                referencia_id=iid,
                detalle={"motivo": (motivo or "").strip() or "ajuste manual admin"},
                actor_username=actor_username,
                actor_rol=actor_rol,
            )
            conn.commit()
            return updated
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_disponibilidad_producto(producto_id, cantidad=1):
    conn = None
    try:
        pid = int(producto_id)
        qty = float(cantidad or 0)
        if pid <= 0:
            return {"error": "producto_id invalido"}
        if qty <= 0:
            return {"error": "cantidad invalida"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT producto_id, nombre, variante, precio, activo
                FROM productos
                WHERE producto_id = %s
                LIMIT 1
                """,
                (pid,),
            )
            producto = cur.fetchone()
            if not producto:
                return {"ok": False, "error": "Producto no encontrado", "producto_id": pid}
            if not bool(producto.get("activo")):
                return {
                    "ok": False,
                    "error": f"{producto.get('nombre')} {producto.get('variante') or ''}".strip() + " esta inactivo.",
                    "producto_id": pid,
                    "producto": producto,
                }

            cur.execute(
                """
                SELECT
                    r.insumo_id,
                    i.nombre AS insumo,
                    i.unidad_medida,
                    i.stock_actual,
                    i.stock_minimo,
                    r.cantidad_por_unidad,
                    (r.cantidad_por_unidad * %s)::NUMERIC(12,3) AS requerido
                FROM recetas_producto_insumo r
                JOIN insumos i ON i.insumo_id = r.insumo_id
                WHERE r.producto_id = %s
                  AND r.activo = TRUE
                ORDER BY i.nombre
                """,
                (qty, pid),
            )
            componentes = cur.fetchall() or []
            if not componentes:
                return {
                    "ok": False,
                    "error": f"{producto.get('nombre')} {producto.get('variante') or ''}".strip() + " no tiene receta activa.",
                    "producto_id": pid,
                    "producto": producto,
                }

            faltantes = []
            for comp in componentes:
                disponible = float(comp.get("stock_actual") or 0)
                requerido = float(comp.get("requerido") or 0)
                if disponible < requerido:
                    faltantes.append(
                        {
                            "insumo_id": comp.get("insumo_id"),
                            "insumo": comp.get("insumo"),
                            "disponible": disponible,
                            "requerido": requerido,
                            "unidad_medida": comp.get("unidad_medida"),
                        }
                    )

            if faltantes:
                detalle = " | ".join(
                    f"{f['insumo']}: disponible={f['disponible']:.3f} / requerido={f['requerido']:.3f} {f['unidad_medida']}"
                    for f in faltantes
                )
                return {
                    "ok": False,
                    "error": f"Stock insuficiente para {producto.get('nombre')} {producto.get('variante') or ''}. {detalle}".strip(),
                    "producto_id": pid,
                    "producto": producto,
                    "faltantes": faltantes,
                }

            return {
                "ok": True,
                "producto_id": pid,
                "producto": producto,
                "cantidad": qty,
            }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def guardar_componente_receta(producto_id, insumo_id, cantidad_por_unidad, activo=True):
    conn = None
    try:
        pid = int(producto_id)
        iid = int(insumo_id)
        qty = float(cantidad_por_unidad or 0)
        if qty <= 0:
            return {"error": "cantidad_por_unidad debe ser mayor a 0"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM productos WHERE producto_id = %s LIMIT 1", (pid,))
            if not cur.fetchone():
                return {"error": "Producto no encontrado"}

            cur.execute("SELECT 1 FROM insumos WHERE insumo_id = %s LIMIT 1", (iid,))
            if not cur.fetchone():
                return {"error": "Insumo no encontrado"}

            cur.execute(
                """
                INSERT INTO recetas_producto_insumo (producto_id, insumo_id, cantidad_por_unidad, activo)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (producto_id, insumo_id)
                DO UPDATE SET
                    cantidad_por_unidad = EXCLUDED.cantidad_por_unidad,
                    activo = EXCLUDED.activo,
                    actualizado_en = NOW()
                RETURNING receta_id, producto_id, insumo_id, cantidad_por_unidad, activo, actualizado_en
                """,
                (pid, iid, qty, bool(activo)),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_recetas_producto(producto_id=None, texto=None, activa=None, limit=None, offset=0):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params = []
            filtros = []
            if producto_id is not None:
                filtros.append("r.producto_id = %s")
                params.append(int(producto_id))

            search = str(texto or "").strip()
            if search:
                pattern = f"%{search}%"
                filtros.append("(COALESCE(p.nombre, '') ILIKE %s OR COALESCE(p.variante, '') ILIKE %s OR COALESCE(i.nombre, '') ILIKE %s)")
                params.extend([pattern, pattern, pattern])

            if activa is not None:
                filtros.append("r.activo = %s")
                params.append(bool(activa))

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            limit_sql = ""
            if limit is not None:
                lim = max(1, min(500, int(limit)))
                off = max(0, int(offset or 0))
                limit_sql = " LIMIT %s OFFSET %s"
                params.extend([lim, off])

            cur.execute(
                f"""
                SELECT
                    r.receta_id,
                    r.producto_id,
                    p.nombre AS producto,
                    p.variante,
                    r.insumo_id,
                    i.nombre AS insumo,
                    i.unidad_medida,
                    r.cantidad_por_unidad,
                    r.activo,
                    r.actualizado_en
                FROM recetas_producto_insumo r
                JOIN productos p ON p.producto_id = r.producto_id
                JOIN insumos i ON i.insumo_id = r.insumo_id
                {where_sql}
                ORDER BY p.nombre, p.variante, i.nombre
                {limit_sql}
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_componente_receta(receta_id, activo=None, cantidad_por_unidad=None):
    conn = None
    try:
        rid = int(receta_id)
        cambios = []
        params = []

        if activo is not None:
            cambios.append("activo = %s")
            params.append(bool(activo))

        if cantidad_por_unidad is not None:
            qty = float(cantidad_por_unidad)
            if qty <= 0:
                return {"error": "cantidad_por_unidad debe ser mayor a 0"}
            cambios.append("cantidad_por_unidad = %s")
            params.append(qty)

        if not cambios:
            return {"error": "No hay campos para actualizar"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = f"""
                UPDATE recetas_producto_insumo
                SET {", ".join(cambios)},
                    actualizado_en = NOW()
                WHERE receta_id = %s
                RETURNING receta_id, producto_id, insumo_id, cantidad_por_unidad, activo, actualizado_en
            """
            params.append(rid)
            cur.execute(query, tuple(params))
            row = cur.fetchone()
            if not row:
                return {"error": "Componente de receta no encontrado"}

            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_movimientos_inventario(limit=100, insumo_id=None, tipo=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []
            if insumo_id is not None:
                filtros.append("m.insumo_id = %s")
                params.append(int(insumo_id))
            if tipo:
                filtros.append("m.tipo = %s")
                params.append(str(tipo).strip())

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            params.append(int(limit))
            cur.execute(
                f"""
                SELECT
                    m.movimiento_id,
                    m.insumo_id,
                    i.nombre AS insumo,
                    i.unidad_medida,
                    m.tipo,
                    m.cantidad_movimiento,
                    m.stock_antes,
                    m.stock_despues,
                    m.referencia_tipo,
                    m.referencia_id,
                    m.detalle,
                    m.actor_username,
                    m.actor_rol,
                    m.creado_en
                FROM movimientos_inventario m
                JOIN insumos i ON i.insumo_id = m.insumo_id
                {where_sql}
                ORDER BY m.creado_en DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_resumen_db():
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_auditoria_seguridad(conn)
        _asegurar_tabla_compras_insumos(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*)::INT FROM clientes) AS clientes,
                    (SELECT COUNT(*)::INT FROM pedidos) AS pedidos,
                    (SELECT COUNT(*)::INT FROM pedidos WHERE estado IN ('recibido', 'en_preparacion', 'listo', 'en_camino')) AS pedidos_activos,
                    (SELECT COUNT(*)::INT FROM productos WHERE activo = TRUE) AS productos_activos,
                    (SELECT COUNT(*)::INT FROM insumos) AS insumos,
                    (SELECT COUNT(*)::INT FROM campanas) AS campanas,
                    (SELECT COUNT(*)::INT FROM log_notificaciones) AS logs_notificaciones,
                    (SELECT COUNT(*)::INT FROM auditoria_seguridad) AS eventos_seguridad,
                    (SELECT COUNT(*)::INT FROM auditoria_seguridad WHERE creado_en::date = CURRENT_DATE) AS eventos_seguridad_hoy,
                    (SELECT COUNT(*)::INT FROM auditoria_negocio) AS eventos_negocio,
                    (SELECT COUNT(*)::INT FROM auditoria_negocio WHERE creado_en::date = CURRENT_DATE) AS eventos_negocio_hoy,
                    (SELECT COUNT(*)::INT FROM sesiones_bot WHERE expira_en > NOW()) AS sesiones_activas,
                    (SELECT COALESCE(SUM(total), 0)::NUMERIC(10,2) FROM pedidos WHERE creado_en::date = CURRENT_DATE AND estado <> 'cancelado') AS ventas_hoy,
                                        (SELECT COALESCE(SUM(total), 0)::NUMERIC(10,2) FROM pedidos WHERE DATE_TRUNC('month', creado_en) = DATE_TRUNC('month', CURRENT_DATE) AND estado <> 'cancelado') AS ventas_mes,
                                        (
                                                WITH costo_insumo AS (
                                                        SELECT DISTINCT ON (c.insumo_id)
                                                                c.insumo_id,
                                                                COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                                                        FROM compras_insumos c
                                                        WHERE c.costo_total IS NOT NULL
                                                            AND c.cantidad > 0
                                                        ORDER BY c.insumo_id, c.creado_en DESC
                                                )
                                                SELECT COALESCE(SUM(dp.cantidad * dp.precio_unitario), 0)::NUMERIC(12,2)
                                                FROM pedidos p
                                                JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
                                                WHERE p.creado_en::date = CURRENT_DATE
                                                    AND p.estado <> 'cancelado'
                                        ) AS ingresos_estimados_hoy,
                                        (
                                                WITH costo_insumo AS (
                                                        SELECT DISTINCT ON (c.insumo_id)
                                                                c.insumo_id,
                                                                COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                                                        FROM compras_insumos c
                                                        WHERE c.costo_total IS NOT NULL
                                                            AND c.cantidad > 0
                                                        ORDER BY c.insumo_id, c.creado_en DESC
                                                )
                                                SELECT COALESCE(SUM(dp.cantidad * r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)::NUMERIC(12,2)
                                                FROM pedidos p
                                                JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
                                                LEFT JOIN recetas_producto_insumo r
                                                             ON r.producto_id = dp.producto_id
                                                            AND r.activo = TRUE
                                                LEFT JOIN costo_insumo ci
                                                             ON ci.insumo_id = r.insumo_id
                                                WHERE p.creado_en::date = CURRENT_DATE
                                                    AND p.estado <> 'cancelado'
                                        ) AS costo_estimado_hoy
                """
            )
            row = cur.fetchone() or {}
            ingresos = float(row.get("ingresos_estimados_hoy") or 0)
            costo = float(row.get("costo_estimado_hoy") or 0)
            utilidad = ingresos - costo
            margen_pct = (utilidad / ingresos * 100) if ingresos > 0 else 0
            row["utilidad_estimada_hoy"] = round(utilidad, 2)
            row["margen_estimado_pct_hoy"] = round(margen_pct, 2)
            return row
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def guardar_sesion_bot(whatsapp_id, estado, datos_temp):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO sesiones_bot (whatsapp_id, estado, datos_temp, actualizado_en, expira_en)
                VALUES (%s, %s, %s::jsonb, NOW(), NOW() + INTERVAL '5 days')
                ON CONFLICT (whatsapp_id)
                DO UPDATE SET
                    estado = EXCLUDED.estado,
                    datos_temp = EXCLUDED.datos_temp,
                    actualizado_en = NOW(),
                    expira_en = NOW() + INTERVAL '5 days'
                RETURNING whatsapp_id, estado, datos_temp, actualizado_en, expira_en
                """,
                (whatsapp_id, estado, _to_json_text(datos_temp)),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_sesion_bot(whatsapp_id):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT whatsapp_id, estado, datos_temp, actualizado_en, expira_en
                FROM sesiones_bot
                WHERE whatsapp_id = %s
                  AND expira_en > NOW()
                LIMIT 1
                """,
                (whatsapp_id,),
            )
            return cur.fetchone()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def limpiar_sesiones_expiradas():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                DELETE FROM sesiones_bot
                WHERE expira_en <= NOW()
                RETURNING whatsapp_id
                """
            )
            borradas = cur.fetchall()
            conn.commit()
            return {"eliminadas": len(borradas)}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_campania(nombre, mensaje, segmento="general", creada_por=None):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO campanas (nombre, mensaje, segmento, creada_por)
                VALUES (%s, %s, %s, %s)
                RETURNING campana_id, nombre, mensaje, segmento, creada_por, creado_en
                """,
                (nombre, mensaje, segmento, creada_por),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tabla_envios_campana(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS campanas_envios (
                envio_id BIGSERIAL PRIMARY KEY,
                campana_id BIGINT NOT NULL REFERENCES campanas(campana_id) ON DELETE CASCADE,
                cliente_id BIGINT,
                whatsapp_id VARCHAR(50) NOT NULL,
                estado VARCHAR(20) NOT NULL,
                error TEXT,
                enviado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_campanas_envios_estado CHECK (estado IN ('enviado', 'fallido'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_campanas_envios_campana
                ON campanas_envios (campana_id, estado)
            """
        )


def obtener_campanias(limit=100):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_envios_campana(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH resumen AS (
                    SELECT
                        campana_id,
                        COUNT(*) FILTER (WHERE estado = 'enviado')::INT AS mensajes_enviados,
                        COUNT(*) FILTER (WHERE estado = 'fallido')::INT AS mensajes_fallidos,
                        COUNT(*)::INT AS total_intentos
                    FROM campanas_envios
                    GROUP BY campana_id
                )
                SELECT
                    c.campana_id,
                    c.nombre,
                    c.segmento,
                    c.creada_por,
                    c.creado_en,
                    COALESCE(r.mensajes_enviados, 0)::INT AS mensajes_enviados,
                    COALESCE(r.mensajes_fallidos, 0)::INT AS mensajes_fallidos,
                    COALESCE(r.total_intentos, 0)::INT AS total_intentos
                FROM campanas c
                LEFT JOIN resumen r ON r.campana_id = c.campana_id
                ORDER BY c.creado_en DESC
                LIMIT %s
                """,
                (int(limit),),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _build_segmento_where(filtro):
    filtro_normalizado = (filtro or "todos").strip().lower()

    if filtro_normalizado in {"", "todos", "general"}:
        return "TRUE", []

    if filtro_normalizado in {"mujeres", "mujer"}:
        return "LOWER(COALESCE(c.genero_trato, 'neutro')) = 'mujer'", []

    if filtro_normalizado in {"hombres", "hombre"}:
        return "LOWER(COALESCE(c.genero_trato, 'neutro')) = 'hombre'", []

    if filtro_normalizado == "top":
        return "COALESCE(st.total_pedidos, 0) > 0", []

    if filtro_normalizado == "inactivos_30d":
        return "(st.ultima_compra IS NULL OR st.ultima_compra < NOW() - INTERVAL '30 days')", []

    return "TRUE", []


def contar_clientes_para_campania(filtro="todos"):
    conn = None
    try:
        conn = get_connection()
        where_sql, params = _build_segmento_where(filtro)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH stats AS (
                    SELECT
                        p.cliente_id,
                        COUNT(*) FILTER (WHERE p.estado <> 'cancelado')::INT AS total_pedidos,
                        MAX(p.creado_en) FILTER (WHERE p.estado <> 'cancelado') AS ultima_compra
                    FROM pedidos p
                    GROUP BY p.cliente_id
                )
                SELECT COUNT(*)::INT AS total
                FROM clientes c
                LEFT JOIN stats st ON st.cliente_id = c.cliente_id
                WHERE COALESCE(NULLIF(TRIM(c.whatsapp_id), ''), '') <> ''
                  AND ({where_sql})
                """,
                tuple(params),
            )
            row = cur.fetchone() or {}
            return {"count": int(row.get("total") or 0), "filtro": (filtro or "todos")}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_clientes_para_campania(filtro="todos"):
    conn = None
    try:
        conn = get_connection()
        where_sql, params = _build_segmento_where(filtro)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH stats AS (
                    SELECT
                        p.cliente_id,
                        COUNT(*) FILTER (WHERE p.estado <> 'cancelado')::INT AS total_pedidos,
                        MAX(p.creado_en) FILTER (WHERE p.estado <> 'cancelado') AS ultima_compra
                    FROM pedidos p
                    GROUP BY p.cliente_id
                )
                SELECT
                    c.cliente_id,
                    c.whatsapp_id,
                    c.nombre,
                    c.apellidos,
                    COALESCE(c.genero_trato, 'neutro') AS genero_trato,
                    COALESCE(st.total_pedidos, 0)::INT AS total_pedidos,
                    st.ultima_compra
                FROM clientes c
                LEFT JOIN stats st ON st.cliente_id = c.cliente_id
                WHERE COALESCE(NULLIF(TRIM(c.whatsapp_id), ''), '') <> ''
                  AND ({where_sql})
                ORDER BY COALESCE(st.total_pedidos, 0) DESC, st.ultima_compra DESC NULLS LAST, c.cliente_id DESC
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def registrar_envio_campana(campana_id, cliente_id, whatsapp_id, enviado, error=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_envios_campana(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO campanas_envios (campana_id, cliente_id, whatsapp_id, estado, error)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING envio_id, campana_id, cliente_id, whatsapp_id, estado, error, enviado_en
                """,
                (
                    int(campana_id),
                    int(cliente_id) if cliente_id is not None else None,
                    str(whatsapp_id),
                    "enviado" if bool(enviado) else "fallido",
                    (str(error) if error else None),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_empleados():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT empleado_id, nombre, apellidos, rol, telefono, activo
                FROM empleados
                ORDER BY rol, nombre
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tabla_log_notificaciones(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS log_notificaciones (
                log_id BIGSERIAL PRIMARY KEY,
                pedido_id BIGINT NOT NULL,
                canal VARCHAR(30) NOT NULL,
                destino VARCHAR(30) NOT NULL,
                tipo VARCHAR(30) NOT NULL,
                mensaje TEXT NOT NULL,
                total NUMERIC(10,2),
                direccion TEXT,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_log_notificaciones_pedido_id
                ON log_notificaciones (pedido_id)
            """
        )


def _asegurar_tabla_tickets_soporte(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets_soporte (
                ticket_id          BIGSERIAL PRIMARY KEY,
                numero_ticket      VARCHAR(30)  NOT NULL UNIQUE,
                categoria          VARCHAR(40)  NOT NULL DEFAULT 'otro',
                prioridad          VARCHAR(15)  NOT NULL DEFAULT 'media',
                nombre_contacto    VARCHAR(120) NOT NULL,
                whatsapp_contacto  VARCHAR(30),
                descripcion        TEXT         NOT NULL,
                estado             VARCHAR(20)  NOT NULL DEFAULT 'abierto',
                notas_resolucion   TEXT,
                resuelto_por       VARCHAR(80),
                creado_en          TIMESTAMP    NOT NULL DEFAULT NOW(),
                actualizado_en     TIMESTAMP    NOT NULL DEFAULT NOW(),
                resuelto_en        TIMESTAMP,
                CONSTRAINT chk_tickets_soporte_categoria CHECK (
                    categoria IN ('acceso', 'facturacion', 'tecnico', 'pedido', 'otro')
                ),
                CONSTRAINT chk_tickets_soporte_prioridad CHECK (
                    prioridad IN ('baja', 'media', 'alta', 'urgente')
                ),
                CONSTRAINT chk_tickets_soporte_estado CHECK (
                    estado IN ('abierto', 'en_proceso', 'resuelto', 'cerrado')
                )
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_soporte_estado
                ON tickets_soporte (estado, creado_en DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_soporte_numero
                ON tickets_soporte (numero_ticket)
            """
        )
        conn.commit()


def _generar_numero_ticket(cur):
    """Genera un numero de ticket tipo TKT-YYYYMMDD-NNN."""
    hoy = datetime.now().strftime("%Y%m%d")
    cur.execute(
        """
        SELECT COUNT(*)::INT + 1 AS siguiente
        FROM tickets_soporte
        WHERE numero_ticket LIKE %s
        """,
        (f"TKT-{hoy}-%",),
    )
    row = cur.fetchone()
    seq = int(row["siguiente"] if isinstance(row, dict) else row[0])
    return f"TKT-{hoy}-{seq:03d}"


def crear_ticket_soporte(categoria, prioridad, nombre_contacto, whatsapp_contacto, descripcion):
    conn = None
    try:
        categoria = (categoria or "otro").strip().lower()
        prioridad = (prioridad or "media").strip().lower()
        nombre = (nombre_contacto or "").strip()
        whatsapp = (whatsapp_contacto or "").strip() or None
        desc = (descripcion or "").strip()

        if not nombre:
            return {"error": "El nombre de contacto es obligatorio."}
        if not desc:
            return {"error": "La descripcion del problema es obligatoria."}
        if categoria not in {"acceso", "facturacion", "tecnico", "pedido", "otro"}:
            categoria = "otro"
        if prioridad not in {"baja", "media", "alta", "urgente"}:
            prioridad = "media"

        conn = get_connection()
        _asegurar_tabla_tickets_soporte(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            numero = _generar_numero_ticket(cur)
            cur.execute(
                """
                INSERT INTO tickets_soporte
                    (numero_ticket, categoria, prioridad, nombre_contacto,
                     whatsapp_contacto, descripcion, estado)
                VALUES (%s, %s, %s, %s, %s, %s, 'abierto')
                RETURNING ticket_id, numero_ticket, categoria, prioridad,
                          nombre_contacto, whatsapp_contacto, descripcion,
                          estado, creado_en
                """,
                (numero, categoria, prioridad, nombre, whatsapp, desc),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_tickets_soporte(estado=None, limit=200):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_tickets_soporte(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if estado:
                cur.execute(
                    """
                    SELECT ticket_id, numero_ticket, categoria, prioridad, nombre_contacto,
                           whatsapp_contacto, descripcion, estado, notas_resolucion,
                           resuelto_por, creado_en, actualizado_en, resuelto_en
                    FROM tickets_soporte
                    WHERE estado = %s
                    ORDER BY
                        CASE prioridad
                            WHEN 'urgente' THEN 1 WHEN 'alta' THEN 2
                            WHEN 'media'   THEN 3 WHEN 'baja' THEN 4
                        END,
                        creado_en DESC
                    LIMIT %s
                    """,
                    (estado, int(limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT ticket_id, numero_ticket, categoria, prioridad, nombre_contacto,
                           whatsapp_contacto, descripcion, estado, notas_resolucion,
                           resuelto_por, creado_en, actualizado_en, resuelto_en
                    FROM tickets_soporte
                    ORDER BY
                        CASE estado
                            WHEN 'abierto'    THEN 1 WHEN 'en_proceso' THEN 2
                            WHEN 'resuelto'   THEN 3 WHEN 'cerrado'    THEN 4
                        END,
                        CASE prioridad
                            WHEN 'urgente' THEN 1 WHEN 'alta' THEN 2
                            WHEN 'media'   THEN 3 WHEN 'baja' THEN 4
                        END,
                        creado_en DESC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_estado_ticket(numero_ticket, nuevo_estado, notas_resolucion=None, resuelto_por=None):
    conn = None
    try:
        numero = (numero_ticket or "").strip().upper()
        nuevo_estado = (nuevo_estado or "").strip().lower()
        if not numero:
            return {"error": "numero_ticket es obligatorio."}
        if nuevo_estado not in {"abierto", "en_proceso", "resuelto", "cerrado"}:
            return {"error": f"Estado invalido: {nuevo_estado}"}

        conn = get_connection()
        _asegurar_tabla_tickets_soporte(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE tickets_soporte
                SET
                    estado           = %s,
                    notas_resolucion = COALESCE(%s, notas_resolucion),
                    resuelto_por     = COALESCE(%s, resuelto_por),
                    actualizado_en   = NOW(),
                    resuelto_en      = CASE
                        WHEN %s IN ('resuelto', 'cerrado') THEN COALESCE(resuelto_en, NOW())
                        ELSE resuelto_en
                    END
                WHERE UPPER(numero_ticket) = %s
                RETURNING ticket_id, numero_ticket, categoria, prioridad, nombre_contacto,
                          whatsapp_contacto, descripcion, estado, notas_resolucion,
                          resuelto_por, creado_en, actualizado_en, resuelto_en
                """,
                (nuevo_estado, notas_resolucion or None, resuelto_por or None, nuevo_estado, numero),
            )
            row = cur.fetchone()
            if not row:
                return {"error": f"Ticket {numero} no encontrado."}
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_log_notificacion(payload):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_log_notificaciones(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO log_notificaciones
                    (pedido_id, canal, destino, tipo, mensaje, total, direccion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING log_id, pedido_id, canal, destino, tipo, mensaje, total, direccion, creado_en
                """,
                (
                    int(payload.get("pedido_id")),
                    payload.get("canal"),
                    payload.get("destino"),
                    payload.get("tipo"),
                    payload.get("mensaje"),
                    payload.get("total"),
                    payload.get("direccion"),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tabla_logs_sistema(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs_sistema (
                id BIGSERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                nivel VARCHAR(10) NOT NULL,
                componente VARCHAR(40) NOT NULL,
                funcion VARCHAR(120),
                mensaje TEXT NOT NULL,
                detalle TEXT,
                whatsapp_id VARCHAR(30),
                pedido_id BIGINT,
                ip_origen VARCHAR(64),
                duracion_ms INTEGER,
                resuelto BOOLEAN NOT NULL DEFAULT FALSE,
                resuelto_en TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_logs_sistema_timestamp
                ON logs_sistema (timestamp DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_logs_sistema_nivel
                ON logs_sistema (nivel)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_logs_sistema_componente
                ON logs_sistema (componente)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_logs_sistema_resuelto
                ON logs_sistema (resuelto)
            """
        )
        conn.commit()


def insertar_log_sistema(
    nivel,
    componente,
    funcion,
    mensaje,
    detalle=None,
    whatsapp_id=None,
    pedido_id=None,
    ip_origen=None,
    duracion_ms=None,
):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_logs_sistema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO logs_sistema
                    (nivel, componente, funcion, mensaje, detalle,
                     whatsapp_id, pedido_id, ip_origen, duracion_ms)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, timestamp, nivel, componente, funcion, mensaje,
                          detalle, whatsapp_id, pedido_id, ip_origen, duracion_ms, resuelto
                """,
                (
                    str((nivel or "INFO")).upper()[:10],
                    str((componente or "app")).lower()[:40],
                    (str(funcion)[:120] if funcion else None),
                    str(mensaje or "")[:500],
                    (str(detalle) if detalle is not None else None),
                    (str(whatsapp_id)[:30] if whatsapp_id else None),
                    (int(pedido_id) if pedido_id not in (None, "") else None),
                    (str(ip_origen)[:64] if ip_origen else None),
                    (int(duracion_ms) if duracion_ms not in (None, "") else None),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_logs_sistema(nivel=None, componente=None, limit=50, offset=0, solo_pendientes=False, q=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_logs_sistema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where_parts = []
            params = []

            nivel_norm = (str(nivel or "").strip().upper())
            if nivel_norm:
                where_parts.append("nivel = %s")
                params.append(nivel_norm)

            componente_norm = (str(componente or "").strip().lower())
            if componente_norm:
                where_parts.append("componente = %s")
                params.append(componente_norm)

            if solo_pendientes:
                where_parts.append("resuelto = FALSE")
                where_parts.append("nivel IN ('ERROR', 'CRITICAL')")

            q_norm = (str(q or "").strip())
            if q_norm:
                where_parts.append("(mensaje ILIKE %s OR COALESCE(detalle, '') ILIKE %s)")
                like = f"%{q_norm}%"
                params.extend([like, like])

            where_sql = ""
            if where_parts:
                where_sql = " WHERE " + " AND ".join(where_parts)

            limit_int = max(1, min(500, int(limit)))
            offset_int = max(0, int(offset))
            params.extend([limit_int, offset_int])

            cur.execute(
                f"""
                SELECT id, timestamp, nivel, componente, funcion,
                       mensaje, detalle, whatsapp_id, pedido_id,
                       ip_origen, duracion_ms, resuelto, resuelto_en
                FROM logs_sistema
                {where_sql}
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def contar_logs_sistema(nivel=None, componente=None, solo_pendientes=False, q=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_logs_sistema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where_parts = []
            params = []

            nivel_norm = (str(nivel or "").strip().upper())
            if nivel_norm:
                where_parts.append("nivel = %s")
                params.append(nivel_norm)

            componente_norm = (str(componente or "").strip().lower())
            if componente_norm:
                where_parts.append("componente = %s")
                params.append(componente_norm)

            if solo_pendientes:
                where_parts.append("resuelto = FALSE")
                where_parts.append("nivel IN ('ERROR', 'CRITICAL')")

            q_norm = (str(q or "").strip())
            if q_norm:
                where_parts.append("(mensaje ILIKE %s OR COALESCE(detalle, '') ILIKE %s)")
                like = f"%{q_norm}%"
                params.extend([like, like])

            where_sql = ""
            if where_parts:
                where_sql = " WHERE " + " AND ".join(where_parts)

            cur.execute(f"SELECT COUNT(*)::INT AS total FROM logs_sistema{where_sql}", params)
            row = cur.fetchone() or {}
            return int(row.get("total") or 0)
    except Exception:
        return 0
    finally:
        if conn:
            conn.close()


def marcar_log_sistema_resuelto(log_id):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_logs_sistema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE logs_sistema
                SET resuelto = TRUE,
                    resuelto_en = COALESCE(resuelto_en, NOW())
                WHERE id = %s
                RETURNING id, resuelto, resuelto_en
                """,
                (int(log_id),),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return {"error": "Log no encontrado"}
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def resumen_logs_sistema():
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_logs_sistema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE nivel = 'ERROR' AND timestamp >= NOW() - INTERVAL '24 hours')::INT AS errores_24h,
                    COUNT(*) FILTER (WHERE nivel = 'CRITICAL' AND timestamp >= NOW() - INTERVAL '24 hours')::INT AS criticos_24h,
                    COUNT(*) FILTER (WHERE nivel = 'WARNING' AND timestamp >= NOW() - INTERVAL '24 hours')::INT AS warnings_24h,
                    COUNT(*) FILTER (WHERE resuelto = FALSE AND nivel IN ('ERROR', 'CRITICAL'))::INT AS pendientes,
                    MAX(timestamp) FILTER (WHERE nivel IN ('ERROR', 'CRITICAL')) AS ultimo_error
                FROM logs_sistema
                """
            )
            row = cur.fetchone() or {}
            return {
                "errores_24h": int(row.get("errores_24h") or 0),
                "criticos_24h": int(row.get("criticos_24h") or 0),
                "warnings_24h": int(row.get("warnings_24h") or 0),
                "pendientes": int(row.get("pendientes") or 0),
                "ultimo_error": row.get("ultimo_error"),
            }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()
