from flask import Flask
from controllers.tamu_controller import tamu_bp

app = Flask(__name__)
app.secret_key = 'kunci_petik'

# Mendaftarkan rute dari controller menggunakan Blueprint
app.register_blueprint(tamu_bp)

if __name__ == '__main__':
    app.run(debug=True)