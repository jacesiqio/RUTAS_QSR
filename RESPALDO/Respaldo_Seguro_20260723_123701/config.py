import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Restricciones operativas inamovibles
HORA_LIMITE_RETORNO = "18:00"  # 6:00 PM Estricto en Casa o en el Hotel

# Duración de servicios Ecolab (minutos)
DURACION_VISITA_STANDARD = 80
DURACION_VISITA_INSTALACION = 120

# Matriz predictiva de rendimiento de combustible (km/l)
RENDIMIENTO_TRAFICO_ALTO = 9.0
RENDIMIENTO_TRAFICO_MEDIO = 10.0
RENDIMIENTO_TRAFICO_BAJO = 11.0
PRECIO_GASOLINA_PREMIUM = 25.50