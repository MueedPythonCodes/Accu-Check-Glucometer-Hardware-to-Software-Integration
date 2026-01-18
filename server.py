import threading
import asyncio
import time
import csv
import os
import struct
import webbrowser
from datetime import datetime
from flask import Flask, jsonify, send_file
from bleak import BleakScanner, BleakClient

# --- CONFIGURATION ---
GLUCOSE_SERVICE_UUID = "00001808-0000-1000-8000-00805f9b34fb"
GLUCOSE_MEASUREMENT_UUID = "00002a18-0000-1000-8000-00805f9b34fb"
CSV_FILE = "sugar_readings.csv"

# Global State
app = Flask(__name__)
latest_status = "Initializing..."
readings_cache = []

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return send_file('index.html')

@app.route('/api/data')
def get_data():
    return jsonify({
        "status": latest_status,
        "readings": readings_cache
    })

# --- DATA HELPERS ---
def load_csv():
    global readings_cache
    readings_cache = []
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    readings_cache.append({
                        "timestamp": row['Timestamp'],
                        "mgdl": row['Glucose (mg/dL)'],
                        "mmol": row['Glucose (mmol/L)']
                    })
        except:
            pass

def save_reading(timestamp, mgdl, mmol):
    global readings_cache
    # Always overwrite mode 'w' to keep only the latest reading (+ header)
    with open(CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Glucose (mg/dL)", "Glucose (mmol/L)"])
        writer.writerow([timestamp, mgdl, mmol])
    
    # Update the global cache immediately so /api/data reflects this
    readings_cache = [{
        "timestamp": timestamp,
        "mgdl": str(mgdl),
        "mmol": str(mmol)
    }]
    
    print(f"NEW READING: {mgdl} mg/dL. UI will update on next poll.")

# --- BLUETOOTH LOGIC (IEEE 11073-20601 PARSING) ---
def parse_glucose(data):
    # Byte 0: Flags
    flags = data[0]
    time_offset_present = (flags & 0x01) == 1
    type_sample_location_present = (flags & 0x02) == 2
    concentration_unit_kg_l = (flags & 0x04) == 0 # bit 2: 0=kg/L (mg/dL), 1=mol/L
    
    offset = 1
    
    # Sequence Number (2 bytes)
    offset += 2
    
    # Base Time (7 bytes)
    year = struct.unpack('<H', data[offset:offset+2])[0]
    month = data[offset+2]
    day = data[offset+3]
    hours = data[offset+4]
    minutes = data[offset+5]
    seconds = data[offset+6]
    offset += 7
    
    # Time Offset (2 bytes)
    if time_offset_present:
        offset += 2 # Skip for now
        
    dt_str = f"{year}-{month:02d}-{day:02d} {hours:02d}:{minutes:02d}:{seconds:02d}"
    
    # Glucose Concentration (SFLOAT - 16 bit)
    # IEEE 11073 SFLOAT: 12-bit mantissa (signed), 4-bit exponent (signed)
    raw_sfloat = struct.unpack('<H', data[offset:offset+2])[0]
    
    mantissa = raw_sfloat & 0x0FFF
    exponent = raw_sfloat >> 12
    
    # Handle signed 12-bit mantissa
    if mantissa >= 0x0800:
        mantissa = -((0x1000 - mantissa))
        
    # Handle signed 4-bit exponent
    if exponent >= 0x08:
        exponent = -((0x10 - exponent))
        
    val = mantissa * (10 ** exponent)
    
    mgdl = 0
    mmol = 0
    
    if concentration_unit_kg_l:
        # Unit is kg/L. Convert to mg/dL.
        # usually exponent is -5 for kg/L
        mgdl = round(val * 100000)
        mmol = round(mgdl / 18.0182, 1)
    else:
        # Unit is mol/L.
        mmol = round(val * 1000, 1)
        mgdl = round(mmol * 18.0182)
        
    return dt_str, mgdl, mmol

def notification_handler(sender, data):
    try:
        dt, mgdl, mmol = parse_glucose(data)
        print(f" [BLE] Parsed: {mgdl} mg/dL at {dt}")
        save_reading(dt, mgdl, mmol)
    except Exception as e:
        print(f" [BLE] Parse Error: {e}")

async def ble_loop():
    global latest_status
    print("--- Background Bluetooth Service Started ---")
    
    while True:
        latest_status = "Scanning for Accu-Chek..."
        # print(latest_status)
        
        try:
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: GLUCOSE_SERVICE_UUID in ad.service_uuids if ad.service_uuids else False,
                timeout=5.0
            )
            
            if not device:
                # Fallback: name check if UUID advertising is missing
                device = await BleakScanner.find_device_by_filter(
                    lambda d, ad: d.name and "Accu" in d.name,
                    timeout=2.0
                )

            if device:
                latest_status = f"Connecting to {device.name}..."
                print(f" [BLE] Found {device.name}, Connecting...")
                
                try:
                    async with BleakClient(device, timeout=20.0) as client:
                        if client.is_connected:
                            latest_status = "Connected! Waiting for Data..."
                            print(" [BLE] Connected. Subscribing...")
                            
                            await client.start_notify(GLUCOSE_MEASUREMENT_UUID, notification_handler)
                            
                            # Keep connection alive to receive data
                            # Accu-chek usually sends all stored records then disconnects
                            await asyncio.sleep(10.0) 
                            
                            await client.stop_notify(GLUCOSE_MEASUREMENT_UUID)
                            print(" [BLE] Sync Complete.")
                except Exception as e:
                    print(f" [BLE] Connection Error: {e}")
            
            else:
                pass # Not found, loop again
                
        except Exception as e:
            print(f" [BLE] Loop Error: {e}")
            
        await asyncio.sleep(2.0)

# --- THREADING ---
def run_ble_logic():
    asyncio.run(ble_loop())

if __name__ == '__main__':
    # Load existing CSV data
    load_csv()
    
    # Start BLE Thread
    t = threading.Thread(target=run_ble_logic)
    t.daemon = True
    t.start()
    
    # Start Flask
    print("Starting Flask Server...")
    webbrowser.open("http://localhost:5000")
    app.run(port=5000, debug=False, use_reloader=False)