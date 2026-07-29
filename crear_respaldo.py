import os
import shutil
from datetime import datetime

def hacer_respaldo():
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta_respaldo = f"Respaldo_Seguro_{fecha}"
    os.makedirs(carpeta_respaldo, exist_ok=True)
    
    archivos_a_salvar = ["app.py", "datos.py", "config.py"]
    for archivo in archivos_a_salvar:
        if os.path.exists(archivo):
            shutil.copy(archivo, os.path.join(carpeta_respaldo, archivo))
            
    if os.path.exists("data"):
        shutil.copytree("data", os.path.join(carpeta_respaldo, "data"))
        
    print(f"✅ ¡Respaldo completado! Tus archivos seguros están en la carpeta: {carpeta_respaldo}")

if __name__ == "__main__":
    hacer_respaldo()