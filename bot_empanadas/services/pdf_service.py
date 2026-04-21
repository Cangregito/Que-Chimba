#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servicio de Generación de PDFs de Facturas
============================================

Genera PDFs de facturas con datos de empresa, cliente y pedido.
Utiliza reportlab para máxima compatibilidad y control.
"""

import os
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


def generar_pdf_factura(
    pedido_id,
    folio_factura,
    datos_cliente=None,
    datos_fiscales=None,
    items_pedido=None,
    total=0,
    fecha_emision=None,
    logo_path=None,
    output_path=None,
    empresa_nombre="QUE CHIMBA",
    empresa_rfc="XXX123456XYZ"
):
    """
    Genera PDF de factura profesional.
    
    Args:
        pedido_id: ID del pedido
        folio_factura: Folio o número de factura (p.ej. FAC-2026-04-001)
        datos_cliente: Dict con nombre, apellidos, whatsapp_id, etc.
        datos_fiscales: Dict con rfc, razon_social, regimen_fiscal, uso_cfdi, email
        items_pedido: List de dicts con producto, cantidad, precio_unitario
        total: Monto total del pedido
        fecha_emision: Fecha de emisión (default: hoy)
        logo_path: Ruta a logo de empresa (opcional)
        output_path: Ruta donde guardar el PDF (default: /tmp/factura_{folio}.pdf)
        empresa_nombre: Nombre de la empresa
        empresa_rfc: RFC de la empresa
    
    Returns:
        Dict con 'ruta' del PDF generado o 'error'
    """
    
    if not HAS_REPORTLAB:
        return {
            "error": "reportlab no está instalado. Instala con: pip install reportlab"
        }
    
    # Validaciones básicas
    if not folio_factura:
        return {"error": "Folio de factura es requerido"}
    
    if not datos_cliente:
        datos_cliente = {}
    
    if not datos_fiscales:
        datos_fiscales = {}
    
    if not items_pedido:
        items_pedido = []
    
    # Determinar ruta de salida
    if not output_path:
        tmp_dir = Path("/tmp") if os.name != 'nt' else Path(os.environ.get('TEMP', 'C:\\temp'))
        tmp_dir.mkdir(exist_ok=True, parents=True)
        folio_safe = folio_factura.replace(" ", "_").replace("/", "_").upper()
        output_path = str(tmp_dir / f"factura_{folio_safe}.pdf")
    
    # Crear directorio si no existe
    output_dir = Path(output_path).parent
    output_dir.mkdir(exist_ok=True, parents=True)
    
    try:
        # Crear documento
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch,
        )
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Estilos personalizados
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=colors.HexColor('#1f4788'),
            spaceAfter=6,
            alignment=1  # Centro
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=11,
            textColor=colors.HexColor('#333333'),
            spaceAfter=4,
            fontName='Helvetica-Bold'
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#333333'),
            spaceAfter=2,
        )
        
        # Header con nombre de empresa
        elements.append(Paragraph(empresa_nombre.upper(), title_style))
        elements.append(Paragraph(f"RFC: {empresa_rfc}", normal_style))
        elements.append(Spacer(1, 0.15*inch))
        
        # Folio y fecha
        fecha_str = (fecha_emision or datetime.now()).strftime("%d/%m/%Y %H:%M")
        header_data = [
            [f"<b>FOLIO</b><br/>{folio_factura}", f"<b>FECHA</b><br/>{fecha_str}", f"<b>PEDIDO #</b><br/>{pedido_id}"]
        ]
        header_table = Table(header_data, colWidths=[2.2*inch, 2.2*inch, 2.2*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#333333')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Información del cliente y datos fiscales
        cliente_nombre = f"{datos_cliente.get('nombre', 'Cliente')} {datos_cliente.get('apellidos', '')}".strip()
        rfc = datos_fiscales.get('rfc', 'N/A')
        razon_social = datos_fiscales.get('razon_social', 'N/A')
        regimen = datos_fiscales.get('regimen_fiscal', 'N/A')
        
        info_data = [
            ['CLIENTE', 'RFC / DATOS FISCALES'],
            [cliente_nombre, rfc],
            ['', razon_social],
            ['', f"Régimen: {regimen}"]
        ]
        
        info_table = Table(info_data, colWidths=[3.5*inch, 3.5*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4788')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 1), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Tabla de productos
        items_data = [['PRODUCTO', 'CANTIDAD', 'P. UNITARIO', 'SUBTOTAL']]
        total_calculado = 0
        
        for item in items_pedido:
            producto = item.get('producto') or item.get('nombre', 'Producto')
            cantidad = item.get('cantidad', 1)
            precio_unit = float(item.get('precio_unitario') or item.get('precio_unit') or 0)
            subtotal = cantidad * precio_unit
            total_calculado += subtotal
            
            items_data.append([
                producto,
                f"{cantidad}",
                f"${precio_unit:,.2f}",
                f"${subtotal:,.2f}"
            ])
        
        items_table = Table(items_data, colWidths=[3.2*inch, 1.0*inch, 1.3*inch, 1.5*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4788')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.15*inch))
        
        # Total
        total_final = total or total_calculado
        totales_data = [
            ['', '', 'SUBTOTAL', f"${total_final:,.2f}"],
            ['', '', 'IVA (16%)', f"${total_final * 0.16:,.2f}"],
            ['', '', 'TOTAL', f"${total_final * 1.16:,.2f}"]
        ]
        
        totales_table = Table(totales_data, colWidths=[3.2*inch, 1.0*inch, 1.3*inch, 1.5*inch])
        totales_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (2, 0), (-1, 1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 2), (-1, 2), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (2, 2), (-1, 2), colors.HexColor('#1f4788')),
            ('TEXTCOLOR', (2, 2), (-1, 2), colors.whitesmoke),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (2, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
        ]))
        elements.append(totales_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Pie de página
        footer_text = (
            "Este documento es una FACTURA válida. No requiere firma digital para efectos fiscales.<br/>"
            "Para consultas: info@quechimba.com | WhatsApp: +52 (614) 4-CHIMBA<br/>"
            f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        elements.append(Paragraph(footer_text, ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=7,
            textColor=colors.HexColor('#666666'),
            alignment=1,
        )))
        
        # Generar PDF
        doc.build(elements)
        
        return {
            "ruta": output_path,
            "folio": folio_factura,
            "pedido_id": pedido_id,
            "total": total_final,
            "fecha_generacion": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "error": f"Error generando PDF: {str(e)}"
        }


def obtener_ruta_pdf_factura(folio_factura):
    """Obtiene la ruta esperada del PDF para un folio dado."""
    tmp_dir = Path("/tmp") if os.name != 'nt' else Path(os.environ.get('TEMP', 'C:\\temp'))
    folio_safe = folio_factura.replace(" ", "_").replace("/", "_").upper()
    return str(tmp_dir / f"factura_{folio_safe}.pdf")


if __name__ == "__main__":
    # Prueba básica
    print("🧪 Prueba de Generación de PDF de Factura")
    print("-" * 70)
    
    # Datos de prueba
    resultado = generar_pdf_factura(
        pedido_id=12345,
        folio_factura="FAC-2026-04-001",
        datos_cliente={
            "nombre": "Juan",
            "apellidos": "García López",
            "whatsapp_id": "+5216144123456"
        },
        datos_fiscales={
            "rfc": "JGL123456T12",
            "razon_social": "JUAN GARCÍA GARCÍA SA DE CV",
            "regimen_fiscal": "601",
            "uso_cfdi": "G01",
            "email": "juan@ejemplo.com"
        },
        items_pedido=[
            {"producto": "Empanadas de Carne", "cantidad": 12, "precio_unitario": 8.50},
            {"producto": "Empanadas de Pollo", "cantidad": 6, "precio_unitario": 7.50},
            {"producto": "Salsa Picante", "cantidad": 2, "precio_unitario": 15.00}
        ],
        total=218.00
    )
    
    if "error" in resultado:
        print(f"❌ Error: {resultado['error']}")
    else:
        print(f"✅ PDF Generado Exitosamente")
        print(f"   Folio: {resultado['folio']}")
        print(f"   Ruta: {resultado['ruta']}")
        print(f"   Total: ${resultado['total']:,.2f}")
        print(f"   Fecha: {resultado['fecha_generacion']}")
        
        # Verificar que el archivo existe
        if Path(resultado['ruta']).exists():
            tamaño = Path(resultado['ruta']).stat().st_size
            print(f"   Tamaño: {tamaño:,} bytes")
