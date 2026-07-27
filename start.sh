#!/bin/bash
# Render için başlangıç scripti
echo "Uygulama başlatılıyor..."

# Veritabanı tablolarını oluştur
python -c "
from app import app, db, create_tables
with app.app_context():
    try:
        db.create_all()
        print('Veritabanı tabloları oluşturuldu!')
    except Exception as e:
        print(f'Veritabanı hatası: {e}')
"

# Uygulamayı başlat
echo "Gunicorn başlatılıyor..."
gunicorn app:app
