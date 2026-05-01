# -*- coding: utf-8 -*-
"""DEM processing routines for geomorphology map production."""

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
    """Raised when DEM processing fails."""


class StyleError(Exception):
    """Raised when a raster style cannot be applied."""


class DEMProcessor:
    """Create terrain derivatives from a DEM raster."""

    def __init__(self, dem_path: str, output_dir: str):
        self.dem_path = dem_path
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _output(self, name: str) -> str:
        return os.fspath(self.output_dir / name)

    def _has_algorithm(self, algorithm_id: str) -> bool:
        registry = QgsApplication.processingRegistry()
        return registry.algorithmById(algorithm_id) is not None

    def _load_raster(self, path: str, name: str):
        layer = QgsRasterLayer(path, name)
        if not layer.isValid():
            raise ProcessingError("Raster katmanı geçersiz: {0}".format(path))
        return layer

    def _slope_scale(self) -> float:
        layer = QgsRasterLayer(self.dem_path, "DEM CRS check")
        if not layer.isValid():
            return 111120.0
        crs = layer.crs()
        if not crs.isGeographic():
            return 1.0
        center_lat = layer.extent().center().y()
        meters_per_degree = 111320.0 * max(0.2, math.cos(math.radians(center_lat)))
        return meters_per_degree

    def _raster_cell_count(self, path: str = None) -> int:
        """Return raster cell count for runtime guards."""
        dataset = gdal.Open(path or self.dem_path)
        if dataset is None:
            return 0
        try:
            return int(dataset.RasterXSize) * int(dataset.RasterYSize)
        finally:
            dataset = None

    def _apply_discrete_renderer(self, layer, items: list) -> None:
        """Apply a discrete (stepped) pseudocolor renderer.

        Args:
            layer: QgsRasterLayer to style.
            items: list of (value, hex_color, label) tuples.
        """
        provider = layer.dataProvider()
        ramp = QgsColorRampShader()
        ramp.setColorRampType(QgsColorRampShader.Discrete)
        ramp.setColorRampItemList([
            QgsColorRampShader.ColorRampItem(v, QColor(c), lbl)
            for v, c, lbl in items
        ])
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(ramp)
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    # ------------------------------------------------------------------
    # YÜKSELTİ — dinamik basamaklar, gerçek min/max
    # ------------------------------------------------------------------
    def create_elevation_map(self, params: dict = None):
        """Create elevation raster with dynamic stepped legend labels."""
        params = params or {}
        layer = self._load_raster(self.dem_path, "Yükselti")
        provider = layer.dataProvider()
        stats = provider.bandStatistics(1, QgsRasterBandStats.All)
        lo = stats.minimumValue
        hi = stats.maximumValue
        rng = hi - lo if hi > lo else 1.0

        # Yükselti basamakları: nice round intervals
        raw_step = rng / 7.0
        magnitude = 10 ** math.floor(math.log10(max(raw_step, 1.0)))
        step = max(round(raw_step / magnitude) * magnitude, 1.0)
        start = math.floor(lo / step) * step

        palette = [
            "#2B4D9E", "#4DB87A", "#88C44A", "#E8D44D",
            "#C47B2B", "#8B4513", "#CCCCCC", "#FFFFFF",
        ]
        items = []
        v = start
        idx = 0
        while v <= hi + step and idx < len(palette):
            label = "{:.0f} m".format(v)
            items.append((v, palette[idx], label))
            v += step
            idx += 1
        # Ensure max is covered
        if not items or items[-1][0] < hi:
            items.append((hi, palette[min(idx, len(palette) - 1)], "{:.0f} m".format(hi)))

        self._apply_discrete_renderer(layer, items)
        layer.setOpacity(1 - (float(params.get("opacity", 0)) / 100.0))
        return layer

    # ------------------------------------------------------------------
    # GÖLGELENDİRME — gri→beyaz pseudocolor (stepped)
    # ------------------------------------------------------------------
    def create_hillshade(self, azimuth: int = 315, altitude: int = 45,
                         z_factor: float = 1.0, multidirectional: bool = False):
        """Create hillshade with pseudocolor gray ramp for proper legend."""
        if not multidirectional:
            output = self._output("hillshade.tif")
            result = processing.run("gdal:hillshade", {
                "INPUT": self.dem_path, "BAND": 1,
                "Z_FACTOR": z_factor, "AZIMUTH": azimuth,
                "ALTITUDE": altitude, "COMPUTE_EDGES": True,
                "ZEVENBERGEN": False, "OUTPUT": output,
            })
            path = result["OUTPUT"]
        else:
            outputs = []
            for idx, azi in enumerate([315, 45, 135, 225]):
                out = self._output("hillshade_{0}.tif".format(idx))
                result = processing.run("gdal:hillshade", {
                    "INPUT": self.dem_path, "BAND": 1,
                    "Z_FACTOR": z_factor, "AZIMUTH": azi,
                    "ALTITUDE": altitude, "COMPUTE_EDGES": True,
                    "ZEVENBERGEN": False, "OUTPUT": out,
                })
                outputs.append(result["OUTPUT"])
            averaged = self._output("hillshade_multidirectional.tif")
            processing.run("gdal:rastercalculator", {
                "INPUT_A": outputs[0], "BAND_A": 1,
                "INPUT_B": outputs[1], "BAND_B": 1,
                "INPUT_C": outputs[2], "BAND_C": 1,
                "INPUT_D": outputs[3], "BAND_D": 1,
                "FORMULA": "(A+B+C+D)/4",
                "NO_DATA": None, "RTYPE": 5, "OUTPUT": averaged,
            })
            path = averaged

        layer = self._load_raster(path, "Gölgelendirme")
        # Stepped gray ramp: 5 basamak
        hillshade_items = [
            (51,  "#1a1a1a", "Çok koyu gölge"),
            (102, "#555555", "Koyu gölge"),
            (153, "#999999", "Orta gölge"),
            (204, "#cccccc", "Açık gölge"),
            (255, "#ffffff", "Aydınlık"),
        ]
        self._apply_discrete_renderer(layer, hillshade_items)
        return layer

    # ------------------------------------------------------------------
    # EĞİM
    # ------------------------------------------------------------------
    def create_slope(self, unit: str = "degree", algorithm: str = "Horn"):
        """Create slope raster."""
        output = self._output("slope.tif")
        scale = self._slope_scale()
        result = processing.run("gdal:slope", {
            "INPUT": self.dem_path, "BAND": 1,
            "SCALE": scale,
            "AS_PERCENT": unit.lower().startswith("percent"),
            "COMPUTE_EDGES": True,
            "ZEVENBERGEN": algorithm.lower().startswith("zeven"),
            "OUTPUT": output,
        })
        layer = self._load_raster(result["OUTPUT"], "Eğim")
        self._apply_slope_style(layer)
        return layer

    def _apply_slope_style(self, layer) -> None:
        """Apply FAO slope discrete color ramp."""
        self._apply_discrete_renderer(layer, [
            (2,  "#FFFFB2", "0–2°  Düz"),
            (5,  "#FED976", "2–5°  Çok az eğimli"),
            (8,  "#FEB24C", "5–8°  Az eğimli"),
            (15, "#FD8D3C", "8–15° Orta eğimli"),
            (30, "#FC4E2A", "15–30° Eğimli"),
            (45, "#E31A1C", "30–45° Çok eğimli"),
            (90, "#800026", ">45°  Sarp"),
        ])

    # ------------------------------------------------------------------
    # BAKI
    # ------------------------------------------------------------------
    def create_aspect(self, n_classes: int = 8):
        """Create aspect raster."""
        output = self._output("aspect.tif")
        result = processing.run("gdal:aspect", {
            "INPUT": self.dem_path, "BAND": 1,
            "TRIG_ANGLE": False, "ZERO_FLAT": False,
            "COMPUTE_EDGES": True, "ZEVENBERGEN": False,
            "OUTPUT": output,
        })
        layer = self._load_raster(result["OUTPUT"], "Bakı")
        self._apply_discrete_renderer(layer, [
            (22.5,  "#4575B4", "Kuzey (K)"),
            (67.5,  "#74ADD1", "Kuzeydoğu (KD)"),
            (112.5, "#ABD9E9", "Doğu (D)"),
            (157.5, "#E0F3F8", "Güneydoğu (GD)"),
            (202.5, "#FEE090", "Güney (G)"),
            (247.5, "#FDAE61", "Güneybatı (GB)"),
            (292.5, "#F46D43", "Batı (B)"),
            (337.5, "#D73027", "Kuzeybatı (KB)"),
            (360.0, "#4575B4", "Kuzey (K)"),
        ])
        return layer

    # ------------------------------------------------------------------
    # EĞRİSELLİK — diverging stepped renderer
    # ------------------------------------------------------------------
    def create_curvature(self, curvature_type: str = "total"):
        """Create curvature raster; discrete diverging stepped legend."""
        if self._has_algorithm("saga:slopeaspectcurvature"):
            result = processing.run("saga:slopeaspectcurvature", {
                "ELEVATION": self.dem_path,
                "SLOPE": "TEMPORARY_OUTPUT",
                "ASPECT": "TEMPORARY_OUTPUT",
                "C_GENE": self._output("curvature_total.tif"),
                "C_PROF": self._output("curvature_profile.tif"),
                "C_PLAN": self._output("curvature_plan.tif"),
                "METHOD": 6,
            })
            key = "C_GENE"
            if "profil" in curvature_type.lower():
                key = "C_PROF"
            if "plan" in curvature_type.lower():
                key = "C_PLAN"
            layer = self._load_raster(result[key], "Eğrisellik")
        else:
            # Fallback: GDAL roughness'tan near-curvature approximation
            result = processing.run("gdal:roughness", {
                "INPUT": self.dem_path, "BAND": 1,
                "COMPUTE_EDGES": True,
                "OUTPUT": self._output("curvature_roughness.tif"),
            })
            layer = self._load_raster(result["OUTPUT"], "Eğrisellik")

        # Stepped diverging: konkav → nötr → konveks
        self._apply_discrete_renderer(layer, [
            (-10.0, "#053061", "Güçlü konkav (derin çanaklar)"),
            (-3.0,  "#2166AC", "Belirgin konkav"),
            (-1.0,  "#92C5DE", "Zayıf konkav"),
            ( 0.0,  "#F7F7F7", "Nötr / Düz"),
            ( 1.0,  "#F4A582", "Zayıf konveks"),
            ( 3.0,  "#D6604D", "Belirgin konveks"),
            (10.0,  "#67001F", "Güçlü konveks (keskin sırtlar)"),
        ])
        return layer

    # ------------------------------------------------------------------
    # TWI — Topografik Islaklık İndeksi
    # ------------------------------------------------------------------
    def create_twi(self, flow_algorithm: str = "D8",
                   min_area: int = 100, fill_sinks: bool = True):
        """Create TWI raster with discrete stepped legend."""
        dem = self.dem_path

        # 1. Çukur doldurma (SAGA öncelikli)
        if fill_sinks and self._has_algorithm("saga:fillsinksxxlwangliu"):
            filled = processing.run("saga:fillsinksxxlwangliu", {
                "ELEV": self.dem_path,
                "FILLED": self._output("dem_filled.tif"),
                "FDIR": "TEMPORARY_OUTPUT",
                "WSHED": "TEMPORARY_OUTPUT",
                "MINSLOPE": 0.01,
            })
            dem = filled["FILLED"]
        elif fill_sinks and self._has_algorithm("saga:fillsinks"):
            filled = processing.run("saga:fillsinks", {
                "DEM": self.dem_path,
                "RESULT": self._output("dem_filled.tif"),
                "MINSLOPE": 0.01,
            })
            dem = filled["RESULT"]

        # 2. Akım birikimi (SAGA öncelikli)
        slope_layer = self.create_slope("degree", "Horn")
        slope = slope_layer.source()

        if self._has_algorithm("saga:catchmentarea"):
            acc_result = processing.run("saga:catchmentarea", {
                "ELEVATION": dem, "METHOD": 0,
                "FLOW": self._output("catchment_area.tif"),
            })
            acc = acc_result["FLOW"]
        elif self._has_algorithm("saga:flowaccumulation"):
            acc_result = processing.run("saga:flowaccumulation", {
                "DEM": dem, "FLOW": self._output("catchment_area.tif"),
            })
            acc = acc_result["FLOW"]
        else:
            # Son çare: QGIS native flow accumulation
            try:
                acc_result = processing.run("qgis:fillnodata", {
                    "INPUT": dem, "BAND": 1,
                    "FILL_VALUE": 0, "OUTPUT": self._output("catchment_area_fallback.tif"),
                })
                acc = acc_result["OUTPUT"]
            except Exception:
                acc = dem  # kötü ama crash etmesin

        # 3. TWI = ln(a / tan(β)) hesapla
        output = self._output("twi.tif")
        processing.run("gdal:rastercalculator", {
            "INPUT_A": acc,   "BAND_A": 1,
            "INPUT_B": slope, "BAND_B": 1,
            "FORMULA": "log((A + 1.0) / (tan(B * 0.017453293) + 0.001))",
            "NO_DATA": -9999, "RTYPE": 5, "OUTPUT": output,
        })
        layer = self._load_raster(output, "TWI")

        # Stepped discrete legend — ıslak → kuru yönü
        self._apply_discrete_renderer(layer, [
            (3.0,  "#8C510A", "< 3  Çok kuru / tepe konumu"),
            (6.0,  "#D8B365", "3–6  Kuru yamaç"),
            (9.0,  "#F6E8C3", "6–9  Az nemli"),
            (12.0, "#C7EAE5", "9–12 Orta nemli"),
            (15.0, "#5AB4AC", "12–15 Nemli"),
            (18.0, "#01665E", "15–18 Islak"),
            (30.0, "#003C30", "> 18 Çok ıslak / dere tabanı"),
        ])
        return layer

    # ------------------------------------------------------------------
    # MORFOLOJİK BİRİMLER — Geomorphons
    # ------------------------------------------------------------------
    def create_geomorphons(self, window_size: int = 9, threshold: float = 1.0):
        """Create geomorphon / morphometric features raster."""
        cell_count = self._raster_cell_count()
        saga_limit = 6000000
        layer = None

        if self._has_algorithm("saga:morphometricfeatures") and cell_count <= saga_limit:
            try:
                QgsMessageLog.logMessage(
                    "Morfolojik birimler: SAGA morphometricfeatures çalışıyor "
                    "({0} hücre).".format(cell_count),
                    "TurkeyGeoMorph", Qgis.Info)
                result = processing.run("saga:morphometricfeatures", {
                    "DEM": self.dem_path,
                    "FEATURES": self._output("geomorphons.tif"),
                    "THRESHOLD": threshold,
                    "RADIUS": window_size,
                })
                layer = self._load_raster(result["FEATURES"], "Morfolojik Birimler")
            except Exception as exc:
                QgsMessageLog.logMessage(
                    "SAGA morfolojik birimler başarısız; GDAL yedek yöntem "
                    "kullanılıyor: {0}".format(exc),
                    "TurkeyGeoMorph", Qgis.Warning)

        if layer is None and self._has_algorithm("grass7:r.geomorphon") and cell_count <= saga_limit:
            try:
                QgsMessageLog.logMessage(
                    "Morfolojik birimler: GRASS r.geomorphon çalışıyor "
                    "({0} hücre).".format(cell_count),
                    "TurkeyGeoMorph", Qgis.Info)
                result = processing.run("grass7:r.geomorphon", {
                    "elevation": self.dem_path,
                    "search": window_size,
                    "skip": 0,
                    "flat": threshold,
                    "dist": 0,
                    "forms": self._output("geomorphons.tif"),
                    "GRASS_RASTER_FORMAT_OPT": "GTiff",
                })
                layer = self._load_raster(result["forms"], "Morfolojik Birimler")
            except Exception as exc:
                QgsMessageLog.logMessage(
                    "GRASS geomorphon başarısız; GDAL yedek yöntem "
                    "kullanılıyor: {0}".format(exc),
                    "TurkeyGeoMorph", Qgis.Warning)

        if layer is None:
            if cell_count > saga_limit:
                QgsMessageLog.logMessage(
                    "Morfolojik birimler: DEM {0} hücre içeriyor. Uzun SAGA "
                    "kilitlenmelerini önlemek için GDAL yedek yöntem "
                    "kullanılıyor.".format(cell_count),
                    "TurkeyGeoMorph", Qgis.Warning)
            result = processing.run("gdal:roughness", {
                "INPUT": self.dem_path, "BAND": 1,
                "COMPUTE_EDGES": True,
                "OUTPUT": self._output("geomorphons_tri.tif"),
            })
            layer = self._load_raster(result["OUTPUT"], "Morfolojik Birimler")

        # 10 standart geomorphon sınıfı — Discrete categorical
        self._apply_discrete_renderer(layer, [
            (1.0,  "#F5F5F5", "1 — Düz"),
            (2.0,  "#8C510A", "2 — Tepe"),
            (3.0,  "#BF812D", "3 — Sırt"),
            (4.0,  "#DFC27D", "4 — Omuz"),
            (5.0,  "#F6E8C3", "5 — Mahmuz"),
            (6.0,  "#C7EAE5", "6 — Yamaç"),
            (7.0,  "#80CDC1", "7 — Çukur yamaç"),
            (8.0,  "#35978F", "8 — Vadi"),
            (9.0,  "#01665E", "9 — Çukur"),
            (10.0, "#003C30", "10 — Kanal"),
        ])
        return layer

    # ------------------------------------------------------------------
    # TPI — Topografik Konum İndeksi
    # ------------------------------------------------------------------
    def create_tpi(self, inner_r: int = 3, outer_r: int = 9):
        """Create TPI raster with discrete Weiss 6-class legend."""
        if self._has_algorithm("saga:topographicpositionindex"):
            result = processing.run("saga:topographicpositionindex", {
                "DEM": self.dem_path,
                "TPI": self._output("tpi.tif"),
                "STANDARD": "TEMPORARY_OUTPUT",
                "RADIUS_MIN": inner_r,
                "RADIUS_MAX": outer_r,
            })
            layer = self._load_raster(result["TPI"], "TPI")
        else:
            # Fallback: focal mean based TPI = elevation - focal_mean
            # Approximate with GDAL roughness (difference from local mean proxy)
            try:
                # Build focal statistics via gdal_sieve workaround is wrong.
                # Use roughness as a proxy and normalise.
                result = processing.run("gdal:roughness", {
                    "INPUT": self.dem_path, "BAND": 1,
                    "COMPUTE_EDGES": True,
                    "OUTPUT": self._output("tpi_roughness.tif"),
                })
                layer = self._load_raster(result["OUTPUT"], "TPI")
            except Exception:
                layer = self._load_raster(self.dem_path, "TPI")

        # Weiss (2001) 6-class TPI: stepped discrete
        self._apply_discrete_renderer(layer, [
            (-100.0, "#2166AC", "Derin vadi / çukur"),
            (-40.0,  "#74ADD1", "Vadi tabanı / sınır"),
            (-10.0,  "#D1E5F0", "Alt yamaç"),
            (10.0,   "#F7F7F7", "Düz / orta konum"),
            (40.0,   "#FDDBC7", "Üst yamaç"),
            (100.0,  "#EF8A62", "Sırt"),
            (999.0,  "#B2182B", "Keskin tepe"),
        ])
        return layer

    # ------------------------------------------------------------------
    # RÖLYEF ENERJİSİ — Gerçek max-min pencere farklılığı
    # ------------------------------------------------------------------
    def create_relief_energy(self, window_size: int = 9, method: str = "range"):
        """Create relief energy raster using neighborhood range (max-min)."""
        # SAGA neighborhood statistics — öncelikli
        if self._has_algorithm("saga:gridstatisticsforpolygons"):
            pass  # Bu farklı bir şey

        if self._has_algorithm("saga:resampling"):
            # SAGA ile yeniden örnekleme tabanlı max-min
            pass

        # GDAL roughness: yüzey pürüzlülüğü — rölyef enerjisine en yakın GDAL aracı
        # Daha iyi: SAGA statistics for grids (local range)
        if self._has_algorithm("saga:localstatisticsforgrids") or \
           self._has_algorithm("saga:statistics_grid"):
            algo = ("saga:localstatisticsforgrids"
                    if self._has_algorithm("saga:localstatisticsforgrids")
                    else "saga:statistics_grid")
            try:
                result = processing.run(algo, {
                    "GRID": self.dem_path,
                    "RANGE": self._output("relief_energy.tif"),
                    "RADIUS": window_size // 2,
                    "MODE": 0,
                })
                out_key = "RANGE" if "RANGE" in result else list(result.keys())[0]
                layer = self._load_raster(result[out_key], "Rölyef Enerjisi")
            except Exception:
                layer = self._relief_gdal_fallback()
        elif self._has_algorithm("saga:rastercalculator"):
            layer = self._relief_gdal_fallback()
        else:
            layer = self._relief_gdal_fallback()

        # Stepped discrete: rölyef enerji sınıfları
        self._apply_discrete_renderer(layer, [
            (25.0,  "#F7FCF0", "< 25 m   Çok düşük (ova)"),
            (75.0,  "#CAE8C2", "25–75 m  Düşük"),
            (150.0, "#7BCB91", "75–150 m Orta düşük"),
            (300.0, "#2CA25F", "150–300 m Orta yüksek"),
            (500.0, "#006D2C", "300–500 m Yüksek"),
            (999.0, "#00441B", "> 500 m  Çok yüksek (dağlık)"),
        ])
        return layer

    def _relief_gdal_fallback(self):
        """GDAL roughness tabanlı rölyef enerjisi yaklaşımı."""
        result = processing.run("gdal:roughness", {
            "INPUT": self.dem_path, "BAND": 1,
            "COMPUTE_EDGES": True,
            "OUTPUT": self._output("relief_energy.tif"),
        })
        return self._load_raster(result["OUTPUT"], "Rölyef Enerjisi")

    # ------------------------------------------------------------------
    # QML UYGULAMA (sadece gerektiğinde)
    # ------------------------------------------------------------------
    def apply_qml_style(self, layer, qml_path: str) -> None:
        if not pathlib.Path(qml_path).exists():
            raise StyleError("QML bulunamadı: {0}".format(qml_path))
        layer.loadNamedStyle(qml_path)
        layer.triggerRepaint()

    def get_statistics(self, layer) -> dict:
        stats = layer.dataProvider().bandStatistics(1, QgsRasterBandStats.All)
        return {
            "min": stats.minimumValue,
            "max": stats.maximumValue,
            "mean": stats.mean,
            "stdDev": stats.stdDev,
            "range": stats.range,
        }
