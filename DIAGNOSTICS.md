# Rogue Probe: diagnóstico en la consola física

Herramienta independiente para decidir el siguiente protocolo a partir de medidas de la 3DS. No modifica ni reemplaza `rogue_stream.3dsx`. El controlador Python genera la carga; los tiempos de JPEG y presentación se miden en ARM11. No se ejecutan Azahar, Edge ni PokéRogue.

No mide «todo el hardware» ni garantiza encontrar un máximo absoluto: caracteriza red, decodificación JPEG, preparación/presentación y coexistencia con audio para este tipo de streaming. La batería inicial cubre hasta 1 MiB/s de datagramas de aplicación y hasta 30 FPS de streaming. Si todos los puntos pasan, el techo real queda sin determinar y se puede ampliar después.

## Instalación y uso

1. Copia `dist/3ds/rogue_probe/rogue_probe.3dsx` a `sd:/3ds/rogue_probe/rogue_probe.3dsx`.
2. Conserva `sd:/3ds/rogue_stream/server.txt` con la IPv4 LAN de la PC. Probe comparte ese archivo con el cliente habitual, aunque el binario esté en otra carpeta.
3. PC y consola deben estar en la misma LAN. Cierra el servidor de juego durante la prueba para evitar carga ajena. Usa las mismas condiciones de Wi-Fi con las que juegas.
4. Abre `start-diagnostics.ps1` o ejecuta:

   ```powershell
   python D:\Proyectos\rogue_lan\diagnostics.py --gui
   ```

5. Permite UDP entrante **5001** para Python en el firewall de Windows, solo en la red privada. No necesitas abrir puertos en el router. El juego sigue usando 5000.
6. Pulsa **Iniciar diagnóstico** en la PC. En Homebrew Launcher abre `rogue_probe.3dsx` y pulsa **A**. La consola muestra etapas y recepción; el controlador muestra progreso.
7. Deja terminar una pasada, aproximadamente 4–5 minutos con 6 segundos por etapa. Haz después dos o tres pasadas para comprobar estabilidad. En consola **B** cancela y **START** sale. En PC **Detener y guardar** conserva las etapas completas. Tras una cancelación, reinicia la batería en PC y pulsa A en consola.
8. Para probar coexistencia con audio, activa la casilla antes de iniciar. Emite un tono suave de 440 Hz durante las etapas de streaming. Usa el DSP firmware que ya funciona con el cliente de juego y un volumen cómodo. No captura micrófono ni salida Windows. Comprueba de oído cortes; los contadores no certifican el sonido de los altavoces.

Alternativa por terminal, dos pasadas y audio:

```powershell
python D:\Proyectos\rogue_lan\diagnostics.py --repeats 2 --seconds 6 --audio
```

Para una segunda batería más representativa, usa una captura tuya del juego; la imagen se guarda como referencia junto al informe:

```powershell
python D:\Proyectos\rogue_lan\diagnostics.py --gui --image "D:\capturas\combate.png"
```

Por defecto usa una lámina sintética con texto, bordes, gradientes y una región de mucho detalle. Conviene probar también una escena real de menú y otra de combate. El mismo JPEG se repite en cada etapa: esto mide transporte y decodificación, no ahorro por cambios de escena ni captura del navegador.

## Qué mide

| Etapa | Trabajo | Datos relevantes |
|---|---|---|
| Presentación local | Copia de BGR8 ya preparado, flush y swap a VBlank | FPS, duración CPU de copia/flush, intervalos entre presentaciones |
| UDP | 600 y 1200 bytes por datagrama; 128, 256, 512, 768 y 1024 KiB/s | Envío real, bytes/paquetes únicos recibidos, pérdida, duplicados, reordenación, mayor hueco antes del último paquete recibido |
| JPEG local | Imagen precargada; descompresión repetida sin red de video ni dibujo | Tiempo medio/p50/p95/máximo de header + descompresión |
| Streaming | JPEG fragmentado, worker, escala/rotación, copia y presentación | Frames completos, presentados, incompletos, sustituidos, errores, tiempos de cada fase |
| Audio opcional | Paquetes G.711 de 20 ms concurrentes con streaming | Paquetes enviados/recibidos, disponibilidad DSP y vaciados de cola detectados al recibir audio |
| Control durante etapas | Ping a 10 Hz y mensajes de consola aproximadamente a 20 Hz | RTT, cadencia observada en PC, huecos de secuencia |

JPEG compara 320×192 y 400×240, calidad 70/85, submuestreo 4:2:0/4:4:4. Cada combinación se decodifica localmente y se transmite a 15 y 30 FPS. Total: 35 etapas por pasada. El streaming usa un worker con el mismo esquema de IDCT preciso y rotación que el cliente actual, pero es un receptor de diagnóstico independiente.

**Unidades:** tiempos de consola en microsegundos; RTT en milisegundos; caudales en bytes/s o KiB/s (1024 bytes). Los datagramas incluyen las cabeceras del protocolo de prueba, no UDP/IP ni Wi-Fi. Cada campo `*_us` es `[cantidad, media, p50, p95, maximo]`. Media/máximo/cantidad abarcan la etapa; percentiles usan las últimas 2048 muestras. Un contador cero significa que esa fase no se ejercitó, no que su coste sea cero.

`max_gap` cuenta huecos consecutivos de secuencia hasta `highest` en la etapa UDP; no incluye pérdidas al final. La pérdida total sí compara paquetes únicos recibidos con envíos correctos registrados por el servidor. No se interpreta duplicación como recepción adicional.

`replaced` cuenta JPEG pendientes sustituidos antes de decodificar; `skipped` cuenta resultados decodificados sustituidos antes de copiar a pantalla. `shown` cuenta swaps solicitados y está limitado por VBlank, no mide fotones del LCD. La duración incluye control inicial y 200 ms de drenaje, por lo que los FPS reportados son conservadores. El vaciado de audio puede pasar inadvertido en intervalos sin paquetes; escuchar sigue siendo parte de la prueba.

## Resultados y siguiente protocolo

Se guardan después de cada etapa en `diagnostics-results/FECHA-HORA/`:

- `report.json`: parámetros, imagen identificada por SHA-256, modelo Old/New, métricas y recomendaciones.
- `results.csv`: tabla para comparar pasadas y escenas.
- `summary.md`: resumen legible y perfiles que superaron los criterios.
- `reference.png`: imagen usada para comprobar nitidez visual.

Puedes compartir `report.json` y `summary.md`. Una sesión cancelada o con error conserva las etapas ya terminadas; la etapa interrumpida puede no tener informe. No reutilices resultados de una sesión parcialmente completada como una certificación completa.

El presupuesto orientativo toma un punto donde **todas las repeticiones realizadas** tengan pérdida <=1%, envío real >=90% del objetivo y RTT p95 <=100 ms. Usa el 70% del caudal observado para reservar margen. No se atribuye a la 3DS una limitación si el servidor no logró enviar la carga. Una única pasada solo ofrece evidencia preliminar.

Un perfil JPEG se propone solo si todas sus repeticiones realizadas alcanzan envío y presentación >=90% del objetivo, recepción completa >=99%, RTT p95 <=100 ms y cero errores de decodificación/envío. Con audio exige DSP disponible, recepción >=99%, suficiente envío de audio y cero vaciados detectados. Son criterios explícitos de selección, no garantías universales. Todavía debes valorar nitidez con la imagen visible.

Estos resultados permiten decidir:

- Red holgada y JPEG lento: priorizar un decodificador más sencillo, paletas/RLE o compresión de bloques; comprobar el candidato en hardware.
- Red limitada y JPEG rápido: reducir bytes y enviar solo regiones modificadas.
- Pérdidas múltiples o reordenación: diseñar grupos FEC y una ventana de ensamblado pequeña con límite de edad.
- Presentación/copia costosas: ajustar formato y preparación de framebuffer antes de cambiar la red.
- RTT o cadencia empeoran bajo carga: reservar capacidad para audio/controles y corregir el ritmo de envío.

No se crea ni se aplica automáticamente un protocolo nuevo a partir de una sola batería. Faltan medidas de regiones cambiantes, codecs alternativos, captura real y latencia input-a-fotón; estas pruebas aportan una base para diseñar y validar la siguiente iteración.

## Compilar y verificar el programa

En MSYS2 de devkitPro, dentro de `client/`:

```sh
make -B probe
```

Produce `client/rogue_probe.3dsx`. La IP se lee exclusivamente del archivo SD compartido. No se cambia la compilación ni el binario del juego.

Comprobaciones internas, sin benchmarks, sockets ni emulación:

```powershell
python -m unittest test_diagnostics -v
```

Se verificaron esas comprobaciones y la compilación ARM. No se ejecutó esta batería en PC, Azahar o consola durante su creación: la ejecución física y la revisión visual quedan pendientes.
