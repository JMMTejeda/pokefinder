"""El REGISTRO de la «Oficina»: una ficha por cada proceso que trabaja en PokéFinder, escrita a mano y en un solo sitio (owner, 3 November 2026: "tener como si fuese literalmente una
oficina y saber cómo van todos mis procesos, poder añadir nuevas funcionalidades, que todo se gestione bien, centralizado").
Para añadir una función nueva basta con añadir UNA ficha a PROCESOS (guía en OFICINA.md); oficina.py hace el resto (estado, panel, acciones, actividad).

Campos de una ficha:
  id, nombre, grupo (clave de GRUPOS), icono          qué es y dónde se pinta
  que                                                 qué hace, en una o dos frases
  ejecuta                                             quién lo ejecuta (servidor, subproceso, tarea de Claude, a mano, Windows)
  cuando                                              cuándo se ejecuta
  hora                                                (opcional) hora local tras la cual debería estar hecho hoy; pasada una hora sin hacerse, sale «atrasado»
  recursos                                            qué gasta: lista de [recurso, texto]; recurso ∈ RECURSOS (el panel enseña su gasto real)
  notifica                                            lista de [canal, cuándo]; canal ∈ CANALES (ntfy)
  equipo                                              cómo se reparte con el compañero (o «No» si no aplica)
  datos                                               qué ficheros produce o lee
  ver                                                 ruta de la app donde se ve el resultado
  estado                                              cómo leer su estado: {"adaptador": nombre de una función de oficina.py, ...parámetros}
  lanzar                                              True si el panel puede ejecutarlo ahora (oficina.ACCIONES[id])
  interruptor                                         (opcional) {"adaptador": ...}: cómo se enciende y se apaga
  modo                                                auto | manual | claude | infra  (cómo arranca)
"""

GRUPOS = [
    ("mercado", "📈", "Mercado y precios", "Lo que cuesta cada carta, de dónde sale y cómo cambia."),
    ("contenido", "🎬", "YouTube, comunidades y contenido", "Lo que se dice por ahí y lo que se publica."),
    ("podcasts", "🎙", "Podcasts, vídeos y conocimiento", "Transcribir, resumir y aprender de lo que dicen los expertos, en podcasts y en vídeos de YouTube."),
    ("claude", "🤖", "Tareas de Claude", "Lo que escribe Claude (usa tus tokens, así que se limita)."),
    ("avisos", "🔔", "Avisos y vigilancia", "Lo que te avisa al móvil y lo que comprueba que todo funciona."),
    ("equipo", "🤝", "Equipo y reparto", "Lo que se comparte con tu compañero para no repetir trabajo."),
    ("infra", "🖥", "Infraestructura", "El servidor, el arranque y el acceso desde fuera."),
]

# lo que se gasta y tiene un límite; el panel enseña cuánto va gastado de cada uno
RECURSOS = {
    "ebay": "Llamadas a la API de eBay (5.000 al día, se renuevan a las 9:00 de Madrid)",
    "groq": "Audio de Groq para transcribir (7.200 s por hora y 28.800 s por día; la cola usa el 90 %)",
    "youtube": "Cuota de la API de YouTube (10.000 unidades al día)",
    "claude": "Tokens de Claude (tu uso de la suscripción)",
    "navegador": "Navegador oculto de la torre (CPU y memoria mientras trabaja)",
    "red": "Solo lectura de páginas públicas, sin coste",
    "disco": "Disco local",
}

# los canales de ntfy (tools/avisar.py, .secrets/ntfy.json): el nombre de cada tema es secreto y no sale nunca aquí
CANALES = {
    "tema": ("🔵", "Tu tema", "Avisos para ti: búsquedas terminadas, transcripciones, resumen diario."),
    "salud": ("🔴", "Salud", "Avisos de lo que falló o no se actualizó."),
    "equipo": ("🟢", "Equipo", "Compartido con tu compañero, firmado con tu nombre: quién hizo qué."),
}

PROCESOS = [
    # ------------------------------------------------------------------ MERCADO Y PRECIOS
    {"id": "foto_ebay", "nombre": "Foto diaria de eBay", "grupo": "mercado", "icono": "📸", "modo": "auto",
     "que": "Pregunta a eBay (API oficial) por los anuncios de cada Gold Star en 6 tiendas de eBay y guarda cuántos hay, mediana y percentiles. Alimenta el historial de precios. Es lo que PIDEN los vendedores, no lo que se cobra.",
     "ejecuta": "Servidor, bucle «mercado» (mira cada 5 min) → subproceso mercado.py", "cuando": "Una vez al día desde las 10:00 (10:30 en el ordenador de Jesús)", "hora": 10,
     "recursos": [["ebay", "unas 160 llamadas (tope automático 3.000; hay 2.000 reservadas para tus búsquedas)"], ["red", "—"]],
     "notifica": [["equipo", "al subir su foto o al importar la del otro"], ["salud", "si no se hizo (comprobaciones de las 10, 15 y 18 h)"]],
     "equipo": "El primero en hacerla la sube a git (compartido/ebay) y el otro la importa sin gastar llamadas. Fernando va primero.",
     "datos": ["data/mercado/AAAA-MM-DD.json", "data/mercado/historial.json", "data/historial/fecha=*.parquet"], "ver": "#/mercado/cartas",
     "estado": {"adaptador": "json_estado", "archivo": "data/mercado/estado.json", "hoy": ["data/mercado/ultimo.json", "date"]}, "lanzar": True},
    {"id": "estados", "nombre": "Estado de las cartas (lo que dice el vendedor)", "grupo": "mercado", "icono": "🔎", "modo": "auto",
     "que": "Pregunta a eBay, anuncio por anuncio y una sola vez, el «Card Condition» que eligió el vendedor (Near Mint, Lightly played…) y sus notas de defectos. Se usa para comparar cada carta con las de su mismo estado.",
     "ejecuta": "Servidor, bucle «mercado» → subproceso condiciones.py", "cuando": "Cuando una búsqueda deja anuncios sin estado; hasta 1.500 llamadas al día",
     "recursos": [["ebay", "hasta 1.500 llamadas al día (paran al llegar al límite automático)"]],
     "notifica": [["equipo", "al subir lo que ha leído"]],
     "equipo": "Lo que uno ya preguntó se sube (compartido/estados) y el otro no lo repite.",
     "datos": ["data/app/condiciones.json"], "ver": "#/mercado",
     "estado": {"adaptador": "condiciones"}, "lanzar": True},
    {"id": "ventas", "nombre": "Ventas reales (SNKRDUNK y Collectr)", "grupo": "mercado", "icono": "💰", "modo": "auto",
     "que": "Lee con el navegador oculto las ventas reales de cada carta en SNKRDUNK (con fecha y estado) y el precio de referencia de Collectr. Es lo que decide el valor de mercado y los chollos.",
     "ejecuta": "Servidor, bucle «mercado» → subproceso ventas.py (navegador oculto)", "cuando": "Una vez al día, cuando el equipo está encendido (unos 22 min)", "hora": 9,
     "recursos": [["navegador", "unos 22 minutos al día"], ["red", "sin coste"]],
     "notifica": [["salud", "si no se hizo hoy"]],
     "equipo": "No (cada uno lee lo suyo). Candidato a compartir: son páginas públicas iguales para los dos.",
     "datos": ["data/ventas/*.json"], "ver": "#/chollos",
     "estado": {"adaptador": "json_estado", "archivo": "data/state/ventas.json", "fin": "fin", "dia": "dia"}, "lanzar": True},
    {"id": "precios_graduadas", "nombre": "Precios y graduadas (todas las API)", "grupo": "mercado", "icono": "🏷", "modo": "auto",
     "que": "Cada día pide a PokemonPriceTracker, PokéWallet y TCGAPI.dev el precio de las cartas que sigues (Gold Stars, Call of Legends, Campaign y promos): ventas de eBay por nota (PSA, CGC, BGS, TAG), precio sin gradear en TCGplayer y Cardmarket, y guarda el historial.",
     "ejecuta": "Servidor, bucle «mercado» → subproceso precios_graduadas.py", "cuando": "Una vez al día desde la 01:00 (se renuevan los créditos); si falta algo, reintenta cada 20 minutos", "hora": 9,
     "recursos": [["red", "PokemonPriceTracker 100 créditos al día (2 por carta con ventas de eBay), PokéWallet 100 peticiones por hora, TCGAPI.dev 100 al día"]],
     "notifica": [["salud", "si no se hizo hoy"]],
     "equipo": "Sí: cada carta tiene un dueño (la mitad cada uno, con sus propios créditos gratis); lo pedido se sube a git y el otro lo importa. Pasadas las 14:00, lo que falte lo pide cada uno.",
     "datos": ["data/precios/*.json"], "ver": "#/precios",
     "estado": {"adaptador": "json_estado", "archivo": "data/precios/estado.json", "fin": "fin", "dia": "dia"}, "lanzar": True},
    {"id": "revision_diaria", "nombre": "Revisión diaria de todos los mercados", "grupo": "mercado", "icono": "🛰", "modo": "auto",
     "que": "Busca en todos los mercados (Mercari, SNKRDUNK, Rakuma, Magi, Card Rush…) las colecciones que toquen hoy, una búsqueda cada vez y solo si el motor está libre.",
     "ejecuta": "Servidor, bucle «diario» (cada minuto) → motor de búsquedas", "cuando": "Si está encendida: tras las 7:00, una búsqueda cada vez (unos 5 min cada una)",
     "recursos": [["navegador", "horas de motor; una búsqueda cada ~5 min"], ["ebay", "las búsquedas de eBay entran en «tus búsquedas»"]],
     "notifica": [["tema", "al terminar, parar o fallar una búsqueda"]],
     "equipo": "No.", "datos": ["data/mercado/diario.json"], "ver": "#/mercado",
     "estado": {"adaptador": "revision_diaria"}, "lanzar": False, "interruptor": {"adaptador": "revision_diaria"}},
    {"id": "motor", "nombre": "Motor de búsquedas", "grupo": "mercado", "icono": "⚙️", "modo": "infra",
     "que": "El que ejecuta tus búsquedas: abre un navegador oculto (Playwright) y lee Mercari, SNKRDUNK, Rakuma, Magi, etc., y la API de eBay. Trabaja de una búsqueda en una. Reanuda por páginas si se corta.",
     "ejecuta": "Proceso aparte (motor.py) que arranca el servidor", "cuando": "Siempre encendido; trabaja cuando hay una búsqueda en la cola",
     "recursos": [["navegador", "mientras dura cada búsqueda"], ["ebay", "tus búsquedas (origen «manual», con 2.000 llamadas reservadas)"]],
     "notifica": [["tema", "búsqueda terminada, parada o fallida"]],
     "equipo": "Las búsquedas guardadas se comparten con tools/importar_busquedas.py.", "datos": ["data/app/jobs/", "data/app/searches/"], "ver": "#/recientes",
     "estado": {"adaptador": "motor"}, "lanzar": False},
    {"id": "chollos", "nombre": "Chollos (por debajo del valor de mercado)", "grupo": "mercado", "icono": "💸", "modo": "auto",
     "que": "Marca los anuncios que están al 80 % o menos del valor de mercado, comparando solo la misma casa de gradeo, nota y edición, con la confianza del dato (ventas que coinciden, o solo una referencia).",
     "ejecuta": "Al abrir la pestaña Chollos y en los avisos (ventas.marcar)", "cuando": "Cada vez que termina una búsqueda",
     "recursos": [["disco", "—"]], "notifica": [["equipo", "chollo de confianza media o alta (uno por anuncio, con su enlace)"]],
     "equipo": "Los chollos de confianza media o alta se avisan al equipo para que no se repitan.", "datos": ["data/ventas/*.json"], "ver": "#/chollos",
     "estado": {"adaptador": "sin_estado", "texto": "Se calcula al momento: no tiene estado propio."}, "lanzar": False},
    {"id": "historial", "nombre": "Historial de precios (Parquet + DuckDB)", "grupo": "mercado", "icono": "📉", "modo": "auto",
     "que": "Guarda cada día los anuncios de la foto en ficheros Parquet y se consulta con SQL (DuckDB), sin servidor. De ahí salen las gráficas de evolución.",
     "ejecuta": "Se escribe solo al terminar la foto de eBay (historial.py)", "cuando": "Cada vez que hay una foto válida",
     "recursos": [["disco", "pocos KB al día"]], "notifica": [["salud", "si falta el día de hoy"]],
     "equipo": "Cada uno guarda el suyo (se completa con la foto compartida).", "datos": ["data/historial/fecha=*.parquet"], "ver": "#/historial",
     "estado": {"adaptador": "historial"}, "lanzar": False},

    # ------------------------------------------------------------------ YOUTUBE, COMUNIDADES Y CONTENIDO
    {"id": "youtube", "nombre": "YouTube: vídeos y comentarios", "grupo": "contenido", "icono": "▶️", "modo": "auto",
     "que": "Lee con la API de YouTube los vídeos nuevos de los canales seguidos (16, con Card Men) y sus comentarios; saca temas, Pokémon, sets y tono.",
     "ejecuta": "Servidor, bucle «mercado» → subproceso contenido.py", "cuando": "Una vez al día desde las 7:00",
     "recursos": [["youtube", "unas 60 unidades al día de 10.000"]], "notifica": [["salud", "si no se hizo hoy"]],
     "equipo": "No (cada uno tiene su clave de YouTube).", "datos": ["data/contenido/*.json"], "ver": "#/mercado/youtube", "hora": 9,
     "estado": {"adaptador": "json_estado", "archivo": "data/contenido/estado.json"}, "lanzar": True},
    {"id": "comunidades", "nombre": "Comunidades: foros y Reddit", "grupo": "contenido", "icono": "💬", "modo": "auto",
     "que": "Lee foros y comunidades públicas (Elite Fourum, PokeBeach, r/PokeInvesting) y guarda los hilos nuevos con su eco. Sin cuenta.",
     "ejecuta": "Servidor, bucle «mercado» → subproceso comunidades.py", "cuando": "Una vez al día desde las 7:00",
     "recursos": [["red", "una petición cada 15 s a Reddit"]], "notifica": [["salud", "si no se hizo hoy"]],
     "equipo": "No (candidato a compartir).", "datos": ["data/comunidades/posts.json"], "ver": "#/mercado/comunidades", "hora": 9,
     "estado": {"adaptador": "json_estado", "archivo": "data/comunidades/estado.json"}, "lanzar": True},
    {"id": "estudio", "nombre": "Estudio de contenido", "grupo": "contenido", "icono": "🎞", "modo": "manual",
     "que": "Monta vídeos verticales, posters y carruseles con tus datos reales (¿cuál vale más?, así se ha vendido, tops). Local y gratis, sin voz.",
     "ejecuta": "A mano desde la pestaña Estudio → subproceso estudio.py", "cuando": "Solo cuando lo pides",
     "recursos": [["disco", "un vídeo ocupa pocos MB"]], "notifica": [], "equipo": "No.", "datos": ["data/reels/"], "ver": "#/estudio",
     "estado": {"adaptador": "estudio"}, "lanzar": False},

    # ------------------------------------------------------------------ PODCASTS Y CONOCIMIENTO
    {"id": "podcast_cola", "nombre": "Cola de transcripción de podcasts", "grupo": "podcasts", "icono": "🎧", "modo": "auto",
     "que": "Transcribe con Groq los episodios de Card Lounge y Card Men sin repetir: primero el último mes, luego 3 meses y luego lo anterior, un episodio a la vez y sin pasar los límites de audio de Groq. Groq solo transcribe.",
     "ejecuta": "Servidor, bucle «podcasts» (cada 5 min)", "cuando": "Cada 5 minutos mira si cabe otro episodio",
     "recursos": [["groq", "hasta 6.480 s por hora y 25.920 s por día"], ["red", "descarga el audio del feed público"]],
     "notifica": [["tema", "cada episodio transcrito"]],
     "equipo": "Sí: cada episodio tiene un dueño (la mitad cada uno, por su identificador); quien lo transcribe lo sube a git y el otro lo importa. Si en 6 horas no llega, lo hace el otro.", "datos": ["data/transcripciones/", "data/transcripciones_db/"], "ver": "#/mercado/podcasts",
     "estado": {"adaptador": "podcast_cola"}, "lanzar": True, "interruptor": {"adaptador": "podcast_cola"}},
    {"id": "expertise", "nombre": "Base de conocimiento del TCG", "grupo": "podcasts", "icono": "🧠", "modo": "manual",
     "que": "Todo lo que se va aprendiendo (cartas, jerga, rarezas, probabilidades, mercado, comparativas) con su fuente, su nivel de confianza y el razonamiento de por qué se cree o no. Los datos de podcasts y webs entran como «por comprobar».",
     "ejecuta": "La rellena Claude (tarea diaria) o tú a mano; screener/scripts/expertise.py", "cuando": "Cuando se aprende algo",
     "recursos": [["claude", "lo que gaste la tarea que la rellena"], ["disco", "DuckDB local"]], "notifica": [],
     "equipo": "No (se podría compartir como fichero).", "datos": ["data/expertise/expertise.duckdb"], "ver": "",
     "estado": {"adaptador": "expertise"}, "lanzar": False},

    # ------------------------------------------------------------------ TAREAS DE CLAUDE
    {"id": "t_resumen_podcasts", "nombre": "Resúmenes de podcasts (Claude)", "grupo": "claude", "icono": "📝", "modo": "claude",
     "que": "Escribe «Lo esencial» de cada episodio con citas literales comprobadas en la transcripción y la jerga explicada. Como mucho 3 episodios por ejecución para gastar pocos tokens; comprueba cada cita antes de guardar.",
     "ejecuta": "Tarea programada de la app de Claude (pokefinder-resumen-podcasts)", "cuando": "Cada día a las 10:30, con el equipo encendido",
     "recursos": [["claude", "unos 15.000 tokens de lectura por hora de audio y episodio (máx. 3 al día)"]], "notifica": [],
     "equipo": "Sí: cada resumen tiene dueño (la mitad cada uno); el resumen de Claude se sube a git y el otro lo importa. Si en 12 horas no llega, lo escribe el otro.", "datos": ["data/podcasts/resumenes/"], "ver": "#/mercado/podcasts",
     "estado": {"adaptador": "claude_tarea", "id": "pokefinder-resumen-podcasts", "pendientes": "resumenes"}, "lanzar": False},
    {"id": "t_resumen_comunidades", "nombre": "Resumen de comunidades (Claude)", "grupo": "claude", "icono": "🗞", "modo": "claude",
     "que": "Escribe cada día «qué está pasando» en las comunidades, con un enlace por punto. Lo escribe Claude (decisión del 2 de noviembre), no Groq.",
     "ejecuta": "Tarea programada de la app de Claude (pokefinder-resumen-comunidades)", "cuando": "Cada día a las 9:30 — AÚN NO CREADA",
     "recursos": [["claude", "menos que un episodio de podcast"]], "notifica": [],
     "equipo": "No.", "datos": ["data/comunidades/resumenes/"], "ver": "#/mercado/comunidades",
     "estado": {"adaptador": "claude_tarea", "id": "pokefinder-resumen-comunidades"}, "lanzar": False},

    # ------------------------------------------------------------------ AVISOS Y VIGILANCIA
    {"id": "avisos", "nombre": "Avisos al móvil", "grupo": "avisos", "icono": "📲", "modo": "auto",
     "que": "Te avisa por ntfy de las búsquedas que terminan, paran o fallan, de los chollos nuevos (uno por anuncio, con enlace) y manda un resumen diario. Cuando una búsqueda de texto no tiene ventas con las que comparar, manda aparte hasta 3 «posibles chollos»: anuncios en inglés o japonés (o sin idioma indicado, salvo Vinted y países no ingleses) entre el 40 % y el 65 % de la mediana de lo que piden por la misma carta y nota, con al menos 12 anuncios comparables. Es precio pedido, no vendido. Nunca lleva claves ni datos personales.",
     "ejecuta": "Servidor, bucle «avisos» (cada minuto)", "cuando": "Cada minuto mira; el resumen diario a las 10:00",
     "recursos": [["red", "ntfy.sh, gratis"]], "notifica": [["tema", "búsquedas, posibles chollos y resumen diario"], ["equipo", "chollos fiables"]],
     "equipo": "Los chollos fiables van al tema compartido, firmados.", "datos": ["data/state/avisos.json"], "ver": "",
     "estado": {"adaptador": "avisos"}, "lanzar": False},
    {"id": "salud", "nombre": "Vigilante de salud", "grupo": "avisos", "icono": "🩺", "modo": "auto",
     "que": "Comprueba que el trabajo diario ocurrió de verdad: servidor, foto de eBay, comunidades, ventas, historial, trabajos con error y disco libre. Solo lee; si algo falló, avisa una vez por franja.",
     "ejecuta": "Servidor, bucle «salud» → tools/comprobar_salud.py", "cuando": "A las 10:00, 15:00 y 18:00",
     "recursos": [["red", "ntfy.sh"]], "notifica": [["salud", "lo que no se actualizó (urgente)"]],
     "equipo": "No.", "datos": ["data/state/salud.json"], "ver": "",
     "estado": {"adaptador": "salud"}, "lanzar": False},

    # ------------------------------------------------------------------ EQUIPO Y REPARTO
    {"id": "compartir", "nombre": "Reparto con tu compañero (git)", "grupo": "equipo", "icono": "🔁", "modo": "auto",
     "que": "Lo que uno lee en eBay una vez (foto del día y estados de cartas) se sube solo a compartido/ y el otro lo importa con git fetch + git show, sin tocar su carpeta ni gastar llamadas.",
     "ejecuta": "Dentro de la foto de eBay y de los estados (compartir.py)", "cuando": "Antes de gastar llamadas (importar) y al terminar (publicar)",
     "recursos": [["red", "GitHub"]], "notifica": [["equipo", "foto subida, estados subidos o foto importada"]],
     "equipo": "Es el reparto en sí. Necesita git config pokefinder.rama <fernando|jesus>.", "datos": ["compartido/ebay/", "compartido/estados/", "data/state/compartir.log"], "ver": "",
     "estado": {"adaptador": "compartir"}, "lanzar": False},
    {"id": "cuota_ebay", "nombre": "Contador y reserva de eBay", "grupo": "equipo", "icono": "🧮", "modo": "auto",
     "que": "Apunta cada llamada a eBay con quién la pidió (tus búsquedas, foto, estados, imágenes) y reserva 2.000 de las 5.000 para tus búsquedas: las automáticas paran en 3.000. Cada uno tiene su cuota y sus claves.",
     "ejecuta": "Dentro de cada llamada a eBay (ebay_cuota.py)", "cuando": "En cada llamada",
     "recursos": [["ebay", "es quien las cuenta"]], "notifica": [], "equipo": "Cada ordenador cuenta lo suyo; el tope se ajusta en data/mercado/config.json.",
     "datos": ["data/state/ebay_llamadas/AAAA-MM-DD.txt"], "ver": "#/mercado",
     "estado": {"adaptador": "cuota_ebay"}, "lanzar": False},
    {"id": "importar_busquedas", "nombre": "Importar búsquedas del compañero", "grupo": "equipo", "icono": "📥", "modo": "manual",
     "que": "Importa como búsquedas sueltas las que el otro ha subido a busquedas/. Nunca pisa tus colecciones. No duplica.",
     "ejecuta": "A mano: python tools/importar_busquedas.py (Claude lo ejecuta tras traer cambios de main)", "cuando": "Cada vez que traes cambios de main",
     "recursos": [["disco", "—"]], "notifica": [], "equipo": "Es la forma de ver lo que ha buscado el otro.", "datos": ["busquedas/", "data/app/searches/"], "ver": "#/recientes",
     "estado": {"adaptador": "sin_estado", "texto": "A mano; no deja estado."}, "lanzar": False},
    {"id": "sincronizar", "nombre": "Sincronizar con git", "grupo": "equipo", "icono": "⬆️", "modo": "manual",
     "que": "Guarda los cambios en tu rama, trae main y sube. La rama fernando/jesus se fusiona sola en main (GitHub Action).",
     "ejecuta": "A mano: tools/sincronizar.ps1", "cuando": "Cuando quieres subir lo tuyo",
     "recursos": [["red", "GitHub"]], "notifica": [], "equipo": "Es el camino del código entre los dos.", "datos": [".github/workflows/fusionar.yml"], "ver": "",
     "estado": {"adaptador": "sincronizar"}, "lanzar": False},

    # ------------------------------------------------------------------ INFRAESTRUCTURA
    {"id": "servidor", "nombre": "Servidor de PokéFinder", "grupo": "infra", "icono": "🖥", "modo": "infra",
     "que": "server.py: sirve la app y la API en el puerto 8800 y arranca los bucles de arriba. Solo librería estándar de Python.",
     "ejecuta": "Windows, al iniciar sesión (acceso directo «PokeFinder» en Inicio)", "cuando": "Siempre encendido",
     "recursos": [["disco", "—"]], "notifica": [["salud", "si no responde"]], "equipo": "Cada uno tiene el suyo en su ordenador.", "datos": ["server.py"], "ver": "",
     "estado": {"adaptador": "servidor"}, "lanzar": False},
    {"id": "acceso_remoto", "nombre": "Acceso desde el móvil", "grupo": "infra", "icono": "📱", "modo": "infra",
     "que": "Tailscale (red privada) para abrir la app desde el iPhone en http://IP:8800 y Remote Control para manejar la sesión de Claude. El puerto no se abre nunca en el router.",
     "ejecuta": "Tailscale y la app de Claude (a mano la primera vez)", "cuando": "Siempre",
     "recursos": [["red", "—"]], "notifica": [], "equipo": "Cada uno el suyo.", "datos": ["CASA.md"], "ver": "",
     "estado": {"adaptador": "tailscale"}, "lanzar": False},
    {"id": "ntfy", "nombre": "Canales de ntfy", "grupo": "infra", "icono": "🔔", "modo": "infra",
     "que": "Tres temas secretos: el tuyo, el de salud y el compartido con tu compañero (firmado con tu nombre). Los programas publican en ellos con tools/avisar.py.",
     "ejecuta": "tools/avisar.py (lo llaman los demás procesos)", "cuando": "Cuando un proceso tiene algo que decir",
     "recursos": [["red", "ntfy.sh, gratis"]], "notifica": [["tema", ""], ["salud", ""], ["equipo", ""]], "equipo": "El tema de equipo es el mismo para los dos.", "datos": [".secrets/ntfy.json"], "ver": "",
     "estado": {"adaptador": "ntfy"}, "lanzar": False},
]
