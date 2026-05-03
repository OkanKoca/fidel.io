# Algoritma Değişiklik Günlüğü

---

## [2026-05-03] Cargo Atama Sıralaması: FFD → Distance-First → FFD (geri alındı)

> **Karar:** Distance-first Karabük gibi küçük şehirlerde anlamlı zon oluşturmuyor.
> Kapasite kullanımı FFD'de daha iyi. Asıl rota sorunu için 2-opt planlandı.

## [2026-05-03] Cargo Atama Sıralaması: FFD → Distance-First (REVERTED)

### Değişen Dosya
`backend/main.py` — `assign_cargos_geographic()` fonksiyonu

---

### Eski Yöntem: FFD (Largest-Desi First)

```python
sorted_items = sorted(cargo_nodes, key=lambda x: x[0].desi, reverse=True)
```

**Nasıl çalışıyordu:**
- Kargolar ağırlığa (desi) göre büyükten küçüğe sıralanırdı.
- Her araç, frontier'ına (başlangıçta hub) en yakın kargoyu alırdı.
- Büyük bir kargo uzak bir noktadaysa frontier oraya zıplardı.
- Kalan küçük kargolar o uzak frontier'a göre kümelenirdi.

**Problemi:**
- Büyük desi'li kargo kuzey uçta → frontier kuzey uca gider.
- Sonraki küçük kargolar kuzey bölgesine yığılır, araç çok uzağa çıkar.
- Desi ağırlığı coğrafi mantığı bozar: ağır kargo neredeyse tüm bölge oraya kayar.
- Sonuç: bazı araçlar hub'dan çok uzak rotalar çizer (pembe rota sorunu).

---

### Yeni Yöntem: Distance-First (Farthest-from-Hub First)

```python
hub_lat, hub_lon = node_lat_lon(hub_node)
sorted_items = sorted(
    cargo_nodes,
    key=lambda x: haversine_km(hub_lat, hub_lon, *node_lat_lon(x[1])),
    reverse=True,  # hub'dan en uzak kargo önce
)
```

**Nasıl çalışıyor:**
- Kargolar hub'a olan haversine mesafesine göre uzaktan yakına sıralanır.
- En uzak kargolar önce atanır → frontier coğrafi bölgeyi doğal olarak tanımlar.
- Her araç kendine en yakın uzak bölgeyi sahiplenir, sonra çevresini doldurur.
- Desi kapasitesi aşılırsa kargo bir sonraki araca geçer (bu kısım değişmedi).

**İyileştirme:**
- Kargo ağırlığı bölge atamasını artık etkilemez.
- Hub'dan uzak duraklar aynı araca düşer → zikzak azalır.
- Araçlar daha tutarlı coğrafi zonlar oluşturur.
- Ortalama rota uzunluğu düşer, çakışan güzergahlar azalır.

**Tradeoff:**
- Kapasite doluluk oranı FFD'ye kıyasla hafif düşebilir (büyük kargo önce
  yerleştirme garantisi kalktı). Bunu telafi etmek için nearest-neighbor
  sıralaması hâlâ her araç içinde çalışmaya devam eder.

---

## [2026-05-03] Tick Endpoint: sim_elapsed_seconds Güncellenmiyordu

### Değişen Dosya
`backend/main.py` — `/api/sim/tick` endpoint'i

### Eski Kod
```python
for courier in state.couriers:
    advance_courier(courier, 5.0 * state.speed_multiplier)
state.tick += 1
```

### Yeni Kod
```python
step = 5.0 * state.speed_multiplier
state.sim_elapsed_seconds += step   # ← eksik olan satır
for courier in state.couriers:
    advance_courier(courier, step)
state.tick += 1
```

**Sorun:** İleri sarma butonuna basıldığında araçlar ilerliyor ama simülasyon
saati güncellenmiyordu. `sim_elapsed_seconds` sadece `advance_running_state()`
içinde (otomatik çalışma modunda) artıyordu, tek adım modunda artmıyordu.

---

## [2026-05-03] Yeni Özellik: Klasik vs Dinamik Karşılaştırma Paneli

### Değişen Dosyalar
- `frontend/src/App.jsx` — `ComparisonPanel` bileşeni + `EventsRail` proof tab yeniden yazıldı
- `frontend/src/styles.css` — `.cmp-*` stil sınıfları eklendi

**Önce:** "Kazanç" sekmesinde 3 küçük sayı (saved_tl, saved_km, dynamic_extra_tl)

**Sonra:** İki sütunlu karşılaştırma bloğu
- Sol sütun (kırmızı): KLASİK SİSTEM — her iade için ayrı hub→iade→hub seferi
- Sağ sütun (yeşil): DİNAMİK SİSTEM — Best Insertion ile rotaya ekleme
- Alt banner: net tasarruf km + TL + yüzde
- İade eklenmeden önce "boş durum" mesajı gösterilir
- Atama detayları accordion olarak altta korundu

**Veri kaynağı:** `owner_metrics` — backend `classic_route_metrics()` fonksiyonu ile
gerçekçi klasik model hesaplanıyor (bkz. aşağıdaki değişiklik).

---

## [2026-05-03] Klasik Baseline Hesabı Düzeltildi: Per-Return → Toplu Tur

### Değişen Dosyalar
- `backend/main.py` — `classic_route_metrics()` fonksiyonu eklendi, `owner_metrics()` güncellendi
- `frontend/src/App.jsx` — `ComparisonPanel` yeni alanları kullanıyor

**Eski (yanlış):**
Her iade için ayrı `hub → iade → hub` hesaplanıp toplandı.
Gerçekte bu hiç yapılmaz — 5 iade için 5 ayrı sefer yok.

**Yeni (gerçekçi):**
`classic_route_metrics()` fonksiyonu:
1. Günün tüm iadeleri toplanır
2. `CLASSIC_VEHICLE_CAPACITY_DESI` (150 desi) kapasiteli araçlara doldurulur
3. Her araç için hub çıkış → NN sıralaması → hub dönüş mesafesi hesaplanır
4. Kapasite aşılırsa araç sayısı artar (gerçek operasyon gibi)

**Yeni alanlar:** `classic_km`, `classic_tl`, `classic_vehicles`
**Kaldırılan alanlar:** `baseline_pickup_km`, `baseline_pickup_tl`, `total_extra_km`

**Ayrıca düzeltildi:** `add_vehicle` endpoint'inde `await try_reload_from_hub` → 
`try_reload_from_hub` (fonksiyon async değil).

---

## [2026-05-03] Yeni Özellik: Filoya Araç Ekleme

### Değişen Dosyalar
- `backend/main.py` — `AddVehicleRequest` modeli + `/api/sim/add_vehicle` endpoint
- `frontend/src/App.jsx` — `FleetRail` bileşenine araç ekleme UI'ı

**Davranış:** Simülasyon başlatıldıktan sonra sol panelden yeni araç eklenebilir.
Yeni araç hub konumundan başlar, kapasitesi belirtilir, hub'da bekleyen kargo
varsa otomatik olarak yüklenir.
