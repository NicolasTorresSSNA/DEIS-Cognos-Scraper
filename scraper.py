"""
COGNOS DEIS Chile - Automatizador de descargas (Unificado y Optimizado)
=======================================================================
Descarga automáticamente reportes de "Atenciones de Urgencia" desde http://cognos.deis.cl.
"""

import argparse
import json
import os
import re
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich import print as rprint
from rich.table import Table

# ============================================================================
# CONFIGURACION & CONSTANTES
# ============================================================================

URL_REPORTE = "http://cognos.deis.cl/ibmcognos/cgi-bin/cognos.cgi?b_action=cognosViewer&ui.action=run&ui.object=/content/folder[@name=%27PUB%27]/folder[@name=%27REPORTES%27]/folder[@name=%27Atenciones%20de%20Urgencia%27]/report[@name=%27Atenciones%20Urgencia%20-%20Vista%20por%20semanas%20-%20Servicios%27]&ui.name=Atenciones%20Urgencia%20-%20Vista%20por%20semanas%20-%20Servicios&run.outputFormat=&run.prompt=true"

ANIOS_DISPONIBLES = list(range(2015, 2026))
SERVICIOS_DISPONIBLES = [
    "Aconcagua", "Aisén", "Antofagasta", "Araucanía Norte", "Araucanía Sur", "Arauco", "Arica", "Atacama", "Bíobío",
    "Chiloé", "Concepción", "Coquimbo", "Del Maule", "Del Reloncaví", "Iquique", "Libertador B. O'Higgins",
    "Magallanes", "Metropolitano Central", "Metropolitano Norte", "Metropolitano Occidente", "Metropolitano Oriente",
    "Metropolitano Sur", "Metropolitano Suroriente", "Ñuble", "Osorno", "Talcahuano", "Valdivia",
    "Valparaíso San Antonio", "Viña Del Mar Quillota"
]
TIPOS_ESTABLECIMIENTO = ["Hospital", "SAPU", "SAR", "SUR", "CEAR", "PAME"]

DIR_DESCARGAS_DEFAULT = Path("./descargas")
MAX_REINTENTOS = 3
TIMEOUT_REPORTE = 180_000
TIMEOUT_DESCARGA = 120_000
ESPERA_CARGA_PAGINA = 15

console = Console()

# ============================================================================
# LOGGING (Archivo oculto para debug)
# ============================================================================

def setup_logging(base_dir=DIR_DESCARGAS_DEFAULT):
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)
    log_file = base_path / "log.txt"
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("cognos")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    return logger

# ============================================================================
# UTILIDADES
# ============================================================================

def sanitizar_nombre(nombre: str) -> str:
    nombre = nombre.strip().replace(" ", "_").replace(".", "").replace(",", "")
    nombre = nombre.replace("(", "").replace(")", "").replace("/", "-").replace("\\", "-")
    nombre = re.sub(r'[<>"|?*:]', '', nombre)
    return nombre[:100]

def limpiar_pantalla():
    os.system("cls" if os.name == "nt" else "clear")

# ============================================================================
# SCRAPER CORE
# ============================================================================

class CognosScraper:
    def __init__(self, config: dict, logger=None):
        self.config = config
        self.headless = not config.get("visible", False)
        self.log = logger or logging.getLogger("cognos")
        self.playwright = None
        self.browser = None
        self.page = None
        self._select_ids = {}
        self.total_descargados = 0
        self.total_errores = 0
        self.total_saltados = 0
        self.dir_descargas = Path(config.get("dir", DIR_DESCARGAS_DEFAULT))

    def iniciar(self):
        self.log.info("[INICIO] Iniciando navegador Chromium...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        self.context = self.browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
        self.page = self.context.new_page()

    def cerrar(self):
        if self.browser: self.browser.close()
        if self.playwright: self.playwright.stop()
        self.log.info("[FIN] Navegador cerrado")

    def navegar_al_reporte(self):
        self.log.debug("Navegando a URL del reporte...")
        self.page.goto(URL_REPORTE, wait_until="domcontentloaded", timeout=60_000)
        self.page.wait_for_timeout(ESPERA_CARGA_PAGINA * 1000)

    def descubrir_selectores(self, reintentos: int = 5):
        for _ in range(reintentos):
            selects = self.page.query_selector_all("select")
            self._select_ids = {}
            for sel in selects:
                sel_id = sel.get_attribute("id") or ""
                options = sel.query_selector_all("option")
                if not options: continue
                texts = [o.text_content().strip() for o in options[:5]]
                
                if all(t.isdigit() and 2010 <= int(t) <= 2030 for t in texts if t.isdigit()) and any(t.isdigit() for t in texts):
                    self._select_ids["anio"] = sel_id
                elif any("Semana" in t for t in texts):
                    self._select_ids["semana"] = sel_id
                elif any(t in TIPOS_ESTABLECIMIENTO for t in texts):
                    self._select_ids["tipo_est"] = sel_id
                elif any(t in ("Talcahuano", "Concepción", "Arauco", "Metropolitano Central", "Metropolitano Suroriente", "Osorno", "Arica") for t in texts):
                    self._select_ids["servicio"] = sel_id

            mapped_ids = set(self._select_ids.values())
            for sel in selects:
                sel_id = sel.get_attribute("id") or ""
                if sel_id and sel_id not in mapped_ids:
                    if len(sel.query_selector_all("option")) > 0:
                        self._select_ids["establecimiento"] = sel_id
                        break
            
            if "establecimiento" in self._select_ids and "anio" in self._select_ids:
                return
            self.page.wait_for_timeout(1000)

    def _get_select(self, nombre):
        return self.page.locator(f"#{self._select_ids[nombre]}")

    def aplicar_filtros_base(self, anios_target: list = None, servicio_actual: str = None):
        """Aplica filtros base seleccionando los años especificados simultáneamente y desbloqueando semanas."""
        serv_target = servicio_actual or self.config.get("servicio", "TODOS")
        anios = anios_target or self.config.get("anios", ANIOS_DISPONIBLES)
        
        anios_label = f"{anios[0]}-{anios[-1]}" if len(anios) > 1 else str(anios[0])
        self.log.info(f"[CONFIG] Aplicando filtros base para servicio '{serv_target}' (Años: {anios_label})...")
        self.descubrir_selectores()
        
        # 1. Año: Seleccionar los años especificados simultáneamente
        if set(anios) == set(ANIOS_DISPONIBLES):
            link_id = self._select_ids["anio"].replace("PRMT_SV_", "PRMT_SV_LINK_SELECT_")
            link = self.page.locator(f"#{link_id}")
            if link.count() > 0: 
                link.click()
            else: 
                self._get_select("anio").evaluate("el => { for(let o of el.options) o.selected = true; }")
        else:
            str_anios = [str(a) for a in anios]
            sel_anio = self._get_select("anio")
            sel_anio.evaluate("""(el, targetYears) => {
                for(let o of el.options) {
                    o.selected = targetYears.includes(o.text.trim());
                }
            }""", str_anios)

        self.page.wait_for_timeout(2000)
        self.descubrir_selectores()

        # 2. Edad (Asegurar que todas las 5 edades estén marcadas)
        checkboxes = self.page.query_selector_all("input[role='checkbox']") or self.page.query_selector_all("input[type='checkbox']")
        for cb in checkboxes:
            try:
                aria_chk = cb.get_attribute("aria-checked")
                if aria_chk != "true" and not cb.is_checked():
                    cb.click()
                    self.page.wait_for_timeout(100)
            except Exception:
                pass

        # 3. Servicio de Salud
        if serv_target != "TODOS":
            sel_serv = self._get_select("servicio")
            val = sel_serv.evaluate("""(el, target) => {
                let cleanTarget = target.toLowerCase().replace(/\\s+/g, ' ').trim();
                for(let o of el.options) {
                    let optTxt = o.text.toLowerCase().replace(/\\s+/g, ' ').trim();
                    if(optTxt === cleanTarget) return o.value;
                }
                for(let o of el.options) {
                    let optTxt = o.text.toLowerCase().replace(/\\s+/g, ' ').trim();
                    if(optTxt.includes(cleanTarget)) return o.value;
                }
                return null;
            }""", serv_target)
            if val:
                sel_serv.select_option(value=val)
            else:
                self.log.warning(f"No se encontró opción para servicio '{serv_target}'")
        self.page.wait_for_timeout(3000)
        self.descubrir_selectores()

        # 4. Tipo de Establecimiento
        tipo_est = self.config.get("tipo_est", "TODOS")
        if tipo_est != "TODOS":
            self._get_select("tipo_est").select_option(label=tipo_est)
        else:
            link_id = self._select_ids["tipo_est"].replace("PRMT_SV_", "PRMT_SV_LINK_SELECT_")
            link = self.page.locator(f"#{link_id}")
            if link.count() > 0: link.click()
            else: self._get_select("tipo_est").evaluate("el => { for(let o of el.options) o.selected = true; }")
        self.page.wait_for_timeout(3000)
        self.descubrir_selectores()

        # Obtener lista de establecimientos disponibles
        establecimientos = self._get_select("establecimiento").evaluate("""el => {
            return Array.from(el.options).map(o => ({ nombre: o.text.trim(), value: o.value })).filter(o => o.nombre !== '');
        }""")

        # 5. Seleccionar el primer establecimiento para habilitar el envío del formulario
        if establecimientos:
            self._get_select("establecimiento").select_option(value=establecimientos[0]["value"])

        # 6. Primer click a "Nueva solicitud" para que Cognos cargue todas las semanas de los años seleccionados
        self.log.info(f"Enviando primera solicitud con años ({anios_label}) seleccionados...")
        boton_nueva = self.page.locator("input[value='Nueva solicitud'], button:has-text('Nueva solicitud')")
        with self.page.expect_response(lambda response: "cognos.cgi" in response.url, timeout=TIMEOUT_REPORTE):
            boton_nueva.first.click()
        self.page.wait_for_timeout(3000)
        self.descubrir_selectores()

        # 7. Semanas: Seleccionar TODAS las semanas (ahora disponibles para los años seleccionados)
        link_id = self._select_ids["semana"].replace("PRMT_SV_", "PRMT_SV_LINK_SELECT_")
        link = self.page.locator(f"#{link_id}")
        if link.count() > 0: 
            link.click()
        else: 
            self._get_select("semana").evaluate("el => { for(let o of el.options) o.selected = true; }")
        
        # 8. Segundo click a "Nueva solicitud" para cargar la vista completa con todas las semanas
        self.log.info("Enviando segunda solicitud con todas las semanas seleccionadas...")
        with self.page.expect_response(lambda response: "cognos.cgi" in response.url, timeout=TIMEOUT_REPORTE):
            boton_nueva.first.click()
        
        # Esperar confirmación de que cargó el reporte
        link_excel = self.page.locator("a:has-text('Descargar como Excel')")
        link_excel.wait_for(state="visible", timeout=TIMEOUT_REPORTE)
        self.page.wait_for_timeout(1500)
        
        self.descubrir_selectores()
        return establecimientos

    def descargar_establecimiento(self, est: dict, ruta_destino: Path, servicio_actual: str = None):
        # 1. Deseleccionar cualquier establecimiento previo para evitar descargas acumuladas
        if "establecimiento" in self._select_ids:
            try:
                link_id = self._select_ids["establecimiento"].replace("PRMT_SV_", "PRMT_SV_LINK_DESELECT_")
                link = self.page.locator(f"#{link_id}")
                if link.count() > 0: 
                    link.click()
                    self.page.wait_for_timeout(400)
            except Exception:
                pass
            
            # 2. Seleccionar el nuevo
            self._get_select("establecimiento").select_option(value=est["value"])
        
        # 3. Boton "Nueva solicitud"
        boton = self.page.locator("input[value='Nueva solicitud'], button:has-text('Nueva solicitud')")
        link_excel = self.page.locator("a:has-text('Descargar como Excel')")
        
        # Ocultar temporalmente el link para forzar que reaparezca en el DOM/se haga visible al finalizar la carga
        try:
            link_excel.evaluate("el => el.style.display = 'none'")
        except Exception:
            pass

        with self.page.expect_response(lambda response: "cognos.cgi" in response.url, timeout=TIMEOUT_REPORTE):
            boton.first.click()

        # 4. Esperar dinámicamente al botón de Excel
        link_excel.wait_for(state="visible", timeout=TIMEOUT_REPORTE)
        self.page.wait_for_timeout(1500)
        
        ruta_destino.parent.mkdir(parents=True, exist_ok=True)
        
        # 5. Capturar descarga de forma robusta en el contexto
        with self.context.expect_event("download", timeout=TIMEOUT_DESCARGA) as download_info:
            link_excel.click()
        download = download_info.value
        download.save_as(str(ruta_destino))
        
        # Cerrar posibles popups residuales
        for p in self.context.pages:
            if p != self.page:
                try: p.close()
                except: pass
        
        exito = ruta_destino.exists() and ruta_destino.stat().st_size > 0
        self.descubrir_selectores()
        return exito

# ============================================================================
# UI INTERACTIVA (Rich)
# ============================================================================

def mostrar_banner():
    console.print(Panel.fit(
        "[bold cyan]🏥 DEIS COGNOS SCRAPER - CHILE[/bold cyan]\n"
        "[dim]Automatizador de Descarga de Atenciones de Urgencia - Ministerio de Salud[/dim]",
        border_style="cyan"
    ))

def solicitar_servicios():
    console.print("\n[bold yellow]PASO 1: SELECCIÓN DE SERVICIO(S) DE SALUD[/bold yellow]")
    console.print("  [green][0][/green] [bold]TODOS LOS SERVICIOS (Chile Completo)[/bold]")
    for i, serv in enumerate(SERVICIOS_DISPONIBLES, 1):
        console.print(f"  [cyan][{i}][/cyan] {serv}")
            
    while True:
        opc = Prompt.ask("\n➤ Elige número(s) o nombre(s) (ej: 'Metropolitano Sur, Metropolitano Suroriente' o números separados por coma '22,23')")
        if opc.strip() == "0" or opc.lower() in ("todos", "all"):
            return ["TODOS"]
        
        # Procesar lista separada por coma o espacio si ingresa varios
        partes = [p.strip() for p in opc.split(",") if p.strip()]
        servicios_seleccionados = []
        valido = True
        for p in partes:
            if p.isdigit() and 1 <= int(p) <= len(SERVICIOS_DISPONIBLES):
                servicios_seleccionados.append(SERVICIOS_DISPONIBLES[int(p) - 1])
            else:
                coincidencias = [s for s in SERVICIOS_DISPONIBLES if p.lower() in s.lower()]
                if len(coincidencias) == 1:
                    servicios_seleccionados.append(coincidencias[0])
                elif p in SERVICIOS_DISPONIBLES:
                    servicios_seleccionados.append(p)
                else:
                    console.print(f"[red]⚠ Servicio no reconocido o ambiguo: '{p}'[/red]")
                    valido = False
                    break
        if valido and servicios_seleccionados:
            return servicios_seleccionados

def solicitar_anios():
    console.print("\n[bold yellow]PASO 2: AÑOS ESTADÍSTICOS[/bold yellow]")
    console.print("  [cyan][1][/cyan] Todos los años (2015 a 2025)")
    console.print("  [cyan][2][/cyan] Un año específico (ej: 2015)")
    console.print("  [cyan][3][/cyan] Rango de años (ej: 2020-2023)")
    opc = Prompt.ask("➤ Elige opción", choices=["1", "2", "3"], default="1")
    
    if opc == "1": return ANIOS_DISPONIBLES
    elif opc == "2":
        while True:
            a = Prompt.ask("➤ Ingresa el año específico (ej: 2024)")
            if a.isdigit() and int(a) in ANIOS_DISPONIBLES:
                return [int(a)]
            console.print("[red]⚠ Año inválido o fuera de rango (2015-2025).[/red]")
    else:
        while True:
            r = Prompt.ask("➤ Ingresa el rango (ej: 2020-2024)")
            if "-" in r:
                partes = r.split("-")
                if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
                    desde, hasta = int(partes[0]), int(partes[1])
                    if desde in ANIOS_DISPONIBLES and hasta in ANIOS_DISPONIBLES and desde <= hasta:
                        return list(range(desde, hasta + 1))
            console.print("[red]⚠ Formato incorrecto o años fuera de rango (ej: 2020-2024).[/red]")

def solicitar_tipo_est():
    console.print("\n[bold yellow]PASO 3: TIPO DE ESTABLECIMIENTO[/bold yellow]")
    console.print("  [cyan][1][/cyan] Todos (Hospital, SAPU, SAR, SUR, CEAR, PAME)")
    console.print("  [cyan][2][/cyan] Elegir específico")
    opc = Prompt.ask("➤ Elige opción", choices=["1", "2"], default="1")
    if opc == "2":
        for i, t in enumerate(TIPOS_ESTABLECIMIENTO, 1):
            console.print(f"  [cyan][{i}][/cyan] {t}")
        while True:
            idx = Prompt.ask("➤ Número")
            if idx.isdigit() and 1 <= int(idx) <= len(TIPOS_ESTABLECIMIENTO):
                return TIPOS_ESTABLECIMIENTO[int(idx)-1]
            console.print("[red]⚠ Por favor, ingresa un número válido de la lista.[/red]")
    return "TODOS"

def obtener_nombres_establecimientos(config_temp):
    """Obtiene la lista real de nombres usando un scraper headless temporal"""
    logger = setup_logging(config_temp.get("dir", DIR_DESCARGAS_DEFAULT))
    scraper = CognosScraper(config_temp, logger)
    serv = config_temp["servicios"][0] if isinstance(config_temp.get("servicios"), list) else config_temp.get("servicio", "TODOS")
    try:
        scraper.iniciar()
        scraper.navegar_al_reporte()
        return scraper.aplicar_filtros_base(servicio_actual=serv)
    except Exception as e:
        console.print(f"[red]Error consultando Cognos: {e}[/red]")
        return []
    finally:
        scraper.cerrar()

def solicitar_establecimiento(config_temp):
    console.print("\n[bold yellow]PASO 2: ESTABLECIMIENTOS[/bold yellow]")
    console.print("  [cyan][1][/cyan] Todos los establecimientos (Descarga automática 1 a 1)")
    console.print("  [cyan][2][/cyan] Elegir específico de la lista")
    opc = Prompt.ask("➤ Elige opción", choices=["1", "2"], default="1")
    
    if opc == "2":
        servs = config_temp.get("servicios", [config_temp.get("servicio")])
        if servs != ["TODOS"]:
            with console.status("[bold cyan]⏳ Conectando a Cognos DEIS para obtener los nombres reales...[/bold cyan]", spinner="dots"):
                lista = obtener_nombres_establecimientos(config_temp)
            if lista:
                console.print(f"\n[bold green]Encontrados {len(lista)} recintos:[/bold green]")
                for i, est in enumerate(lista, 1):
                    console.print(f"  [cyan][{i}][/cyan] {est['nombre']}")
                while True:
                    idx = Prompt.ask("➤ Número")
                    if idx.isdigit() and 1 <= int(idx) <= len(lista):
                        return lista[int(idx)-1]
                    console.print("[red]⚠ Por favor, ingresa un número válido de la lista.[/red]")
        else:
            console.print("[yellow]⚠ Si buscas 'Todos los servicios', no se puede listar establecimientos específicos.[/yellow]")
    return "TODOS"

def main_interactivo():
    limpiar_pantalla()
    mostrar_banner()
    
    config = {}
    config["servicios"] = solicitar_servicios()
    config["anios"] = ANIOS_DISPONIBLES
    config["semanas"] = "TODAS"
    config["tipo_est"] = solicitar_tipo_est()
    config["establecimiento"] = solicitar_establecimiento(config)
    config["dir"] = DIR_DESCARGAS_DEFAULT
    config["visible"] = False
    
    # Resumen
    est_str = "Todos (Descarga 1 por 1)" if config['establecimiento'] == 'TODOS' else config['establecimiento']['nombre']
    serv_str = ", ".join(config['servicios']) if isinstance(config['servicios'], list) else config['servicios']

    tabla = Table(title="📋 RESUMEN DE CONFIGURACIÓN", border_style="green")
    tabla.add_column("Parámetro", style="bold")
    tabla.add_column("Valor", style="cyan")
    tabla.add_row("🏥 Servicio(s)", serv_str)
    tabla.add_row("📅 Años", "[green]Todos (2015-2025)[/green]")
    tabla.add_row("📊 Semanas", config['semanas'])
    tabla.add_row("👥 Grupos de edad", "[green]Todos (5 grupos marcados)[/green]")
    tabla.add_row("🏢 Tipo Establecimiento", config['tipo_est'])
    tabla.add_row("📍 Establecimiento", est_str)
    
    console.print()
    console.print(tabla)
    
    if Confirm.ask("\n[bold green]¿Iniciar la descarga?[/bold green]"):
        ejecutar_scraper(config)
    else:
        console.print("[yellow]Operación cancelada.[/yellow]")

# ============================================================================
# EJECUCIÓN
# ============================================================================

def ejecutar_scraper(config):
    dir_salida = Path(config.get("dir", DIR_DESCARGAS_DEFAULT))
    logger = setup_logging(dir_salida)
    scraper = CognosScraper(config, logger)
    
    servicios = config.get("servicios")
    if not servicios:
        servs = [config.get("servicio", "Metropolitano Suroriente")]
    else:
        servs = servicios
        
    anios = config.get("anios", ANIOS_DISPONIBLES)
    rango_label = f"{anios[0]}-{anios[-1]}" if len(anios) > 1 else str(anios[0])
    
    console.print(f"\n[bold cyan]🚀 INICIANDO AUTOMATIZADOR DE DESCARGAS DEIS (AÑOS: {rango_label})...[/bold cyan]")
    
    try:
        with console.status("[bold blue]Inicializando Chromium...[/bold blue]"):
            scraper.iniciar()
        
        for serv in servs:
            console.print(f"\n[bold yellow]🏥 SERVICIO DE SALUD: {serv}[/bold yellow]")
            
            with console.status(f"[bold yellow]Configurando filtros base para {serv} (Años: {rango_label})...[/bold yellow]"):
                scraper.navegar_al_reporte()
                establecimientos = scraper.aplicar_filtros_base(anios_target=anios, servicio_actual=serv)
                
            if config.get("establecimiento") != "TODOS" and isinstance(config.get("establecimiento"), dict):
                establecimientos = [e for e in establecimientos if e["value"] == config["establecimiento"]["value"]]
                
            if not establecimientos:
                console.print(f"[red]⚠ No se encontraron establecimientos para {serv}.[/red]")
                continue
                
            console.print(f"[green]✓ Filtros aplicados con éxito. {len(establecimientos)} archivo(s) por descargar.[/green]\n")
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(complete_style="green", finished_style="blue"),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                
                task_id = progress.add_task(f"Descargando {serv}...", total=len(establecimientos))
                
                for est in establecimientos:
                    serv_folder = sanitizar_nombre(serv)
                    nombre_archivo = f"{rango_label}_{serv_folder}_{sanitizar_nombre(est['nombre'])}.xlsx"
                    ruta = dir_salida / serv_folder / rango_label / nombre_archivo
                    
                    if ruta.exists() and ruta.stat().st_size > 0:
                        scraper.total_saltados += 1
                        progress.console.print(f"[dim]⏭ Saltado (Ya existe): {nombre_archivo}[/dim]")
                        progress.advance(task_id)
                        continue
                        
                    progress.update(task_id, description=f"Descargando: [cyan]{est['nombre']}[/cyan]")
                    
                    exito = False
                    for intento in range(MAX_REINTENTOS):
                        try:
                            if scraper.descargar_establecimiento(est, ruta, servicio_actual=serv):
                                exito = True
                                break
                        except Exception as e:
                            logger.error(f"Intento {intento+1} falló: {e}")
                            if intento < MAX_REINTENTOS - 1:
                                progress.console.print(f"[yellow]⚠ Reintentando {est['nombre']} ({intento+2}/{MAX_REINTENTOS})...[/yellow]")
                                try:
                                    scraper.navegar_al_reporte()
                                    scraper.aplicar_filtros_base(anios_target=anios, servicio_actual=serv)
                                except: pass
                                
                    if exito:
                        scraper.total_descargados += 1
                        progress.console.print(f"[green]✓ OK: {nombre_archivo}[/green]")
                    else:
                        scraper.total_errores += 1
                        progress.console.print(f"[red]✗ FALLO: {nombre_archivo}[/red]")
                    
                    progress.advance(task_id)
                    time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[red]⛔ Proceso cancelado por el usuario.[/red]")
    except Exception as e:
        console.print(f"\n[red]💥 ERROR FATAL: {e}[/red]")
        logger.exception("Error fatal")
    finally:
        scraper.cerrar()
        resumen = Panel(
            f"✅ [green]Descargados:[/green] {scraper.total_descargados}\n"
            f"⏭  [yellow]Saltados:[/yellow]    {scraper.total_saltados}\n"
            f"❌ [red]Errores:[/red]       {scraper.total_errores}",
            title="[bold]Resumen de Descargas[/bold]",
            border_style="cyan",
            expand=False
        )
        console.print("\n")
        console.print(resumen)

# ============================================================================
# ENTRY POINT
# ============================================================================

def parsear_anios_arg(val):
    if not val:
        return ANIOS_DISPONIBLES
    val = val.strip().lower()
    if val in ("todos", "all"):
        return ANIOS_DISPONIBLES
    if "-" in val:
        partes = val.split("-")
        if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
            desde, hasta = int(partes[0]), int(partes[1])
            return [a for a in range(desde, hasta + 1) if a in ANIOS_DISPONIBLES]
    if "," in val:
        partes = [p.strip() for p in val.split(",") if p.strip().isdigit()]
        return [int(p) for p in partes if int(p) in ANIOS_DISPONIBLES]
    if val.isdigit() and int(val) in ANIOS_DISPONIBLES:
        return [int(val)]
    return ANIOS_DISPONIBLES

def main():
    parser = argparse.ArgumentParser(description="Descarga automática COGNOS DEIS")
    parser.add_argument("--servicios", nargs="+", help="Servicios de Salud (ej: 'Metropolitano Sur' 'Metropolitano Suroriente')")
    parser.add_argument("--anio", "--anios", type=str, dest="anios", help="Descargar año o rango de años (ej: 2015-2025, 2024, o todos)")
    parser.add_argument("--tipo-est", type=str, default="TODOS", help="Tipo de establecimiento (Hospital, SAPU, SAR, SUR, CEAR, PAME o TODOS)")
    parser.add_argument("--dir", type=str, default="./descargas", help="Directorio de destino para descargas")
    parser.add_argument("--silencioso", action="store_true", help="No interactivo")
    parser.add_argument("--visible", action="store_true", help="Mostrar navegador")
    args = parser.parse_args()

    if args.silencioso or args.servicios or args.anios:
        # Modo cli automatizado
        servs = args.servicios if args.servicios else ["Metropolitano Sur", "Metropolitano Suroriente"]
        config = {
            "servicios": servs,
            "anios": parsear_anios_arg(args.anios),
            "semanas": "TODAS",
            "tipo_est": args.tipo_est,
            "establecimiento": "TODOS",
            "dir": args.dir,
            "visible": args.visible
        }
        ejecutar_scraper(config)
    else:
        # Modo interactivo
        try:
            main_interactivo()
        except KeyboardInterrupt:
            console.print("\n[yellow]Salida solicitada.[/yellow]")

if __name__ == "__main__":
    main()
