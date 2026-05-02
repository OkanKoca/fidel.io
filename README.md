# Dinamik Kargo Rotalama Demo

FastAPI + React/Vite tabanlı OSRM destekli demo:

- Araç sayısı ve desi kapasiteleri kullanıcıdan alınır.
- Karabük Merkez için seed'li rastgele teslimat durakları üretilir.
- İadeler havuza eklenir, hemen atanmaz.
- Tick ilerledikçe yakınlık tetikleyici çalışır.
- OSRM Table API Best Insertion kararını verir.
- OSRM Route API frontend polyline verisini üretir.

## Çalıştırma

Backend:

```powershell
cd backend
python -m pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

OSRM varsayılan adresi:

```text
http://127.0.0.1:5000
```

Farklı adres için backend'i `OSRM_BASE_URL` ortam değişkeniyle başlatın.

OSRM çalışmıyorsa demo durmaz. Backend varsayılan olarak Haversine mesafe matrisi ve düz çizgi polyline fallback'i kullanır. Bunu kapatmak için:

```powershell
$env:OSRM_FALLBACK_ENABLED="false"
```
