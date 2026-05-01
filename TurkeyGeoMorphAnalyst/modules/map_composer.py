# -*- coding: utf-8 -*-
"""QGIS layout composer helpers."""

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
    """Raised when a layout export fails."""


class MapComposer:
    """Create and export QGIS print layouts."""

    def __init__(self):
        self.project = QgsProject.instance()

    def create_layout(self, name: str, paper_size: str = "A4",
                      orientation: str = "Landscape"):
        manager = self.project.layoutManager()
        old = manager.layoutByName(name)
        if old is not None:
            manager.removeLayout(old)
        layout = QgsPrintLayout(self.project)
        layout.initializeDefaults()
        layout.setName(name)
        page = layout.pageCollection().page(0)
        size = QgsLayoutSize(297, 210, QgsUnitTypes.LayoutMillimeters)
        if paper_size.upper().startswith("A3"):
            size = QgsLayoutSize(420, 297, QgsUnitTypes.LayoutMillimeters)
        if orientation.lower().startswith("portrait"):
            size = QgsLayoutSize(size.height(), size.width(),
                                 QgsUnitTypes.LayoutMillimeters)
        page.setPageSize(size)
        manager.addLayout(layout)
        return layout

    def _page_dimensions(self, layout) -> tuple:
        try:
            page = layout.pageCollection().page(0)
            size = page.pageSize()
            return float(size.width()), float(size.height())
        except Exception:
            return 297.0, 210.0

    def _layout_regions(self, layout, content_aspect: float = None) -> dict:
        """Return layout regions in mm.

        content_aspect: width/height of the geographic extent.  When supplied,
        the map frame height is clipped so it matches the extent aspect ratio,
        eliminating empty white space below the map.

        Layout (A4 Landscape):
        ┌──────────────────────────────────────────────────────────────┐
        │  BAŞLIK  ← harita solundan lejant sağına kadar tam hizalı   │
        ├──────────────────────────────────────┬───────────────────────┤
        │                                      │                       │
        │      HARİTA ÇERÇEVESİ (auto-fit)     │   AÇIKLAMALAR         │
        │                        [Kuzey oku]   │   (lejant)            │
        │  [Ölçek çubuğu — harita içinde]      │                       │
        └──────────────────────────────────────┴───────────────────────┘
        """
        width, height = self._page_dimensions(layout)
        margin    = 8.0
        title_h   = 12.0
        title_gap = 5.0
        sidebar_w = 52.0 if width <= 310 else 64.0
        gap       = 6.0   # harita - sidebar arası (grid annotation için alan)

        map_x = margin
        map_y = margin + title_h + title_gap
        map_w = width - (2 * margin) - sidebar_w - gap

        # Alt kenarda grid anotasyonları ve sayfa nefesi için küçük ama gerçek
        # bir pay bırakılır. Bu, geniş harita çerçevesinin sayfa dışına taşmış
        # gibi görünmesini engeller.
        max_map_h = height - map_y - margin - 7.0
        map_h = max_map_h

        side_x = map_x + map_w + gap
        side_y = map_y
        side_w = sidebar_w
        side_h = map_h

        # Başlık: harita sol ↔ lejant sağ (tam hizalı)
        title_x = margin
        title_y = margin
        title_w = width - 2 * margin

        return {
            "page_w":  width,
            "page_h":  height,
            "margin":  margin,
            "title":   (title_x, title_y, title_w, title_h),
            "map":     (map_x, map_y, map_w, map_h),
            "sidebar": (side_x, side_y, side_w, side_h),
        }

    def _sidebar_regions(self, layout) -> dict:
        """Return right-panel regions for legend, north arrow and scale."""
        regions = self._layout_regions(layout)
        side_x, side_y, side_w, side_h = regions["sidebar"]
        gap = 4.0
        scale_h = 15.0
        arrow_h = 22.0
        legend_h = max(55.0, side_h - scale_h - arrow_h - (2 * gap))
        arrow_y = side_y + legend_h + gap
        scale_y = arrow_y + arrow_h + gap
        return {
            "legend": (side_x, side_y, side_w, legend_h),
            "arrow": (side_x, arrow_y, side_w, arrow_h),
            "scale": (side_x, scale_y, side_w, scale_h),
        }

    def _item_rect(self, item, layout) -> tuple:
        """Return item position and size in layout millimeters."""
        try:
            pos = item.positionWithUnits()
            size = item.sizeWithUnits()
            return (
                float(pos.x()), float(pos.y()),
                float(size.width()), float(size.height()),
            )
        except Exception:
            regions = self._layout_regions(layout)
            return regions["map"]

    # ------------------------------------------------------------------
    # HARİTA ÇERÇEVESİ — extent otomatik doldurma
    # ------------------------------------------------------------------
    def add_map_frame(self, layout, extent, layers: list):
        """Add map frame; auto-fit extent to eliminate white space."""
        # Coğrafi en-boy oranına göre layout bölgelerini hesapla
        content_aspect = None
        fitted_extent = extent
        if extent is not None:
            try:
                geo_w = extent.width()
                geo_h = extent.height()
                if geo_w > 0 and geo_h > 0:
                    content_aspect = geo_w / geo_h
                    # Küçük kenar boşluğu ekle (%3) — veriyi tam sığdır
                    buf = max(geo_w, geo_h) * 0.03
                    fitted_extent = QgsRectangle(
                        extent.xMinimum() - buf * 0.3,
                        extent.yMinimum() - buf * 0.3,
                        extent.xMaximum() + buf * 0.3,
                        extent.yMaximum() + buf * 0.3,
                    )
            except Exception:
                pass

        regions = self._layout_regions(layout, content_aspect)
        map_x, map_y, map_w, map_h = regions["map"]

        item = QgsLayoutItemMap(layout)
        item.setRect(0, 0, map_w, map_h)
        item.attemptMove(QgsLayoutPoint(map_x, map_y,
                                        QgsUnitTypes.LayoutMillimeters))
        item.attemptResize(QgsLayoutSize(map_w, map_h,
                                         QgsUnitTypes.LayoutMillimeters))
        if fitted_extent is not None:
            item.setExtent(fitted_extent)
        if layers:
            item.setLayers(layers)
            if hasattr(item, "setKeepLayerSet"):
                item.setKeepLayerSet(True)
        if hasattr(item, "setFrameEnabled"):
            item.setFrameEnabled(True)
        if hasattr(item, "setFrameStrokeWidth"):
            item.setFrameStrokeWidth(QgsLayoutMeasurement(
                0.4, QgsUnitTypes.LayoutMillimeters))
        if hasattr(item, "setBackgroundEnabled"):
            item.setBackgroundEnabled(True)
        layout.addLayoutItem(item)
        return item

    # ------------------------------------------------------------------
    # BAŞLIK
    # ------------------------------------------------------------------
    def add_title(self, layout, text: str, font_size: int = 16,
                  content_aspect: float = None):
        """Add title bar spanning map-left to legend-right."""
        regions = self._layout_regions(layout, content_aspect)
        title_x, title_y, title_w, title_h = regions["title"]

        shape = QgsLayoutItemShape(layout)
        shape.setShapeType(QgsLayoutItemShape.Rectangle)
        shape.attemptMove(QgsLayoutPoint(title_x, title_y,
                                         QgsUnitTypes.LayoutMillimeters))
        shape.attemptResize(QgsLayoutSize(title_w, title_h,
                                          QgsUnitTypes.LayoutMillimeters))
        fill_sym = QgsFillSymbol.createSimple({
            "color": "25,70,145,255",
            "outline_color": "15,45,100,255",
            "outline_width": "0.3",
        })
        shape.setSymbol(fill_sym)
        layout.addLayoutItem(shape)

        label = QgsLayoutItemLabel(layout)
        label.setText(text)
        font = QFont("Arial", max(10, min(font_size, 15)))
        font.setBold(True)
        label.setFont(font)
        label.setFontColor(QColor(255, 255, 255))
        if hasattr(label, "setHAlign"):
            label.setHAlign(Qt.AlignCenter)
        if hasattr(label, "setVAlign"):
            label.setVAlign(Qt.AlignVCenter)
        label.attemptMove(QgsLayoutPoint(title_x, title_y,
                                         QgsUnitTypes.LayoutMillimeters))
        label.attemptResize(QgsLayoutSize(title_w, title_h,
                                          QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(label)
        return label

    # ------------------------------------------------------------------
    # AÇIKLAMALAR — Lejant (nokta→çizgi→alan→raster sırası)
    # ------------------------------------------------------------------
    def add_legend(self, layout, map_item, layers: list,
                   legend_layers: list = None,
                   content_aspect: float = None):
        """Add legend titled 'Açıklamalar' with point→line→polygon→raster order."""
        regions = self._layout_regions(layout, content_aspect)
        side_x, side_y, side_w, side_h = regions["sidebar"]

        legend = QgsLayoutItemLegend(layout)
        legend.setTitle("Açıklamalar")
        legend.setLinkedMap(map_item)

        # Lejant sadece bu layout'un katmanlarını göstermeli. Bunu proje katman
        # ağacını temizlemeden, ayrı bir QgsLayerTreeGroup ile kuruyoruz.
        if hasattr(legend, "setAutoUpdateModel"):
            legend.setAutoUpdateModel(False)
        if hasattr(legend, "setLegendFilterByMapEnabled"):
            legend.setLegendFilterByMapEnabled(True)
        if hasattr(legend, "setResizeToContents"):
            legend.setResizeToContents(False)
        try:
            custom_root = QgsLayerTreeGroup("Açıklamalar")
            for layer in layers:
                custom_root.addLayer(layer)
            model = legend.model()
            if hasattr(model, "setRootGroup"):
                model.setRootGroup(custom_root)
                legend._turkey_geomorph_legend_root = custom_root
            else:
                QgsMessageLog.logMessage(
                    "Bu QGIS sürümünde lejant kök grubu değiştirilemiyor.",
                    "TurkeyGeoMorph", Qgis.Warning)
        except Exception as exc:
            QgsMessageLog.logMessage(
                "Lejant katmanları sınırlandırılamadı: {0}".format(exc),
                "TurkeyGeoMorph", Qgis.Warning)

        legend.setStyleFont(QgsLegendStyle.Title, QFont("Arial", 9, QFont.Bold))
        legend.setStyleFont(QgsLegendStyle.Group, QFont("Arial", 8, QFont.Bold))
        legend.setStyleFont(QgsLegendStyle.Subgroup,
                            QFont("Arial", 7, QFont.StyleItalic))
        legend.setStyleFont(QgsLegendStyle.SymbolLabel, QFont("Arial", 7))

        try:
            legend.setSymbolWidth(5.5)
            legend.setSymbolHeight(3.5)
        except Exception:
            pass
        try:
            legend.setBoxSpace(1.5)
            legend.setColumnSpace(2.5)
            legend.setSymbolSpace(1.5)
            legend.setIconLabelSpace(1.5)
            legend.setLayerSpace(2.5)
        except Exception:
            pass
        try:
            legend.setBackgroundEnabled(True)
            legend.setBackgroundColor(QColor(255, 255, 255, 245))
        except Exception:
            pass
        if hasattr(legend, "setFrameEnabled"):
            legend.setFrameEnabled(True)
        if hasattr(legend, "setFrameStrokeWidth"):
            legend.setFrameStrokeWidth(QgsLayoutMeasurement(
                0.25, QgsUnitTypes.LayoutMillimeters))

        legend_x, legend_y, legend_w, legend_h = (
            self._sidebar_regions(layout)["legend"]
        )
        legend.attemptMove(QgsLayoutPoint(legend_x, legend_y,
                                          QgsUnitTypes.LayoutMillimeters))
        legend.attemptResize(QgsLayoutSize(legend_w, legend_h,
                                           QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(legend)
        return legend

    # ------------------------------------------------------------------
    # ÖLÇEK ÇUBUĞU — harita çerçevesi SOL ALT (içinde)
    # ------------------------------------------------------------------
    def add_scalebar(self, layout, map_item,
                     content_aspect: float = None):
        """Add scale bar in the right-side layout panel."""
        scale_x, scale_y, scale_w, scale_h = self._sidebar_regions(layout)["scale"]

        bar_w = min(44.0, scale_w - 6.0)
        bar_h = 8.0
        bar_x = scale_x + (scale_w - bar_w) / 2.0
        bar_y = scale_y + 4.0

        bar = QgsLayoutItemScaleBar(layout)
        bar.setStyle("Single Box")
        bar.setLinkedMap(map_item)
        bar.setUnits(QgsUnitTypes.DistanceKilometers)
        bar.setNumberOfSegments(4)
        bar.setNumberOfSegmentsLeft(0)
        bar.setUnitsPerSegment(10)
        bar.setUnitLabel("km")
        bar.setFont(QFont("Arial", 6))
        bar.setHeight(2.5)

        try:
            bar.setFontColor(QColor(20, 20, 20))
            bar.setFillColor(QColor(20, 20, 20))
            bar.setFillColor2(QColor(255, 255, 255))
            bar.setStrokeColor(QColor(20, 20, 20))
            bar.setStrokeWidth(QgsLayoutMeasurement(
                0.2, QgsUnitTypes.LayoutMillimeters))
        except Exception:
            pass
        try:
            bar.setBackgroundEnabled(True)
            bar.setBackgroundColor(QColor(255, 255, 255, 200))
        except Exception:
            pass

        bar.update()
        bar.attemptMove(QgsLayoutPoint(bar_x, bar_y,
                                       QgsUnitTypes.LayoutMillimeters))
        bar.attemptResize(QgsLayoutSize(bar_w, bar_h,
                                        QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(bar)
        return bar

    # ------------------------------------------------------------------
    # KUZEY OKU — harita çerçevesi sağ üst köşe (içinde)
    # ------------------------------------------------------------------
    def add_north_arrow(self, layout, map_item=None,
                        content_aspect: float = None):
        arrow_region = self._sidebar_regions(layout)["arrow"]
        arrow_panel_x, arrow_panel_y, arrow_panel_w, arrow_panel_h = arrow_region

        arrow_size = 17.0
        arrow_x = arrow_panel_x + (arrow_panel_w - arrow_size) / 2.0
        arrow_y = arrow_panel_y + (arrow_panel_h - arrow_size) / 2.0

        bg_size = arrow_size + 3.0
        shape = QgsLayoutItemShape(layout)
        shape.setShapeType(QgsLayoutItemShape.Rectangle)
        shape.attemptMove(QgsLayoutPoint(arrow_x - 1.5, arrow_y - 1.5,
                                         QgsUnitTypes.LayoutMillimeters))
        shape.attemptResize(QgsLayoutSize(bg_size, bg_size,
                                          QgsUnitTypes.LayoutMillimeters))
        bg_sym = QgsFillSymbol.createSimple({
            "color": "255,255,255,180",
            "outline_color": "160,160,160,160",
            "outline_width": "0.15",
        })
        shape.setSymbol(bg_sym)
        layout.addLayoutItem(shape)

        arrow = QgsLayoutItemPicture(layout)
        candidates = []
        bundled = (pathlib.Path(__file__).resolve().parents[1]
                   / "resources" / "icons" / "north_arrow.svg")
        if bundled.exists():
            candidates.append(bundled)
        try:
            for root in [pathlib.Path(p) for p in QgsApplication.svgPaths()]:
                if root.exists():
                    for pat in ("*NorthArrow*.svg", "*north_arrow*.svg",
                                "*north*.svg"):
                        candidates.extend(root.rglob(pat))
        except Exception:
            pass

        if candidates:
            arrow.setPicturePath(os.fspath(candidates[0]))
        arrow.attemptMove(QgsLayoutPoint(arrow_x, arrow_y,
                                         QgsUnitTypes.LayoutMillimeters))
        arrow.attemptResize(QgsLayoutSize(arrow_size, arrow_size,
                                          QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(arrow)

        if not candidates:
            lbl = QgsLayoutItemLabel(layout)
            lbl.setText("N\n↑")
            lbl.setFont(QFont("Arial", 7, QFont.Bold))
            lbl.setFontColor(QColor(30, 30, 30))
            if hasattr(lbl, "setHAlign"):
                lbl.setHAlign(Qt.AlignCenter)
            lbl.attemptMove(QgsLayoutPoint(arrow_x, arrow_y,
                                            QgsUnitTypes.LayoutMillimeters))
            lbl.attemptResize(QgsLayoutSize(arrow_size, arrow_size,
                                             QgsUnitTypes.LayoutMillimeters))
            layout.addLayoutItem(lbl)
        return arrow

    # ------------------------------------------------------------------
    # BİLGİ KUTUSU
    # ------------------------------------------------------------------
    def add_info_box(self, layout, province: str = "", district: str = "",
                     data_source: str = "",
                     content_aspect: float = None) -> None:
        regions = self._layout_regions(layout, content_aspect)
        side_x, side_y, side_w, side_h = regions["sidebar"]

        legend_h = side_h * 0.88
        info_y = side_y + legend_h + 3.0
        info_h = side_h - legend_h - 3.0
        if info_h < 10.0:
            return

        lines = []
        if province:
            lines.append("İl: {}".format(province))
        if district:
            lines.append("İlçe: {}".format(district))
        if data_source:
            lines.append("Kaynak: {}".format(data_source))
        lines.append("Koordinat Sistemi: WGS 84")
        lines.append("Projeksiyon: Coğrafi")

        label = QgsLayoutItemLabel(layout)
        label.setText("\n".join(lines))
        label.setFont(QFont("Arial", 6))
        label.setFontColor(QColor(50, 50, 50))
        if hasattr(label, "setHAlign"):
            label.setHAlign(Qt.AlignLeft)
        if hasattr(label, "setVAlign"):
            label.setVAlign(Qt.AlignTop)
        if hasattr(label, "setMargin"):
            label.setMargin(1.5)
        try:
            label.setBackgroundEnabled(True)
            label.setBackgroundColor(QColor(245, 245, 245, 230))
        except Exception:
            pass
        if hasattr(label, "setFrameEnabled"):
            label.setFrameEnabled(True)

        label.attemptMove(QgsLayoutPoint(side_x, info_y,
                                         QgsUnitTypes.LayoutMillimeters))
        label.attemptResize(QgsLayoutSize(side_w, info_h,
                                          QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(label)

    # ------------------------------------------------------------------
    # KOORDİNAT IZGARASI
    # ------------------------------------------------------------------
    def add_grid(self, layout, map_item, crs,
                 interval: float = 0.25,
                 content_aspect: float = None) -> None:
        grid = map_item.grid()
        grid.setEnabled(True)
        grid.setIntervalX(interval)
        grid.setIntervalY(interval)
        grid.setAnnotationEnabled(True)
        grid.setCrs(crs)
        grid.setFrameStyle(QgsLayoutItemMapGrid.NoFrame)
        try:
            grid.setAnnotationFont(QFont("Arial", 5))
            grid.setAnnotationFrameDistance(1.0)
            grid.setGridLineWidth(0.10)
            grid.setGridLineColor(QColor(80, 80, 80, 120))
        except Exception:
            pass
        # Annotasyonları harita çerçevesi içine al (üst + sağ taraf)
        try:
            for side in (QgsLayoutItemMapGrid.Right,
                         QgsLayoutItemMapGrid.Top):
                grid.setAnnotationPosition(
                    QgsLayoutItemMapGrid.InsideMapFrame, side)
        except Exception:
            pass
        map_item.update()

    # ------------------------------------------------------------------
    # DIŞA AKTARMA
    # ------------------------------------------------------------------
    def export_to_pdf(self, layout, path: str, dpi: int = 300) -> bool:
        exporter = QgsLayoutExporter(layout)
        s = QgsLayoutExporter.PdfExportSettings()
        s.dpi = dpi
        return exporter.exportToPdf(path, s) == QgsLayoutExporter.Success

    def export_to_png(self, layout, path: str, dpi: int = 300) -> bool:
        exporter = QgsLayoutExporter(layout)
        s = QgsLayoutExporter.ImageExportSettings()
        s.dpi = dpi
        return exporter.exportToImage(path, s) == QgsLayoutExporter.Success

    def export_to_svg(self, layout, path: str) -> bool:
        exporter = QgsLayoutExporter(layout)
        s = QgsLayoutExporter.SvgExportSettings()
        return exporter.exportToSvg(path, s) == QgsLayoutExporter.Success

    def export_to_tiff(self, layout, path: str, dpi: int = 300) -> bool:
        return self.export_to_png(layout, path, dpi)
