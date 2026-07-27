from flask import Blueprint, jsonify
import requests
from app import cache, fetch_current_weather

weather_bp = Blueprint('weather', __name__)


@weather_bp.route('/weather/<country>/<city>')
@cache.memoize(timeout=1800)  # 30 dakika - hava durumu bu sıklıkta yenilense yeterli
def get_weather(country, city):
    try:
        weather = fetch_current_weather(country, city)
        if not weather:
            return jsonify({'error': f"Location not found for {city}, {country}"}), 404
        return jsonify(weather)
    except requests.RequestException as e:
        print(f"Weather API error: {e}")
        return jsonify({'error': 'Weather service temporarily unavailable'}), 503

@weather_bp.route('/currency/<from_currency>/<to_currency>')
@cache.memoize(timeout=3600)  # 1 saat - döviz kurları bu sıklıkta güncellense yeterli
def get_currency_rate(from_currency, to_currency):
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    try:
        resp = requests.get(
            'https://api.frankfurter.app/latest',
            params={'from': from_currency, 'to': to_currency},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = data.get('rates', {}).get(to_currency)
        if rate is None:
            return jsonify({'error': f'No rate available for {from_currency} -> {to_currency}'}), 404
        return jsonify({
            'from': from_currency,
            'to': to_currency,
            'rate': rate,
            'date': data.get('date'),
            'source': 'frankfurter.app (European Central Bank)',
        })
    except requests.RequestException as e:
        print(f"Currency API error: {e}")
        return jsonify({'error': 'Currency service temporarily unavailable'}), 503
