import pymysql

def get_connection():
    # Sesuaikan dengan kredensial default MySQL Laragon
    return pymysql.connect(
        host='localhost',
        user='root',
        password='',
        database='sitamu_petik',
        cursorclass=pymysql.cursors.DictCursor
    )