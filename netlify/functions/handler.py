import os
import sys

# Tambahkan direktori proyek ke Python path agar bisa mengimpor app
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, PROJECT_ROOT)

from app import app as application # Impor aplikasi Flask Anda

def handler(event, context):
    """
    Handler function yang dipanggil oleh Netlify.
    Meneruskan permintaan ke aplikasi Flask.
    """
    # Secara sederhana, untuk contoh ini, kita tidak benar-benar "menjalankan" seluruh aplikasi Flask
    # untuk setiap permintaan. Biasanya, Anda akan menggunakan library seperti `wsgi-adapter`
    # untuk menjalankan aplikasi WSGI Flask di lingkungan serverless.

    # Contoh sederhana (tidak berfungsi penuh untuk semua jenis permintaan Flask):
    path = event.get('path', '/')
    method = event.get('httpMethod', 'GET').upper()
    headers = event.get('headers', {})
    body = event.get('body', None)

    # Implementasi yang lebih lengkap memerlukan WSGI adapter.
    # Namun, untuk contoh sederhana, kita bisa mencoba mengembalikan respons statis.
    if path == '/':
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/plain'},
            'body': 'Aplikasi Flask Anda berjalan di Netlify Function (sederhana)!'
        }
    else:
        return {
            'statusCode': 404,
            'body': 'Not Found'
        }

    # Implementasi yang benar akan melibatkan menjalankan aplikasi Flask WSGI
    # dan menerjemahkan antara format Netlify event/context dan WSGI environ/start_response.