# -*- coding: utf-8 -*-
"""QGIS plugin entry point for TurkeyGeoMorph Analyst."""

from qgis.core import QgsApplication, Qgis
from qgis.utils import iface as qgis_iface


def classFactory(iface):
    """Create the plugin instance for QGIS.

    Args:
        iface: Active QGIS interface object.

    Returns:
        TurkeyGeoMorphPlugin: Initialized plugin object.
    """
    try:
        from osgeo import gdal

        gdal.VersionInfo()
    except ImportError:
        qgis_iface.messageBar().pushMessage(
            "TurkeyGeoMorph",
            "GDAL bulunamadı. QGIS kurulumunu kontrol edin.",
            level=Qgis.Critical,
            duration=8,
        )

    try:
        algorithms = QgsApplication.processingRegistry().algorithms()
        saga_available = any(
            "saga" in algorithm.id().lower() for algorithm in algorithms
        )
        if not saga_available:
            qgis_iface.messageBar().pushMessage(
                "TurkeyGeoMorph",
                "SAGA algoritmaları bulunamadı. TWI, Geomorphons ve TPI "
                "analizlerinde GDAL tabanlı yedek yöntemler kullanılacak.",
                level=Qgis.Warning,
                duration=8,
            )
    except Exception as exc:
        qgis_iface.messageBar().pushMessage(
            "TurkeyGeoMorph",
            "Processing kayıt defteri kontrol edilemedi: {0}".format(exc),
            level=Qgis.Warning,
            duration=8,
        )

    from .plugin_main import TurkeyGeoMorphPlugin

    return TurkeyGeoMorphPlugin(iface)
