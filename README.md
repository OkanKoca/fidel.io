# Dinamik Kargo Rotalama Demo

FastAPI + React/Vite tabanli OSM graph destekli demo:

- Arac sayisi ve desi kapasiteleri kullanicidan alinir.
- Karabuk Merkez icin seed'li rastgele teslimat duraklari OSM yol graph'ina snap edilir.
- Iadeler havuza eklenir, hemen atanmaz.
- Backend graph uzerinde araclari canli ilerletir.
- Yakinlik tetikleyici calisinca Best Insertion iade noktasini rotaya ekler.
- Rota mesafeleri NetworkX shortest path length ile hesaplanir.
- Ilk calistirmada OSMnx graph olusturulur ve `backend/data/karabuk_drive.graphml` olarak cache'lenir.

## Calistirma

Backend:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Canli hareket hizi varsayilan olarak 35 km/s'dir. Degistirmek icin:

```powershell
$env:SIM_SPEED_KMH="50"
```

Graph cache yolunu degistirmek icin:

```powershell
$env:GRAPH_CACHE_PATH="backend/data/karabuk_drive.graphml"
```

Graph bolgesini degistirmek icin:

```powershell
$env:GRAPH_PLACE="Karabuk Merkez, Karabuk, Turkiye"
```
