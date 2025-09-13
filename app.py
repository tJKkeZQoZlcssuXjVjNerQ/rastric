import threading
import requests
import time
import json
import os

# === Leemos TODAS las variables de entorno que configurarás en Koyeb ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TRACKING_PAYLOAD = os.getenv("TRACKING_PAYLOAD")
API_TOKEN = os.getenv("API_TOKEN")

# === Configuración de la petición ===
API_URL = "https://node.qs.gt/rastreo/tracking"
PAYLOAD = TRACKING_PAYLOAD
HEADERS = {
    "dispositivo": "Mozilla/5.0 (Linux; Android 9; SM-G970U Build/PQ3A.190801.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/81.0.4044.117 Mobile Safari/537.36",
    "token": API_TOKEN,
    "Content-Type": "application/x-www-form-urlencoded"
}
STATE_FILE = "estado.json"

# === Bot functions (sin cambios) ===
def get_tracking():
    if not PAYLOAD or not API_TOKEN:
        print("❌ Error: TRACKING_PAYLOAD o API_TOKEN no están configurados.")
        return None
    r = requests.post(API_URL, headers=HEADERS, data=PAYLOAD)
    r.raise_for_status()
    return r.json()
  
def get_chat_id():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    r = requests.get(url).json()
    try:
        message = r["result"][-1]["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")

        # Si el último mensaje fue /start → responder
        if text == "/start":
            url_send = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url_send, data={"chat_id": chat_id, "text": "👋 Hola! Estoy activo y te avisaré de cambios en tu paquete 📦"})

        return chat_id
    except Exception as e:
        print("Error obteniendo chat_id:", e)
        return None


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ TELEGRAM_TOKEN o CHAT_ID no están configurados.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def tracking_loop():
    global CHAT_ID
    print(f"✅ Bot activo, enviando a chat {CHAT_ID}")
    
    while True:
        last_state = load_state()
        try:
            new_state = get_tracking()
            if new_state is None:
                time.sleep(60)
                continue

            eventos = new_state.get("records", [])
            
            if eventos:
                paquete = eventos[-1]
                new_status = paquete.get("descripcion", "sin status")
                
                if last_state.get("status") != new_status:
                    fecha = paquete.get("fecha", "")
                    ubicacion = paquete.get("comentario", "")
                    descripcion = paquete.get("descripcion_producto", "")
                    msg = f"📦 Estado: {new_status}\n📍 {ubicacion}\n🗓 {fecha} \n📦 {descripcion}"
                    print(f"Nuevo estado detectado: {new_status}. Enviando notificación.")
                    send_telegram(msg)
                    last_state["status"] = new_status
                    save_state(last_state)
                else:
                    print(f"Sin cambios. Estado actual: {new_status}")
            
        except requests.exceptions.RequestException as e:
            print(f"Error de red al obtener tracking: {e}")
        except Exception as e:
            print(f"Error inesperado en el loop: {e}")

        time.sleep(300)

# === Punto de entrada principal ===
if __name__ == "__main__":
    tracking_loop()
