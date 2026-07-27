# Bad Gateway Hatası Çözüm Rehberi

## 🚨 Bad Gateway Hatası Nedir?
Bad Gateway (502) hatası, Render'da uygulamanızın başlatılamadığı veya çalışmadığı anlamına gelir.

## 🔍 Hata Sebepleri ve Çözümleri

### 1. **Veritabanı Bağlantı Sorunu**
**Sebepler:**
- PostgreSQL veritabanı bağlantısı kurulamıyor
- DATABASE_URL environment variable eksik veya yanlış
- Veritabanı tabloları oluşturulmamış

**Çözüm:**
- Render dashboard'da PostgreSQL servisi oluşturun
- DATABASE_URL environment variable'ını ekleyin
- Uygulama otomatik olarak tabloları oluşturacak

### 2. **Uygulama Başlatma Hatası**
**Sebepler:**
- Python paketleri yüklenemiyor
- Import hataları
- Port bağlantı sorunu

**Çözüm:**
- Requirements.txt'deki paketleri kontrol edin
- Logs sekmesinden hata mesajlarını okuyun

### 3. **Environment Variables Eksik**
**Sebepler:**
- SECRET_KEY tanımlanmamış
- DATABASE_URL tanımlanmamış

**Çözüm:**
- Render dashboard'da Environment sekmesine gidin
- Gerekli environment variables'ları ekleyin

## 🛠️ Adım Adım Çözüm

### Adım 1: Render Logs Kontrol
1. Render dashboard'da projenize gidin
2. "Logs" sekmesine tıklayın
3. Hata mesajlarını okuyun
4. En son hata mesajını not edin

### Adım 2: Environment Variables Kontrol
Render dashboard'da Environment sekmesinde şunlar olmalı:
```
SECRET_KEY=your-very-secret-key-here
DATABASE_URL=postgresql://username:password@hostname:port/database
```

### Adım 3: PostgreSQL Veritabanı Kontrol
1. Render dashboard'da "New +" → "PostgreSQL" seçin
2. Veritabanı adını girin
3. Plan seçin (Free tier mevcut)
4. Veritabanı oluşturulduktan sonra URL'yi kopyalayın
5. Web service'inizin DATABASE_URL'ine yapıştırın

### Adım 4: Uygulamayı Yeniden Deploy
1. "Manual Deploy" → "Deploy latest commit" seçin
2. Deploy işlemini bekleyin
3. Logs'u takip edin

## 🔧 Yapılan Düzeltmeler

### 1. **init_db() Fonksiyonu Düzeltildi**
- SQLite sadece local development için kullanılıyor
- PostgreSQL için uyumlu hale getirildi

### 2. **Hata Yakalama Eklendi**
- Try-catch blokları eklendi
- Uygulama hata olsa bile çalışmaya devam ediyor

### 3. **start.sh Scripti Eklendi**
- Veritabanı tablolarını otomatik oluşturuyor
- Gunicorn'u güvenli şekilde başlatıyor

## 📋 Kontrol Listesi

- [ ] PostgreSQL veritabanı oluşturuldu
- [ ] DATABASE_URL environment variable eklendi
- [ ] SECRET_KEY environment variable eklendi
- [ ] Uygulama yeniden deploy edildi
- [ ] Logs kontrol edildi
- [ ] Site erişilebilir durumda

## 🆘 Hala Çalışmıyorsa

1. **Logs'u kontrol edin** - En önemli adım
2. **Environment variables'ları doğrulayın**
3. **PostgreSQL bağlantısını test edin**
4. **Manual deploy yapın**
5. **Render support'a başvurun**

## 💡 İpuçları

- Free tier'da uygulama 15 dakika inaktiviteden sonra uyku moduna geçer
- İlk açılış 30-60 saniye sürebilir
- Logs sekmesinden gerçek zamanlı hata takibi yapabilirsiniz
- Environment variables değiştikten sonra mutlaka yeniden deploy edin
