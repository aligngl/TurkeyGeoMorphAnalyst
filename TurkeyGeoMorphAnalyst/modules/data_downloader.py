# -*- coding: utf-8 -*-
"""DEM, OSM river and province boundary data helpers."""

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


class DEMDownloadError(Exception):
    """Raised when DEM download or preparation fails."""


class OSMDownloadError(Exception):
    """Raised when OSM river download or extraction fails."""


class StyleError(Exception):
    """Raised when a style cannot be applied."""


class NASAEarthDataSession:
    """NASA EarthData session based on urllib and CookieJar."""

    LOGIN_URL = "https://urs.earthdata.nasa.gov/login"
    AUTHORIZE_URL = "https://urs.earthdata.nasa.gov/oauth/authorize"
    TEST_URL = "https://urs.earthdata.nasa.gov/profile"

    def __init__(self):
        """Create an unauthenticated EarthData session."""
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = self._build_opener()
        self.username = ""
        self.authenticated = False

    def _build_opener(self):
        """Build a cookie-aware urllib opener.

        Returns:
            urllib.request.OpenerDirector: Configured opener.
        """
        processor = urllib.request.HTTPCookieProcessor(self.cookie_jar)
        opener = urllib.request.build_opener(processor)
        opener.addheaders = [
            ("User-Agent", "TurkeyGeoMorphAnalyst/1.0 QGIS Plugin"),
        ]
        return opener

    def login(self, username: str, password: str) -> bool:
        """Authenticate with NASA EarthData.

        Args:
            username: EarthData username.
            password: EarthData password.

        Returns:
            bool: True when a session cookie is obtained.
        """
        self.username = username
        try:
            self.opener.open(self.AUTHORIZE_URL, timeout=30)
        except Exception:
            pass

        payload = urllib.parse.urlencode(
            {"username": username, "password": password}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.LOGIN_URL,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "TurkeyGeoMorphAnalyst/1.0 QGIS Plugin",
            },
        )
        try:
            response = self.opener.open(request, timeout=45)
            body = response.read(2048).decode("utf-8", "ignore")
            has_cookie = len(list(self.cookie_jar)) > 0
            self.authenticated = has_cookie and "Invalid" not in body
            QgsMessageLog.logMessage(
                "NASA EarthData oturum sonucu: {0}".format(
                    "başarılı" if self.authenticated else "kontrol gerekli"
                ),
                "TurkeyGeoMorph",
                Qgis.Info,
            )
            return self.authenticated
        except urllib.error.URLError as exc:
            QgsMessageLog.logMessage(
                "NASA EarthData bağlantı hatası: {0}".format(exc),
                "TurkeyGeoMorph",
                Qgis.Critical,
            )
            return False

    def test_connection(self) -> bool:
        """Test the authenticated EarthData connection.

        Returns:
            bool: True when the profile endpoint is reachable.
        """
        try:
            response = self.opener.open(self.TEST_URL, timeout=30)
            return 200 <= response.getcode() < 400
        except Exception as exc:
            QgsMessageLog.logMessage(
                "NASA EarthData test hatası: {0}".format(exc),
                "TurkeyGeoMorph",
                Qgis.Warning,
            )
            return False

    def authenticated_download(self, url: str, output_path: str) -> bool:
        """Download a protected EarthData URL.

        Args:
            url: Remote URL.
            output_path: Local output file path.

        Returns:
            bool: True when a non-empty file is written.
        """
        target = pathlib.Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.opener.open(url, timeout=180) as response:
                with open(os.fspath(target), "wb") as output_file:
                    shutil.copyfileobj(response, output_file)
            return target.exists() and target.stat().st_size > 0
        except Exception as exc:
            QgsMessageLog.logMessage(
                "NASA indirme hatası {0}: {1}".format(url, exc),
                "TurkeyGeoMorph",
                Qgis.Critical,
            )
            return False


class DEMDownloader:
    """Download, mosaic, clip and normalize DEM datasets."""

    SRTM_GL1_URL = (
        "https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/"
        "2000.02.11/{tile}"
    )
    SRTM_GL3_URL = (
        "https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL3.003/"
        "2000.02.11/{tile}"
    )
    ASTER_URL = (
        "https://e4ftl01.cr.usgs.gov/ASTT/ASTGTMV003.003/"
        "2000.03.01/{tile}"
    )
    NASADEM_URL = (
        "https://e4ftl01.cr.usgs.gov/MEASURES/NASADEM_HGT.001/"
        "2000.02.11/{tile}"
    )

    def __init__(self, session, output_dir: str):
        """Initialize downloader.

        Args:
            session: NASAEarthDataSession instance or None.
            output_dir: Directory for downloaded and processed rasters.
        """
        self.session = session
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _bbox_values(self, bbox):
        """Return bbox values as south, north, west, east."""
        if hasattr(bbox, "yMinimum"):
            return (
                bbox.yMinimum(),
                bbox.yMaximum(),
                bbox.xMinimum(),
                bbox.xMaximum(),
            )
        if isinstance(bbox, dict):
            return (bbox["south"], bbox["north"], bbox["west"], bbox["east"])
        lat_min, lat_max, lon_min, lon_max = bbox
        return (lat_min, lat_max, lon_min, lon_max)

    def get_tiles_for_bbox(self, bbox) -> list:
        """Calculate one-degree DEM tiles intersecting a bbox.

        Args:
            bbox: QgsRectangle, dict or tuple.

        Returns:
            list: List of (lat, lon) tile origins.
        """
        south, north, west, east = self._bbox_values(bbox)
        tiles = []
        for lat in range(math.floor(south), math.ceil(north)):
            for lon in range(math.floor(west), math.ceil(east)):
                tiles.append((lat, lon))
        return tiles

    def _tile_ns_ew(self, lat: int, lon: int) -> tuple:
        """Build hemisphere/name fragments for a tile."""
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        return ns, abs(lat), ew, abs(lon)

    def _download_url(self, url: str, output_path: pathlib.Path) -> str:
        """Download an unauthenticated URL."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "TurkeyGeoMorphAnalyst/1.0 QGIS Plugin"},
            )
            with urllib.request.urlopen(request, timeout=240) as response:
                status = getattr(response, "status", response.getcode())
                content_type = response.headers.get("Content-Type", "")
                if status < 200 or status >= 300:
                    raise DEMDownloadError(
                        "HTTP {0}: {1}".format(status, url)
                    )
                with open(os.fspath(output_path), "wb") as output_file:
                    shutil.copyfileobj(response, output_file)
        except DEMDownloadError:
            raise
        except Exception as exc:
            raise DEMDownloadError(
                "İndirme başarısız: {0} ({1})".format(url, exc)
            )
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise DEMDownloadError("Boş indirme: {0}".format(url))
        if output_path.suffix.lower() in [".tif", ".tiff"]:
            dataset = gdal.Open(os.fspath(output_path))
            if dataset is None:
                sample = output_path.read_bytes()[:256]
                raise DEMDownloadError(
                    "İndirilen dosya raster değil: {0} | içerik türü: {1} | ilk bayt: {2}".format(
                        url, content_type, sample[:80]
                    )
                )
            dataset = None
        return os.fspath(output_path)

    def _extract_zip_member(self, zip_path: str, suffix: str) -> str:
        """Extract a matching member from a zip archive."""
        out_dir = pathlib.Path(zip_path).with_suffix("")
        out_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = [
                name for name in archive.namelist()
                if name.lower().endswith(suffix.lower())
            ]
            if not names:
                raise DEMDownloadError(
                    "Zip içinde {0} uzantılı dosya yok: {1}".format(
                        suffix, zip_path
                    )
                )
            archive.extract(names[0], os.fspath(out_dir))
            return os.fspath(out_dir / names[0])

    def _hgt_to_tiff(self, hgt_path: str) -> str:
        """Translate HGT to GeoTIFF."""
        output = pathlib.Path(hgt_path).with_suffix(".tif")
        ds = gdal.Open(hgt_path)
        if ds is None:
            raise DEMDownloadError("HGT açılamadı: {0}".format(hgt_path))
        result = gdal.Translate(os.fspath(output), ds, format="GTiff")
        ds = None
        if result is None:
            raise DEMDownloadError("HGT GeoTIFF'e çevrilemedi.")
        result = None
        return os.fspath(output)

    def download_srtm_gl1(self, bbox) -> str:
        """Download and mosaic SRTM GL1 30 m DEM."""
        paths = []
        for lat, lon in self.get_tiles_for_bbox(bbox):
            ns, alat, ew, alon = self._tile_ns_ew(lat, lon)
            tile = "{0}{1:02d}{2}{3:03d}.SRTMGL1.hgt.zip".format(
                ns, alat, ew, alon
            )
            zip_path = self.output_dir / "srtm_gl1" / tile
            url = self.SRTM_GL1_URL.format(tile=tile)
            if self.session is None:
                raise DEMDownloadError("NASA EarthData oturumu gerekli.")
            if not self.session.authenticated_download(url, os.fspath(zip_path)):
                raise DEMDownloadError("SRTM GL1 indirilemedi: {0}".format(tile))
            paths.append(self._hgt_to_tiff(self._extract_zip_member(
                os.fspath(zip_path), ".hgt"
            )))
        return self.merge_tiles(paths)

    def download_srtm_gl3(self, bbox) -> str:
        """Download and mosaic SRTM GL3 90 m DEM."""
        paths = []
        for lat, lon in self.get_tiles_for_bbox(bbox):
            ns, alat, ew, alon = self._tile_ns_ew(lat, lon)
            tile = "{0}{1:02d}{2}{3:03d}.SRTMGL3.hgt.zip".format(
                ns, alat, ew, alon
            )
            zip_path = self.output_dir / "srtm_gl3" / tile
            url = self.SRTM_GL3_URL.format(tile=tile)
            if self.session is None:
                raise DEMDownloadError("NASA EarthData oturumu gerekli.")
            if not self.session.authenticated_download(url, os.fspath(zip_path)):
                raise DEMDownloadError("SRTM GL3 indirilemedi: {0}".format(tile))
            paths.append(self._hgt_to_tiff(self._extract_zip_member(
                os.fspath(zip_path), ".hgt"
            )))
        return self.merge_tiles(paths)

    def download_aster_gdem(self, bbox) -> str:
        """Download and mosaic ASTER GDEM v3."""
        paths = []
        for lat, lon in self.get_tiles_for_bbox(bbox):
            ns, alat, ew, alon = self._tile_ns_ew(lat, lon)
            basename = "ASTGTMV003_{0}{1:02d}{2}{3:03d}".format(
                ns, alat, ew, alon
            )
            tile = basename + ".zip"
            zip_path = self.output_dir / "aster_gdem" / tile
            url = self.ASTER_URL.format(tile=tile)
            if self.session is None:
                raise DEMDownloadError("NASA EarthData oturumu gerekli.")
            if not self.session.authenticated_download(url, os.fspath(zip_path)):
                raise DEMDownloadError("ASTER indirilemedi: {0}".format(tile))
            paths.append(self._extract_zip_member(os.fspath(zip_path), "_dem.tif"))
        return self.merge_tiles(paths)

    def download_copernicus(self, bbox) -> str:
        """Download and mosaic Copernicus DEM GLO-30 COG tiles.

        Tries two CDN endpoints per tile:
        1. AWS S3 (copernicus-dem-30m.s3.amazonaws.com)  — primary
        2. Element84 / OpenTopography CDN                — fallback

        Ocean or uninhabited tiles may genuinely not exist on the server;
        those 404s are logged as warnings and skipped, not treated as fatal
        errors.  The download is only failed when *no* tile succeeds at all.
        """
        # AWS-hosted GLO-30 bucket (public, no auth required)
        AWS_TMPL = (
            "https://copernicus-dem-30m.s3.amazonaws.com/"
            "{folder}/{filename}"
        )
        # Element84 / Planetary Computer mirror (often faster in EU/TR)
        E84_TMPL = (
            "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/"
            "{folder}/{filename}"
        )

        paths = []
        failures = []

        for lat, lon in self.get_tiles_for_bbox(bbox):
            ns, alat, ew, alon = self._tile_ns_ew(lat, lon)
            folder = (
                "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM"
            ).format(ns=ns, lat=alat, ew=ew, lon=alon)
            filename = folder + ".tif"
            out = self.output_dir / "copernicus_glo30" / filename

            # Use cached tile if already present and valid
            if out.exists() and out.stat().st_size > 0:
                ds = gdal.Open(os.fspath(out))
                if ds is not None:
                    ds = None
                    paths.append(os.fspath(out))
                    continue

            tile_ok = False
            last_exc = None
            for tmpl in (AWS_TMPL, E84_TMPL):
                url = tmpl.format(folder=folder, filename=filename)
                try:
                    paths.append(self._download_url(url, out))
                    tile_ok = True
                    break
                except DEMDownloadError as exc:
                    last_exc = exc
                    # 404/NoSuchKey means the tile simply does not exist
                    # (ocean cell), not a network failure — stop trying other
                    # mirrors for this tile.
                    msg = str(exc).lower()
                    if "404" in msg or "nosuchkey" in msg or "http 4" in msg:
                        QgsMessageLog.logMessage(
                            "Copernicus tile mevcut değil (okyanus/boş): "
                            "{0}".format(filename),
                            "TurkeyGeoMorph",
                            Qgis.Info,
                        )
                        break
                    QgsMessageLog.logMessage(
                        "Copernicus mirror deneniyor ({0}): {1}".format(
                            tmpl.split("/")[2], exc
                        ),
                        "TurkeyGeoMorph",
                        Qgis.Warning,
                    )

            if not tile_ok:
                err_msg = str(last_exc) if last_exc else "Bilinmeyen hata"
                failures.append("{0}: {1}".format(filename, err_msg))
                QgsMessageLog.logMessage(
                    "Copernicus tile atlandı: {0}".format(err_msg),
                    "TurkeyGeoMorph",
                    Qgis.Warning,
                )

        if not paths:
            raise DEMDownloadError(
                "Copernicus DEM indirilemedi.\n"
                "Tile hataları: {0}\n"
                "İpucu: İnternet bağlantınızı veya güvenlik duvarı "
                "ayarlarınızı kontrol edin. Alternatif olarak "
                "OpenTopography 30m kaynağını kullanabilirsiniz.".format(
                    " | ".join(failures[:5])
                )
            )
        return self.merge_tiles(paths)

    def download_alos_aw3d30(self, bbox, user: str, pw: str) -> str:
        """Download and mosaic ALOS AW3D30 tiles with Basic Auth."""
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        base = "https://www.eorc.jaxa.jp/"
        password_mgr.add_password(None, base, user, pw)
        opener = urllib.request.build_opener(
            urllib.request.HTTPBasicAuthHandler(password_mgr)
        )
        opener.addheaders = [
            ("User-Agent", "TurkeyGeoMorphAnalyst/1.0 QGIS Plugin"),
        ]
        paths = []
        for lat, lon in self.get_tiles_for_bbox(bbox):
            lat5 = int(math.floor(lat / 5.0) * 5)
            lon5 = int(math.floor(lon / 5.0) * 5)
            ns = "N" if lat5 >= 0 else "S"
            ew = "E" if lon5 >= 0 else "W"
            folder = "{0}{1:03d}{2}{3:03d}".format(
                ns, abs(lat5), ew, abs(lon5)
            )
            tile = "ALPSMLC30_{0}_DSM.tif".format(folder)
            zip_name = tile + ".zip"
            url = (
                "https://www.eorc.jaxa.jp/ALOS/aw3d30/data/"
                "release_v2303/{0}/{1}"
            ).format(folder, zip_name)
            zip_path = self.output_dir / "alos_aw3d30" / zip_name
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with opener.open(url, timeout=180) as response:
                    with open(os.fspath(zip_path), "wb") as output_file:
                        shutil.copyfileobj(response, output_file)
            except Exception as exc:
                raise DEMDownloadError(
                    "ALOS AW3D30 indirilemedi: {0}".format(exc)
                )
            paths.append(self._extract_zip_member(os.fspath(zip_path), ".tif"))
        return self.merge_tiles(paths)

    def download_opentopography(
        self, bbox, api_key: str, demtype: str = "COP30"
    ) -> str:
        """Download clipped DEM from OpenTopography Global DEM API."""
        south, north, west, east = self._bbox_values(bbox)
        if abs(north - south) > 5 or abs(east - west) > 5:
            QgsMessageLog.logMessage(
                "OpenTopography alanı 5x5 dereceden büyük; zaman aşımı olabilir.",
                "TurkeyGeoMorph",
                Qgis.Warning,
            )
        params = urllib.parse.urlencode(
            {
                "demtype": demtype,
                "south": south,
                "north": north,
                "west": west,
                "east": east,
                "outputFormat": "GTiff",
                "API_Key": api_key,
            }
        )
        url = "https://portal.opentopography.org/API/globaldem?{0}".format(
            params
        )
        out = self.output_dir / "opentopography" / "{0}.tif".format(demtype)
        return self._download_url(url, out)

    def download_nasadem(self, bbox) -> str:
        """Download and mosaic NASADEM 30 m DEM."""
        paths = []
        for lat, lon in self.get_tiles_for_bbox(bbox):
            ns, alat, ew, alon = self._tile_ns_ew(lat, lon)
            tile = "NASADEM_HGT_{0}{1:02d}{2}{3:03d}.zip".format(
                ns, alat, ew, alon
            )
            zip_path = self.output_dir / "nasadem" / tile
            url = self.NASADEM_URL.format(tile=tile)
            if self.session is None:
                raise DEMDownloadError("NASA EarthData oturumu gerekli.")
            if not self.session.authenticated_download(url, os.fspath(zip_path)):
                raise DEMDownloadError("NASADEM indirilemedi: {0}".format(tile))
            paths.append(self._hgt_to_tiff(self._extract_zip_member(
                os.fspath(zip_path), ".hgt"
            )))
        return self.merge_tiles(paths)

    def load_local_dem(self, file_path: str) -> str:
        """Validate and normalize a user-provided DEM file."""
        source = pathlib.Path(file_path)
        if not source.exists():
            raise DEMDownloadError("Yerel DEM bulunamadı: {0}".format(file_path))
        ds = gdal.Open(os.fspath(source))
        if ds is None:
            raise DEMDownloadError("GDAL bu DEM dosyasını açamadı.")
        ds = None
        if source.suffix.lower() in [".hgt", ".asc", ".img", ".vrt", ".nc",
                                     ".h5", ".hdf5", ".tiff", ".tif"]:
            out = self.output_dir / "local_dem.tif"
            result = gdal.Translate(os.fspath(out), os.fspath(source),
                                    format="GTiff")
            if result is None:
                raise DEMDownloadError("Yerel DEM GeoTIFF'e çevrilemedi.")
            result = None
            return os.fspath(out)
        raise DEMDownloadError("Desteklenmeyen DEM formatı: {0}".format(source))

    def merge_tiles(self, tile_paths: list) -> str:
        """Merge one or more tiles with GDAL Warp."""
        if not tile_paths:
            raise DEMDownloadError("Mozaiklenecek tile bulunamadı.")
        if len(tile_paths) == 1:
            return tile_paths[0]
        output = self.output_dir / "dem_mosaic.tif"
        result = gdal.Warp(os.fspath(output), tile_paths, format="GTiff")
        if result is None:
            raise DEMDownloadError("DEM mozaikleme başarısız.")
        result = None
        return os.fspath(output)

    def _boundary_to_cutline(self, boundary_layer) -> str:
        """Persist a QGIS boundary layer to a temporary GeoJSON cutline."""
        temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="tga_cutline_"))
        output = temp_dir / "boundary.geojson"
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GeoJSON"
        result, message = QgsVectorFileWriter.writeAsVectorFormatV2(
            boundary_layer,
            os.fspath(output),
            QgsProject.instance().transformContext(),
            options,
        )
        if result != QgsVectorFileWriter.NoError:
            raise DEMDownloadError("Sınır dosyası yazılamadı: {0}".format(message))
        return os.fspath(output)

    def clip_to_boundary(self, dem_path: str, boundary_layer) -> str:
        """Clip DEM to a selected province/district boundary."""
        cutline = self._boundary_to_cutline(boundary_layer)
        output = self.output_dir / "dem_clipped.tif"
        result = gdal.Warp(
            os.fspath(output),
            dem_path,
            cutlineDSName=cutline,
            cropToCutline=True,
            dstNodata=-9999,
            format="GTiff",
        )
        if result is None:
            raise DEMDownloadError("DEM il sınırına kırpılamadı.")
        result = None
        return os.fspath(output)

    def reproject_if_needed(self, dem_path: str, target_epsg: int = 4326) -> str:
        """Reproject DEM when it is not in the target EPSG."""
        ds = gdal.Open(dem_path)
        if ds is None:
            raise DEMDownloadError("DEM açılamadı: {0}".format(dem_path))
        projection = ds.GetProjection()
        srs = osr.SpatialReference()
        if projection:
            srs.ImportFromWkt(projection)
        auth = srs.GetAuthorityCode(None)
        ds = None
        if auth == str(target_epsg):
            return dem_path
        output = self.output_dir / "dem_epsg_{0}.tif".format(target_epsg)
        result = gdal.Warp(
            os.fspath(output),
            dem_path,
            dstSRS="EPSG:{0}".format(target_epsg),
            format="GTiff",
        )
        if result is None:
            raise DEMDownloadError("DEM reprojeksiyon başarısız.")
        result = None
        return os.fspath(output)


class OSMRiverDownloader:
    """Download and extract rivers from OSM with urllib and GDAL/OGR."""

    PBF_URL = "https://download.geofabrik.de/europe/turkey-latest.osm.pbf"
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    def __init__(self, output_dir: str):
        """Initialize river downloader."""
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_osm_pbf(self, output_dir: str = None) -> str:
        """Download Geofabrik Turkey PBF."""
        target_dir = pathlib.Path(output_dir) if output_dir else self.output_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        output = target_dir / "turkey-latest.osm.pbf"
        try:
            urllib.request.urlretrieve(self.PBF_URL, os.fspath(output))
        except Exception as exc:
            raise OSMDownloadError("Geofabrik PBF indirilemedi: {0}".format(exc))
        return os.fspath(output)

    def _feature_count(self, vector_path: str, layer_name: str = "rivers") -> int:
        """Return feature count for a vector datasource layer."""
        datasource = ogr.Open(vector_path)
        if datasource is None:
            return 0
        layer = datasource.GetLayerByName(layer_name)
        if layer is None:
            layer = datasource.GetLayer(0)
        count = layer.GetFeatureCount() if layer is not None else 0
        datasource = None
        return count

    def extract_rivers_gdal(
        self, pbf_path: str, boundary, filter_types: list
    ) -> str:
        """Extract waterway lines from PBF and clip to boundary."""
        ds = ogr.Open(pbf_path)
        if ds is None:
            raise OSMDownloadError("PBF açılamadı; GDAL OSM driver kontrol edin.")
        lines_layer = ds.GetLayerByName("lines")
        if lines_layer is None:
            ds = None
            raise OSMDownloadError("OSM 'lines' katmanı bulunamadı.")
        values = ",".join(["'{0}'".format(value) for value in filter_types])
        lines_layer.SetAttributeFilter("waterway IN ({0})".format(values))

        output = self.output_dir / "osm_rivers_raw.gpkg"
        if output.exists():
            output.unlink()
        driver = ogr.GetDriverByName("GPKG")
        out_ds = driver.CreateDataSource(os.fspath(output))
        out_ds.CopyLayer(lines_layer, "rivers", [])
        out_ds = None
        ds = None

        clipped = self.output_dir / "osm_rivers_clipped.gpkg"
        result = processing.run(
            "native:clip",
            {
                "INPUT": os.fspath(output) + "|layername=rivers",
                "OVERLAY": boundary,
                "OUTPUT": os.fspath(clipped),
            },
        )
        if self._feature_count(result["OUTPUT"], "rivers") == 0:
            raise OSMDownloadError("Geofabrik akarsu kırpma sonucu boş.")
        return result["OUTPUT"]

    def query_overpass(
        self, province_name: str, filter_types: list, boundary_layer=None
    ) -> str:
        """Query Overpass API by selected boundary bbox and write waterways.

        Province-name area queries are fragile because OSM admin levels and
        Turkish names differ across regions. Bbox query plus QGIS clipping is
        deterministic for both province and district selections.
        """
        bbox_clause = ""
        if boundary_layer is not None:
            extent = boundary_layer.extent()
            bbox_clause = "({0},{1},{2},{3})".format(
                extent.yMinimum(),
                extent.xMinimum(),
                extent.yMaximum(),
                extent.xMaximum(),
            )
        way_queries = "\n".join(
            ['way["waterway"="{0}"]{1};'.format(item, bbox_clause)
             for item in filter_types]
        )
        query = """
[out:json][timeout:180];
(
{ways}
);
out body geom;
""".format(ways=way_queries)
        data = query.encode("utf-8")
        request = urllib.request.Request(
            self.OVERPASS_URL,
            data=data,
            headers={
                "Content-Type": "text/plain; charset=UTF-8",
                "User-Agent": "TurkeyGeoMorphAnalyst/1.0 QGIS Plugin",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=210) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise OSMDownloadError("Overpass sorgusu başarısız: {0}".format(exc))

        output = self.output_dir / "overpass_rivers.gpkg"
        if output.exists():
            output.unlink()
        driver = ogr.GetDriverByName("GPKG")
        ds = driver.CreateDataSource(os.fspath(output))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        layer = ds.CreateLayer("rivers", srs, ogr.wkbLineString)
        layer.CreateField(ogr.FieldDefn("osm_id", ogr.OFTString))
        layer.CreateField(ogr.FieldDefn("waterway", ogr.OFTString))
        layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))

        definition = layer.GetLayerDefn()
        for element in payload.get("elements", []):
            geometry_items = element.get("geometry", [])
            if len(geometry_items) < 2:
                continue
            line = ogr.Geometry(ogr.wkbLineString)
            for point in geometry_items:
                line.AddPoint(float(point["lon"]), float(point["lat"]))
            feature = ogr.Feature(definition)
            feature.SetGeometry(line)
            feature.SetField("osm_id", str(element.get("id", "")))
            tags = element.get("tags", {})
            feature.SetField("waterway", tags.get("waterway", ""))
            feature.SetField("name", tags.get("name", ""))
            layer.CreateFeature(feature)
            feature = None
        ds = None
        if boundary_layer is None:
            return os.fspath(output)
        clipped = self.output_dir / "overpass_rivers_clipped.gpkg"
        if clipped.exists():
            clipped.unlink()
        result = processing.run(
            "native:clip",
            {
                "INPUT": os.fspath(output) + "|layername=rivers",
                "OVERLAY": boundary_layer,
                "OUTPUT": os.fspath(clipped),
            },
        )
        if self._feature_count(result["OUTPUT"], "rivers") == 0:
            raise OSMDownloadError("Overpass akarsu sorgusu seçilen sınırda boş döndü.")
        return result["OUTPUT"]

    def apply_river_style(self, layer) -> None:
        """Apply built-in categorized river style when available."""
        style_path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "resources" / "styles" / "rivers.qml"
        )
        if style_path.exists():
            layer.loadNamedStyle(os.fspath(style_path))
            layer.triggerRepaint()


class ProvinceManager:
    """Manage embedded Turkey province boundaries."""

    def __init__(self, geojson_path: str):
        """Initialize province manager from embedded GeoJSON."""
        self.geojson_path = pathlib.Path(geojson_path)
        self.district_geojson_path = self.geojson_path.with_name(
            "turkey_districts.geojson"
        )
        self.layer = None
        self.district_layer = None
        self.name_field = None
        self.district_province_field = None
        self.district_name_field = None
        self.load_from_geojson()
        self.load_districts_from_geojson()

    def load_from_geojson(self) -> bool:
        """Load the embedded GeoJSON layer."""
        if not self.geojson_path.exists():
            return False
        self.layer = QgsVectorLayer(
            os.fspath(self.geojson_path), "Turkey provinces", "ogr"
        )
        if not self.layer.isValid():
            self.layer = None
            return False
        fields = [field.name() for field in self.layer.fields()]
        for candidate in ["name", "NAME_1", "Name", "province", "il", "shapeName"]:
            if candidate in fields:
                self.name_field = candidate
                break
        if self.name_field is None and fields:
            self.name_field = fields[0]
        return self.name_field is not None

    def load_districts_from_geojson(self) -> bool:
        """Load embedded GADM Level 2 district boundaries."""
        if not self.district_geojson_path.exists():
            return False
        self.district_layer = QgsVectorLayer(
            os.fspath(self.district_geojson_path), "Turkey districts", "ogr"
        )
        if not self.district_layer.isValid():
            self.district_layer = None
            return False
        fields = [field.name() for field in self.district_layer.fields()]
        for candidate in ["NAME_1", "province", "il"]:
            if candidate in fields:
                self.district_province_field = candidate
                break
        for candidate in ["NAME_2", "district", "ilce", "İlçe"]:
            if candidate in fields:
                self.district_name_field = candidate
                break
        return (
            self.district_province_field is not None
            and self.district_name_field is not None
        )

    def _feature_name(self, feature) -> str:
        """Read province name from a feature."""
        return str(feature[self.name_field])

    def get_province_list(self) -> list:
        """Return alphabetic province names."""
        if self.layer is None:
            return []
        names = [self._feature_name(feature) for feature in self.layer.getFeatures()]
        return sorted(names, key=lambda value: value.lower())

    def get_province_boundary(self, name: str):
        """Return a memory layer containing a single province boundary."""
        if self.layer is None:
            return None
        crs = self.layer.crs().authid() or "EPSG:4326"
        memory = QgsVectorLayer(
            "MultiPolygon?crs={0}".format(crs), name, "memory"
        )
        provider = memory.dataProvider()
        provider.addAttributes(self.layer.fields())
        memory.updateFields()
        for feature in self.layer.getFeatures():
            if self._feature_name(feature).lower() == name.lower():
                provider.addFeature(feature)
                memory.updateExtents()
                return memory
        return None

    def get_province_bbox(self, name: str):
        """Return province bbox."""
        layer = self.get_province_boundary(name)
        if layer is None:
            return None
        return layer.extent()

    def get_districts(self, province_name: str) -> list:
        """Return GADM Level 2 districts for a province."""
        if self.district_layer is None:
            return []
        names = []
        for feature in self.district_layer.getFeatures():
            if str(feature[self.district_province_field]).lower() == province_name.lower():
                names.append(str(feature[self.district_name_field]))
        return sorted(set(names), key=lambda value: value.lower())

    def get_district_boundary(self, province_name: str, district_name: str = None):
        """Return a memory layer containing a single district boundary."""
        if district_name is None:
            district_name = province_name
            province_name = ""
        if self.district_layer is None:
            return self.fallback_nominatim(district_name)
        crs = self.district_layer.crs().authid() or "EPSG:4326"
        memory = QgsVectorLayer(
            "MultiPolygon?crs={0}".format(crs), district_name, "memory"
        )
        provider = memory.dataProvider()
        provider.addAttributes(self.district_layer.fields())
        memory.updateFields()
        for feature in self.district_layer.getFeatures():
            province_ok = True
            if province_name:
                province_ok = (
                    str(feature[self.district_province_field]).lower()
                    == province_name.lower()
                )
            district_ok = (
                str(feature[self.district_name_field]).lower()
                == district_name.lower()
            )
            if province_ok and district_ok:
                provider.addFeature(feature)
                memory.updateExtents()
                return memory
        return self.fallback_nominatim(
            "{0} {1}".format(district_name, province_name).strip()
        )

    def fallback_nominatim(self, name: str):
        """Fetch a boundary polygon from Nominatim when internet is available."""
        params = urllib.parse.urlencode(
            {
                "q": "{0}, Turkey".format(name),
                "format": "geojson",
                "polygon_geojson": 1,
                "limit": 1,
            }
        )
        url = "https://nominatim.openstreetmap.org/search?{0}".format(params)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "TurkeyGeoMorphAnalyst/1.0 QGIS Plugin"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = response.read().decode("utf-8")
        except Exception as exc:
            raise OSMDownloadError("Nominatim sınır sorgusu başarısız: {0}".format(exc))
        temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="tga_nominatim_"))
        output = temp_dir / "boundary.geojson"
        with open(os.fspath(output), "w", encoding="utf-8") as output_file:
            output_file.write(payload)
        layer = QgsVectorLayer(os.fspath(output), name, "ogr")
        if not layer.isValid():
            raise OSMDownloadError("Nominatim GeoJSON katmanı geçersiz.")
        return layer
