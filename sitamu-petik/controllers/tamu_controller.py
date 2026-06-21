from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from models.db_config import get_connection
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import csv
from flask import Response

tamu_bp = Blueprint('tamu', __name__)


# ==========================================
# ROUTE UNTUK SECURITY (PETUGAS POS)
# ==========================================

@tamu_bp.route('/')
def dashboard():
    # Proteksi: Hanya untuk role petugas
    if 'logged_in' not in session or session.get('role') != 'petugas':
        return redirect(url_for('tamu.login'))

    conn = get_connection()
    with conn.cursor() as cursor:
        # 1. Statistik Kartu Atas
        cursor.execute("SELECT COUNT(*) as total FROM tamu WHERE DATE(waktu_masuk) = CURDATE()")
        total_hari_ini = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as aktif FROM tamu WHERE status = 'aktif'")
        tamu_aktif = cursor.fetchone()['aktif']

        cursor.execute(
            "SELECT COUNT(*) as selesai FROM tamu WHERE status = 'selesai' AND DATE(waktu_masuk) = CURDATE()")
        tamu_selesai = cursor.fetchone()['selesai']

        cursor.execute(
            "SELECT COUNT(*) as total_bulan FROM tamu WHERE MONTH(waktu_masuk) = MONTH(CURDATE()) AND YEAR(waktu_masuk) = YEAR(CURDATE())")
        total_bulan_ini = cursor.fetchone()['total_bulan']

        # 2. Tamu yang Masih Aktif di Area (Horizontal Scroll)
        cursor.execute("""
            SELECT t.*, s.nama_staf 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE t.status = 'aktif'
            ORDER BY t.waktu_masuk DESC LIMIT 10
        """)
        list_aktif = cursor.fetchall()

        # 3. Riwayat Tabel Bawah (Semua status)
        cursor.execute("""
            SELECT t.*, s.nama_staf 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            ORDER BY t.waktu_masuk DESC LIMIT 10
        """)
        riwayat_terbaru = cursor.fetchall()

        # 4. Klasifikasi Lembaga vs Pribadi (Bulan Ini)
        cursor.execute("""
            SELECT jenis_keperluan, COUNT(*) as jumlah 
            FROM tamu 
            WHERE MONTH(waktu_masuk) = MONTH(CURDATE()) AND YEAR(waktu_masuk) = YEAR(CURDATE())
            GROUP BY jenis_keperluan
        """)
        klasifikasi = cursor.fetchall()
        lembaga = next((item['jumlah'] for item in klasifikasi if item['jenis_keperluan'] == 'lembaga'), 0)
        pribadi = next((item['jumlah'] for item in klasifikasi if item['jenis_keperluan'] == 'pribadi'), 0)

        # 5. Top Tamu & Staf Bulan Ini
        cursor.execute("""
                    SELECT s.nama_staf, s.divisi, COUNT(t.id) as total 
                    FROM tamu t JOIN staf s ON t.staf_id = s.id 
                    WHERE MONTH(t.waktu_masuk) = MONTH(CURDATE())
                    GROUP BY s.id, s.nama_staf, s.divisi 
                    ORDER BY total DESC LIMIT 3
                """)
        top_staf = cursor.fetchall()

        cursor.execute("""
                    SELECT MAX(nama_lengkap) as nama_lengkap, MAX(instansi) as instansi, COUNT(id) as total 
                    FROM tamu 
                    WHERE MONTH(waktu_masuk) = MONTH(CURDATE())
                    GROUP BY nik 
                    ORDER BY total DESC LIMIT 3
                """)
        top_tamu = cursor.fetchall()

    conn.close()

    # Hitung Persentase Klasifikasi
    persen_lembaga = int((lembaga / total_bulan_ini) * 100) if total_bulan_ini > 0 else 0
    persen_pribadi = int((pribadi / total_bulan_ini) * 100) if total_bulan_ini > 0 else 0

    return render_template('security/dashboard.html',
                           total_hari_ini=total_hari_ini,
                           tamu_aktif=tamu_aktif,
                           tamu_selesai=tamu_selesai,
                           total_bulan_ini=total_bulan_ini,
                           list_aktif=list_aktif,
                           riwayat_terbaru=riwayat_terbaru,
                           lembaga=lembaga,
                           pribadi=pribadi,
                           persen_lembaga=persen_lembaga,
                           persen_pribadi=persen_pribadi,
                           top_staf=top_staf,
                           top_tamu=top_tamu)


# Rute Baru untuk Export CSV Data Hari Ini
@tamu_bp.route('/export/harian')
def export_harian():
    if 'logged_in' not in session or session.get('role') != 'petugas':
        return redirect(url_for('tamu.login'))

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT t.waktu_masuk, t.waktu_keluar, t.nama_lengkap, t.instansi, t.keperluan, s.nama_staf, t.status 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE DATE(t.waktu_masuk) = CURDATE()
            ORDER BY t.waktu_masuk DESC
        """)
        data = cursor.fetchall()
    conn.close()

    def generate():
        yield 'Waktu Masuk,Waktu Keluar,Nama Tamu,Instansi/Pribadi,Keperluan,Bertemu,Status\n'
        for row in data:
            masuk = row['waktu_masuk'].strftime('%Y-%m-%d %H:%M:%S') if row['waktu_masuk'] else '-'
            keluar = row['waktu_keluar'].strftime('%Y-%m-%d %H:%M:%S') if row['waktu_keluar'] else '-'
            instansi = row['instansi'] if row['instansi'] else 'Pribadi'
            yield f"{masuk},{keluar},{row['nama_lengkap']},{instansi},{row['keperluan']},{row['nama_staf']},{row['status']}\n"

    return Response(generate(), mimetype='text/csv',
                    headers={"Content-Disposition": "attachment; filename=kunjungan_hari_ini.csv"})


@tamu_bp.route('/register', methods=['GET', 'POST'])
def register():
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))
    conn = get_connection()

    if request.method == 'POST':
        nik = request.form.get('nik')
        nama = request.form.get('nama')
        telepon = request.form.get('telepon')
        instansi = request.form.get('instansi')
        alamat = request.form.get('alamat')
        jenis_keperluan = request.form.get('jenis_keperluan')
        staf_id = request.form.get('staf_id')
        keperluan = request.form.get('keperluan')
        foto_base64 = request.form.get('foto_base64')

        with conn.cursor() as cursor:
            sql = """INSERT INTO tamu 
                     (nik, nama_lengkap, telepon, instansi, alamat, jenis_keperluan, keperluan, staf_id, foto_base64)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
            cursor.execute(sql,
                           (nik, nama, telepon, instansi, alamat, jenis_keperluan, keperluan, staf_id, foto_base64))
            conn.commit()
        conn.close()
        return redirect(url_for('tamu.dashboard'))

    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM staf WHERE status = 'aktif'")
        staf_list = cursor.fetchall()
    conn.close()

    return render_template('security/register.html', staf_list=staf_list)


# 1. HALAMAN UTAMA RIWAYAT + FILTER + BACA DATA
@tamu_bp.route('/riwayat')
def riwayat():
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))

    # Tangkap data filter
    search = request.args.get('search', '')
    tanggal = request.args.get('tanggal', '')
    kategori = request.args.get('kategori', 'semua')

    where_clause = "1=1"
    params = []

    if search:
        where_clause += " AND (t.nama_lengkap LIKE %s OR t.nik LIKE %s OR t.instansi LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if tanggal:
        where_clause += " AND DATE(t.waktu_masuk) = %s"
        params.append(tanggal)
    if kategori != 'semua':
        where_clause += " AND t.jenis_keperluan = %s"
        params.append(kategori)

    conn = get_connection()
    with conn.cursor() as cursor:
        sql = f"""
            SELECT t.*, s.nama_staf, s.divisi 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE {where_clause} 
            ORDER BY t.waktu_masuk DESC
        """
        cursor.execute(sql, tuple(params))
        riwayat_list = cursor.fetchall()
    conn.close()

    return render_template('security/riwayat.html',
                           riwayat_list=riwayat_list,
                           search=search,
                           tanggal=tanggal,
                           kategori=kategori)


@tamu_bp.route('/export/riwayat')
def export_riwayat():
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))

    search = request.args.get('search', '')
    tanggal = request.args.get('tanggal', '')
    kategori = request.args.get('kategori', 'semua')

    where_clause = "1=1"
    params = []

    if search:
        where_clause += " AND (t.nama_lengkap LIKE %s OR t.nik LIKE %s OR t.instansi LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if tanggal:
        where_clause += " AND DATE(t.waktu_masuk) = %s"
        params.append(tanggal)
    if kategori != 'semua':
        where_clause += " AND t.jenis_keperluan = %s"
        params.append(kategori)

    conn = get_connection()
    with conn.cursor() as cursor:
        sql = f"""
            SELECT t.waktu_masuk, t.waktu_keluar, t.nik, t.nama_lengkap, t.jenis_keperluan, t.instansi, t.keperluan, s.nama_staf, t.status 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE {where_clause}
            ORDER BY t.waktu_masuk DESC
        """
        cursor.execute(sql, tuple(params))
        data = cursor.fetchall()
    conn.close()

    def generate():
        yield 'Waktu Masuk,Waktu Keluar,NIK,Nama Tamu,Kategori,Instansi,Keperluan,Bertemu,Status\n'
        for row in data:
            masuk = row['waktu_masuk'].strftime('%Y-%m-%d %H:%M') if row['waktu_masuk'] else '-'
            keluar = row['waktu_keluar'].strftime('%Y-%m-%d %H:%M') if row['waktu_keluar'] else '-'
            instansi = row['instansi'] if row['instansi'] else 'Pribadi'
            yield f"{masuk},{keluar},{row['nik']},{row['nama_lengkap']},{row['jenis_keperluan']},{instansi},{row['keperluan']},{row['nama_staf']},{row['status']}\n"

    return Response(generate(), mimetype='text/csv',
                    headers={"Content-Disposition": "attachment; filename=riwayat_kunjungan.csv"})


# 1. HALAMAN TAMU AKTIF (DENGAN FILTER & SORTING)
@tamu_bp.route('/tamu-aktif')
def tamu_aktif():
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))

    search = request.args.get('search', '')
    sort = request.args.get('sort', 'terbaru')

    where_clause = "t.status = 'aktif'"
    params = []

    # Logika Pencarian
    if search:
        where_clause += " AND (t.nama_lengkap LIKE %s OR t.nik LIKE %s OR t.instansi LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    # Logika Pengurutan
    order_clause = "DESC" if sort == 'terbaru' else "ASC"

    conn = get_connection()
    with conn.cursor() as cursor:
        sql = f"""
            SELECT t.*, s.nama_staf, s.divisi 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE {where_clause}
            ORDER BY t.waktu_masuk {order_clause}
        """
        cursor.execute(sql, tuple(params))
        list_aktif = cursor.fetchall()
    conn.close()

    # Mengirim data 'now' untuk menghitung durasi secara real-time di HTML
    return render_template('security/tamu_aktif.html',
                           list_aktif=list_aktif,
                           search=search,
                           sort=sort,
                           now=datetime.now())


# 2. PROSES CHECKOUT TAMU
@tamu_bp.route('/tamu-aktif/checkout/<int:id>', methods=['POST'])
def proses_checkout(id):
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))

    conn = get_connection()
    with conn.cursor() as cursor:
        # Ubah status menjadi selesai dan catat waktu keluar
        cursor.execute("UPDATE tamu SET status = 'selesai', waktu_keluar = NOW() WHERE id = %s", (id,))
        conn.commit()
    conn.close()

    flash('Tamu berhasil di-checkout dan keluar dari area!', 'success')
    return redirect(url_for('tamu.tamu_aktif'))


@tamu_bp.route('/laporan')
def laporan():
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))
    return render_template('security/laporan.html')


@tamu_bp.route('/staf')
def staf():
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT s.*, COUNT(t.id) as total_tamu 
            FROM staf s 
            LEFT JOIN tamu t ON s.id = t.staf_id 
            GROUP BY s.id 
            ORDER BY s.nama_staf ASC
        """)
        staf_list = cursor.fetchall()
    conn.close()
    return render_template('security/staf.html', staf_list=staf_list)


@tamu_bp.route('/pengaturan')
def pengaturan():
    if 'logged_in' not in session: return redirect(url_for('tamu.login'))
    return render_template('security/pengaturan.html')


# API Cek Data Tamu Berdasarkan NAMA atau NIK
@tamu_bp.route('/api/cek_tamu')
def cek_tamu():
    # Menangkap query parameter ?nama= atau ?nik=
    nama = request.args.get('nama')
    nik = request.args.get('nik')

    conn = get_connection()
    tamu = None

    with conn.cursor() as cursor:
        if nik:
            # Cari spesifik berdasarkan NIK
            cursor.execute("SELECT * FROM tamu WHERE nik = %s ORDER BY id DESC LIMIT 1", (nik,))
            tamu = cursor.fetchone()
        elif nama:
            # Cari berdasarkan kecocokan nama (case-insensitive)
            cursor.execute("SELECT * FROM tamu WHERE nama_lengkap LIKE %s ORDER BY id DESC LIMIT 1", (f"%{nama}%",))
            tamu = cursor.fetchone()

    conn.close()

    if tamu:
        return jsonify({
            "status": "found",
            "data": {
                "nik": tamu['nik'],
                "nama": tamu['nama_lengkap'],
                "telepon": tamu['telepon'],
                "instansi": tamu['instansi'],
                "alamat": tamu['alamat']
            }
        })
    return jsonify({"status": "not_found"})


# ==========================================
# ROUTE UNTUK AUTHENTICATION (LOGIN/LOGOUT)
# ==========================================

@tamu_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_connection()
        with conn.cursor() as cursor:
            # Ambil data user yang aktif
            cursor.execute("SELECT * FROM users WHERE username=%s AND status='aktif'", (username,))
            user = cursor.fetchone()

            # Cek kecocokan password enkripsi
            if user and check_password_hash(user['password'], password):
                session['logged_in'] = True
                session['user_id'] = user['id']
                session['role'] = user['role']
                session['nama_lengkap'] = user['nama_lengkap']

                # Catat waktu login terakhir
                cursor.execute("UPDATE users SET last_login=NOW() WHERE id=%s", (user['id'],))
                conn.commit()
                conn.close()

                # Pengalihan berdasarkan peran (Role)
                if user['role'] == 'admin':
                    return redirect(url_for('tamu.admin_dashboard'))
                elif user['role'] == 'petugas':
                    return redirect(url_for('tamu.dashboard'))

            else:
                flash('Username atau password salah, atau akun nonaktif!', 'error')

        conn.close()

    return render_template('login.html')


@tamu_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('tamu.login'))


# ==========================================
# ROUTE UNTUK ADMINISTRATOR
# ==========================================

@tamu_bp.route('/admin/dashboard')
def admin_dashboard():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    filter_type = request.args.get('filter', 'semua')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    where_clause = "1=1"
    params = []

    if start_date and end_date:
        where_clause += " AND DATE(waktu_masuk) BETWEEN %s AND %s"
        params.extend([start_date, end_date])
        filter_type = 'custom'
    elif filter_type == 'hari_ini':
        where_clause += " AND DATE(waktu_masuk) = CURDATE()"
    elif filter_type == 'minggu_ini':
        where_clause += " AND YEARWEEK(waktu_masuk, 1) = YEARWEEK(CURDATE(), 1)"
    elif filter_type == 'bulan_ini':
        where_clause += " AND MONTH(waktu_masuk) = MONTH(CURDATE()) AND YEAR(waktu_masuk) = YEAR(CURDATE())"
    elif filter_type == 'tahun_ini':
        where_clause += " AND YEAR(waktu_masuk) = YEAR(CURDATE())"

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) as total FROM tamu WHERE {where_clause}", tuple(params))
        total_kunjungan = cursor.fetchone()['total']

        cursor.execute(f"SELECT COUNT(DISTINCT nama_lengkap) as unik FROM tamu WHERE {where_clause}", tuple(params))
        tamu_unik = cursor.fetchone()['unik']

        cursor.execute(f"""
            SELECT s.nama_staf, COUNT(t.id) as jumlah 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE {where_clause}
            GROUP BY s.id 
            ORDER BY jumlah DESC 
            LIMIT 1
        """, tuple(params))
        top_staf_row = cursor.fetchone()
        top_staf = top_staf_row['nama_staf'] if top_staf_row else "Belum Ada Data"

        cursor.execute("SELECT COUNT(*) as aktif FROM tamu WHERE status = 'aktif'")
        tamu_aktif = cursor.fetchone()['aktif']

        cursor.execute("""
            SELECT t.*, s.nama_staf 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE t.status = 'aktif'
            ORDER BY t.waktu_masuk DESC
        """)
        list_tamu_aktif = cursor.fetchall()

    conn.close()

    return render_template('admin/dashboard.html',
                           total_kunjungan=total_kunjungan,
                           tamu_unik=tamu_unik,
                           tamu_aktif=tamu_aktif,
                           top_staf=top_staf,
                           list_tamu_aktif=list_tamu_aktif,
                           current_filter=filter_type,
                           start_date=start_date,
                           end_date=end_date)


@tamu_bp.route('/admin/tamu')
@tamu_bp.route('/admin/tamu')
def admin_tamu():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    # Tangkap parameter filter & pencarian
    search = request.args.get('search', '')
    kategori = request.args.get('kategori', 'semua')

    where_clause = "1=1"
    params = []

    if search:
        where_clause += " AND (nama_lengkap LIKE %s OR nik LIKE %s OR instansi LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    if kategori != 'semua':
        where_clause += " AND jenis_keperluan = %s"
        params.append(kategori)

    conn = get_connection()
    with conn.cursor() as cursor:
        # Mengelompokkan berdasarkan NIK agar tahu total kunjungan per individu
        sql = f"""
            SELECT 
                nik, 
                MAX(nama_lengkap) as nama_lengkap, 
                MAX(telepon) as telepon, 
                MAX(jenis_keperluan) as jenis_keperluan, 
                MAX(instansi) as instansi, 
                COUNT(id) as total_visit, 
                MAX(waktu_masuk) as kunjungan_terakhir
            FROM tamu 
            WHERE {where_clause}
            GROUP BY nik
            ORDER BY kunjungan_terakhir DESC
        """
        cursor.execute(sql, tuple(params))
        daftar_tamu = cursor.fetchall()

        # Total baris data setelah difilter
        total_tamu = len(daftar_tamu)

    conn.close()

    return render_template('admin/manajemen_tamu.html',
                           daftar_tamu=daftar_tamu,
                           total_tamu=total_tamu,
                           search=search,
                           kategori=kategori)


@tamu_bp.route('/admin/kunjungan')
def admin_kunjungan():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    # Tangkap parameter filter & pencarian
    search = request.args.get('search', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    status = request.args.get('status', 'semua')

    where_clause = "1=1"
    params = []

    if search:
        where_clause += " AND (t.nama_lengkap LIKE %s OR t.nik LIKE %s OR t.instansi LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    if start_date:
        where_clause += " AND DATE(t.waktu_masuk) >= %s"
        params.append(start_date)

    if end_date:
        where_clause += " AND DATE(t.waktu_masuk) <= %s"
        params.append(end_date)

    if status != 'semua':
        where_clause += " AND t.status = %s"
        params.append(status)

    conn = get_connection()
    with conn.cursor() as cursor:
        sql = f"""
            SELECT t.*, s.nama_staf, s.divisi 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE {where_clause} 
            ORDER BY t.waktu_masuk DESC
        """
        cursor.execute(sql, tuple(params))
        list_kunjungan = cursor.fetchall()
        total_kunjungan = len(list_kunjungan)
    conn.close()

    return render_template('admin/kunjungan.html',
                           list_kunjungan=list_kunjungan,
                           total_kunjungan=total_kunjungan,
                           search=search,
                           start_date=start_date,
                           end_date=end_date,
                           status=status)


@tamu_bp.route('/admin/staf')
def admin_staf():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    # Tangkap parameter search & filter divisi
    search = request.args.get('search', '')
    divisi = request.args.get('divisi', 'semua')

    where_clause = "1=1"
    params = []

    if search:
        where_clause += " AND (nama_staf LIKE %s OR nip LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    if divisi != 'semua':
        where_clause += " AND divisi = %s"
        params.append(divisi)

    conn = get_connection()
    with conn.cursor() as cursor:
        # Query mengambil data staf dan menghitung total tamu yang pernah mengunjungi mereka
        sql = f"""
            SELECT s.*, COUNT(t.id) as total_tamu 
            FROM staf s 
            LEFT JOIN tamu t ON s.id = t.staf_id 
            WHERE {where_clause}
            GROUP BY s.id 
            ORDER BY s.nama_staf ASC
        """
        cursor.execute(sql, tuple(params))
        staf_list = cursor.fetchall()
        total_staf = len(staf_list)
    conn.close()

    return render_template('admin/staf.html',
                           staf_list=staf_list,
                           total_staf=total_staf,
                           search=search,
                           divisi=divisi)


@tamu_bp.route('/admin/staf/tambah', methods=['POST'])
def admin_staf_tambah():
    if 'logged_in' not in session or session.get('role') != 'admin': return redirect(url_for('tamu.login'))

    data = (
        request.form.get('nama_staf'), request.form.get('nip'), request.form.get('telepon'),
        request.form.get('email'), request.form.get('divisi'), request.form.get('jabatan'),
        request.form.get('status', 'aktif')
    )

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO staf (nama_staf, nip, telepon, email, divisi, jabatan, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            data)
        conn.commit()
    conn.close()
    return redirect(url_for('tamu.admin_staf'))


@tamu_bp.route('/admin/staf/edit/<int:id>', methods=['POST'])
def admin_staf_edit(id):
    if 'logged_in' not in session or session.get('role') != 'admin': return redirect(url_for('tamu.login'))

    data = (
        request.form.get('nama_staf'), request.form.get('nip'), request.form.get('telepon'),
        request.form.get('email'), request.form.get('divisi'), request.form.get('jabatan'),
        request.form.get('status'), id
    )

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE staf SET nama_staf=%s, nip=%s, telepon=%s, email=%s, divisi=%s, jabatan=%s, status=%s WHERE id=%s",
            data)
        conn.commit()
    conn.close()
    return redirect(url_for('tamu.admin_staf'))


@tamu_bp.route('/admin/staf/hapus/<int:id>', methods=['POST'])
def admin_staf_hapus(id):
    if 'logged_in' not in session or session.get('role') != 'admin': return redirect(url_for('tamu.login'))

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM staf WHERE id=%s", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('tamu.admin_staf'))


@tamu_bp.route('/admin/laporan')
def admin_laporan():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    # 1. Tangkap parameter dari form Report Builder
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    kategori = request.args.get('kategori', 'semua')
    divisi = request.args.get('divisi', 'semua')

    where_clause = "1=1"
    params = []

    if start_date:
        where_clause += " AND DATE(t.waktu_masuk) >= %s"
        params.append(start_date)
    if end_date:
        where_clause += " AND DATE(t.waktu_masuk) <= %s"
        params.append(end_date)
    if kategori != 'semua':
        where_clause += " AND t.jenis_keperluan = %s"
        params.append(kategori)
    if divisi != 'semua':
        where_clause += " AND s.divisi = %s"
        params.append(divisi)

    conn = get_connection()
    with conn.cursor() as cursor:
        # 2. Ambil Data Kunjungan Utama
        sql = f"""
            SELECT t.*, s.nama_staf, s.divisi 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE {where_clause} 
            ORDER BY t.waktu_masuk ASC
        """
        cursor.execute(sql, tuple(params))
        laporan_data = cursor.fetchall()

        # 3. Hitung Data untuk Kartu Analitik
        total_tamu = len(laporan_data)
        total_lembaga = sum(1 for t in laporan_data if t['jenis_keperluan'] == 'lembaga')
        rasio_lembaga = int((total_lembaga / total_tamu * 100)) if total_tamu > 0 else 0

        # 4. Cari Staf Terbanyak Dikunjungi
        sql_top = f"""
            SELECT s.nama_staf, COUNT(t.id) as jumlah 
            FROM tamu t 
            JOIN staf s ON t.staf_id = s.id 
            WHERE {where_clause}
            GROUP BY s.id 
            ORDER BY jumlah DESC 
            LIMIT 1
        """
        cursor.execute(sql_top, tuple(params))
        top_staf_row = cursor.fetchone()
        top_staf = top_staf_row['nama_staf'] if top_staf_row else "Belum Ada"
        top_staf_kunjungan = top_staf_row['jumlah'] if top_staf_row else 0

        # 5. Ambil data pengaturan (Langsung di koneksi yang sama)
        cursor.execute("SELECT * FROM pengaturan LIMIT 1")
        profil = cursor.fetchone()

    conn.close()

    # Variabel tanggal ini jangan sampai hilang
    tanggal_cetak = datetime.now().strftime("%d %B %Y")

    return render_template('admin/laporan.html',
                           profil=profil,
                           laporan_data=laporan_data,
                           total_tamu=total_tamu,
                           rasio_lembaga=rasio_lembaga,
                           top_staf=top_staf,
                           top_staf_kunjungan=top_staf_kunjungan,
                           tanggal_cetak=tanggal_cetak,
                           start_date=start_date,  # Mengirim kembali nilai form filter
                           end_date=end_date,      # Mengirim kembali nilai form filter
                           kategori=kategori,      # Mengirim kembali nilai form filter
                           divisi=divisi)          # Mengirim kembali nilai form filter


@tamu_bp.route('/admin/dokumentasi')
def admin_dokumentasi():
    if 'logged_in' not in session or session.get('role') != 'admin': return redirect(url_for('tamu.login'))
    return render_template('admin/dokumentasi.html')


# 1. TAMPILKAN HALAMAN PENGGUNA & FILTER
@tamu_bp.route('/admin/pengguna')
def admin_pengguna():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    search = request.args.get('search', '')
    role_filter = request.args.get('role', 'semua')
    status_filter = request.args.get('status', 'semua')

    where_clause = "1=1"
    params = []

    if search:
        where_clause += " AND (nama_lengkap LIKE %s OR username LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])
    if role_filter != 'semua':
        where_clause += " AND role = %s"
        params.append(role_filter)
    if status_filter != 'semua':
        where_clause += " AND status = %s"
        params.append(status_filter)

    conn = get_connection()
    with conn.cursor() as cursor:
        # Asumsi nama tabel di database kamu adalah 'users'
        sql = f"SELECT * FROM users WHERE {where_clause} ORDER BY id DESC"
        cursor.execute(sql, tuple(params))
        users = cursor.fetchall()
        total_users = len(users)
    conn.close()

    return render_template('admin/pengguna.html',
                           users=users,
                           total_users=total_users,
                           search=search,
                           role_filter=role_filter,
                           status_filter=status_filter)


# 2. PROSES TAMBAH PENGGUNA
@tamu_bp.route('/admin/pengguna/tambah', methods=['POST'])
def admin_pengguna_tambah():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    nama_lengkap = request.form.get('nama_lengkap')
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role')

    # Enkripsi sandi sebelum masuk ke database
    hashed_password = generate_password_hash(password)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO users (nama_lengkap, username, password, role, status) 
                VALUES (%s, %s, %s, %s, 'aktif')
            """, (nama_lengkap, username, hashed_password, role))
            conn.commit()

        # Jika sukses, kirim pesan sukses
        flash('Pengguna baru berhasil ditambahkan!', 'success')

    except Exception as e:
        # Jika gagal (misal: username sudah dipakai), tangkap errornya
        print(f"Error Database: {e}")
        flash('Gagal! Username mungkin sudah digunakan atau ada masalah sistem.', 'error')

    finally:
        conn.close()

    return redirect(url_for('tamu.admin_pengguna'))


# 3. PROSES EDIT PENGGUNA
@tamu_bp.route('/admin/pengguna/edit/<int:id>', methods=['POST'])
def admin_pengguna_edit(id):
    if 'logged_in' not in session or session.get('role') != 'admin': return redirect(url_for('tamu.login'))

    nama_lengkap = request.form.get('nama_lengkap')
    username = request.form.get('username')
    password = request.form.get('password')  # Kosong jika tidak diubah
    role = request.form.get('role')
    status = request.form.get('status')

    conn = get_connection()
    with conn.cursor() as cursor:
        if password:  # Jika input password diisi, update dengan enkripsi baru
            hashed_password = generate_password_hash(password)
            cursor.execute("""
                UPDATE users SET nama_lengkap=%s, username=%s, password=%s, role=%s, status=%s WHERE id=%s
            """, (nama_lengkap, username, hashed_password, role, status, id))
        else:  # Jika input password dikosongkan, hiraukan update password
            cursor.execute("""
                UPDATE users SET nama_lengkap=%s, username=%s, role=%s, status=%s WHERE id=%s
            """, (nama_lengkap, username, role, status, id))
        conn.commit()
    conn.close()

    flash('Data pengguna berhasil diperbarui!', 'success')
    return redirect(url_for('tamu.admin_pengguna'))


# 4. PROSES HAPUS PENGGUNA
@tamu_bp.route('/admin/pengguna/hapus/<int:id>', methods=['POST'])
def admin_pengguna_hapus(id):
    if 'logged_in' not in session or session.get('role') != 'admin': return redirect(url_for('tamu.login'))

    # Keamanan ekstra: Cegah admin menghapus dirinya sendiri secara paksa
    if session.get('user_id') == id:
        flash('Anda tidak dapat menghapus akun Anda sendiri!', 'error')
        return redirect(url_for('tamu.admin_pengguna'))

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM users WHERE id=%s", (id,))
        conn.commit()
    conn.close()

    flash('Akun pengguna berhasil dihapus!', 'success')
    return redirect(url_for('tamu.admin_pengguna'))


@tamu_bp.route('/admin/notifikasi')
def admin_notifikasi():
    if 'logged_in' not in session or session.get('role') != 'admin': return redirect(url_for('tamu.login'))
    return render_template('admin/notifikasi.html')


# ==========================================
# FUNGSI PEMBANTU UNTUK MENCATAT LOG
# (Panggil fungsi ini di route lain saat ada aksi penting)
# Contoh penggunaan: catat_log(session['nama_lengkap'], session['role'], 'tamu', 'CREATE_TAMU', 'Menambah tamu baru.', request.remote_addr)
# ==========================================
def catat_log(nama_user, role, modul, aksi, deskripsi, ip_address):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO audit_logs (nama_user, role, modul, aksi, deskripsi, ip_address) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (nama_user, role, modul, aksi, deskripsi, ip_address))
        conn.commit()
    conn.close()

# ==========================================
# ROUTE UNTUK MENAMPILKAN HALAMAN AUDIT LOG
# ==========================================
@tamu_bp.route('/admin/audit')
def admin_audit_log():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    # Tangkap parameter pencarian dan filter
    search = request.args.get('search', '')
    tanggal = request.args.get('tanggal', '')
    modul = request.args.get('modul', 'semua')

    where_clause = "1=1"
    params = []

    if search:
        where_clause += " AND (nama_user LIKE %s OR aksi LIKE %s OR ip_address LIKE %s OR deskripsi LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])
    if tanggal:
        where_clause += " AND DATE(waktu) = %s"
        params.append(tanggal)
    if modul != 'semua':
        where_clause += " AND modul = %s"
        params.append(modul)

    conn = get_connection()
    with conn.cursor() as cursor:
        sql = f"SELECT * FROM audit_logs WHERE {where_clause} ORDER BY waktu DESC"
        cursor.execute(sql, tuple(params))
        logs = cursor.fetchall()
        total_logs = len(logs)
    conn.close()

    return render_template('admin/audit.html',
                           logs=logs,
                           total_logs=total_logs,
                           search=search,
                           tanggal=tanggal,
                           modul=modul)


@tamu_bp.route('/admin/pengaturan')
def admin_pengaturan():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    conn = get_connection()
    with conn.cursor() as cursor:
        # Ambil data pengaturan yang tersimpan
        cursor.execute("SELECT * FROM pengaturan LIMIT 1")
        profil = cursor.fetchone()
    conn.close()

    # Jika database kosong, beri nilai default agar tidak error
    if not profil:
        profil = {'nama_instansi': '', 'alamat': '', 'telepon': '', 'email': '', 'batas_waktu': 2}

    return render_template('admin/pengaturan.html', profil=profil)


@tamu_bp.route('/admin/pengaturan/save', methods=['POST'])
def admin_pengaturan_save():
    if 'logged_in' not in session or session.get('role') != 'admin':
        return redirect(url_for('tamu.login'))

    nama_instansi = request.form.get('nama_instansi')
    alamat = request.form.get('alamat')
    telepon = request.form.get('telepon')
    email = request.form.get('email')
    batas_waktu = request.form.get('batas_waktu')
    # Tangkap data penandatangan
    nama_penandatangan = request.form.get('nama_penandatangan')
    nip_penandatangan = request.form.get('nip_penandatangan')

    logo = request.files.get('logo')
    logo_filename = None

    if logo and logo.filename != '':
        upload_folder = os.path.join('static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        logo_filename = secure_filename(logo.filename)
        logo.save(os.path.join(upload_folder, logo_filename))

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, logo_path FROM pengaturan LIMIT 1")
        exists = cursor.fetchone()

        if not logo_filename and exists:
            logo_filename = exists['logo_path']

        if exists:
            cursor.execute("""
                UPDATE pengaturan 
                SET nama_instansi=%s, alamat=%s, telepon=%s, email=%s, batas_waktu=%s, logo_path=%s,
                    nama_penandatangan=%s, nip_penandatangan=%s
                WHERE id=%s
            """, (nama_instansi, alamat, telepon, email, batas_waktu, logo_filename, nama_penandatangan, nip_penandatangan, exists['id']))
        else:
            cursor.execute("""
                INSERT INTO pengaturan (nama_instansi, alamat, telepon, email, batas_waktu, logo_path, nama_penandatangan, nip_penandatangan) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (nama_instansi, alamat, telepon, email, batas_waktu, logo_filename, nama_penandatangan, nip_penandatangan))
        conn.commit()
    conn.close()

    flash('Pengaturan sistem berhasil disimpan!', 'success')
    return redirect(url_for('tamu.admin_pengaturan'))


@tamu_bp.route('/setup-admin')
def setup_admin():
    # Enkripsi password 'admin123'
    hashed = generate_password_hash('admin123')

    conn = get_connection()
    with conn.cursor() as cursor:
        # Masukkan ke tabel users
        cursor.execute("""
            INSERT INTO users (nama_lengkap, username, password, role, status) 
            VALUES ('Admin Utama', 'admin_baru', %s, 'admin', 'aktif')
        """, (hashed,))
        conn.commit()
    conn.close()

    return "Akun admin berhasil dibuat! Silakan login dengan Username: admin_baru dan Password: admin123"