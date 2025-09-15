import threading
import requests
import time
import json
import os
import re # Importamos el módulo de expresiones regulares

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

# === Configuración para la segunda paquetería (Loginext) ===
LOGINEXT_URL_CHECK = "https://products.loginextsolutions.com/ShipmentApp/shipment/fmlm/get/webLinkdata"
LOGINEXT_URL_DETAILS = "https://products.loginextsolutions.com/ShipmentApp/middlemile/shipment/order/iframe/details"
LOGINEXT_HEADERS = {
    'www-authenticate': 'BASIC c586fa65-473e-454d-826b-448cea88b320',
    'Content-Type': 'application/json'
}

# === Bot functions (sin cambios) ===
def get_tracking():
    if not PAYLOAD or not API_TOKEN:
        print("❌ Error: TRACKING_PAYLOAD o API_TOKEN no están configurados.")
        return None
    r = requests.post(API_URL, headers=HEADERS, data=PAYLOAD)
    r.raise_for_status()
    return r.json()

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

# === NUEVAS FUNCIONES para Loginext ===
def check_loginext_guidance(guide_number):
    """Primera verificación a Loginext para ver si la guía es válida."""
    print(f"🔎 Verificando guía de Loginext: {guide_number}")
    payload = json.dumps({"orderNo": guide_number})
    try:
        response = requests.post(LOGINEXT_URL_CHECK, headers=LOGINEXT_HEADERS, data=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == 200 and not data.get("hasError"):
            print("✅ Guía de Loginext válida.")
            return True
        else:
            print(f"⚠️ Guía de Loginext inválida o con error: {data.get('message')}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de red al verificar guía de Loginext: {e}")
        return False
    
def get_loginext_details(guide_number):
    """Obtiene los detalles completos y el orderRefId de Loginext."""
    print(f"📄 Obteniendo detalles de Loginext para: {guide_number}")
    payload = json.dumps({
        "userType": "DELIVERCUSTOMER",
        "orderNo": guide_number
    })
    try:
        response = requests.post(LOGINEXT_URL_DETAILS, headers=LOGINEXT_HEADERS, data=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == 200:
            order_ref_id = data.get("data", {}).get("orderRefId")
            if order_ref_id:
                print(f"✅ Obtenido orderRefId: {order_ref_id}")
                return order_ref_id
            else:
                print("❌ No se encontró 'orderRefId' en la respuesta de Loginext.")
                return None
        else:
            print("❌ La respuesta de detalles de Loginext no fue exitosa.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de red al obtener detalles de Loginext: {e}")
        return None

def process_secondary_tracking(ubicacion, last_state):
    """Busca, procesa y notifica el tracking de la segunda paquetería."""
    # Usamos una expresión regular para encontrar el número de guía
    match = re.search(r"guia\s+([\w-]+)", ubicacion, re.IGNORECASE)
    if not match:
        return

    guide_number = match.group(1)
    # Verificamos si esta guía ya fue procesada
    if last_state.get("secondary_guide_processed") == guide_number:
        print(f"ℹ️ La guía secundaria {guide_number} ya fue procesada. Omitiendo.")
        return

    print(f"‼️ Detectada nueva guía de tránsito: {guide_number}")
    
    # 1. Verificar si la guía es válida
    if check_loginext_guidance(guide_number):
        # 2. Obtener el orderRefId
        order_ref_id = get_loginext_details(guide_number)
        
        if order_ref_id:
            # 3. Construir la URL y enviar la notificación
            final_url = f"https://products.loginextsolutions.com/trackall/#/order?referenceId={order_ref_id}&aid=c586fa65-473e-454d-826b-448cea88b320&type=DELIVERCUSTOMER"
            msg = f"🚚 Tu paquete ha sido transferido a la paquetería local.\n\nGuía: {guide_number}\n\nPuedes rastrearlo aquí:\n{final_url}"
            send_telegram(msg)
            print("✅ Notificación de seguimiento local enviada a Telegram.")
            
            # 4. Guardar el estado para no volver a notificar
            last_state["secondary_guide_processed"] = guide_number
            save_state(last_state)

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
                # --- NUEVA LÓGICA para la segunda paquetería ---
                process_secondary_tracking(ubicacion, last_state)
            
        except requests.exceptions.RequestException as e:
            print(f"Error de red al obtener tracking: {e}")
        except Exception as e:
            print(f"Error inesperado en el loop: {e}")
        print("--- Esperando 3 minutos para la próxima verificación ---")
        time.sleep(180)

# === Punto de entrada principal ===
if __name__ == "__main__":
    tracking_loop()
