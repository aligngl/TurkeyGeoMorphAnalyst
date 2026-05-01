# -*- coding: utf-8 -*-
"""Hydrological analysis routines."""

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
    """Raised when hydrological processing fails."""


class HydrologicalAnalyst:
    """Perform DEM-based hydrological analysis."""

    def __init__(self, output_dir: str):
        """Initialize hydrology analyst."""
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _out(self, name: str) -> str:
        """Build output path."""
        return os.fspath(self.output_dir / name)

    def _has_algorithm(self, algorithm_id: str) -> bool:
        """Return True when a Processing algorithm exists."""
        return QgsApplication.processingRegistry().algorithmById(
            algorithm_id
        ) is not None

    def fill_sinks(self, dem):
        """Fill DEM sinks."""
        if not self._has_algorithm("saga:fillsinksxxlwangliu"):
            raise ProcessingError("SAGA Fill Sinks algoritması bulunamadı.")
        result = processing.run(
            "saga:fillsinksxxlwangliu",
            {
                "ELEV": dem,
                "FILLED": self._out("filled_dem.tif"),
                "FDIR": "TEMPORARY_OUTPUT",
                "WSHED": "TEMPORARY_OUTPUT",
                "MINSLOPE": 0.01,
            },
        )
        return QgsRasterLayer(result["FILLED"], "Çukur Doldurulmuş DEM")

    def flow_direction(self, filled):
        """Create flow direction raster."""
        if not self._has_algorithm("saga:flowdirectionfromdem"):
            raise ProcessingError("SAGA Flow Direction algoritması bulunamadı.")
        result = processing.run(
            "saga:flowdirectionfromdem",
            {"DEM": filled, "DIRECTION": self._out("flow_direction.tif")},
        )
        return QgsRasterLayer(result["DIRECTION"], "Akış Yönü")

    def flow_accumulation(self, flow_dir):
        """Create flow accumulation raster."""
        if self._has_algorithm("saga:flowaccumulation"):
            result = processing.run(
                "saga:flowaccumulation",
                {"FLOW": flow_dir, "ACCU": self._out("flow_accumulation.tif")},
            )
            return QgsRasterLayer(result["ACCU"], "Akış Birikimi")
        raise ProcessingError("SAGA Flow Accumulation algoritması bulunamadı.")

    def channel_network(self, flow_acc, threshold: int = 1000):
        """Create channel network vector layer."""
        if not self._has_algorithm("saga:channelnetworkanddrainagebasins"):
            raise ProcessingError("SAGA Channel Network algoritması bulunamadı.")
        result = processing.run(
            "saga:channelnetworkanddrainagebasins",
            {
                "ELEVATION": flow_acc,
                "THRESHOLD": threshold,
                "SEGMENTS": self._out("channels.gpkg"),
                "BASINS": self._out("basins.gpkg"),
            },
        )
        return QgsVectorLayer(result["SEGMENTS"], "Akarsu Ağı", "ogr")

    def stream_order(self, channels):
        """Calculate Strahler stream order."""
        if not self._has_algorithm("saga:strahlerorder"):
            raise ProcessingError("SAGA Strahler algoritması bulunamadı.")
        result = processing.run(
            "saga:strahlerorder",
            {"SEGMENTS": channels, "ORDER": self._out("stream_order.gpkg")},
        )
        return QgsVectorLayer(result["ORDER"], "Strahler Sırası", "ogr")

    def watershed_basins(self, flow_dir):
        """Create watershed basins."""
        if not self._has_algorithm("saga:watershedbasins"):
            raise ProcessingError("SAGA Watershed Basins algoritması bulunamadı.")
        result = processing.run(
            "saga:watershedbasins",
            {"DEM": flow_dir, "BASINS": self._out("watershed_basins.gpkg")},
        )
        return QgsVectorLayer(result["BASINS"], "Havzalar", "ogr")

    def drainage_density(self, rivers_layer, area_km2: float) -> float:
        """Calculate drainage density in km/km2."""
        total_m = 0.0
        for feature in rivers_layer.getFeatures():
            total_m += feature.geometry().length()
        if area_km2 <= 0:
            return 0.0
        return (total_m / 1000.0) / area_km2

    def calculate_sinuosity(self, river_layer):
        """Add sinuosity values to a copied river layer."""
        output = QgsVectorLayer(
            "LineString?crs={0}".format(river_layer.crs().authid()),
            "Akarsu Sinuozite",
            "memory",
        )
        provider = output.dataProvider()
        provider.addAttributes(river_layer.fields())
        provider.addAttributes([QgsField("sinuosity", QVariant.Double)])
        output.updateFields()
        for feature in river_layer.getFeatures():
            geom = feature.geometry()
            points = geom.asPolyline()
            if len(points) < 2 and geom.isMultipart():
                parts = geom.asMultiPolyline()
                points = parts[0] if parts else []
            direct = 0.0
            if len(points) >= 2:
                direct = points[0].distance(points[-1])
            length = geom.length()
            sinuosity = length / direct if direct > 0 else 0.0
            new_feature = QgsFeature(output.fields())
            new_feature.setGeometry(geom)
            attrs = feature.attributes() + [sinuosity]
            new_feature.setAttributes(attrs)
            provider.addFeature(new_feature)
        output.updateExtents()
        return output
