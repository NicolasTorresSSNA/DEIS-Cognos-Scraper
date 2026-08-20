# 🚀 Ejemplos de Ejecución - DEIS Cognos Scraper

Comandos de terminal (Bash / PowerShell) para ejecutar el automatizador de descargas de **Atenciones de Urgencia DEIS**.

---

## 📋 Comandos de Prueba

```bash
# Descargar un rango de años para las zonas de interés
python scraper.py --servicios "Metropolitano Sur" "Metropolitano Suroriente" --anios 2015-2025

# Descargar un año específico mostrando la interfaz gráfica del navegador
python scraper.py --servicios "Metropolitano Oriente" --anios 2024 --visible

# Descargar un rango personalizado de forma silenciosa
python scraper.py --servicios "Metropolitano Sur" --anios 2020-2023 --silencioso

# Ejecutar el asistente interactivo en terminal
python scraper.py
```

---

## 📌 Notas de Uso

- **Múltiples Servicios de Salud:** Puedes especificar uno o más servicios entre comillas separados por espacio en `--servicios`.
- **Formatos de Años en `--anios`:**
  - Rango completo: `2015-2025`
  - Rango acotado: `2020-2023`
  - Año único: `2024`
  - Todos los años: `todos`
- **Ubicación de archivos descargados:**
  Se organizan automáticamente en `./descargas/<Servicio>/<Rango_o_Año>/`.
