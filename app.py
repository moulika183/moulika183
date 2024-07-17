from flask import Flask, render_template, jsonify, request, redirect, url_for, send_file
import requests
import pandas as pd
import pymysql
from datetime import datetime
import os
import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__, static_folder='static', template_folder='templates')

# Constants
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Moulika3040!',
    'db': 'ohlc'
}
HEADERS = {'Accept': 'application/json'}
BASE_URL = 'https://api.upstox.com/v2/historical-candle/{instrument_key}/1minute/{from_date}/{to_date}'
API_KEY = 'c9f85407-29ef-41a0-9198-145e547e45fb'
REDIRECT_URL = 'http://localhost:4321/upstock'
BASE_AUTH_URL = "https://api-v2.upstox.com/"
CLIENT_SECRET = 'zpdqfbxasz'

@app.route('/')
def home():
    instrument_keys = fetch_instrument_keys()
    return render_template('index.html', instrument_keys=instrument_keys)

@app.route('/get-access-token', methods=['POST'])
def get_access_token():
    code = request.json.get('code')
    token_url = f"{BASE_AUTH_URL}login/authorization/token"
    
    data = {
        "code": code,
        "client_id": API_KEY,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URL,
        "grant_type": "authorization_code"
    }

    response = requests.post(token_url, data=data)
    token_response = response.json()

    if response.status_code == 200:
        access_token = token_response.get('access_token')
        return jsonify({"access_token": access_token})
    else:
        return jsonify({"error": "Failed to retrieve access token", "details": token_response})

@app.route('/renew-access')
def renew_access():
    authorization_url = f"{BASE_AUTH_URL}login/authorization/dialog?client_id={API_KEY}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(authorization_url)

@app.route('/fetch-instrument-keys', methods=['POST'])
def fetch_instrument_keys():
    # Load CSV directly from URL
    csv_url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
    try:
        df = pd.read_csv(csv_url)
        filtered_index = df[df['instrument_type'] == 'INDEX']
        filtered_futidx = df[df['instrument_type'] == 'FUTIDX']
        instrument_keys = list(filtered_index['instrument_key'].unique()) + list(filtered_futidx['instrument_key'].unique())
        return instrument_keys
    except Exception as e:
        return []

@app.route('/fetch-ohlc', methods=['POST'])
def fetch_ohlc():
    data = request.json
    start_date = data['start_date']
    end_date = data['end_date']
    instrument_keys = data['instrument_keys']

    start_date = datetime.strptime(start_date, '%d-%m-%Y').strftime('%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%d-%m-%Y').strftime('%Y-%m-%d')

    # Load CSV directly from URL
    csv_url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
    try:
        df = pd.read_csv(csv_url)
        filtered_index = df[df['instrument_type'] == 'INDEX']
        filtered_futidx = df[df['instrument_type'] == 'FUTIDX']
        if 'All Instrument Keys' in instrument_keys:
            instrument_keys = list(filtered_index['instrument_key'].unique()) + list(filtered_futidx['instrument_key'].unique())
        else:
            if instrument_keys:
                filtered_index = filtered_index[filtered_index['instrument_key'].isin(instrument_keys)]
                filtered_futidx = filtered_futidx[filtered_futidx['instrument_key'].isin(instrument_keys)]
    except Exception as e:
        return jsonify({"error": "Error loading CSV from URL", "details": str(e)})

    if filtered_index.empty and filtered_futidx.empty:
        return jsonify({"error": "No data to process after filtering"})

    try:
        connection = pymysql.connect(**DB_CONFIG)
        cursor = connection.cursor()
    except pymysql.MySQLError as e:
        return jsonify({"error": "Database connection failed", "details": str(e)})

    try:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS Indexohlc (
            Instr_Type VARCHAR(255),
            Instr_Key VARCHAR(255),
            DateTime DATETIME,
            Open DOUBLE,
            High DOUBLE,
            Low DOUBLE,
            Close DOUBLE,
            Vol BIGINT,
            OI BIGINT,
            UNIQUE KEY (Instr_Key, DateTime)
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS futidxohlc (
            Instr_Type VARCHAR(255),
            Instr_Key VARCHAR(255),
            DateTime DATETIME,
            Open DOUBLE,
            High DOUBLE,
            Low DOUBLE,
            Close DOUBLE,
            Vol BIGINT,
            OI BIGINT,
            UNIQUE KEY (Instr_Key, DateTime)
        )
        ''')

        for _, row in pd.concat([filtered_index, filtered_futidx]).iterrows():
            url = BASE_URL.format(instrument_key=row['instrument_key'], from_date=start_date, to_date=end_date)
            response = requests.get(url, headers=HEADERS)
            if response.status_code == 200:
                candles = response.json().get('data', {}).get('candles', [])
                for candle in candles:
                    timestamp = datetime.fromisoformat(candle[0])
                    values = (row['instrument_type'], row['instrument_key'], timestamp, candle[1], candle[2], candle[3], candle[4], candle[5], candle[6])
                    if row['instrument_type'] == 'INDEX':
                        cursor.execute('''
                        INSERT INTO Indexohlc (Instr_Type, Instr_Key, DateTime, Open, High, Low, Close, Vol, OI)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE Open=VALUES(Open), High=VALUES(High), Low=VALUES(Low), Close=VALUES(Close), Vol=VALUES(Vol), OI=VALUES(OI)
                        ''', values)
                    else:
                        cursor.execute('''
                        INSERT INTO futidxohlc (Instr_Type, Instr_Key, DateTime, Open, High, Low, Close, Vol, OI)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE Open=VALUES(Open), High=VALUES(High), Low=VALUES(Low), Close=VALUES(Close), Vol=VALUES(Vol), OI=VALUES(OI)
                        ''', values)
            else:
                return jsonify({"error": f"Error fetching data for {row['instrument_key']}: {response.status_code} - {response.text}"})
        connection.commit()
    except Exception as e:
        return jsonify({"error": "Error during database operation", "details": str(e)})
    finally:
        cursor.close()
        connection.close()

    return jsonify({"message": "Data fetched and stored successfully"})

@app.route('/view-data', methods=['GET'])
def view_data():
    instrument_key = request.args.get('instrument_key')

    try:
        connection = pymysql.connect(**DB_CONFIG)
        cursor = connection.cursor()
        cursor.execute(f"SELECT * FROM Indexohlc WHERE Instr_Key='{instrument_key}' ORDER BY DateTime ASC")
        data = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(data, columns=columns)

        if df.empty:
            return jsonify({"error": "No data found for the selected instrument key"})

        # Generate OHLC chart using Matplotlib
        fig, ax = plt.subplots()
        df['DateTime'] = pd.to_datetime(df['DateTime'])
        df.set_index('DateTime', inplace=True)

        ax.plot(df.index, df['Open'], label='Open')
        ax.plot(df.index, df['High'], label='High')
        ax.plot(df.index, df['Low'], label='Low')
        ax.plot(df.index, df['Close'], label='Close')

        ax.set_xlabel('DateTime')
        ax.set_ylabel('Price')
        ax.legend()

        img = io.BytesIO()
        plt.savefig(img, format='png')
        img.seek(0)
        chart_url = base64.b64encode(img.getvalue()).decode()

        return jsonify({
            "instrument_key": instrument_key,
            "start_entry": data[0],
            "end_entry": data[-1],
            "chart_url": f"data:image/png;base64,{chart_url}"
        })
    except Exception as e:
        return jsonify({"error": "Database connection failed", "details": str(e)})
    finally:
        connection.close()

@app.route('/download-csv', methods=['POST'])
def download_csv():
    data = request.json
    instrument_keys = data['instrument_keys']
    start_date = data['start_date']
    end_date = data['end_date']

    start_date = datetime.strptime(start_date, '%d-%m-%Y').strftime('%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%d-%m-%Y').strftime('%Y-%m-%d')

    try:
        connection = pymysql.connect(**DB_CONFIG)
        cursor = connection.cursor()

        query = '''
        SELECT Instr_Type, Instr_Key, DateTime, Open, High, Low, Close, Vol, OI
        FROM Indexohlc
        WHERE DateTime BETWEEN %s AND %s
        '''
        cursor.execute(query, (start_date, end_date))
        data = cursor.fetchall()
        df_index = pd.DataFrame(data, columns=['Instr_Type', 'Instr_Key', 'DateTime', 'Open', 'High', 'Low', 'Close', 'Vol', 'OI'])

        query = '''
        SELECT Instr_Type, Instr_Key, DateTime, Open, High, Low, Close, Vol, OI
        FROM futidxohlc
        WHERE DateTime BETWEEN %s AND %s
        '''
        cursor.execute(query, (start_date, end_date))
        data = cursor.fetchall()
        df_futidx = pd.DataFrame(data, columns=['Instr_Type', 'Instr_Key', 'DateTime', 'Open', 'High', 'Low', 'Close', 'Vol', 'OI'])

        df = pd.concat([df_index, df_futidx])

        # Save to CSV
        file_path = os.path.join('static', 'ohlc_data.csv')
        df.to_csv(file_path, index=False)

        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": "Error during database operation", "details": str(e)})
    finally:
        cursor.close()
        connection.close()

if __name__ == '__main__':
    app.run(port=4321, debug=True)
