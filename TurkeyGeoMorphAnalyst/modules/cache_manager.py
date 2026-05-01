# -*- coding: utf-8 -*-
"""Persistent cache management for clipped DEM and river datasets."""

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


class CacheError(Exception):
    """Raised when cache operations fail."""


class CacheManager:
    """Store and retrieve clipped DEM and river outputs by area/source key."""

    def __init__(self, cache_root: str, ttl_days: int = 30):
        """Initialize cache manager.

        Args:
            cache_root: Root cache directory.
            ttl_days: Number of days before cached files expire.
        """
        self.cache_root = pathlib.Path(cache_root)
        self.ttl_days = max(1, int(ttl_days or 30))
        self.cache_root.mkdir(parents=True, exist_ok=True)
        (self.cache_root / "dem").mkdir(exist_ok=True)
        (self.cache_root / "rivers").mkdir(exist_ok=True)

    def _safe(self, value: str) -> str:
        """Return a filesystem-safe key fragment."""
        text = str(value or "").strip()
        chars = []
        for char in text:
            if char.isalnum():
                chars.append(char)
            else:
                chars.append("_")
        safe = "_".join("".join(chars).split("_"))
        return safe[:160] or "empty"

    def _file_stamp(self, path: str) -> str:
        """Return a stable source stamp for local files."""
        if not path:
            return "none"
        file_path = pathlib.Path(path)
        if not file_path.exists():
            return self._safe(file_path.name)
        stat = file_path.stat()
        return self._safe(
            "{0}_{1}_{2}".format(file_path.name, stat.st_size, int(stat.st_mtime))
        )

    def _area_key(self, settings: dict) -> str:
        """Return selected area key."""
        parts = [
            settings.get("boundary_type", "province"),
            settings.get("province", ""),
        ]
        if settings.get("boundary_type") == "district":
            parts.append(settings.get("district", ""))
        return self._safe("_".join(parts))

    def dem_key(self, settings: dict) -> str:
        """Return DEM cache key."""
        source = settings.get("dem_source", "")
        parts = [self._area_key(settings), source]
        if source == "local":
            parts.append(self._file_stamp(settings.get("local_dem_path", "")))
        if source == "tandemx":
            parts.append(self._file_stamp(settings.get("tandemx_path", "")))
        return self._safe("_".join(parts))

    def rivers_key(self, settings: dict) -> str:
        """Return river cache key."""
        filters = "_".join(settings.get("river_types", []))
        return self._safe("{0}_rivers_{1}".format(self._area_key(settings), filters))

    def _is_valid(self, path: pathlib.Path) -> bool:
        """Return True when a cached file exists and is not expired."""
        if not path.exists() or path.stat().st_size == 0:
            return False
        now = QDateTime.currentSecsSinceEpoch()
        age_seconds = now - int(path.stat().st_mtime)
        return age_seconds <= self.ttl_days * 24 * 60 * 60

    def _metadata_path(self, data_path: pathlib.Path) -> pathlib.Path:
        """Return sidecar metadata path."""
        return data_path.with_suffix(data_path.suffix + ".json")

    def _write_metadata(self, data_path: pathlib.Path, settings: dict,
                        kind: str) -> None:
        """Write cache metadata."""
        metadata = {
            "kind": kind,
            "created": QDateTime.currentDateTimeUtc().toString(Qt.ISODate),
            "ttl_days": self.ttl_days,
            "province": settings.get("province", ""),
            "district": settings.get("district", ""),
            "boundary_type": settings.get("boundary_type", ""),
            "dem_source": settings.get("dem_source", ""),
            "river_types": settings.get("river_types", []),
        }
        with open(os.fspath(self._metadata_path(data_path)), "w",
                  encoding="utf-8") as output_file:
            json.dump(metadata, output_file, ensure_ascii=False, indent=2)

    def get_dem(self, settings: dict) -> str:
        """Return cached clipped DEM path, or empty string."""
        path = self.cache_root / "dem" / "{0}.tif".format(self.dem_key(settings))
        return os.fspath(path) if self._is_valid(path) else ""

    def store_dem(self, source_path: str, settings: dict) -> str:
        """Copy clipped DEM into cache and return cache path."""
        target = self.cache_root / "dem" / "{0}.tif".format(self.dem_key(settings))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, os.fspath(target))
        self._write_metadata(target, settings, "dem")
        return os.fspath(target)

    def get_rivers(self, settings: dict) -> str:
        """Return cached clipped river GeoPackage path, or empty string."""
        path = self.cache_root / "rivers" / "{0}.gpkg".format(
            self.rivers_key(settings)
        )
        return os.fspath(path) if self._is_valid(path) else ""

    def store_rivers(self, source_path: str, settings: dict) -> str:
        """Copy clipped river data into cache and return cache path."""
        target = self.cache_root / "rivers" / "{0}.gpkg".format(
            self.rivers_key(settings)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, os.fspath(target))
        self._write_metadata(target, settings, "rivers")
        return os.fspath(target)

    def clean_expired(self) -> int:
        """Delete expired cached files.

        Returns:
            int: Number of removed files.
        """
        removed = 0
        for path in self.cache_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".json":
                continue
            if not self._is_valid(path):
                metadata = self._metadata_path(path)
                try:
                    path.unlink()
                    removed += 1
                except Exception:
                    pass
                if metadata.exists():
                    try:
                        metadata.unlink()
                    except Exception:
                        pass
        return removed

    def clear_all(self) -> None:
        """Remove the whole cache tree."""
        if self.cache_root.exists():
            shutil.rmtree(os.fspath(self.cache_root), ignore_errors=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        (self.cache_root / "dem").mkdir(exist_ok=True)
        (self.cache_root / "rivers").mkdir(exist_ok=True)
