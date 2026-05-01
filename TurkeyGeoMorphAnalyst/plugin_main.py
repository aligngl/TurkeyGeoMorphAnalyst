# -*- coding: utf-8 -*-
"""Main QGIS plugin integration for TurkeyGeoMorph Analyst."""

import os
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, QLocale
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction
from qgis.core import QgsMessageLog, Qgis


class TurkeyGeoMorphPlugin:
    """Register TurkeyGeoMorph Analyst actions in QGIS."""

    PLUGIN_NAME = "TurkeyGeoMorph Analyst"
    LOG_TAG = "TurkeyGeoMorph"

    def __init__(self, iface):
        """Initialize plugin state.

        Args:
            iface: Active QGIS interface object.
        """
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.actions = []
        self.menu = self.tr("&TurkeyGeoMorph Analyst")
        self.toolbar = None
        self.dialog = None
        self.locale = QLocale.system().name()

    def tr(self, message: str) -> str:
        """Translate a UI message through Qt translation infrastructure.

        Args:
            message: Source text.

        Returns:
            str: Translated text when a translation is available.
        """
        return QCoreApplication.translate("TurkeyGeoMorphPlugin", message)

    def initGui(self) -> None:
        """Create toolbar and menu entries in QGIS."""
        self.toolbar = self.iface.addToolBar(self.PLUGIN_NAME)
        self.toolbar.setObjectName("TurkeyGeoMorphAnalystToolbar")

        icon_path = self.plugin_dir / "resources" / "icons" / "plugin_icon.png"
        action = QAction(
            QIcon(str(icon_path)),
            self.tr("TurkeyGeoMorph Analyst"),
            self.iface.mainWindow(),
        )
        action.setObjectName("TurkeyGeoMorphAnalystAction")
        action.setWhatsThis(
            self.tr(
                "Türkiye illeri için otomatik jeomorfoloji haritaları üretir."
            )
        )
        action.setStatusTip(
            self.tr("TurkeyGeoMorph Analyst ana penceresini aç")
        )
        action.triggered.connect(self.run)

        self.add_action(action)
        QgsMessageLog.logMessage(
            self.tr("TurkeyGeoMorph Analyst arayüz eylemi yüklendi."),
            self.LOG_TAG,
            Qgis.Info,
        )

    def add_action(self, action: QAction) -> None:
        """Add an existing QAction to the plugin menu and toolbar.

        Args:
            action: QAction instance to register.
        """
        self.iface.addPluginToRasterMenu(self.menu, action)
        if self.toolbar is not None:
            self.toolbar.addAction(action)
        self.actions.append(action)

    def unload(self) -> None:
        """Remove plugin UI entries from QGIS."""
        for action in self.actions:
            self.iface.removePluginRasterMenu(self.menu, action)
            if self.toolbar is not None:
                self.toolbar.removeAction(action)
        self.actions = []

        if self.toolbar is not None:
            del self.toolbar
            self.toolbar = None

        QgsMessageLog.logMessage(
            self.tr("TurkeyGeoMorph Analyst arayüz eylemi kaldırıldı."),
            self.LOG_TAG,
            Qgis.Info,
        )

    def run(self) -> None:
        """Open the main plugin dialog."""
        try:
            from .plugin_dialog import TurkeyGeoMorphDialog
        except ImportError as exc:
            self.iface.messageBar().pushMessage(
                self.tr("TurkeyGeoMorph"),
                self.tr(
                    "Ana diyalog dosyası henüz oluşturulmadı. "
                    "ADIM 2-3 ve ADIM 11 tamamlandıktan sonra arayüz açılır."
                ),
                level=Qgis.Warning,
                duration=8,
            )
            QgsMessageLog.logMessage(
                self.tr("plugin_dialog içe aktarılamadı: {0}").format(exc),
                self.LOG_TAG,
                Qgis.Warning,
            )
            return

        if self.dialog is None:
            self.dialog = TurkeyGeoMorphDialog(self.iface)

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def plugin_path(self, *parts: str) -> str:
        """Build an absolute path inside the plugin directory.

        Args:
            *parts: Path fragments to append to the plugin root.

        Returns:
            str: Absolute path.
        """
        return os.fspath(self.plugin_dir.joinpath(*parts))
