"""
Vercel serverless function wrapper for Flask app
"""
import os
import sys

# Set Vercel environment variable BEFORE importing app
os.environ['VERCEL'] = '1'

# Get the directory where this file is located (api/)
current_file = os.path.abspath(__file__)
api_dir = os.path.dirname(current_file)
# Get the parent directory (project root)
project_root = os.path.dirname(api_dir)

# Add project root to Python path
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Change working directory to project root for relative imports
try:
    os.chdir(project_root)
except:
    pass

# Now import the Flask app
try:
    from app import app, db

    # Ensure tables exist on cold start. db.create_all() is idempotent
    # (CREATE TABLE IF NOT EXISTS-equivalent), so this is safe to run on
    # every cold start rather than only once.
    try:
        with app.app_context():
            db.create_all()
    except Exception as e:
        print(f"Database table creation error: {e}")

    # Export handler for Vercel
    # Vercel's @vercel/python runtime automatically detects Flask apps
    handler = app
    
except ImportError as e:
    import traceback
    error_msg = f"Import error: {str(e)}\n{traceback.format_exc()}"
    print(error_msg)
    
    # Create minimal error app
    from flask import Flask, jsonify
    error_app = Flask(__name__)
    
    @error_app.route('/', defaults={'path': ''})
    @error_app.route('/<path:path>')
    def error_handler(path):
        return jsonify({
            'error': 'Server configuration error',
            'message': str(e),
            'path': project_root,
            'sys_path': sys.path
        }), 500
    
    handler = error_app

except Exception as e:
    import traceback
    error_msg = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
    print(error_msg)
    
    from flask import Flask, jsonify
    error_app = Flask(__name__)
    
    @error_app.route('/', defaults={'path': ''})
    @error_app.route('/<path:path>')
    def error_handler(path):
        return jsonify({
            'error': 'Server startup error',
            'message': str(e),
            'type': type(e).__name__
        }), 500
    
    handler = error_app

