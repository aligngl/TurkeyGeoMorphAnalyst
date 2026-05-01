# -*- coding: utf-8 -*-
"""Export helpers for maps, statistics and project files."""

from qgis.core import *
from qgis.gui import *
from qgis.analysis import *
from qgis.utils import iface
import processing
from osgeo import gdal, ogr, osr
import os, sys, json, math, statistics, csv, tempfile
import pathlib, shutil, zipfile, gzip
import urllib.request, urllib.error, urllib.parse
import http.cookiejar
import xml.etree.ElementTree as ET
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *


class ExportError(Exception):
    """Raised when export fails."""


class ExportManager:
    """Manage layout, data, report and package exports."""

    def safe_name(self, value: str) -> str:
        """Return a filesystem-safe file stem."""
        text = value or "turkey_geomorph"
        replacements = {
            "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U",
            "ş": "s", "Ş": "S", "ı": "i", "İ": "I",
            "ö": "o", "Ö": "O", "ç": "c", "Ç": "C",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        safe = []
        for char in text:
            if char.isalnum() or char in ["-", "_"]:
                safe.append(char)
            elif char.isspace():
                safe.append("_")
        return "".join(safe).strip("_") or "turkey_geomorph"

    def export_pdf(self, layout, path: str, dpi: int = 300) -> bool:
        """Export layout to PDF."""
        settings = QgsLayoutExporter.PdfExportSettings()
        settings.dpi = dpi
        return QgsLayoutExporter(layout).exportToPdf(
            path, settings
        ) == QgsLayoutExporter.Success

    def export_png(self, layout, path: str, dpi: int = 300) -> bool:
        """Export layout to PNG."""
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = dpi
        return QgsLayoutExporter(layout).exportToImage(
            path, settings
        ) == QgsLayoutExporter.Success

    def export_tiff(self, layout, path: str, dpi: int = 300) -> bool:
        """Export layout to TIFF image."""
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = dpi
        return QgsLayoutExporter(layout).exportToImage(
            path, settings
        ) == QgsLayoutExporter.Success

    def export_svg(self, layout, path: str) -> bool:
        """Export layout to SVG."""
        settings = QgsLayoutExporter.SvgExportSettings()
        return QgsLayoutExporter(layout).exportToSvg(
            path, settings
        ) == QgsLayoutExporter.Success

    def save_qgis_project(self, path: str) -> bool:
        """Save current QGIS project."""
        return QgsProject.instance().write(path)

    def export_statistics_csv(self, stats_dict: dict, path: str) -> bool:
        """Export statistics to CSV."""
        with open(path, "w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=["metric", "value"])
            writer.writeheader()
            for key, value in stats_dict.items():
                writer.writerow({"metric": key, "value": value})
        return True

    def export_statistics_html(self, stats_dict: dict, path: str,
                               title: str = "TurkeyGeoMorph İstatistikleri",
                               interpretation: str = "") -> bool:
        """Export statistics to a styled HTML report."""
        html = ET.Element("html")
        head = ET.SubElement(html, "head")
        meta = ET.SubElement(head, "meta")
        meta.set("charset", "utf-8")
        style = ET.SubElement(head, "style")
        style.text = (
            "body{font-family:Arial,sans-serif;margin:28px;color:#222;}"
            "h1{color:#174a92;border-bottom:3px solid #174a92;padding-bottom:8px;}"
            "h2{color:#333;margin-top:24px;}"
            "table{border-collapse:collapse;width:100%;margin-top:16px;}"
            "td,th{border:1px solid #c8d2df;padding:7px 9px;font-size:13px;}"
            "th{background:#e9f0f8;text-align:left;}"
            ".note{background:#f6f8fb;border-left:4px solid #174a92;padding:12px;}"
        )
        body = ET.SubElement(html, "body")
        ET.SubElement(body, "h1").text = title
        if interpretation:
            ET.SubElement(body, "h2").text = "Jeomorfolojik Yorum"
            note = ET.SubElement(body, "div")
            note.set("class", "note")
            for line in interpretation.splitlines():
                if line.strip():
                    ET.SubElement(note, "p").text = line.strip()
        ET.SubElement(body, "h2").text = "İstatistik Tablosu"
        table = ET.SubElement(body, "table")
        header = ET.SubElement(table, "tr")
        ET.SubElement(header, "th").text = "Metrik"
        ET.SubElement(header, "th").text = "Değer"
        for key, value in stats_dict.items():
            row = ET.SubElement(table, "tr")
            ET.SubElement(row, "td").text = str(key)
            ET.SubElement(row, "td").text = str(value)
        ET.ElementTree(html).write(path, encoding="utf-8", method="html")
        return True

    def batch_export(self, layouts: list, formats: list,
                     out_dir: str, prefix: str, dpi: int = 300) -> dict:
        """Export multiple layouts in multiple formats."""
        output_dir = pathlib.Path(out_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        results = {}
        safe_prefix = self.safe_name(prefix)
        for layout in layouts:
            layout_name = self.safe_name(layout.name())
            for fmt in formats:
                ext = fmt.lower()
                path = output_dir / "{0}_{1}.{2}".format(
                    safe_prefix, layout_name, ext
                )
                try:
                    QCoreApplication.processEvents()
                    if ext == "pdf":
                        ok = self.export_pdf(layout, os.fspath(path), dpi)
                    elif ext == "png":
                        ok = self.export_png(layout, os.fspath(path), dpi)
                    elif ext in ["tif", "tiff", "geotiff"]:
                        ok = self.export_tiff(layout, os.fspath(path), dpi)
                    elif ext == "svg":
                        ok = self.export_svg(layout, os.fspath(path))
                    else:
                        ok = False
                    QCoreApplication.processEvents()
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        "Dışa aktarma hatası ({0}): {1}".format(path, exc),
                        "TurkeyGeoMorph", Qgis.Warning)
                    ok = False
                results[os.fspath(path)] = ok
        return results

    def write_manifest_csv(self, records: list, path: str) -> bool:
        """Write export manifest CSV."""
        fieldnames = ["path", "type", "status", "size_mb"]
        with open(path, "w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow(record)
        return True

    def create_summary_log(self, results_dict: dict, path: str) -> None:
        """Write a plain text export log."""
        with open(path, "w", encoding="utf-8") as output_file:
            for key, value in results_dict.items():
                output_file.write("{0}: {1}\n".format(key, value))

    def create_zip_package(self, source_dir: str, zip_path: str) -> str:
        """Create a ZIP package from an export directory."""
        source = pathlib.Path(source_dir)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in source.rglob("*"):
                if path.is_file() and os.fspath(path) != zip_path:
                    archive.write(path, path.relative_to(source))
        return zip_path
