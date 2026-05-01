# TurkeyGeoMorph Analyst Kurulum ve Test Senaryoları

## Kurulum

1. `TurkeyGeoMorphAnalyst` klasörünü QGIS eklenti klasörüne kopyalayın.
   - Windows için tipik yol:
     `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\TurkeyGeoMorphAnalyst`
2. QGIS'i yeniden başlatın.
3. `Eklentiler > Eklentileri Yönet ve Kur` menüsünden `TurkeyGeoMorph Analyst` eklentisini etkinleştirin.
4. Araç çubuğundaki `TurkeyGeoMorph Analyst` ikonuna basarak ana pencereyi açın.

## Bağımlılık Sınırı

Bu eklenti pip, conda veya harici Python paketi gerektirmez. Kullanılan bileşenler:

- PyQGIS
- QGIS Processing Framework
- GDAL/OGR/OSR
- PyQt5
- Python standart kütüphanesi

SAGA algoritmaları QGIS kurulumunda etkinse TWI, TPI, geomorphons ve hidroloji adımlarında kullanılır. SAGA yoksa eklenti uyarı verir ve GDAL tabanlı sınırlı yedek işlemlere döner.

## Gömülü Sınır Verisi

`data/turkey_provinces.geojson` dosyası GADM 4.1 Türkiye Level 1 verisinden üretilmiştir:

`https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_TUR_1.json.zip`

Eklenti il adlarını GADM `NAME_1` alanından okur.

`data/turkey_districts.geojson` dosyası GADM 4.1 Türkiye Level 2 verisinden üretilmiştir:

`https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_TUR_2.json.zip`

Eklenti ilçe adlarını GADM `NAME_2` alanından, bağlı oldukları ili `NAME_1` alanından okur.

## Hızlı Test

1. QGIS'i açın ve eklentiyi çalıştırın.
2. `Çalışma Alanı` sekmesinde `Ankara` ilini seçin.
3. `Sınırı Haritada Göster` düğmesine basın.
4. Haritada Ankara il sınırının göründüğünü doğrulayın.

## Yerel DEM ile İşlem Testi

1. `Veri İndirme` sekmesinde `Yerel DEM Dosyası` seçeneğini işaretleyin.
2. `.tif`, `.hgt`, `.asc`, `.img`, `.vrt`, `.nc`, `.h5` veya `.hdf5` formatında bir DEM dosyası seçin.
3. `Akarsu verisini indir` seçeneğini kapatın.
4. `Harita Üretimi` sekmesinde yalnızca `Yükselti`, `Hillshade`, `Eğim` ve `Bakı` haritalarını açık bırakın.
5. `Verileri İndir` düğmesine basın.
6. İşlem tamamlandığında katmanların QGIS katman paneline eklendiğini doğrulayın.

## Copernicus DEM Testi

1. `Çalışma Alanı` sekmesinde küçük yüzölçümlü bir il seçin.
2. `Veri İndirme` sekmesinde `Copernicus DEM GLO-30` seçeneğini kullanın.
3. İnternet bağlantınız olduğundan emin olun.
4. `Verileri İndir` düğmesine basın.
5. `raw`, `processed`, `exports` ve `reports` klasörlerinin çıktı klasörü altında oluştuğunu doğrulayın.

## NASA EarthData Testi

1. `SRTM GL1`, `SRTM GL3`, `ASTER GDEM v3` veya `NASADEM` seçeneğini işaretleyin.
2. NASA EarthData kullanıcı adı ve şifrenizi girin.
3. `Bağlantıyı Test Et` düğmesine basın.
4. Başarılı bağlantı sonrası `Verileri İndir` ile tile indirme ve mozaikleme akışını çalıştırın.

## OpenTopography Testi

1. `OpenTopography API` seçeneğini işaretleyin.
2. API anahtarınızı girin.
3. Küçük bir il veya dar çalışma alanı seçin.
4. `Verileri İndir` düğmesine basın.

## Akarsu Verisi Testi

1. `Akarsu verisini indir` seçeneğini açık bırakın.
2. Filtreyi `river+stream` olarak seçin.
3. İşlem tamamlandığında `Akarsular` adlı GeoPackage katmanının QGIS'e eklendiğini doğrulayın.

## Dışa Aktarma Testi

1. Haritalar üretildikten sonra `Dışa Aktarma` sekmesine geçin.
2. `PDF` ve `PNG` formatlarını seçin.
3. `Tüm Haritaları Üret ve Kaydet` düğmesine basın.
4. Çıktı klasörü altındaki `exports` klasöründe dosyaları ve `export_log.txt` kaydını kontrol edin.

## Rapor Testi

1. Harita üretimi tamamlandıktan sonra `İstatistik & Rapor` sekmesine geçin.
2. İstatistik tablosunda DEM metriklerinin listelendiğini doğrulayın.
3. `Raporu Dışa Aktar` düğmesine basın.
4. `reports/statistics.csv` ve `reports/statistics.html` dosyalarını kontrol edin.

## Bilinen Operasyonel Notlar

- TanDEM-X 90m ücretsiz sürümü otomatik indirilemediği için kullanıcıdan yerel GeoTIFF olarak seçilmesi beklenir.
- Geofabrik PBF yolu GDAL OSM driver'a bağlıdır. Driver yoksa Overpass API yolu önerilir.
- Büyük iller veya çok sayıda 1 derecelik DEM tile içeren alanlarda indirme ve mozaikleme uzun sürebilir.
