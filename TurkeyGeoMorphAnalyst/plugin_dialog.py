# -*- coding: utf-8 -*-
"""Main dialog and worker thread for TurkeyGeoMorph Analyst."""

import os
import pathlib
import shutil
import tempfile

from PyQt5.QtCore import QCoreApplication, QSettings, QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QTableWidgetItem,
)
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsApplication,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsWkbTypes,
    Qgis,
)
from osgeo import gdal

from .ui.main_dialog_base import Ui_TurkeyGeoMorphDialog
from .modules.data_downloader import DEMDownloader, OSMRiverDownloader, ProvinceManager
from .modules.cache_manager import CacheManager
from .modules.dem_processor import DEMProcessor
from .modules.export_manager import ExportManager
from .modules.map_composer import MapComposer
from .modules.morphometric_analysis import MorphometricAnalyst


class OperationCanceled(Exception):
    """Raised when the user requests worker cancellation."""


class WorkerThread(QThread):
    """Run long-running downloads and raster processing in the background."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    canceled = pyqtSignal(str)

    def __init__(self, settings: dict, parent=None):
        """Initialize worker with immutable settings."""
        super().__init__(parent)
        self.settings = settings

    def _check_cancel(self) -> None:
        """Stop execution when cancellation was requested."""
        if self.isInterruptionRequested():
            raise OperationCanceled("İşlem kullanıcı tarafından durduruldu.")

    def run(self):
        """Execute data download and map production."""
        try:
            results = {
                "layers": [],
                "rasters": {},
                "vectors": {},
                "statistics": {},
                "messages": [],
                "selected_maps": self.settings["maps"],
            }
            self.status.emit("İl sınırı yükleniyor...")
            self.progress.emit(5)
            manager = ProvinceManager(self.settings["province_geojson"])
            if self.settings.get("boundary_type") == "district":
                boundary = manager.get_district_boundary(
                    self.settings["province"],
                    self.settings.get("district", ""),
                )
            else:
                boundary = manager.get_province_boundary(self.settings["province"])
            if boundary is None:
                raise RuntimeError("Seçilen çalışma alanı sınırı bulunamadı.")
            results["boundary"] = boundary
            self._check_cancel()

            output_dir = pathlib.Path(self.settings["output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            raw_dir = output_dir / "raw"
            processed_dir = output_dir / "processed"
            maps_dir = output_dir / "maps"
            raw_dir.mkdir(exist_ok=True)
            processed_dir.mkdir(exist_ok=True)
            maps_dir.mkdir(exist_ok=True)
            cache_manager = CacheManager(
                self.settings["cache_dir"],
                self.settings.get("cache_ttl_days", 30),
            )
            removed_cache = cache_manager.clean_expired()
            if removed_cache:
                self.status.emit(
                    "Süresi dolan {0} önbellek dosyası temizlendi.".format(
                        removed_cache
                    )
                )

            self.status.emit("DEM indiriliyor veya hazırlanıyor...")
            self.progress.emit(15)
            downloader = DEMDownloader(None, os.fspath(raw_dir))
            bbox = boundary.extent()
            source = self.settings["dem_source"]
            dem_path = ""
            if self.settings.get("use_cache", True):
                dem_path = cache_manager.get_dem(self.settings)
            if dem_path:
                self.status.emit("DEM önbellekten yükleniyor...")
            else:
                self._check_cancel()
                if source == "copernicus":
                    dem_path = downloader.download_copernicus(bbox)
                elif source == "opentopography_30":
                    dem_path = downloader.download_opentopography(
                        bbox,
                        self.settings.get("opentopo_key", ""),
                        "COP30",
                    )
                elif source == "opentopography_90":
                    dem_path = downloader.download_opentopography(
                        bbox,
                        self.settings.get("opentopo_key", ""),
                        "SRTMGL3",
                    )
                elif source == "tandemx":
                    dem_path = downloader.load_local_dem(
                        self.settings.get("tandemx_path", "")
                    )
                else:
                    dem_path = downloader.load_local_dem(
                        self.settings.get("local_dem_path", "")
                    )
                self._check_cancel()
                dem_path = downloader.reproject_if_needed(dem_path, 4326)
                self._check_cancel()
                dem_path = downloader.clip_to_boundary(dem_path, boundary)
                if self.settings.get("use_cache", True):
                    dem_path = cache_manager.store_dem(dem_path, self.settings)
            results["dem"] = dem_path
            # Ham DEM sadece işlem/statistik kaynağıdır. Görünür katman listesine
            # eklenirse seçilen yükselti haritasıyla ikinci bir yükselti katmanı
            # gibi görünür ve layout lejantını da kirletir.

            self.status.emit("Akarsu verisi işleniyor...")
            self.progress.emit(25)
            if self.settings.get("download_rivers", False):
                river_downloader = OSMRiverDownloader(os.fspath(raw_dir))
                river_types = self.settings.get(
                    "river_types",
                    ["river", "stream", "canal", "drain", "tidal_channel"],
                )
                rivers = ""
                if self.settings.get("use_cache", True):
                    rivers = cache_manager.get_rivers(self.settings)
                if rivers:
                    self.status.emit("Akarsu verisi önbellekten yükleniyor...")
                else:
                    self._check_cancel()
                    try:
                        rivers = river_downloader.query_overpass(
                            self.settings["province"], river_types, boundary
                        )
                    except Exception as exc:
                        QgsMessageLog.logMessage(
                            "Overpass başarısız, Geofabrik deneniyor: {0}".format(exc),
                            "TurkeyGeoMorph",
                            Qgis.Warning,
                        )
                        self._check_cancel()
                        pbf = river_downloader.download_osm_pbf(os.fspath(raw_dir))
                        self._check_cancel()
                        rivers = river_downloader.extract_rivers_gdal(
                            pbf, boundary, river_types
                        )
                    if self.settings.get("use_cache", True):
                        rivers = cache_manager.store_rivers(rivers, self.settings)
                results["vectors"]["rivers"] = rivers
                results["layers"].append(("vector", "Akarsular", rivers))
            elif self.settings["maps"].get("rivers", False):
                raise RuntimeError(
                    "Akarsu Ağı haritası seçildi. Lütfen Veri İndirme "
                    "sekmesinde akarsu verisini indirmeyi etkinleştirin."
                )

            processor = DEMProcessor(dem_path, os.fspath(processed_dir))
            steps = [
                ("elevation", "Yükselti haritası hazırlanıyor..."),
                ("hillshade", "Gölgelendirme haritası hazırlanıyor..."),
                ("slope", "Eğim haritası hazırlanıyor..."),
                ("aspect", "Bakı haritası hazırlanıyor..."),
                ("curvature", "Eğrisellik haritası hazırlanıyor..."),
                ("twi", "TWI hazırlanıyor..."),
                ("geomorphons", "Morfolojik birimler hazırlanıyor..."),
                ("tpi", "TPI hazırlanıyor..."),
                ("relief", "Rölyef enerjisi hazırlanıyor..."),
            ]
            for index, item in enumerate(steps):
                key, message = item
                if not self.settings["maps"].get(key, False):
                    continue
                self._check_cancel()
                self.status.emit(message)
                self.progress.emit(30 + int(index * 6))
                layer = self._run_map_step(processor, key)
                self._check_cancel()
                results["rasters"][key] = layer.source()
                results["statistics"][self._map_display_name_static(key)] = (
                    processor.get_statistics(layer)
                )
                results["layers"].append(("raster", layer.name(), layer.source()))

            self.status.emit("İstatistikler hesaplanıyor...")
            self.progress.emit(92)
            dem_layer = QgsRasterLayer(dem_path, "DEM")
            if dem_layer.isValid():
                results["statistics"]["DEM"] = processor.get_statistics(dem_layer)
                morph = MorphometricAnalyst()
                results["statistics"]["Hipsometrik integral"] = (
                    morph.hypsometric_integral(dem_layer)
                )

            self.status.emit("Bitti")
            self.progress.emit(100)
            self.finished.emit(results)
        except OperationCanceled as exc:
            self.status.emit(str(exc))
            self.canceled.emit(str(exc))
        except Exception as exc:
            QgsMessageLog.logMessage(
                "WorkerThread hatası: {0}".format(exc),
                "TurkeyGeoMorph",
                Qgis.Critical,
            )
            self.error.emit(str(exc))

    def _run_map_step(self, processor, key: str):
        """Execute a selected map-processing step."""
        if key == "elevation":
            return processor.create_elevation_map()
        if key == "hillshade":
            return processor.create_hillshade(
                self.settings.get("hillshade_azimuth", 315),
                self.settings.get("hillshade_altitude", 45),
                self.settings.get("hillshade_z", 1.0),
                self.settings.get("hillshade_multi", False),
            )
        if key == "slope":
            unit = "degree" if self.settings.get("slope_degree", True) else "percent"
            return processor.create_slope(
                unit, self.settings.get("slope_algorithm", "Horn")
            )
        if key == "aspect":
            return processor.create_aspect(8)
        if key == "curvature":
            return processor.create_curvature("total")
        if key == "twi":
            return processor.create_twi()
        if key == "geomorphons":
            return processor.create_geomorphons()
        if key == "tpi":
            return processor.create_tpi()
        if key == "relief":
            return processor.create_relief_energy()
        raise RuntimeError("Bilinmeyen harita adımı: {0}".format(key))

    def _map_display_name_static(self, key: str) -> str:
        """Return Turkish display name usable inside the worker thread."""
        names = {
            "elevation": "Yükselti",
            "hillshade": "Gölgelendirme",
            "slope": "Eğim",
            "aspect": "Bakı",
            "curvature": "Eğrisellik",
            "twi": "TWI",
            "geomorphons": "Morfolojik Birimler",
            "tpi": "TPI",
            "relief": "Rölyef Enerjisi",
        }
        return names.get(key, key)


class TurkeyGeoMorphDialog(QDialog, Ui_TurkeyGeoMorphDialog):
    """Main plugin dialog."""

    def __init__(self, iface, parent=None):
        """Initialize dialog and connect UI events."""
        super().__init__(parent)
        self.iface = iface
        self.plugin_dir = pathlib.Path(__file__).resolve().parent
        self.worker = None
        self.current_boundary = None
        self.last_results = {}
        self.province_manager = None
        self.generated_layouts = []
        self.setupUi(self)
        self._load_provinces()
        self._connect_signals()
        self._load_persistent_settings()
        self._update_credentials_panel()

    def tr(self, message: str) -> str:
        """Translate UI strings."""
        return QCoreApplication.translate("TurkeyGeoMorphDialog", message)

    def _connect_signals(self) -> None:
        """Connect widget signals."""
        self.btnBrowseOutput.clicked.connect(self._browse_output)
        self.btnShowBoundary.clicked.connect(self._show_boundary)
        self.btnDownloadData.clicked.connect(self._start_worker)
        self.btnStopWorker.clicked.connect(self._stop_worker)
        self.btnClearCache.clicked.connect(self._clear_cache)
        self.btnGenerateAllMaps.clicked.connect(self._export_maps)
        self.btnExportReport.clicked.connect(self._export_report)
        self.btnValidateOpenTopo.clicked.connect(self._validate_opentopo)
        self.fileLocalDem.fileChanged.connect(self._update_local_dem_info)
        self.fileTandemx.fileChanged.connect(self._update_local_dem_info)
        self.cmbProvince.currentTextChanged.connect(self._load_districts)
        for button in self.demSourceButtons.buttons():
            button.toggled.connect(self._update_credentials_panel)
        self.dialHillshadeAzimuth.valueChanged.connect(
            self.spinHillshadeAzimuth.setValue
        )
        self.spinHillshadeAzimuth.valueChanged.connect(
            self.dialHillshadeAzimuth.setValue
        )

    def _load_provinces(self) -> None:
        """Load embedded province names into the combo box."""
        path = self.plugin_dir / "data" / "turkey_provinces.geojson"
        self.province_manager = ProvinceManager(os.fspath(path))
        names = self.province_manager.get_province_list()
        self.cmbProvince.clear()
        self.cmbProvince.addItems(names)
        if "Ankara" in names:
            self.cmbProvince.setCurrentText("Ankara")
        self._load_districts(self.cmbProvince.currentText())
        self.lineOutputFolder.setText(os.fspath(pathlib.Path.home() / "TurkeyGeoMorph_Output"))

    def _load_districts(self, province_name: str) -> None:
        """Fill district combo from embedded GADM Level 2 data."""
        self.cmbDistrict.clear()
        if self.province_manager is None or not province_name:
            return
        districts = self.province_manager.get_districts(province_name)
        self.cmbDistrict.addItems(districts)

    def _browse_output(self) -> None:
        """Choose output folder."""
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Çıktı klasörü seç"), self.lineOutputFolder.text()
        )
        if folder:
            self.lineOutputFolder.setText(folder)
            self._save_persistent_settings()

    def _settings(self):
        """Return plugin QSettings namespace."""
        return QSettings("TurkeyGeoMorph", "TurkeyGeoMorphAnalyst")

    def _default_cache_dir(self) -> str:
        """Return the default persistent cache directory."""
        return os.fspath(
            pathlib.Path(QgsApplication.qgisSettingsDirPath())
            / "TurkeyGeoMorphAnalyst"
            / "cache"
        )

    def _load_persistent_settings(self) -> None:
        """Load saved API key and user paths."""
        settings = self._settings()
        self.lineOpenTopoKey.setText(settings.value("opentopo_key", "", type=str))
        output_dir = settings.value("output_dir", "", type=str)
        if output_dir:
            self.lineOutputFolder.setText(output_dir)
        province = settings.value("province", "", type=str)
        if province:
            index = self.cmbProvince.findText(province)
            if index >= 0:
                self.cmbProvince.setCurrentIndex(index)
        local_dem = settings.value("local_dem_path", "", type=str)
        tandemx = settings.value("tandemx_path", "", type=str)
        if local_dem and hasattr(self.fileLocalDem, "setFilePath"):
            self.fileLocalDem.setFilePath(local_dem)
        if tandemx and hasattr(self.fileTandemx, "setFilePath"):
            self.fileTandemx.setFilePath(tandemx)
        self.checkUseCache.setChecked(
            settings.value("use_cache", True, type=bool)
        )
        self.spinCacheDays.setValue(
            int(settings.value("cache_ttl_days", 30, type=int))
        )

    def _save_persistent_settings(self) -> None:
        """Persist API key and reusable file paths."""
        settings = self._settings()
        settings.setValue("opentopo_key", self.lineOpenTopoKey.text())
        settings.setValue("output_dir", self.lineOutputFolder.text())
        settings.setValue("province", self.cmbProvince.currentText())
        settings.setValue("local_dem_path", self.fileLocalDem.filePath())
        settings.setValue("tandemx_path", self.fileTandemx.filePath())
        settings.setValue("use_cache", self.checkUseCache.isChecked())
        settings.setValue("cache_ttl_days", self.spinCacheDays.value())
        settings.sync()

    def _selected_dem_source(self) -> str:
        """Return selected DEM source key."""
        mapping = [
            (self.radioCopernicus, "copernicus"),
            (self.radioOpenTopo30, "opentopography_30"),
            (self.radioOpenTopo90, "opentopography_90"),
            (self.radioTandemx, "tandemx"),
            (self.radioLocalDem, "local"),
        ]
        for button, key in mapping:
            if button.isChecked():
                return key
        return "copernicus"

    def _river_types(self) -> list:
        """Return selected OSM river filters."""
        text = self.cmbRiverFilter.currentText()
        if text == "river+stream":
            return ["river", "stream"]
        if text == "Yalnızca river":
            return ["river"]
        if text == "Kanal ve drenaj dahil":
            return ["river", "stream", "canal", "drain"]
        return ["river", "stream", "canal", "drain", "tidal_channel"]

    def _collect_settings(self) -> dict:
        """Collect UI settings for WorkerThread."""
        return {
            "province_geojson": os.fspath(
                self.plugin_dir / "data" / "turkey_provinces.geojson"
            ),
            "province": self.cmbProvince.currentText(),
            "district": self.cmbDistrict.currentText(),
            "boundary_type": (
                "district" if self.radioDistrictBoundary.isChecked()
                else "manual" if self.radioManualBoundary.isChecked()
                else "province"
            ),
            "output_dir": self.lineOutputFolder.text(),
            "project_name": self.lineProjectName.text() or "jeomorfoloji_analizi",
            "dem_source": self._selected_dem_source(),
            "opentopo_key": self.lineOpenTopoKey.text(),
            "tandemx_path": self.fileTandemx.filePath(),
            "local_dem_path": self.fileLocalDem.filePath(),
            "use_cache": self.checkUseCache.isChecked(),
            "cache_ttl_days": self.spinCacheDays.value(),
            "cache_dir": self._default_cache_dir(),
            "download_rivers": self.checkDownloadRivers.isChecked(),
            "river_types": self._river_types(),
            "maps": {
                "elevation": self.checkElevationMap.isChecked(),
                "hillshade": self.checkHillshadeMap.isChecked(),
                "slope": self.checkSlopeMap.isChecked(),
                "aspect": self.checkAspectMap.isChecked(),
                "curvature": self.checkCurvatureMap.isChecked(),
                "twi": self.checkTwiMap.isChecked(),
                "rivers": self.checkRiversMap.isChecked(),
                "geomorphons": self.checkGeomorphonsMap.isChecked(),
                "tpi": self.checkTpiMap.isChecked(),
                "relief": self.checkReliefMap.isChecked(),
            },
            "hillshade_azimuth": self.spinHillshadeAzimuth.value(),
            "hillshade_altitude": self.spinHillshadeAltitude.value(),
            "hillshade_z": self.spinHillshadeZ.value(),
            "hillshade_multi": self.checkMultidirectionalHillshade.isChecked(),
            "slope_degree": self.radioSlopeDegree.isChecked(),
            "slope_algorithm": self.cmbSlopeAlgorithm.currentText(),
        }

    def _show_boundary(self) -> None:
        """Show selected province boundary in QGIS and preview canvas."""
        manager = ProvinceManager(os.fspath(
            self.plugin_dir / "data" / "turkey_provinces.geojson"
        ))
        if self.radioDistrictBoundary.isChecked():
            boundary = manager.get_district_boundary(
                self.cmbProvince.currentText(),
                self.cmbDistrict.currentText(),
            )
        else:
            boundary = manager.get_province_boundary(self.cmbProvince.currentText())
        if boundary is None:
            QMessageBox.warning(self, self.tr("TurkeyGeoMorph"), self.tr("Sınır bulunamadı."))
            return
        self.current_boundary = boundary
        QgsProject.instance().addMapLayer(boundary)
        self.mapCanvas.setLayers([boundary])
        self.mapCanvas.setExtent(boundary.extent())
        self.mapCanvas.refresh()

    def _start_worker(self) -> None:
        """Start background data and map production."""
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, self.tr("TurkeyGeoMorph"), self.tr("Bir işlem zaten çalışıyor."))
            return
        settings = self._collect_settings()
        self._save_persistent_settings()
        if not any(settings["maps"].values()):
            QMessageBox.warning(
                self,
                self.tr("TurkeyGeoMorph"),
                self.tr("Lütfen Harita Üretimi sekmesinden en az bir harita seçin."),
            )
            return
        if settings["boundary_type"] == "district" and not settings["district"]:
            QMessageBox.warning(
                self,
                self.tr("TurkeyGeoMorph"),
                self.tr("İlçe sınırı için önce bir ilçe seçin."),
            )
            return
        if settings["dem_source"].startswith("opentopography") and not settings["opentopo_key"]:
            QMessageBox.warning(
                self,
                self.tr("TurkeyGeoMorph"),
                self.tr("OpenTopography için API key gerekli."),
            )
            return
        if settings["dem_source"] == "local" and not settings["local_dem_path"]:
            QMessageBox.warning(
                self,
                self.tr("TurkeyGeoMorph"),
                self.tr("Yerel DEM dosyası seçilmedi."),
            )
            return
        if settings["dem_source"] == "tandemx" and not settings["tandemx_path"]:
            QMessageBox.warning(
                self,
                self.tr("TurkeyGeoMorph"),
                self.tr("TanDEM-X için manuel indirilen DEM dosyası seçilmedi."),
            )
            return
        pathlib.Path(settings["output_dir"]).mkdir(parents=True, exist_ok=True)
        self.textLog.clear()
        self.downloadProgress.setValue(0)
        self.exportProgress.setValue(0)
        self.worker = WorkerThread(settings, self)
        self.worker.progress.connect(self._set_progress)
        self.worker.status.connect(self._set_status)
        self.worker.finished.connect(self._worker_finished)
        self.worker.error.connect(self._worker_error)
        self.worker.canceled.connect(self._worker_canceled)
        self.btnDownloadData.setEnabled(False)
        self.btnStopWorker.setEnabled(True)
        self.worker.start()

    def _stop_worker(self) -> None:
        """Request cancellation for the active worker."""
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.btnStopWorker.setEnabled(False)
            self._set_status(
                self.tr("Durdurma isteği alındı; aktif işlem güvenli noktada duracak.")
            )

    def _set_progress(self, value: int) -> None:
        """Update progress bars."""
        self.downloadProgress.setValue(value)
        self.exportProgress.setValue(value)

    def _set_status(self, message: str) -> None:
        """Update status labels and log."""
        self.labelDownloadStatus.setText(message)
        self.textLog.append(message)
        QgsMessageLog.logMessage(message, "TurkeyGeoMorph", Qgis.Info)

    def _worker_finished(self, results: dict) -> None:
        """Handle worker results in the main thread."""
        self.last_results = results
        layers = []
        layers_by_source = {}
        for layer_type, name, source in results.get("layers", []):
            if layer_type == "raster":
                layer = QgsRasterLayer(
                    source, self._layer_name_for_source(source, name, results)
                )
            else:
                layer = QgsVectorLayer(
                    source, self._layer_name_for_source(source, name, results), "ogr"
                )
            if layer.isValid():
                layer.setCustomProperty("TurkeyGeoMorph/generated", True)
                self._apply_layer_style(layer, source, results)
                QgsProject.instance().addMapLayer(layer)
                layers.append(layer)
                layers_by_source[source] = layer
        boundary = results.get("boundary")
        if boundary is not None and boundary.isValid():
            boundary.setCustomProperty("TurkeyGeoMorph/generated", True)
            self._style_boundary_layer(boundary)
            QgsProject.instance().addMapLayer(boundary)
            layers.append(boundary)
        if layers:
            ordered_layers = self._ordered_layers_for_map(layers)
            self._reorder_project_layers(ordered_layers)
            self.mapCanvas.setLayers(ordered_layers)
            self.mapCanvas.setExtent(layers[-1].extent())
            self.mapCanvas.refresh()
        self._populate_statistics(results.get("statistics", {}))
        self._populate_export_preview(results)
        self._create_editable_layouts(results, layers_by_source)
        self.btnDownloadData.setEnabled(True)
        self.btnStopWorker.setEnabled(False)
        self._set_status(self.tr("İşlem tamamlandı."))

    def _worker_error(self, message: str) -> None:
        """Show worker error."""
        self.btnDownloadData.setEnabled(True)
        self.btnStopWorker.setEnabled(False)
        self._set_status(self.tr("Hata: {0}").format(message))
        QMessageBox.critical(self, self.tr("TurkeyGeoMorph"), message)

    def _worker_canceled(self, message: str) -> None:
        """Handle a user-canceled worker."""
        self.btnDownloadData.setEnabled(True)
        self.btnStopWorker.setEnabled(False)
        self._set_status(message)

    def _populate_statistics(self, stats: dict) -> None:
        """Fill statistics table."""
        rows = []
        for key, value in stats.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    rows.append(("{0}.{1}".format(key, sub_key), sub_value))
            else:
                rows.append((key, value))
        self.tableStatistics.setRowCount(len(rows))
        for row, item in enumerate(rows):
            self.tableStatistics.setItem(row, 0, QTableWidgetItem(str(item[0])))
            self.tableStatistics.setItem(row, 1, QTableWidgetItem(str(item[1])))

    def _populate_export_preview(self, results: dict) -> None:
        """Populate tree preview with generated layers."""
        self.treeExportFiles.clear()
        raster_root = self._tree_item("Raster verileri", "Klasör", "Hazır")
        vector_root = self._tree_item("Vektör verileri", "Klasör", "Hazır")
        layout_root = self._tree_item("QGIS layoutları", "Klasör", "Hazır")
        for key, path in results.get("rasters", {}).items():
            raster_root.addChild(self._tree_item(path, "GeoTIFF", self._file_size_text(path)))
        for key, path in results.get("vectors", {}).items():
            vector_root.addChild(self._tree_item(path, "GeoPackage", self._file_size_text(path)))
        for layout in getattr(self, "generated_layouts", []):
            layout_root.addChild(self._tree_item(layout.name(), "QGIS Layout", "Düzenlenebilir"))
        for root in [raster_root, vector_root, layout_root]:
            if root.childCount() > 0:
                self.treeExportFiles.addTopLevelItem(root)
                root.setExpanded(True)
        if hasattr(self, "textExportInfo"):
            self.textExportInfo.setPlainText(
                self.tr(
                    "Dışa aktarma önizlemesi hazır.\n"
                    "- Layout çıktıları PDF/PNG/SVG olarak kaydedilebilir.\n"
                    "- Raster katmanları GeoTIFF klasörüne kopyalanabilir.\n"
                    "- Akarsu ve sınır gibi vektör verileri ayrı klasörde tutulabilir.\n"
                    "- Manifest ve ZIP seçiliyse teslim paketi otomatik hazırlanır."
                )
            )

    def _tree_item(self, path: str, fmt: str, status: str = ""):
        """Create a QTreeWidgetItem without importing the class globally."""
        from PyQt5.QtWidgets import QTreeWidgetItem

        return QTreeWidgetItem([path, fmt, status])

    def _file_size_text(self, path: str) -> str:
        """Return readable file size for preview rows."""
        try:
            size_mb = pathlib.Path(path).stat().st_size / (1024.0 * 1024.0)
            return "{0:.1f} MB".format(size_mb)
        except Exception:
            return "Hazır"

    def _apply_layer_style(self, layer, source: str, results: dict) -> None:
        """Apply stable QML style to a newly loaded layer."""
        styles = {
            "elevation": "elevation.qml",
            "hillshade": "hillshade.qml",
            "slope": "slope.qml",
            "aspect": "aspect.qml",
            "curvature": "curvature.qml",
            "twi": "twi.qml",
            "geomorphons": "geomorphons.qml",
            "tpi": "tpi.qml",
            "relief": "relief_energy.qml",
        }
        style_name = None
        for key, raster_path in results.get("rasters", {}).items():
            if raster_path == source:
                style_name = styles.get(key)
                break
        if results.get("vectors", {}).get("rivers") == source:
            self._style_river_layer(layer)
            return
        if not style_name:
            return
        style_path = self.plugin_dir / "resources" / "styles" / style_name
        if style_path.exists():
            layer.loadNamedStyle(os.fspath(style_path))
            layer.triggerRepaint()

    def _map_display_name(self, key: str) -> str:
        """Return Turkish display name for a map key."""
        names = {
            "elevation": "Yükselti",
            "hillshade": "Gölgelendirme",
            "slope": "Eğim",
            "aspect": "Bakı",
            "curvature": "Eğrisellik",
            "twi": "TWI",
            "geomorphons": "Morfolojik Birimler",
            "tpi": "TPI",
            "relief": "Rölyef Enerjisi",
        }
        return names.get(key, key)

    def _layer_name_for_source(self, source: str, default_name: str,
                               results: dict) -> str:
        """Return final Turkish layer name for layer tree and legend."""
        for key, raster_path in results.get("rasters", {}).items():
            if raster_path == source:
                return self._map_display_name(key)
        if results.get("vectors", {}).get("rivers") == source:
            return "Akarsular"
        return default_name

    def _layout_title(self, map_name: str) -> str:
        """Build a formal thesis-map title."""
        province = self.cmbProvince.currentText()
        if self.radioDistrictBoundary.isChecked() and self.cmbDistrict.currentText():
            area = "{0} İLİ {1} İLÇESİ".format(
                province.upper(), self.cmbDistrict.currentText().upper()
            )
        else:
            area = "{0} İLİ".format(province.upper())
        return "{0} {1} HARİTASI".format(area, map_name.upper())

    def _ordered_layers_for_map(self, layers: list) -> list:
        """Return layers in QGIS top-to-bottom draw order.

        Katman çizim sırası (listenin başı en üstte çizilir):
          0 — Nokta katmanları      (en üstte)
          1 — Çizgi katmanları     (akarsu, yollar)
          2 — Poligon katmanları   (sınır, havza)
          3 — Raster katmanları    (DEM ürünleri, en altta)

        Bu sıralama akarsuların her zaman raster üzerinde görünmesini sağlar.
        """
        def priority(layer):
            if isinstance(layer, QgsRasterLayer):
                return 3
            if isinstance(layer, QgsVectorLayer):
                geom = layer.geometryType()
                if geom == QgsWkbTypes.LineGeometry:
                    return 1   # akarsu — poligon sınırın üzerinde
                if geom == QgsWkbTypes.PolygonGeometry:
                    return 2
                if geom == QgsWkbTypes.PointGeometry:
                    return 0
            return 4
        return sorted(layers, key=priority)

    def _reorder_project_layers(self, ordered_layers: list) -> None:
        """Keep QGIS Layers panel in point-line-polygon-raster order."""
        root = QgsProject.instance().layerTreeRoot()
        for index, layer in enumerate(ordered_layers):
            node = root.findLayer(layer.id())
            if node is None:
                continue
            parent = node.parent()
            if parent is None:
                continue
            try:
                clone = node.clone()
                root.insertChildNode(index, clone)
                parent.removeChildNode(node)
            except Exception as exc:
                QgsMessageLog.logMessage(
                    "Katman sırası düzenlenemedi: {0}".format(exc),
                    "TurkeyGeoMorph",
                    Qgis.Warning,
                )

    def _legend_layers_for_map(self, map_key: str, layout_layers: list) -> list:
        """Return clean legend layers for a given map type."""
        legend_layers = []
        for layer in layout_layers:
            if map_key == "hillshade" and isinstance(layer, QgsRasterLayer):
                continue
            legend_layers.append(layer)
        return legend_layers

    def _style_boundary_layer(self, layer) -> None:
        """Apply a clean thesis-map boundary outline."""
        if not isinstance(layer, QgsVectorLayer):
            return
        layer.setName("Çalışma Alanı Sınırı")
        symbol = QgsFillSymbol.createSimple({
            "color": "255,255,255,0",
            "outline_color": "30,30,30,255",
            "outline_width": "0.35",
            "outline_width_unit": "MM",
        })
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()

    def _style_river_layer(self, layer) -> None:
        """Apply thesis-map river symbology with Turkish legend labels."""
        if not isinstance(layer, QgsVectorLayer):
            return
        layer.setName("Akarsular")
        specs = [
            ("river", "Nehir", "#0072CE", 0.72, "solid"),
            ("stream", "Dere", "#2CA6E0", 0.34, "solid"),
            ("canal", "Kanal", "#008C8C", 0.48, "dash"),
            ("drain", "Drenaj kanalı", "#7CB7D8", 0.22, "dot"),
            ("tidal_channel", "Gelgit kanalı", "#004C99", 0.42, "dash"),
        ]
        categories = []
        for value, label, color, width, line_style in specs:
            symbol = QgsLineSymbol.createSimple({
                "line_color": color,
                "line_width": str(width),
                "line_width_unit": "MM",
                "line_style": line_style,
                "capstyle": "round",
                "joinstyle": "round",
            })
            categories.append(QgsRendererCategory(value, symbol, label))
        renderer = QgsCategorizedSymbolRenderer("waterway", categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def _create_editable_layouts(self, results: dict, layers_by_source: dict) -> None:
        """Create one editable QGIS layout for every selected/generated map.

        Legend behaviour
        ----------------
        * Legend is linked directly to the map frame item (no hidden map).
        * ``setAutoUpdateModel(True)`` is active: any layer the user adds to
          the QGIS project later (basemaps, extra vectors, …) appears in the
          legend automatically.
        * ``legend_layers`` is no longer passed to ``add_legend`` — the old
          approach used a hidden off-page proxy map which broke QGIS' own
          legend rendering and prevented newly-added layers from showing.
        """
        self.generated_layouts = []
        composer = MapComposer()
        boundary = results.get("boundary")
        river_path = results.get("vectors", {}).get("rivers")
        river_layer = layers_by_source.get(river_path)
        province = self.cmbProvince.currentText()
        district = (
            self.cmbDistrict.currentText()
            if self.radioDistrictBoundary.isChecked()
            else ""
        )
        dem_source_label = {
            "copernicus": "Copernicus DEM",
            "opentopography_30": "OpenTopography COP30",
            "opentopography_90": "OpenTopography SRTMGL3",
            "tandemx": "TanDEM-X",
            "local": "Yerel DEM",
        }.get(results.get("dem_source", ""), "DEM")

        if boundary is not None and boundary.isValid():
            self._style_boundary_layer(boundary)

        for key, source in results.get("rasters", {}).items():
            raster_layer = layers_by_source.get(source)
            if raster_layer is None or not raster_layer.isValid():
                continue
            title = self._layout_title(self._map_display_name(key))
            layout_name = "{0} {1} Haritası".format(
                province, self._map_display_name(key)
            )
            layout = composer.create_layout(layout_name, "A4", "Landscape")
            if hasattr(layout, "setCustomProperty"):
                layout.setCustomProperty("TurkeyGeoMorph/generated", True)

            composer.add_title(layout, title, 16)

            # Harita katman yığını: raster + akarsu (varsa) + sınır (varsa)
            layout_layers = [raster_layer]
            if river_layer is not None and river_layer.isValid():
                layout_layers.append(river_layer)
            if boundary is not None and boundary.isValid():
                layout_layers.append(boundary)
            layout_layers = self._ordered_layers_for_map(layout_layers)

            extent = (
                boundary.extent() if boundary is not None
                else raster_layer.extent()
            )
            map_item = composer.add_map_frame(layout, extent, layout_layers)

            # Lejant: doğrudan map_item'a bağlı, otomatik güncellenen QGIS lejantı
            composer.add_legend(layout, map_item, layout_layers)

            # Koordinat ızgarası
            if self.checkGrid.isChecked():
                composer.add_grid(layout, map_item, raster_layer.crs(), 0.25)

            # Ölçek çubuğu — harita sol alt köşe
            if self.checkScaleBar.isChecked():
                composer.add_scalebar(layout, map_item)

            # Kuzey oku — harita sağ üst köşe
            if self.checkNorthArrow.isChecked():
                composer.add_north_arrow(layout, map_item)

            self.generated_layouts.append(layout)
            self.treeExportFiles.addTopLevelItem(
                self._tree_item(layout.name(), "QGIS Layout")
            )

        # Akarsu ağı haritası
        selected = results.get("selected_maps", {})
        if selected.get("rivers") and river_layer is not None and river_layer.isValid():
            title = self._layout_title("Akarsu Ağı")
            layout = composer.create_layout(
                "{0} Akarsu Ağı Haritası".format(province),
                "A4",
                "Landscape",
            )
            if hasattr(layout, "setCustomProperty"):
                layout.setCustomProperty("TurkeyGeoMorph/generated", True)

            composer.add_title(layout, title, 16)

            layout_layers = [river_layer]
            if boundary is not None and boundary.isValid():
                layout_layers.append(boundary)
            layout_layers = self._ordered_layers_for_map(layout_layers)

            extent = (
                boundary.extent() if boundary is not None
                else river_layer.extent()
            )
            map_item = composer.add_map_frame(layout, extent, layout_layers)

            # Lejant: doğrudan map_item'a bağlı
            composer.add_legend(layout, map_item, layout_layers)

            if self.checkGrid.isChecked():
                composer.add_grid(layout, map_item, river_layer.crs(), 0.25)
            if self.checkScaleBar.isChecked():
                composer.add_scalebar(layout, map_item)
            if self.checkNorthArrow.isChecked():
                composer.add_north_arrow(layout, map_item)

            self.generated_layouts.append(layout)
            self.treeExportFiles.addTopLevelItem(
                self._tree_item(layout.name(), "QGIS Layout")
            )

    def _export_maps(self) -> None:
        """Export layouts, data layers, project files and delivery package."""
        if not self.last_results:
            QMessageBox.information(self, self.tr("TurkeyGeoMorph"), self.tr("Önce veri ve haritaları üretin."))
            return
        self.btnGenerateAllMaps.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        export_manager = ExportManager()
        try:
            prefix = self.lineExportPrefix.text().strip() if hasattr(self, "lineExportPrefix") else ""
            if not prefix:
                prefix = self.lineProjectName.text() or "turkey_geomorph"
            safe_prefix = export_manager.safe_name(prefix)
            output_dir = pathlib.Path(self.lineOutputFolder.text()) / "exports" / safe_prefix
            output_dir.mkdir(parents=True, exist_ok=True)
            layout_dir = output_dir / "01_layout_haritalar"
            raster_dir = output_dir / "02_raster_geotiff"
            vector_dir = output_dir / "03_vektor_veriler"
            project_dir = output_dir / "04_qgis_proje"
            report_dir = output_dir / "05_rapor_istatistik"
            for folder in [layout_dir, raster_dir, vector_dir, project_dir, report_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            formats = []
            if self.checkPdf.isChecked():
                formats.append("pdf")
            if self.checkPng.isChecked():
                formats.append("png")
            if self.checkSvg.isChecked():
                formats.append("svg")
            dpi = int(self.cmbPngDpi.currentText()) if hasattr(self, "cmbPngDpi") else 150
            if not self.generated_layouts and formats:
                QMessageBox.information(
                    self,
                    self.tr("TurkeyGeoMorph"),
                    self.tr("Dışa aktarılacak layout yok. Önce seçili haritaları üretin."),
                )
                return

            self.exportProgress.setValue(5)
            QApplication.processEvents()
            results = {}
            if formats:
                results.update(export_manager.batch_export(
                    self.generated_layouts,
                    formats,
                    os.fspath(layout_dir),
                    safe_prefix,
                    dpi,
                ))
            self.exportProgress.setValue(35)
            QApplication.processEvents()

            if self.checkQgisProject.isChecked():
                project_path = project_dir / "{0}.qgz".format(safe_prefix)
                try:
                    results[os.fspath(project_path)] = export_manager.save_qgis_project(
                        os.fspath(project_path)
                    )
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        "QGIS projesi kaydedilemedi: {0}".format(exc),
                        "TurkeyGeoMorph", Qgis.Warning)
                    results[os.fspath(project_path)] = False
            self.exportProgress.setValue(45)
            QApplication.processEvents()

            if self.checkGeotiff.isChecked():
                for key, source in self.last_results.get("rasters", {}).items():
                    target = raster_dir / "{0}_{1}.tif".format(safe_prefix, key)
                    try:
                        shutil.copy2(source, os.fspath(target))
                        results[os.fspath(target)] = True
                    except Exception as exc:
                        QgsMessageLog.logMessage(
                            "GeoTIFF kopyalanamadı ({0}): {1}".format(source, exc),
                            "TurkeyGeoMorph", Qgis.Warning)
                        results[os.fspath(target)] = False
                    QApplication.processEvents()
                dem_source = self.last_results.get("dem")
                if dem_source:
                    target = raster_dir / "{0}_dem_kirilmis.tif".format(safe_prefix)
                    try:
                        shutil.copy2(dem_source, os.fspath(target))
                        results[os.fspath(target)] = True
                    except Exception as exc:
                        QgsMessageLog.logMessage(
                            "Kırpılmış DEM kopyalanamadı: {0}".format(exc),
                            "TurkeyGeoMorph", Qgis.Warning)
                        results[os.fspath(target)] = False
            self.exportProgress.setValue(65)
            QApplication.processEvents()

            if hasattr(self, "checkExportVectors") and self.checkExportVectors.isChecked():
                for key, source in self.last_results.get("vectors", {}).items():
                    suffix = pathlib.Path(source).suffix or ".gpkg"
                    target = vector_dir / "{0}_{1}{2}".format(safe_prefix, key, suffix)
                    try:
                        shutil.copy2(source, os.fspath(target))
                        results[os.fspath(target)] = True
                    except Exception as exc:
                        QgsMessageLog.logMessage(
                            "Vektör veri kopyalanamadı ({0}): {1}".format(source, exc),
                            "TurkeyGeoMorph", Qgis.Warning)
                        results[os.fspath(target)] = False
                    QApplication.processEvents()
                boundary = self.last_results.get("boundary")
                if boundary is not None and boundary.isValid():
                    boundary_path = vector_dir / "{0}_calisma_alani.gpkg".format(safe_prefix)
                    results[os.fspath(boundary_path)] = self._export_boundary_layer(
                        boundary, boundary_path
                    )
            self.exportProgress.setValue(78)
            QApplication.processEvents()

            stats = self._statistics_from_table()
            if stats:
                csv_path = report_dir / "{0}_istatistik.csv".format(safe_prefix)
                html_path = report_dir / "{0}_rapor.html".format(safe_prefix)
                try:
                    export_manager.export_statistics_csv(stats, os.fspath(csv_path))
                    results[os.fspath(csv_path)] = True
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        "CSV rapor yazılamadı: {0}".format(exc),
                        "TurkeyGeoMorph", Qgis.Warning)
                    results[os.fspath(csv_path)] = False
                try:
                    export_manager.export_statistics_html(
                        stats,
                        os.fspath(html_path),
                        "TurkeyGeoMorph Analiz Raporu",
                        self.textInterpretation.toPlainText(),
                    )
                    results[os.fspath(html_path)] = True
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        "HTML rapor yazılamadı: {0}".format(exc),
                        "TurkeyGeoMorph", Qgis.Warning)
                    results[os.fspath(html_path)] = False
            self.exportProgress.setValue(88)
            QApplication.processEvents()

            records = self._manifest_records(results)
            if hasattr(self, "checkCreateManifest") and self.checkCreateManifest.isChecked():
                manifest_path = output_dir / "manifest.csv"
                try:
                    export_manager.write_manifest_csv(records, os.fspath(manifest_path))
                    results[os.fspath(manifest_path)] = True
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        "Manifest yazılamadı: {0}".format(exc),
                        "TurkeyGeoMorph", Qgis.Warning)
                    results[os.fspath(manifest_path)] = False
            try:
                log_path = output_dir / "export_log.txt"
                export_manager.create_summary_log(results, os.fspath(log_path))
                results[os.fspath(log_path)] = True
            except Exception as exc:
                QgsMessageLog.logMessage(
                    "Export log yazılamadı: {0}".format(exc),
                    "TurkeyGeoMorph", Qgis.Warning)
            QApplication.processEvents()
            if hasattr(self, "checkCreateArchive") and self.checkCreateArchive.isChecked():
                zip_path = output_dir.parent / "{0}_teslim_paketi.zip".format(safe_prefix)
                try:
                    export_manager.create_zip_package(os.fspath(output_dir), os.fspath(zip_path))
                    results[os.fspath(zip_path)] = True
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        "ZIP paketi oluşturulamadı: {0}".format(exc),
                        "TurkeyGeoMorph", Qgis.Warning)
                    results[os.fspath(zip_path)] = False
            self.exportProgress.setValue(100)
            self._show_export_results(results, output_dir)
            self._set_status(self.tr("Dışa aktarma tamamlandı: {0}").format(output_dir))
        except Exception as exc:
            QgsMessageLog.logMessage(
                "Dışa aktarma genel hatası: {0}".format(exc),
                "TurkeyGeoMorph", Qgis.Critical)
            QMessageBox.critical(self, self.tr("TurkeyGeoMorph"), str(exc))
        finally:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self.btnGenerateAllMaps.setEnabled(True)
            QApplication.processEvents()

    def _export_boundary_layer(self, boundary, boundary_path: pathlib.Path) -> bool:
        """Export boundary layer with QGIS 3.x compatible writer calls."""
        try:
            if hasattr(QgsVectorFileWriter, "writeAsVectorFormatV3"):
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.fileEncoding = "utf-8"
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    boundary,
                    os.fspath(boundary_path),
                    QgsProject.instance().transformContext(),
                    options,
                )
                if isinstance(result, tuple):
                    return result[0] == QgsVectorFileWriter.NoError
                return boundary_path.exists()
            QgsVectorFileWriter.writeAsVectorFormat(
                boundary,
                os.fspath(boundary_path),
                "utf-8",
                boundary.crs(),
                "GPKG",
            )
            return boundary_path.exists()
        except Exception as exc:
            QgsMessageLog.logMessage(
                "Çalışma alanı sınırı dışa aktarılamadı: {0}".format(exc),
                "TurkeyGeoMorph", Qgis.Warning)
            return False

    def _statistics_from_table(self) -> dict:
        """Return current statistics table as a dictionary."""
        stats = {}
        for row in range(self.tableStatistics.rowCount()):
            key_item = self.tableStatistics.item(row, 0)
            value_item = self.tableStatistics.item(row, 1)
            if key_item and value_item:
                stats[key_item.text()] = value_item.text()
        return stats

    def _manifest_records(self, results: dict) -> list:
        """Build export manifest records from result paths."""
        records = []
        for path, ok in results.items():
            file_path = pathlib.Path(path)
            size_mb = 0.0
            if file_path.exists() and file_path.is_file():
                size_mb = file_path.stat().st_size / (1024.0 * 1024.0)
            records.append({
                "path": os.fspath(file_path),
                "type": file_path.suffix.lower().lstrip(".") or "folder",
                "status": "OK" if ok else "FAILED",
                "size_mb": "{0:.2f}".format(size_mb),
            })
        return records

    def _show_export_results(self, results: dict, output_dir: pathlib.Path) -> None:
        """Update export preview and log after export."""
        self.treeExportFiles.clear()
        ok_root = self._tree_item("Başarılı çıktılar", "Sonuç", "")
        fail_root = self._tree_item("Başarısız çıktılar", "Sonuç", "")
        lines = ["Dışa aktarma klasörü: {0}".format(output_dir), ""]
        for path, ok in sorted(results.items()):
            status = "OK" if ok else "Hata"
            item = self._tree_item(path, pathlib.Path(path).suffix or "çıktı", status)
            if ok:
                ok_root.addChild(item)
            else:
                fail_root.addChild(item)
            lines.append("[{0}] {1}".format(status, path))
        for root in [ok_root, fail_root]:
            if root.childCount() > 0:
                self.treeExportFiles.addTopLevelItem(root)
                root.setExpanded(True)
        if hasattr(self, "textExportInfo"):
            self.textExportInfo.setPlainText("\n".join(lines))

    def _export_report(self) -> None:
        """Export table statistics to CSV and HTML."""
        try:
            output_dir = pathlib.Path(self.lineOutputFolder.text()) / "reports"
            output_dir.mkdir(parents=True, exist_ok=True)
            stats = self._statistics_from_table()
            if not stats:
                QMessageBox.information(
                    self,
                    self.tr("TurkeyGeoMorph"),
                    self.tr("Rapor için önce harita/istatistik üretin."),
                )
                return
            manager = ExportManager()
            manager.export_statistics_csv(
                stats, os.fspath(output_dir / "statistics.csv"))
            interpretation = self._build_interpretation(stats)
            self.textInterpretation.setPlainText(interpretation)
            manager.export_statistics_html(
                stats,
                os.fspath(output_dir / "statistics.html"),
                "TurkeyGeoMorph İstatistik ve Yorum Raporu",
                interpretation,
            )
            with open(output_dir / "yorum_metni.txt", "w",
                      encoding="utf-8") as output_file:
                output_file.write(interpretation)
            self._set_status(
                self.tr("Rapor dışa aktarıldı: {0}").format(output_dir))
        except Exception as exc:
            QgsMessageLog.logMessage(
                "Rapor dışa aktarma hatası: {0}".format(exc),
                "TurkeyGeoMorph", Qgis.Critical)
            QMessageBox.critical(self, self.tr("TurkeyGeoMorph"), str(exc))

    def _build_interpretation(self, stats: dict) -> str:
        """Build a practical thesis-style geomorphology interpretation."""
        province = self.cmbProvince.currentText()
        district = self.cmbDistrict.currentText() if self.radioDistrictBoundary.isChecked() else ""
        area = "{0} ili {1} ilçesi".format(province, district) if district else "{0} ili".format(province)
        lines = [
            "{0} için üretilen jeomorfometrik çıktılar; yükselti, eğim, bakı, "
            "rölyef enerjisi ve drenaj göstergelerinin birlikte yorumlanmasına "
            "olanak verir.".format(area),
            "",
        ]
        dem_min = stats.get("DEM.min")
        dem_max = stats.get("DEM.max")
        dem_mean = stats.get("DEM.mean")
        if dem_min and dem_max:
            lines.append(
                "Yükselti aralığı {0} m ile {1} m arasında değişmektedir. "
                "Ortalama yükselti {2} m düzeyindedir; bu değer çalışma "
                "alanının genel morfografik seviyesini temsil eder.".format(
                    self._fmt_number(dem_min), self._fmt_number(dem_max),
                    self._fmt_number(dem_mean) if dem_mean else "-"
                )
            )
        hi = stats.get("Hipsometrik integral")
        if hi:
            try:
                hi_value = float(hi)
                if hi_value >= 0.60:
                    comment = "genç ve tektonik/erozyonal olarak daha diri bir topoğrafyaya"
                elif hi_value <= 0.35:
                    comment = "olgunlaşmış aşınım yüzeylerine ve daha düşük rölyef kontrastına"
                else:
                    comment = "orta evrede parçalanmış bir topoğrafik gelişime"
                lines.append(
                    "Hipsometrik integral yaklaşık {0:.2f} olup {1} işaret eder.".format(
                        hi_value, comment
                    )
                )
            except Exception:
                pass
        slope_mean = stats.get("Eğim.mean")
        if slope_mean:
            try:
                slope_value = float(slope_mean)
                if slope_value < 5:
                    slope_comment = "genel olarak düşük eğimli yüzeylerin baskın olduğunu"
                elif slope_value < 15:
                    slope_comment = "orta eğimli yamaçların çalışma alanında önemli yer tuttuğunu"
                else:
                    slope_comment = "dik yamaçların ve parçalanmış topoğrafyanın belirgin olduğunu"
                lines.append(
                    "Ortalama eğim yaklaşık {0:.1f}° olup {1} göstermektedir.".format(
                        slope_value, slope_comment
                    )
                )
            except Exception:
                pass
        relief_mean = stats.get("Rölyef Enerjisi.mean")
        if relief_mean:
            try:
                relief_value = float(relief_mean)
                lines.append(
                    "Rölyef enerjisi ortalaması {0:.1f} düzeyindedir. Bu değer "
                    "yerel yükselti farklarının ve topoğrafik parçalanmanın "
                    "karşılaştırmalı değerlendirilmesinde kullanılmalıdır.".format(relief_value)
                )
            except Exception:
                pass
        twi_mean = stats.get("TWI.mean")
        if twi_mean:
            try:
                twi_value = float(twi_mean)
                lines.append(
                    "TWI ortalaması {0:.1f} olup nem birikimi potansiyelinin "
                    "vadi tabanları, düşük eğimli yüzeyler ve akarsu ağı ile "
                    "birlikte yorumlanması gerekir.".format(twi_value)
                )
            except Exception:
                pass
        lines.extend([
            "",
            "Eğim haritası, yerleşme/ulaşım uygunluğu ve kütle hareketi "
            "duyarlılığı için temel katmandır. Bakı haritası güneşlenme, "
            "nemlilik ve bitki örtüsü farklılaşmalarını yorumlamak için "
            "kullanılmalıdır.",
            "",
            "TWI ve akarsu ağı birlikte değerlendirildiğinde taban suyu "
            "birikimi, vadi tabanları ve drenaj yoğunluğu hakkında daha "
            "güvenilir yorum yapılabilir. Rölyef enerjisi yüksek alanlar "
            "aşınım süreçlerinin güçlü olduğu kesimler olarak ele alınmalıdır.",
            "",
            "Rapor kullanım notu: Bu otomatik yorum ön değerlendirme niteliğindedir. "
            "Tez metninde arazi gözlemleri, litoloji, fay hatları, drenaj düzeni "
            "ve arazi kullanımı bilgileriyle birlikte değerlendirilmelidir.",
        ])
        return "\n".join(lines)

    def _fmt_number(self, value: str) -> str:
        """Format a numeric string for report prose."""
        try:
            return "{0:.1f}".format(float(value))
        except Exception:
            return str(value)

    def _validate_opentopo(self) -> None:
        """Validate OpenTopography key presence."""
        ok = bool(self.lineOpenTopoKey.text().strip())
        QMessageBox.information(
            self,
            self.tr("OpenTopography"),
            self.tr("API key girildi.") if ok else self.tr("API key boş."),
        )
        if ok:
            self._save_persistent_settings()

    def _update_credentials_panel(self) -> None:
        """Update credential help text according to selected source."""
        source = self._selected_dem_source()
        text = {
            "copernicus": "Kimlik bilgisi gerekmez; doğrudan indirilir.",
            "opentopography_30": '<a href="https://portal.opentopography.org/requestApiKey">OpenTopography API key alın</a> — 30m COP30 indirir.',
            "opentopography_90": '<a href="https://portal.opentopography.org/requestApiKey">OpenTopography API key alın</a> — 90m SRTMGL3 indirir.',
            "tandemx": '<a href="https://eoportal.org/web/eoportal/satellite-missions/t/tandem-x">DLR Eoportal: eoportal.org</a>',
            "local": "Yerel DEM dosyasını seçin.",
        }.get(source, "")
        self.labelCredentialInfo.setText(text)

    def _clear_cache(self) -> None:
        """Clear generated layers, layouts and plugin output files.

        DEM and river data caches (``cache/dem`` and ``cache/rivers``) are
        intentionally preserved — they are large downloads that may take a
        long time to re-acquire.  Only ephemeral processing outputs
        (processed, maps, exports, reports) and the QGIS layer/layout
        objects produced by this plugin are removed.
        """
        reply = QMessageBox.question(
            self,
            self.tr("Önbelleği Temizle"),
            self.tr(
                "Üretilmiş katmanlar, layoutlar ve işlenmiş çıktılar temizlenecek.\n"
                "DEM ve akarsu önbellekleri (büyük veri dosyaları) korunacak.\n"
                "API key ve dosya yolu ayarları da korunacak.\n\n"
                "Devam edilsin mi?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # ── QGIS Katmanları ──────────────────────────────────────────
        project = QgsProject.instance()
        remove_ids = [
            layer_id
            for layer_id, layer in project.mapLayers().items()
            if layer.customProperty("TurkeyGeoMorph/generated", False)
        ]
        if remove_ids:
            project.removeMapLayers(remove_ids)

        # ── QGIS Layoutları ─────────────────────────────────────────
        manager = project.layoutManager()
        for layout in list(manager.layouts()):
            name = layout.name()
            if (
                layout in self.generated_layouts
                or (
                    hasattr(layout, "customProperty")
                    and layout.customProperty("TurkeyGeoMorph/generated", False)
                )
                or " Haritası" in name
                or name.startswith(self.lineProjectName.text())
            ):
                manager.removeLayout(layout)
        self.generated_layouts = []
        self.last_results = {}

        # ── UI Temizlik ──────────────────────────────────────────────
        self.treeExportFiles.clear()
        self.tableStatistics.setRowCount(0)
        self.textLog.clear()
        self.downloadProgress.setValue(0)
        self.exportProgress.setValue(0)

        # ── Çıktı Klasörleri (işlenmiş veriler) ─────────────────────
        # DEM ve akarsu önbellekleri (cache/dem, cache/rivers) korunuyor.
        output_dir = pathlib.Path(self.lineOutputFolder.text())
        for child_name in ["raw", "processed", "maps", "exports", "reports"]:
            child = output_dir / child_name
            if child.exists() and child.is_dir():
                shutil.rmtree(os.fspath(child), ignore_errors=True)

        # NOT: CacheManager.clear_all() çağrılmıyor —
        # DEM ve akarsu önbellekleri kasıtlı olarak korunuyor.

        self.mapCanvas.setLayers([])
        self.mapCanvas.refresh()
        self._set_status(self.tr(
            "Önbellek temizlendi. DEM ve akarsu verileri korundu."
        ))

    def _update_local_dem_info(self, file_path: str) -> None:
        """Display CRS, resolution and size for a selected DEM."""
        self._save_persistent_settings()
        if not file_path:
            return
        dataset = gdal.Open(file_path)
        if dataset is None:
            self.labelLocalDemInfo.setText(self.tr("DEM açılamadı."))
            return
        transform = dataset.GetGeoTransform()
        projection = dataset.GetProjection()
        size_mb = pathlib.Path(file_path).stat().st_size / (1024.0 * 1024.0)
        self.labelLocalDemInfo.setText(
            self.tr("Boyut: {0:.1f} MB | Piksel: {1} x {2} | Çözünürlük: {3:.6f}, {4:.6f} | CRS: {5}").format(
                size_mb,
                dataset.RasterXSize,
                dataset.RasterYSize,
                transform[1],
                abs(transform[5]),
                projection[:80] if projection else "Bilinmiyor",
            )
        )
        dataset = None

    def closeEvent(self, event) -> None:
        """Persist reusable settings when the dialog closes."""
        self._save_persistent_settings()
        super().closeEvent(event)
