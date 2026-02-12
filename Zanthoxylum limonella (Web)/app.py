from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'makhaen_up_key'

# --- ส่วนจัดการฐานข้อมูล SQLite ---

def get_db_connection():
    # เชื่อมต่อกับไฟล์ฐานข้อมูล (จะสร้างไฟล์ makhaen.db ให้เองถ้ายังไม่มี)
    conn = sqlite3.connect('makhaen.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """สร้างตารางข้อมูลครั้งแรก"""
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            img_name TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            accuracy REAL,
            surveyor TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
    ''');
    conn.commit()
    conn.close()

# เรียกใช้งานฟังก์ชันสร้างตารางทันทีที่รันโปรแกรม
init_db()

# --- ส่วนควบคุมหน้าเว็บ (Routes) ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        if pwd == '1234': 
            session['user'] = user
            session['role'] = 'admin' if user == 'admin' else 'user'
            return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    # ดึงข้อมูลจาก SQLite มาแสดงบนแผนที่
    data = conn.execute('SELECT * FROM surveys').fetchall()
    conn.close()
    
    return render_template('dashboard.html', 
                           role=session['role'], 
                           user=session['user'], 
                           data=data)

@app.route('/data_table')
def data_table():
    if 'user' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    # ดึงข้อมูลเรียงจากใหม่ไปเก่า
    data = conn.execute('SELECT * FROM surveys ORDER BY timestamp DESC').fetchall()
    conn.close()
    
    return render_template('data_table.html', 
                           role=session['role'], 
                           user=session['user'], 
                           data=data)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- ส่วน API รับข้อมูลจาก Raspberry Pi ---

@app.route('/api/upload', methods=['POST'])
def upload():
    try:
        img = request.files['image']
        lat = request.form.get('lat')
        lng = request.form.get('lng')
        accuracy = request.form.get('accuracy')
        user = request.form.get('user', 'Hardware_Box') # รับชื่อเครื่องหรือผู้ใช้

        # 1. บันทึกไฟล์รูปลงโฟลเดอร์ static/uploads
        if not os.path.exists('static/uploads'):
            os.makedirs('static/uploads')
        img.save(os.path.join('static/uploads', img.filename))

        # 2. บันทึกลง SQLite
        conn = get_db_connection()
        conn.execute('INSERT INTO surveys (img_name, lat, lng, accuracy, surveyor) VALUES (?, ?, ?, ?, ?)',
                     (img.filename, lat, lng, accuracy, user))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "message": "Data stored in SQLite"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # รันเซิร์ฟเวอร์
    app.run(debug=True, host='0.0.0.0', port=5000)