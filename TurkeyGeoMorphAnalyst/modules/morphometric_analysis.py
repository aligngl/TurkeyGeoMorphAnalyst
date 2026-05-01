# -*- coding: utf-8 -*-
"""Morphometric metrics and reporting."""

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


class ProcessingError(Exception):
    """Raised when morphometric analysis fails."""


class MorphometricAnalyst:
    """Calculate morphometric metrics for thesis reporting."""

    def hypsometric_integral(self, dem_layer, boundary=None) -> float:
        """Calculate hypsometric integral."""
        stats = dem_layer.dataProvider().bandStatistics(
            1, QgsRasterBandStats.All
        )
        denominator = stats.maximumValue - stats.minimumValue
        if denominator == 0:
            return 0.0
        return (stats.mean - stats.minimumValue) / denominator

    def hypsometric_curve_data(self, dem_layer, boundary=None) -> tuple:
        """Return hypsometric curve area and elevation percentages."""
        provider = dem_layer.dataProvider()
        stats = provider.bandStatistics(1, QgsRasterBandStats.All)
        histogram = provider.histogram(
            1, 20, stats.minimumValue, stats.maximumValue,
            dem_layer.extent(), 0
        )
        counts = histogram.histogramVector
        total = float(sum(counts)) or 1.0
        cumulative = 0.0
        area_percentages = []
        elevation_percentages = []
        for index, count in enumerate(counts):
            cumulative += count
            area_percentages.append(100.0 * cumulative / total)
            elevation_percentages.append(100.0 * index / max(len(counts) - 1, 1))
        return area_percentages, elevation_percentages

    def elongation_ratio(self, basin_geom) -> float:
        """Calculate elongation ratio."""
        area = basin_geom.area()
        bbox = basin_geom.boundingBox()
        max_length = max(bbox.width(), bbox.height())
        if max_length == 0:
            return 0.0
        lc = 2.0 * math.sqrt(area / math.pi)
        return lc / max_length

    def circularity_ratio(self, basin_geom) -> float:
        """Calculate circularity ratio."""
        area = basin_geom.area()
        perimeter = basin_geom.length()
        if perimeter == 0:
            return 0.0
        return 4.0 * math.pi * area / (perimeter * perimeter)

    def form_factor(self, basin_geom, length: float) -> float:
        """Calculate form factor."""
        if length == 0:
            return 0.0
        return basin_geom.area() / (length * length)

    def relief_ratio(self, dem, basin) -> float:
        """Calculate relief ratio from DEM statistics and basin length."""
        stats = dem.dataProvider().bandStatistics(1, QgsRasterBandStats.All)
        relief = stats.maximumValue - stats.minimumValue
        length = max(basin.boundingBox().width(), basin.boundingBox().height())
        if length == 0:
            return 0.0
        return relief / length

    def ruggedness_number(self, relief: float, drainage_density: float) -> float:
        """Calculate ruggedness number."""
        return relief * drainage_density

    def generate_html_report(self, metrics_dict: dict, output_path: str) -> str:
        """Generate an HTML report with xml.etree."""
        html = ET.Element("html")
        head = ET.SubElement(html, "head")
        meta = ET.SubElement(head, "meta")
        meta.set("charset", "utf-8")
        style = ET.SubElement(head, "style")
        style.text = (
            "body{font-family:Arial,sans-serif;margin:24px;}"
            "table{border-collapse:collapse;width:100%;}"
            "td,th{border:1px solid #bbb;padding:6px;}"
            "th{background:#e8eef7;}"
        )
        body = ET.SubElement(html, "body")
        ET.SubElement(body, "h1").text = "Jeomorfometrik Analiz Raporu"
        table = ET.SubElement(body, "table")
        header = ET.SubElement(table, "tr")
        ET.SubElement(header, "th").text = "Metrik"
        ET.SubElement(header, "th").text = "Değer"
        for key, value in metrics_dict.items():
            row = ET.SubElement(table, "tr")
            ET.SubElement(row, "td").text = str(key)
            ET.SubElement(row, "td").text = str(value)
        ET.SubElement(body, "h2").text = "Yorum Şablonu"
        ET.SubElement(body, "p").text = (
            "Yüksek rölyef enerjisi ve drenaj yoğunluğu, çalışma alanında "
            "akarsu aşındırması ve eğim süreçlerinin güçlü olduğunu gösterir. "
            "Düşük hipsometrik integral daha olgun aşınım yüzeylerine, yüksek "
            "değerler ise genç ve parçalanmış topoğrafyaya işaret eder."
        )
        tree = ET.ElementTree(html)
        tree.write(output_path, encoding="utf-8", method="html")
        return output_path
