# ❖ DEIS Cognos Scraper - Chile

Automatizador interactivo y de línea de comandos (CLI) para descargar reportes oficiales de **Atenciones de Urgencia** desde el portal IBM Cognos de DEIS (Ministerio de Salud de Chile).

---

## ► Requisitos e Instalación

Tener instalado **Python 3.10+**.

1. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Instalar el motor de navegación (Chromium):**
   ```bash
   playwright install chromium
   ```

---

## ◆ Modo de Uso

### 1. Modo Interactivo (Asistente en Terminal)
Ejecutar el script sin argumentos para abrir el menú interactivo con la librería `rich`:

```bash
python scraper.py
```

**Pasos del asistente:**
1. **Servicio(s) de Salud:** Seleccionar uno o más Servicios de Salud (ej: `Metropolitano Sur, Metropolitano Suroriente` o `0` para todo Chile).
2. **Años Estadísticos:** Elegir descargar todos los años (2015-2025), un año específico (ej: `2024`), o un rango personalizado (ej: `2020-2023`).
3. **Tipo de Establecimiento:** Todos (`Hospital`, `SAPU`, `SAR`, `SUR`, `CEAR`, `PAME`) o uno específico.
4. **Establecimientos:** Descarga automática 1 a 1 de todos los recintos detectados en tiempo real.

---

### 2. Modo Automatizado (CLI / Scripts / CI)
Puedes ejecutar descargas masivas directamente con parámetros por consola:

```bash
# Ejemplo 1: Descargar Metropolitana Sur y Suroriente para el rango 2015-2025
python scraper.py --servicios "Metropolitano Sur" "Metropolitano Suroriente" --anios 2015-2025

# Ejemplo 2: Descargar un año específico mostrando la interfaz gráfica del navegador
python scraper.py --servicios "Arica" --anios 2024 --visible

# Ejemplo 3: Rango de años personalizado
python scraper.py --servicios "Metropolitano Oriente" --anios 2020-2023 --silencioso
```

#### Opciones disponibles en CLI:
| Parámetro | Descripción | Ejemplo |
| :--- | :--- | :--- |
| `--servicios` | Uno o varios Servicios de Salud entre comillas. | `--servicios "Metropolitano Sur" "Metropolitano Suroriente"` |
| `--anios` / `--anio` | Año único, rango (`DESDE-HASTA`), o `todos`. | `--anios 2015-2025` o `--anios 2024` |
| `--tipo-est` | Tipo de recinto (`Hospital`, `SAPU`, `SAR`, etc. O`TODOS`). | `--tipo-est TODOS` |
| `--dir` | Carpeta de destino para las descargas (Por defecto: `./descargas`). | `--dir ./descargas` |
| `--visible` | Muestra el navegador Chromium en pantalla. | `--visible` |
| `--silencioso` | Ejecuta sin solicitar confirmaciones interactivas. | `--silencioso` |

---

## ■ Estructura del Proyecto y Descargas

```text
DEIS-Cognos-Scraper/
├── descargas/
│   ├── Metropolitano_Sur/
│   │   └── 2015-2025/
│   │       ├── 2015-2025_Metropolitano_Sur_Hospital_Barros_Luco.xlsx
│   │       └── 2015-2025_Metropolitano_Sur_SAPU_Padre_Esteban_Gumucio.xlsx
│   └── log.txt             # Registro detallado de descargas y auditoría
├── requirements.txt        # Dependencias (Playwright, Rich)
├── scraper.py              # Script principal
└── README.md               # Documentación
```

---

## ◈ Características Destacadas

- **Selección Simultánea de Años:** Permite solicitar rangos completos de años (ej: `2015-2025`) seleccionando todos los años especificados al mismo tiempo en el formulario inicial, maximizando la eficiencia.
- **Desbloqueo Inteligente de Semanas:** Ejecuta automáticamente la primera solicitud para desbloquear todas las semanas estadísticas del período en Cognos y luego realiza la selección masiva de semanas.
- **Sin Navegación "Volver":** Mantiene la vista de reporte activa para alternar únicamente el establecimiento en cada iteración, acelerando la descarga 1 a 1 de toda la región.
- **Auto-recuperación (Resume):** Si el proceso se interrumpe, el script reconoce los archivos `.xlsx` válidos en disco y los salta automáticamente al reiniciar.
- **Listas Dinámicas en Tiempo Real:** Conexión en vivo con el servidor Cognos para leer el catálogo actualizado de recintos por servicio de salud.