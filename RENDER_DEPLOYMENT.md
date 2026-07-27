# QuestWay - Render Deployment Rehberi

## 🚀 Render'da Deploy Etme Adımları

### 1. Render Hesabı Oluşturma
- [Render.com](https://render.com) adresine gidin
- GitHub hesabınızla giriş yapın
- "New +" butonuna tıklayın ve "Web Service" seçin

### 2. Repository Bağlama
- GitHub repository'nizi seçin
- Branch: `main` (veya ana branch'iniz)
- Root Directory: boş bırakın (proje root'unda)

### 3. Build & Deploy Ayarları
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app`
- **Python Version**: 3.11.9 (runtime.txt dosyasından otomatik algılanacak)

### 4. Environment Variables Ayarlama
Render dashboard'da "Environment" sekmesine gidin ve şu değişkenleri ekleyin:

```
SECRET_KEY=your-very-secret-key-here-make-it-long-and-random
DATABASE_URL=postgresql://username:password@hostname:port/database_name
```

**Not**: DATABASE_URL Render tarafından otomatik oluşturulacak PostgreSQL veritabanı için.

### 5. PostgreSQL Veritabanı Oluşturma
- Render dashboard'da "New +" → "PostgreSQL" seçin
- Veritabanı adını girin (örn: `questway-db`)
- Plan seçin (Free tier mevcut)
- Veritabanı oluşturulduktan sonra "Internal Database URL"i kopyalayın
- Bu URL'yi web service'inizin DATABASE_URL environment variable'ına yapıştırın

### 6. Deploy Etme
- "Create Web Service" butonuna tıklayın
- Deploy işlemi 5-10 dakika sürebilir
- Logs sekmesinden deploy durumunu takip edebilirsiniz

## ✅ Deploy Sonrası Kontroller

### 1. Veritabanı Tabloları
Deploy tamamlandıktan sonra, uygulamanız otomatik olarak veritabanı tablolarını oluşturacak.

### 2. Test Etme
- Ana sayfa: `https://your-app-name.onrender.com`
- Kayıt olma ve giriş yapma
- Review ekleme
- Wishlist oluşturma
- Itinerary oluşturma

## 🔧 Olası Sorunlar ve Çözümleri

### 1. Build Hatası
- `requirements.txt` dosyasındaki paket versiyonlarını kontrol edin
- Python versiyonunun 3.11.9 olduğundan emin olun

### 2. Veritabanı Bağlantı Hatası
- DATABASE_URL environment variable'ının doğru olduğundan emin olun
- PostgreSQL servisinin çalıştığından emin olun

### 3. Static Files Hatası
- Static dosyalarınızın `static/` klasöründe olduğundan emin olun
- CSS ve JS dosyalarının yollarını kontrol edin

## 📁 Proje Yapısı
```
questway/
├── app.py                 # Ana Flask uygulaması
├── models.py             # Veritabanı modelleri
├── forms.py              # WTForms formları
├── requirements.txt      # Python paketleri
├── Procfile             # Render için start command
├── runtime.txt          # Python versiyonu
├── static/              # CSS, JS, resimler
├── templates/           # HTML şablonları
└── instance/            # SQLite veritabanı (local)
```

## 🎯 Özellikler
- ✅ Kullanıcı kayıt/giriş sistemi
- ✅ Review sistemi (ülke/şehir bazlı)
- ✅ Wishlist (istek listesi)
- ✅ Itinerary (seyahat planı) oluşturma
- ✅ Arama ve filtreleme
- ✅ Responsive tasarım
- ✅ PostgreSQL desteği

## 💡 İpuçları
- Free tier'da uygulama 15 dakika inaktiviteden sonra uyku moduna geçer
- İlk açılış 30-60 saniye sürebilir
- Production'da SECRET_KEY'i güçlü bir değerle değiştirin
- Logs sekmesinden hataları takip edebilirsiniz

## 🆘 Destek
Herhangi bir sorun yaşarsanız:
1. Render logs'unu kontrol edin
2. Environment variables'ları doğrulayın
3. Veritabanı bağlantısını test edin
4. GitHub repository'nizdeki son değişiklikleri kontrol edin
