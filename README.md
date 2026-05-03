# fidel.io — Dynamic Routing

Kargo dağıtım süreçlerinde en büyük verimsizlik, iade kargolarının yönetimidir. Geleneksel sistemlerde kurye sahaya çıktıktan sonra ortaya çıkan iade talepleri depoya dönerek tekrar rota oluşturulmasını gerektirir; bu da hem ekstra km hem de zaman kaybı demektir.

**fidel.io**, saha görevini sürdüren kuryelere iade kargolarını anlık ve akıllı biçimde yeniden atar. Kurye henüz müşteriye yakınken rotasına minimum ek mesafeyle iade noktası eklenir. Böylece depo dönüşü olmadan aynı gün içinde iade teslim alınmış olur.

## Nasıl Çalışır?

Simülasyon gerçek zamanlı olarak Karabük merkez yol ağında akar:

- Kuryeler sabah hubdan çıkar, teslimat durakları arasında ilerler.
- Gün içinde müşterilerden iade talepleri gelir.
- Bir kurye iade noktasına 2 km yaklaştığında sistem devreye girer ve **Best Insertion** algoritması o iade noktasını kurye rotasına en az maliyetle ekler.
- Simülasyon sonunda **Klasik vs Dinamik** km karşılaştırması gösterilir.

## Kurulum

**Backend:**

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend:**

```powershell
cd frontend
npm install
npm run dev
```

İlk çalıştırmada OSMnx Karabük yol grafiğini indirir ve `backend/data/karabuk_drive.graphml` olarak önbelleğe alır.
