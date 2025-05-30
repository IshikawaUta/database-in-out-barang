import os
from datetime import datetime, timedelta
import calendar
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash # Import session dan flash

from pymongo import MongoClient
from dotenv import load_dotenv

# Memuat variabel lingkungan dari file .env
load_dotenv()

app = Flask(__name__)

# --- Konfigurasi Sesi ---
# Secret key diperlukan untuk mengamankan sesi Flask.
# Ambil dari variabel lingkungan atau gunakan default (HANYA UNTUK PENGEMBANGAN).
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key_if_env_not_set")
if app.secret_key == "fallback_secret_key_if_env_not_set":
    print("Peringatan: SECRET_KEY tidak diatur di .env. Menggunakan kunci default yang tidak aman.")

# --- Kredensial Admin (dari .env) ---
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "password")

# --- Konfigurasi MongoDB ---
MONGO_URI = os.environ.get("MONGO_URI")
DATABASE_NAME = os.environ.get("DATABASE_NAME")

if not MONGO_URI or not DATABASE_NAME:
    raise ValueError("MONGO_URI dan DATABASE_NAME harus diatur di file .env")

try:
    client = MongoClient(MONGO_URI)
    db = client[DATABASE_NAME]
    inventory_collection = db["inventory"]
    transactions_collection = db["transactions"]
    print("Koneksi ke MongoDB berhasil!")
except Exception as e:
    print(f"Gagal terhubung ke MongoDB: {e}")

# --- Fungsi Pembantu ---
def calculate_daily_stock(date_to_calculate):
    """
    Menghitung stok akhir, barang masuk, dan barang keluar untuk setiap barang
    pada tanggal tertentu.
    """
    start_of_day = datetime.combine(date_to_calculate, datetime.min.time())
    end_of_day = datetime.combine(date_to_calculate, datetime.max.time())

    initial_stocks = {
        item['_id']: item.get('initial_stock', 0)
        for item in inventory_collection.find({}, {"_id": 1, "initial_stock": 1})
    }

    pipeline_final_stock = [
        {
            "$match": {
                "timestamp": {"$lte": end_of_day}
            }
        },
        {
            "$group": {
                "_id": "$item_id",
                "total_in_overall": {"$sum": {"$cond": [{"$eq": ["$type", "masuk"]}, "$quantity", 0]}},
                "total_out_overall": {"$sum": {"$cond": [{"$eq": ["$type", "keluar"]}, "$quantity", 0]}}
            }
        }
    ]
    overall_transaction_summary = list(transactions_collection.aggregate(pipeline_final_stock))
    overall_net_changes = {
        summary['_id']: summary['total_in_overall'] - summary['total_out_overall']
        for summary in overall_transaction_summary
    }

    pipeline_daily_in_out = [
        {
            "$match": {
                "timestamp": {"$gte": start_of_day, "$lte": end_of_day}
            }
        },
        {
            "$group": {
                "_id": "$item_id",
                "daily_in": {"$sum": {"$cond": [{"$eq": ["$type", "masuk"]}, "$quantity", 0]}},
                "daily_out": {"$sum": {"$cond": [{"$eq": ["$type", "keluar"]}, "$quantity", 0]}}
            }
        }
    ]
    daily_transaction_summary = list(transactions_collection.aggregate(pipeline_daily_in_out))
    daily_in_out_data = {
        summary['_id']: {'in': summary['daily_in'], 'out': summary['daily_out']}
        for summary in daily_transaction_summary
    }

    daily_stock_results = {}
    for item_id, initial_stock in initial_stocks.items():
        final_stock = initial_stock + overall_net_changes.get(item_id, 0)
        daily_in = daily_in_out_data.get(item_id, {}).get('in', 0)
        daily_out = daily_in_out_data.get(item_id, {}).get('out', 0)

        daily_stock_results[item_id] = {
            'stock_akhir': final_stock,
            'barang_masuk_hari_ini': daily_in,
            'barang_keluar_hari_ini': daily_out
        }
    return daily_stock_results

# --- Rute Aplikasi ---
@app.route('/', methods=['GET', 'POST'])
def index():
    # Proteksi rute POST untuk menambah barang
    if request.method == 'POST':
        if 'logged_in' not in session or not session['logged_in']:
            flash("Anda harus login sebagai admin untuk menambah barang.", "error")
            return redirect(url_for('login'))

        item_id = request.form['item_id'].strip()
        item_name = request.form['item_name'].strip()
        stock_awal = int(request.form['stock_awal'])
        item_creation_date_str = request.form['item_creation_date']
        try:
            item_creation_date = datetime.strptime(item_creation_date_str, '%Y-%m-%d')
        except ValueError:
            flash("Format tanggal penambahan barang tidak valid.", "error")
            items = inventory_collection.find().sort("name", 1)
            return render_template('index.html', items=items, error="Format tanggal penambahan barang tidak valid.", page='home')

        print(f"Menerima permintaan POST untuk menambah barang: ID={item_id}, Nama={item_name}, Stok Awal={stock_awal}, Tanggal Penambahan={item_creation_date.strftime('%Y-%m-%d')}")

        if not item_id or not item_name:
            flash("ID Barang dan Nama Barang tidak boleh kosong.", "error")
            items = inventory_collection.find().sort("name", 1)
            return render_template('index.html', items=items, error="ID Barang dan Nama Barang tidak boleh kosong.", page='home')

        if inventory_collection.find_one({"_id": item_id}):
            flash(f"ID Barang '{item_id}' sudah ada. Gunakan ID lain.", "error")
            items = inventory_collection.find().sort("name", 1)
            return render_template('index.html', items=items, error="ID Barang sudah ada. Gunakan ID lain.", page='home')

        try:
            inventory_collection.insert_one({
                "_id": item_id,
                "name": item_name,
                "stock": stock_awal,
                "initial_stock": stock_awal,
                "creation_date": item_creation_date
            })
            flash(f"Barang '{item_name}' (ID: {item_id}) berhasil ditambahkan.", "success")
            print(f"Barang '{item_name}' (ID: {item_id}) berhasil ditambahkan ke database.")
        except Exception as e:
            flash(f"Gagal menambahkan barang: {e}", "error")
            print(f"Gagal menambahkan barang '{item_name}' (ID: {item_id}) ke database: {e}")
            items = inventory_collection.find().sort("name", 1)
            return render_template('index.html', items=items, error=f"Gagal menambahkan barang: {e}", page='home')

        return redirect(url_for('index'))

    print("Menerima permintaan GET untuk halaman utama. Mengambil daftar barang...")
    items = list(inventory_collection.find().sort("name", 1))
    print(f"Jumlah barang yang diambil dari database: {len(items)}")
    for item in items:
        print(f"  - Barang: {item.get('name')}, ID: {item.get('_id')}, Stok: {item.get('stock')}, Tanggal Dibuat: {item.get('creation_date')}")

    return render_template('index.html', items=items, error=None, page='home', logged_in=session.get('logged_in'))

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    # Proteksi rute
    if 'logged_in' not in session or not session['logged_in']:
        flash("Anda harus login sebagai admin untuk menambah transaksi.", "error")
        return redirect(url_for('login'))

    item_id = request.form['item_id']
    transaction_type = request.form['type']
    quantity = int(request.form['quantity'])
    
    transaction_date_str = request.form['transaction_date']
    try:
        transaction_datetime = datetime.strptime(transaction_date_str, '%Y-%m-%d')
    except ValueError:
        flash("Format tanggal transaksi tidak valid.", "error")
        print(f"Error: Format tanggal tidak valid: {transaction_date_str}")
        return redirect(url_for('index', error="Format tanggal transaksi tidak valid."))

    print(f"Menerima transaksi: Barang ID={item_id}, Tipe={transaction_type}, Jumlah={quantity}, Tanggal={transaction_datetime.strftime('%Y-%m-%d')}")

    item = inventory_collection.find_one({"_id": item_id})
    if not item:
        flash("Barang tidak ditemukan untuk transaksi.", "error")
        print(f"Error: Barang dengan ID '{item_id}' tidak ditemukan untuk transaksi.")
        return redirect(url_for('index', error="Barang tidak ditemukan untuk transaksi."))

    try:
        transactions_collection.insert_one({
            "item_id": item_id,
            "type": transaction_type,
            "quantity": quantity,
            "timestamp": transaction_datetime
        })
        flash(f"Transaksi berhasil dicatat untuk barang ID: {item_id} pada tanggal {transaction_datetime.strftime('%Y-%m-%d')}.", "success")
        print(f"Transaksi berhasil dicatat untuk barang ID: {item_id} pada tanggal {transaction_datetime.strftime('%Y-%m-%d')}.")

        current_stock = item['stock']
        if transaction_type == 'masuk':
            new_stock = current_stock + quantity
        elif transaction_type == 'keluar':
            new_stock = current_stock - quantity
            if new_stock < 0:
                flash(f"Peringatan: Stok {item['name']} menjadi minus ({new_stock}). Transaksi tetap dicatat.", "warning")
                print(f"Peringatan: Stok {item['name']} menjadi minus ({new_stock}). Transaksi tetap dicatat.")
        inventory_collection.update_one({"_id": item_id}, {"$set": {"stock": new_stock}})
        print(f"Stok barang '{item['name']}' diperbarui menjadi: {new_stock}")

    except Exception as e:
        flash(f"Gagal mencatat transaksi: {e}", "error")
        print(f"Gagal mencatat transaksi atau memperbarui stok: {e}")
        return redirect(url_for('index', error=f"Gagal mencatat transaksi: {e}"))

    return redirect(url_for('index'))

@app.route('/edit_item/<item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    # Proteksi rute
    if 'logged_in' not in session or not session['logged_in']:
        flash("Anda harus login sebagai admin untuk mengedit barang.", "error")
        return redirect(url_for('login'))

    item = inventory_collection.find_one({"_id": item_id})
    if not item:
        flash("Barang tidak ditemukan.", "error")
        print(f"Error: Barang dengan ID '{item_id}' tidak ditemukan untuk diedit.")
        return redirect(url_for('index', error="Barang tidak ditemukan."))

    if request.method == 'POST':
        new_name = request.form['item_name'].strip()
        new_stock = int(request.form['stock_awal'])
        new_creation_date_str = request.form['item_creation_date']
        try:
            new_creation_date = datetime.strptime(new_creation_date_str, '%Y-%m-%d')
        except ValueError:
            flash("Format tanggal penambahan barang tidak valid saat edit.", "error")
            print(f"Error: Format tanggal penambahan barang tidak valid saat edit: {new_creation_date_str}")
            return render_template('edit_item.html', item=item, error="Format tanggal penambahan barang tidak valid.", page='home')

        print(f"Menerima permintaan POST untuk edit barang '{item_id}': Nama Baru={new_name}, Stok Baru={new_stock}, Tanggal Dibuat Baru={new_creation_date.strftime('%Y-%m-%d')}")

        if not new_name:
            flash("Nama Barang tidak boleh kosong.", "error")
            print("Error: Nama Barang kosong saat edit.")
            return render_template('edit_item.html', item=item, error="Nama Barang tidak boleh kosong.")

        try:
            inventory_collection.update_one(
                {"_id": item_id},
                {"$set": {
                    "name": new_name,
                    "stock": new_stock,
                    "initial_stock": new_stock,
                    "creation_date": new_creation_date
                }}
            )
            flash(f"Barang '{item_id}' berhasil diperbarui.", "success")
            print(f"Barang '{item_id}' berhasil diperbarui.")
        except Exception as e:
            flash(f"Gagal memperbarui barang: {e}", "error")
            print(f"Gagal memperbarui barang '{item_id}': {e}")
            return render_template('edit_item.html', item=item, error=f"Gagal memperbarui barang: {e}")

        return redirect(url_for('index'))

    return render_template('edit_item.html', item=item, error=None, logged_in=session.get('logged_in'))

@app.route('/delete_item/<item_id>')
def delete_item(item_id):
    # Proteksi rute
    if 'logged_in' not in session or not session['logged_in']:
        flash("Anda harus login sebagai admin untuk menghapus barang.", "error")
        return redirect(url_for('login'))

    item = inventory_collection.find_one({"_id": item_id})
    if not item:
        flash("Barang tidak ditemukan.", "error")
        print(f"Error: Barang dengan ID '{item_id}' tidak ditemukan untuk dihapus.")
        return redirect(url_for('index', error="Barang tidak ditemukan."))

    print(f"Menerima permintaan hapus untuk barang ID: {item_id}.")

    try:
        transactions_collection.delete_many({"item_id": item_id})
        print(f"Semua transaksi terkait barang '{item_id}' berhasil dihapus.")
        inventory_collection.delete_one({"_id": item_id})
        print(f"Barang '{item_id}' berhasil dihapus dari inventory.")
        flash(f"Barang '{item_id}' dan semua transaksinya berhasil dihapus.", "success")
    except Exception as e:
        flash(f"Gagal menghapus barang: {e}", "error")
        print(f"Gagal menghapus barang '{item_id}' atau transaksinya: {e}")
        return redirect(url_for('index', error=f"Gagal menghapus barang: {e}"))

    return redirect(url_for('index'))

@app.route('/report')
def report():
    current_year = datetime.now().year
    current_month = datetime.now().month

    selected_year = request.args.get('year', type=int, default=current_year)
    selected_month = request.args.get('month', type=int, default=current_month)

    if not (1 <= selected_month <= 12):
        selected_month = current_month
    
    if not (current_year - 5 <= selected_year <= current_year + 1):
        selected_year = current_year

    num_days = calendar.monthrange(selected_year, selected_month)[1]

    daily_reports = {}
    for day in range(1, num_days + 1):
        current_date = datetime(selected_year, selected_month, day).date()
        daily_stock = calculate_daily_stock(current_date)
        daily_reports[current_date.strftime('%Y-%m-%d')] = daily_stock

    all_items = {item['_id']: item['name'] for item in inventory_collection.find().sort("name", 1)}
    
    sorted_daily_reports = sorted(daily_reports.items(), key=lambda x: x[0])

    years = range(current_year - 5, current_year + 2)
    months = [
        (1, 'Januari'), (2, 'Februari'), (3, 'Maret'), (4, 'April'),
        (5, 'Mei'), (6, 'Juni'), (7, 'Juli'), (8, 'Agustus'),
        (9, 'September'), (10, 'Oktober'), (11, 'November'), (12, 'Desember')
    ]

    return render_template('index.html',
                           page='report',
                           daily_reports=sorted_daily_reports,
                           all_items=all_items,
                           selected_year=selected_year,
                           selected_month=selected_month,
                           years=years,
                           months=months,
                           logged_in=session.get('logged_in'))

@app.route('/statistics')
def statistics_page():
    """Rute untuk menampilkan halaman statistik."""
    return render_template('index.html', page='statistics', logged_in=session.get('logged_in'))

@app.route('/api/statistics')
def get_statistics_data():
    """API endpoint untuk menyediakan data statistik dalam format JSON."""
    stats_data = {}

    # 1. Ringkasan Keseluruhan
    total_unique_items = inventory_collection.count_documents({})
    total_current_stock = sum(item.get('stock', 0) for item in inventory_collection.find({}, {"stock": 1}))
    stats_data['overall_summary'] = {
        'total_unique_items': total_unique_items,
        'total_current_stock': total_current_stock
    }

    # 2. Tren Transaksi Bulanan (12 bulan terakhir)
    monthly_trends = []
    today = datetime.now()
    for i in range(12): # Untuk 12 bulan terakhir
        target_month = today.month - i
        target_year = today.year
        if target_month <= 0:
            target_month += 12
            target_year -= 1
        
        start_of_month = datetime(target_year, target_month, 1)
        end_of_month = datetime(target_year, target_month, calendar.monthrange(target_year, target_month)[1], 23, 59, 59)

        pipeline_monthly = [
            {
                "$match": {
                    "timestamp": {"$gte": start_of_month, "$lte": end_of_month}
                }
            },
            {
                "$group": {
                    "_id": "$type",
                    "total_quantity": {"$sum": "$quantity"}
                }
            }
        ]
        monthly_summary = list(transactions_collection.aggregate(pipeline_monthly))
        
        masuk_qty = 0
        keluar_qty = 0
        for summary in monthly_summary:
            if summary['_id'] == 'masuk':
                masuk_qty = summary['total_quantity']
            elif summary['_id'] == 'keluar':
                keluar_qty = summary['total_quantity']
        
        monthly_trends.append({
            'year': target_year,
            'month': target_month,
            'month_name': datetime(target_year, target_month, 1).strftime('%b %Y'), # Contoh: Jan 2023
            'masuk': masuk_qty,
            'keluar': keluar_qty
        })
    stats_data['monthly_trends'] = list(reversed(monthly_trends)) # Urutkan dari bulan terlama ke terbaru

    # 3. Top 5 Barang Berdasarkan Stok Saat Ini
    top_stock_items = list(inventory_collection.find({}, {"_id": 1, "name": 1, "stock": 1})
                                              .sort("stock", -1)
                                              .limit(5))
    stats_data['top_stock_items'] = top_stock_items

    # 4. Top 5 Barang Berdasarkan Volume Transaksi (12 bulan terakhir)
    twelve_months_ago = today - timedelta(days=365) # Kira-kira 12 bulan
    pipeline_top_transactions = [
        {
            "$match": {
                "timestamp": {"$gte": twelve_months_ago}
            }
        },
        {
            "$group": {
                "_id": "$item_id",
                "total_volume": {"$sum": "$quantity"}
            }
        },
        {
            "$sort": {"total_volume": -1}
        },
        {
            "$limit": 5
        }
    ]
    top_transaction_items_raw = list(transactions_collection.aggregate(pipeline_top_transactions))
    
    top_transaction_items = []
    for item_data in top_transaction_items_raw:
        item_info = inventory_collection.find_one({"_id": item_data['_id']}, {"name": 1})
        if item_info:
            top_transaction_items.append({
                'item_id': item_data['_id'],
                'name': item_info['name'],
                'total_volume': item_data['total_volume']
            })
    stats_data['top_transaction_items'] = top_transaction_items

    return jsonify(stats_data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            flash('Login berhasil!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Username atau password salah.', 'error')
    return render_template('index.html', page='login', logged_in=session.get('logged_in'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('Anda telah logout.', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
