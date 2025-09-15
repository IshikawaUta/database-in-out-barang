import os
from datetime import datetime, timedelta
import calendar
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from pymongo import MongoClient
from dotenv import load_dotenv
import uuid
from bson.son import SON

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "your_super_secret_key_here_at_least_32_chars_long_and_random_fallback")
if app.secret_key == "your_super_secret_key_here_at_least_32_chars_long_and_random_fallback":
    print("Peringatan: SECRET_KEY tidak diatur di .env atau variabel lingkungan. Menggunakan kunci default yang tidak aman.")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "password123")

MONGO_URI = os.environ.get("MONGO_URI")
DATABASE_NAME = os.environ.get("DATABASE_NAME")

if not MONGO_URI or not DATABASE_NAME:
    raise ValueError("MONGO_URI dan DATABASE_NAME harus diatur di file .env atau variabel lingkungan.")

try:
    client = MongoClient(MONGO_URI)
    db = client[DATABASE_NAME]
    inventory_collection = db["inventory"]
    transactions_collection = db["transactions"]
    print("Koneksi ke MongoDB berhasil!")
except Exception as e:
    print(f"Gagal terhubung ke MongoDB: {e}")
    raise

def calculate_daily_stock(date_to_calculate):
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
            'stock_awal': initial_stock,
            'stock_akhir': final_stock,
            'barang_masuk_hari_ini': daily_in,
            'barang_keluar_hari_ini': daily_out
        }
    return daily_stock_results

@app.route('/', methods=['GET', 'POST'])
def index():
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
            items = list(inventory_collection.find().sort("name", 1))
            return render_template('index.html', items=items, error="Format tanggal penambahan barang tidak valid.", page='home', logged_in=session.get('logged_in'), datetime=datetime)

        if not item_id or not item_name:
            flash("ID Barang dan Nama Barang tidak boleh kosong.", "error")
            items = list(inventory_collection.find().sort("name", 1))
            return render_template('index.html', items=items, error="ID Barang dan Nama Barang tidak boleh kosong.", page='home', logged_in=session.get('logged_in'), datetime=datetime)

        if inventory_collection.find_one({"_id": item_id}):
            flash(f"ID Barang '{item_id}' sudah ada. Gunakan ID lain.", "error")
            items = list(inventory_collection.find().sort("name", 1))
            return render_template('index.html', items=items, error="ID Barang sudah ada. Gunakan ID lain.", page='home', logged_in=session.get('logged_in'), datetime=datetime)

        try:
            inventory_collection.insert_one({
                "_id": item_id,
                "name": item_name,
                "stock": stock_awal,
                "initial_stock": stock_awal,
                "creation_date": item_creation_date
            })
            flash(f"Barang '{item_name}' (ID: {item_id}) berhasil ditambahkan.", "success")
        except Exception as e:
            flash(f"Gagal menambahkan barang: {e}", "error")
            items = list(inventory_collection.find().sort("name", 1))
            return render_template('index.html', items=items, error=f"Gagal menambahkan barang: {e}", page='home', logged_in=session.get('logged_in'), datetime=datetime)

        return redirect(url_for('index'))

    items = list(inventory_collection.find().sort("name", 1))
    return render_template('index.html', items=items, error=None, page='home', logged_in=session.get('logged_in'), datetime=datetime)

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'logged_in' not in session or not session['logged_in']:
        return jsonify({"success": False, "message": "Anda harus login sebagai admin untuk menambah transaksi."}), 403

    data = request.json
    if not data or 'items' not in data or not data['items']:
        return jsonify({"success": False, "message": "Data transaksi tidak valid."}), 400

    shipment_id = str(uuid.uuid4())
    transaction_date_str = data.get('transaction_date')
    if not transaction_date_str:
        return jsonify({"success": False, "message": "Tanggal transaksi tidak boleh kosong."}), 400

    try:
        transaction_datetime = datetime.strptime(transaction_date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({"success": False, "message": "Format tanggal transaksi tidak valid."}), 400

    new_transactions = []
    
    for item_data in data['items']:
        item_id = item_data.get('item_id')
        transaction_type = item_data.get('type')
        quantity = int(item_data.get('quantity', 0))
        description = item_data.get('description', '')

        if not all([item_id, transaction_type, quantity]):
            return jsonify({"success": False, "message": "Semua field item harus diisi."}), 400
        
        item = inventory_collection.find_one({"_id": item_id})
        if not item:
            return jsonify({"success": False, "message": f"Barang dengan ID '{item_id}' tidak ditemukan."}), 404

        current_stock = item['stock']
        if transaction_type == 'masuk':
            new_stock = current_stock + quantity
        elif transaction_type == 'keluar':
            new_stock = current_stock - quantity
        else:
            return jsonify({"success": False, "message": "Tipe transaksi tidak valid."}), 400
        
        try:
            transactions_collection.insert_one({
                "item_id": item_id,
                "type": transaction_type,
                "quantity": quantity,
                "description": description,
                "timestamp": transaction_datetime,
                "shipment_id": shipment_id
            })
            inventory_collection.update_one({"_id": item_id}, {"$set": {"stock": new_stock}})
        except Exception as e:
            return jsonify({"success": False, "message": f"Gagal mencatat transaksi: {e}"}), 500
        
    flash("Transaksi berhasil dicatat.", "success")
    return jsonify({"success": True, "shipment_id": shipment_id})

@app.route('/edit_item/<item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    if 'logged_in' not in session or not session['logged_in']:
        flash("Anda harus login sebagai admin untuk mengedit barang.", "error")
        return redirect(url_for('login'))

    item = inventory_collection.find_one({"_id": item_id})
    if not item:
        flash("Barang tidak ditemukan.", "error")
        return redirect(url_for('index'))

    if request.method == 'POST':
        new_name = request.form['item_name'].strip()
        new_stock = int(request.form['stock_awal'])
        new_creation_date_str = request.form['item_creation_date']
        
        try:
            new_creation_date = datetime.strptime(new_creation_date_str, '%Y-%m-%d')
        except ValueError:
            flash("Format tanggal penambahan barang tidak valid saat edit.", "error")
            return render_template('edit_item.html', item=item, error="Format tanggal penambahan barang tidak valid.", logged_in=session.get('logged_in'), datetime=datetime)

        if not new_name:
            flash("Nama Barang tidak boleh kosong.", "error")
            return render_template('edit_item.html', item=item, error="Nama Barang tidak boleh kosong.", logged_in=session.get('logged_in'), datetime=datetime)

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
        except Exception as e:
            flash(f"Gagal memperbarui barang: {e}", "error")
            return render_template('edit_item.html', item=item, error=f"Gagal memperbarui barang: {e}", logged_in=session.get('logged_in'), datetime=datetime)

        return redirect(url_for('index'))

    return render_template('edit_item.html', item=item, error=None, logged_in=session.get('logged_in'), datetime=datetime)

@app.route('/delete_item/<item_id>')
def delete_item(item_id):
    if 'logged_in' not in session or not session['logged_in']:
        flash("Anda harus login sebagai admin untuk menghapus barang.", "error")
        return redirect(url_for('login'))

    item = inventory_collection.find_one({"_id": item_id})
    if not item:
        flash("Barang tidak ditemukan.", "error")
        return redirect(url_for('index'))

    try:
        transactions_collection.delete_many({"item_id": item_id})
        inventory_collection.delete_one({"_id": item_id})
        flash(f"Barang '{item_id}' dan semua transaksinya berhasil dihapus.", "success")
    except Exception as e:
        flash(f"Gagal menghapus barang: {e}", "error")
        return redirect(url_for('index'))

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
    return render_template('index.html', page='statistics', logged_in=session.get('logged_in'))

@app.route('/api/statistics')
def get_statistics_data():
    stats_data = {}

    total_unique_items = inventory_collection.count_documents({})
    total_current_stock = sum(item.get('stock', 0) for item in inventory_collection.find({}, {"stock": 1}))
    stats_data['overall_summary'] = {
        'total_unique_items': total_unique_items,
        'total_current_stock': total_current_stock
    }

    monthly_trends = []
    today = datetime.now()
    for i in range(12):
        target_month_num = today.month - i
        target_year = today.year
        if target_month_num <= 0:
            target_month_num += 12
            target_year -= 1
        
        start_of_month = datetime(target_year, target_month_num, 1)
        end_of_month = datetime(target_year, target_month_num, calendar.monthrange(target_year, target_month_num)[1], 23, 59, 59)

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
            'month': target_month_num,
            'month_name': datetime(target_year, target_month_num, 1).strftime('%b %Y'),
            'masuk': masuk_qty,
            'keluar': keluar_qty
        })
    stats_data['monthly_trends'] = list(reversed(monthly_trends))

    top_stock_items = list(inventory_collection.find({}, {"_id": 1, "name": 1, "stock": 1})
                                              .sort("stock", -1)
                                              .limit(5))
    stats_data['top_stock_items'] = top_stock_items

    twelve_months_ago = today - timedelta(days=365)
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

@app.route('/surat_jalan/<shipment_id>')
def surat_jalan(shipment_id):
    if 'logged_in' not in session or not session['logged_in']:
        flash("Anda harus login sebagai admin untuk melihat surat jalan.", "error")
        return redirect(url_for('login'))

    transactions = list(transactions_collection.find({"shipment_id": shipment_id}))
    if not transactions:
        flash("Surat jalan tidak ditemukan.", "error")
        return redirect(url_for('index'))
    
    shipment_date = transactions[0]['timestamp']

    items_in_shipment = []
    for tx in transactions:
        item = inventory_collection.find_one({"_id": tx['item_id']})
        if item:
            items_in_shipment.append({
                'item_id': tx['item_id'],
                'item_name': item['name'],
                'quantity': tx['quantity'],
                'description': tx['description'],
                'type': tx['type']
            })
    
    return render_template('surat_jalan.html',
                           shipment_id=shipment_id,
                           shipment_date=shipment_date,
                           items_in_shipment=items_in_shipment,
                           logged_in=session.get('logged_in'))

@app.route('/shipment_history')
def shipment_history():
    if 'logged_in' not in session or not session['logged_in']:
        flash("Anda harus login sebagai admin untuk melihat riwayat surat jalan.", "error")
        return redirect(url_for('login'))

    pipeline = [
        {"$match": {"type": "keluar"}},
        {"$group": {
            "_id": "$shipment_id",
            "date": {"$min": "$timestamp"},
            "item_count": {"$sum": 1}
        }},
        {"$sort": {"date": -1}}
    ]
    
    shipments = list(transactions_collection.aggregate(pipeline))
    
    return render_template('shipment_history.html', shipments=shipments, page='shipment_history', logged_in=session.get('logged_in'))


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