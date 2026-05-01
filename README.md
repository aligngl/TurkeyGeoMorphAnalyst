# TurkeyGeoMorph Analyst

TurkeyGeoMorph Analyst, Türkiye'deki il ve ilçe ölçekli jeomorfoloji çalışmaları için geliştirilmiş bir QGIS eklentisidir. Eklenti; DEM indirme/hazırlama, akarsu verisi işleme, temel morfometrik analizler, tez standardına uygun harita layoutları, dışa aktarma ve istatistik raporlama iş akışlarını tek panel altında toplar.

Bu proje özellikle lisans, yüksek lisans ve doktora öğrencilerinin jeomorfoloji, fiziki coğrafya, havza analizi, arazi şekilleri ve topoğrafik analiz çalışmalarında hızlı, tekrar üretilebilir ve düzenlenebilir harita çıktıları elde etmesi için hazırlanmıştır.

## Temel Özellikler

- Türkiye için il ve ilçe bazlı çalışma alanı seçimi
- GADM tabanlı gömülü il ve ilçe sınır verisi
- Copernicus DEM GLO-30 indirme
- OpenTopography 30 m ve 90 m DEM indirme
- TanDEM-X ve diğer yerel DEM dosyalarını kullanma
- OSM/Overpass tabanlı akarsu verisi indirme ve çalışma alanına kırpma
- DEM ve akarsu verileri için önbellek sistemi
- Varsayılan 30 günlük önbellek saklama süresi
- Üretimi durdurma ve önbelleği temizleme araçları
- Kullanıcı seçimine göre harita üretimi
- Her harita için ayrı, düzenlenebilir QGIS layout üretimi
- PDF ve QGIS projesi odaklı stabil dışa aktarma
- İsteğe bağlı PNG, SVG, GeoTIFF, vektör veri, manifest ve ZIP paket çıktıları
- CSV, HTML ve TXT tabanlı istatistik/yorum raporları
- Harita katman sıralamasında nokta - çizgi - alan mantığı
- QGIS dışı Python paketi gerektirmeyen kurulum

## Üretilen Haritalar

Eklenti, kullanıcı hangi haritaları seçerse yalnızca onları üretir. Böylece gereksiz işlem süresi ve gereksiz katman kalabalığı azaltılır.

Desteklenen harita türleri:

- Yükselti haritası
- Gölgelendirme haritası
- Eğim haritası
- Bakı haritası
- Eğrisellik haritası
- Topografik Islaklık İndeksi (TWI)
- Akarsu ağı haritası
- Morfolojik birimler
- Topografik Pozisyon İndeksi (TPI)
- Rölyef enerjisi haritası

## DEM Kaynakları

Stabil sürümde kimlik doğrulama gerektiren ve QGIS üzerinde kararsız davranabilen kaynaklar arayüzden kaldırılmıştır. Aktif DEM seçenekleri şunlardır:

- Copernicus DEM GLO-30
- OpenTopography 30 m
- OpenTopography 90 m
- TanDEM-X 90 m yerel dosya
- Kullanıcı yerel DEM dosyası

Yerel DEM için desteklenen yaygın formatlar:

- GeoTIFF
- HGT
- IMG
- ASCII Grid
- VRT
- NetCDF
- HDF5

## Akarsu Verisi

Akarsu verisi OSM tabanlıdır. Öncelikli yöntem Overpass API sorgusudur. Büyük alanlarda veya API erişiminde sorun yaşanırsa GDAL/OGR üzerinden Geofabrik PBF işleme yolu kullanılabilir.

Desteklenen OSM `waterway` sınıfları:

- river
- stream
- canal
- drain
- tidal_channel

Akarsular çalışma alanına kırpılır ve haritada daha görünür olacak şekilde çizgi sembolojisiyle gösterilir.

## Önbellek Sistemi

Eklenti DEM ve akarsu verilerini çalışma alanına göre önbelleğe alır. Aynı il/ilçe ve aynı veri kaynağı yeniden kullanıldığında veri tekrar indirilmez, önbellekten okunur.

Varsayılan önbellek süresi 30 gündür. Kullanıcı bu süreyi panelden değiştirebilir.

Önbellekte saklanan veri türleri:

- Kırpılmış DEM
- Kırpılmış akarsu GeoPackage dosyaları

Kullanıcı istediğinde `Önbelleği Temizle` düğmesiyle tüm önbelleği silebilir.

## Layout ve Harita Tasarımı

Her üretilen harita için ayrı bir QGIS layout oluşturulur. Layoutlar QGIS Layout Manager içinde düzenlenebilir durumdadır.

Layout yaklaşımı:

- Başlık Türkçe ve harita türüne özel üretilir.
- Lejant başlığı `Açıklamalar` olarak kullanılır.
- Harita çerçevesi, açıklamalar, kuzey oku ve ölçek profesyonel tez haritası düzenine göre yerleştirilir.
- Harita alanı sayfaya taşmayacak şekilde hesaplanır.
- Lejant yalnızca ilgili haritanın katmanlarını gösterecek şekilde hazırlanır.
- Kullanıcı sonradan katman eklemek veya layout üzerinde değişiklik yapmak isterse QGIS içinde düzenlemeye devam edebilir.

## Dışa Aktarma

Dışa aktarma işlemi yalnızca `Dışa Aktarma` sekmesinden yapılır. `Üretim & Temizlik` sekmesi sadece harita üretimi, durdurma ve önbellek yönetimi içindir.

Varsayılan açık formatlar:

- PDF
- QGIS Projesi

İsteğe bağlı formatlar:

- PNG
- SVG
- GeoTIFF
- Vektör verileri
- Manifest CSV
- ZIP teslim paketi

Bu yapı özellikle stabilite için tercih edilmiştir. Büyük illerde veya çok sayıda layoutta önce PDF + QGIS projesi alınması önerilir. Görsel çıktı gerekiyorsa PNG için önce 150 veya 300 DPI denenmelidir.

## İstatistik ve Rapor

İstatistik sekmesi analiz sonuçlarını tez yazımına uygun şekilde özetlemek için tasarlanmıştır.

Rapor çıktıları:

- CSV istatistik tablosu
- HTML rapor
- TXT yorum metni

Rapor içeriği çalışma alanına göre şu başlıkları destekler:

- DEM temel istatistikleri
- Minimum, maksimum ve ortalama yükselti
- Hipsometrik integral
- Eğim ve morfometrik yorumlar
- Üretilen harita türlerine göre açıklama metinleri

## Kurulum

1. `TurkeyGeoMorphAnalyst.zip` dosyasını indirin.
2. QGIS'i açın.
3. İngilizce QGIS arayüzünde `Plugins > Manage and Install Plugins > Install from ZIP` yolunu izleyin.
4. ZIP dosyasını seçin.
5. Eklentiyi etkinleştirin.
6. Eklentiyi QGIS ana menüsünde `Raster > TurkeyGeoMorph Analyst` altından veya araç çubuğundaki `TurkeyGeoMorph Analyst` ikonundan açın.

Alternatif manuel kurulum:

1. `TurkeyGeoMorphAnalyst` klasörünü QGIS eklenti klasörüne kopyalayın.
2. Windows için tipik yol:

   ```text
   %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\TurkeyGeoMorphAnalyst
   ```

3. QGIS'i yeniden başlatın.
4. Eklentiyi `Plugins > Manage and Install Plugins` menüsünden etkinleştirin.
5. Eklentiyi kullanmak için `Raster > TurkeyGeoMorph Analyst` menüsünü açın.

## Sistem Gereksinimleri

- QGIS 3.16 veya üzeri
- Önerilen QGIS sürümleri: 3.28, 3.34, 3.36 ve üzeri
- İnternet bağlantısı
- Copernicus veya OpenTopography kullanımı için yeterli disk alanı
- Büyük iller için en az 8 GB RAM önerilir

## Bağımlılık Politikası

Bu eklenti pip, conda veya harici Python paketi kullanmaz.

Kullanılan bileşenler:

- PyQGIS
- QGIS Processing Framework
- PyQt5
- GDAL/OGR/OSR
- Python standart kütüphanesi

SAGA algoritmaları QGIS kurulumunda mevcutsa bazı morfometrik analizlerde kullanılabilir. SAGA yoksa eklenti uyarı verir ve GDAL tabanlı yedek yöntemlerle devam eder.

## Hızlı Kullanım

1. `Çalışma Alanı` sekmesinde il veya ilçe seçin.
2. Çıktı klasörünü belirleyin.
3. Proje adını yazın.
4. `Veri İndirme` sekmesinde DEM kaynağını seçin.
5. İsterseniz akarsu verisini etkinleştirin.
6. `Harita Üretimi` sekmesinde üretilecek haritaları işaretleyin.
7. `Üretim & Temizlik` sekmesinden `Seçili Haritaları Üret` düğmesine basın.
8. İşlem bitince layoutları QGIS Layout Manager içinde kontrol edin.
9. `Dışa Aktarma` sekmesinden PDF ve QGIS projesini kaydedin.
10. `İstatistik & Rapor` sekmesinden rapor çıktısını alın.

## Önerilen İş Akışı

Tez veya ödev haritaları için önerilen güvenli iş akışı:

1. Önce küçük bir il veya ilçe ile deneme yapın.
2. Yalnızca Yükselti, Eğim, Bakı ve Gölgelendirme haritalarını üretin.
3. Layoutların doğru oluştuğunu kontrol edin.
4. Akarsu verisini açıp tekrar üretin.
5. Gerekliyse TWI, TPI, Morfolojik Birimler ve Rölyef Enerjisi haritalarını ekleyin.
6. Dışa aktarmada önce PDF + QGIS Projesi alın.
7. Daha sonra gerekirse PNG, SVG veya GeoTIFF seçeneklerini açın.

## Çıktı Klasörü Yapısı

Eklenti çıktı klasöründe düzenli bir yapı oluşturur:

```text
output/
├── raw/
├── processed/
├── maps/
├── exports/
│   └── proje_adi/
│       ├── 01_layout_haritalar/
│       ├── 02_raster_geotiff/
│       ├── 03_vektor_veriler/
│       ├── 04_qgis_proje/
│       └── 05_rapor_istatistik/
└── reports/
```

## Test Senaryoları

Ayrıntılı kurulum ve test adımları için:

```text
TurkeyGeoMorphAnalyst/INSTALL_TESTS.md
```

## Bilinen Notlar

- OpenTopography API için kullanıcı kendi API anahtarını girmelidir.
- TanDEM-X verisi otomatik indirilmez; kullanıcı yerel dosya olarak seçmelidir.
- Büyük illerde raster analizleri uzun sürebilir.
- TWI, TPI ve Morfolojik Birimler gibi analizler SAGA varsa daha kapsamlı çalışır.
- QGIS'in bazı sürümlerinde çok yüksek DPI veya çok büyük layout dışa aktarmaları yavaş olabilir.
- Varsayılan PDF + QGIS projesi akışı bu yüzden daha güvenli seçilmiştir.

## Geliştirici

Author: Ali Ganigülü  
Email: aliganigulu44@gmail.com

Powered By AGLSOFT - Ali Ganigülü™

## Lisans

Bu proje akademik çalışma, eğitim ve tez haritalama süreçlerinde kullanılmak üzere hazırlanmıştır. Kullanım ve dağıtım koşullarını belirlemek için depoya ayrıca bir `LICENSE` dosyası eklenmesi önerilir.
