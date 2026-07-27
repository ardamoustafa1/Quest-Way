# Vercel Deployment Guide

Bu proje artık Vercel'de deploy edilmeye hazır!

## 🚀 Hızlı Başlangıç

### 1. Vercel CLI ile Deploy

```bash
# Vercel CLI'yi yükle (eğer yoksa)
npm install -g vercel

# Projeyi deploy et
vercel

# Production'a deploy et
vercel --prod
```

### 2. GitHub ile Deploy

1. Projeyi GitHub'a push edin
2. [vercel.com](https://vercel.com) adresine gidin
3. GitHub hesabınızla giriş yapın
4. "Add New Project" butonuna tıklayın
5. Repository'nizi seçin
6. Ayarları yapılandırın ve "Deploy" butonuna tıklayın

## ⚙️ Ortam Değişkenleri

Vercel dashboard'unda aşağıdaki ortam değişkenlerini ayarlayın:

### Zorunlu Değişkenler

- `SECRET_KEY`: Flask için gizli anahtar (güçlü bir rastgele string)
- `DATABASE_URL`: PostgreSQL veritabanı URL'si (Vercel Postgres kullanabilirsiniz)

### Örnek SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 🗄️ Veritabanı Konfigürasyonu

### Seçenek 1: Vercel Postgres (Önerilen)

1. Vercel dashboard'unda projenize gidin
2. "Storage" sekmesine tıklayın
3. "Create Database" > "Postgres" seçin
4. Veritabanını oluşturun
5. `DATABASE_URL` otomatik olarak ortam değişkeni olarak eklenir

### Seçenek 2: Harici PostgreSQL

1. [Supabase](https://supabase.com), [Neon](https://neon.tech) veya başka bir PostgreSQL servisi kullanın
2. Veritabanı URL'sini alın
3. Vercel dashboard'unda `DATABASE_URL` ortam değişkenini ekleyin

### Seçenek 3: SQLite (Önerilmez)

Vercel serverless fonksiyonlarda SQLite kullanılması önerilmez çünkü:
- Dosya sistemi kalıcı değil
- Her fonksiyon çağrısında sıfırlanır

## 📁 Proje Yapısı

Deployment için önemli dosyalar:

- `vercel.json`: Vercel konfigürasyonu
- `vercel.py`: Serverless fonksiyon wrapper
- `app.py`: Ana Flask uygulaması
- `requirements.txt`: Python bağımlılıkları
- `.vercelignore`: Deployment'a dahil edilmeyecek dosyalar

## 🔍 Sorun Giderme

### Database bağlantı hatası

Eğer veritabanı bağlantı hatası alırsanız:

1. `DATABASE_URL` ortam değişkeninin doğru ayarlandığından emin olun
2. PostgreSQL URL'si `postgresql://` ile başlamalı (postgres:// değil)
3. Veritabanı bağlantı limitlerini kontrol edin

### Static dosyalar yüklenmiyor

1. `static/` klasörünün doğru yerde olduğundan emin olun
2. `vercel.json` dosyasında static route'un doğru ayarlandığını kontrol edin

### Build hatası

1. `requirements.txt` dosyasını kontrol edin
2. Vercel build loglarını inceleyin
3. Python versiyonunun uyumlu olduğundan emin olun

## 🔐 Güvenlik Notları

1. **SECRET_KEY**: Asla commit etmeyin, her zaman ortam değişkeni olarak kullanın
2. **Veritabanı**: Production'da mutlaka şifrelenmiş bağlantı kullanın
3. **HTTPS**: Vercel otomatik olarak HTTPS sağlar

## 📊 Performans

- Cold start: İlk istek biraz yavaş olabilir
- Keep warm: Pro plan kullanıcıları için keep-warm fonksiyonu mevcut
- Database pooling: Connection pooling kullanın

## 🔗 Yararlı Linkler

- [Vercel Dokümantasyonu](https://vercel.com/docs)
- [Vercel Python Runtime](https://vercel.com/docs/concepts/functions/serverless-functions/runtimes/python)
- [Flask Deploy Guide](https://vercel.com/guides/deploying-flask-with-vercel)

## 📝 Notlar

- Vercel serverless fonksiyonlar 10 saniye timeout'a sahiptir
- Her deployment yeni bir build oluşturur
- Preview deployment'lar her branch için otomatik oluşturulur
- Production deployment: `main` branch'e push yaptığınızda otomatik olur

