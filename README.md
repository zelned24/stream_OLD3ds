# Rogue Stream — PC, Azahar y Old 3DS

La PC ejecuta PokéRogue en Edge; la consola recibe video RGB332 o JPEG y envía botones por UDP. Incluye audio opcional de la salida de Windows. La pantalla inferior tiene un panel gráfico con fondo oscuro, marcos rojos y selección visible.

## Medir la capacidad de tu consola

La herramienta independiente **Rogue Probe** mide UDP, JPEG, copia/presentación, controles y coexistencia con audio en la 3DS física. Copia `dist/3ds/rogue_probe/rogue_probe.3dsx` a la SD y conserva `sd:/3ds/rogue_stream/server.txt`. Abre `start-diagnostics.ps1`, pulsa **Iniciar diagnóstico** y abre Probe en la consola con **A**. Usa UDP 5001; permite ese puerto para Python en la red privada. Una pasada tarda aproximadamente 4–5 minutos. B cancela y START sale.

Los resultados se guardan por etapa en `diagnostics-results/` como JSON, CSV y resumen Markdown. No reemplaza el cliente del juego ni aplica automáticamente otro protocolo. Instalación, significado de las métricas, audio opcional y criterios de selección: [DIAGNOSTICS.md](DIAGNOSTICS.md).

## Actualización: JPEG, modo intermedio y audio

### Prueba de nitidez y recuperación (2026-10-13)

El audio ya funciona al iniciar con `--audio`. Esta revisión añade dos opciones independientes; están desactivadas por defecto para conservar la captura anterior:

- **Nitidez / `--sharp`:** JPEG 4:4:4, calidad 80, sin suavizado ni filtro de enfoque. Puede mejorar bordes de texto y color, pero aumentar tráfico y reducir FPS. `--jpeg-quality 70` permite bajar el peso manteniendo 4:4:4. No es compresión sin pérdida.
- **Recuperación / `--fec`:** un paquete extra permite reconstruir un fragmento perdido por JPEG. Requiere el `.3dsx` nuevo. En **Red**, `FEC` cuenta imágenes reconstruidas y `Drop` las incompletas descartadas. FEC no hace más nítida una imagen completa.

Copia `dist/3ds/rogue_stream/rogue_stream.3dsx` a `sd:/3ds/rogue_stream/rogue_stream.3dsx`, conservando `server.txt`. Reinicia el cliente y el servidor. En la GUI selecciona **400 × 240**, **15 FPS**, captura **Directa**, audio y la casilla **Nitidez**. Compara primero sin recuperación; después activa la casilla de recuperación si hay descartes.

Por terminal, primera prueba:

```powershell
python D:\Proyectos\rogue_lan\server.py --url https://pokerogue.net --channel msedge --visible --bind 0.0.0.0 --fps 15 --mode 0 --audio --sharp --jpeg-quality 80
```

Añade `--fec` para la segunda prueba. Mantén escena y FPS iguales y anota nitidez, FPS recibidos, KB/s, RTT, Drop, FEC y continuidad del sonido. Sin `--sharp` se conserva el filtro y JPEG del navegador anterior. La captura sin filtros no puede recuperar detalle ya perdido en el canvas de origen y puede mostrar aliasing si la reducción no es entera.

Se guardó el binario anterior en `backups/rogue_stream-before-sharp.3dsx`; para volver atrás cópialo a la SD renombrado a `rogue_stream.3dsx` y desactiva ambas opciones. No se modificó el audio ni su buffering.

Compilación ARM y sintaxis Python verificadas. **No se ejecutaron mediciones en PC ni Azahar; nitidez, FPS y recuperación por pérdida real quedan por validar en tu consola.** Comparación de transportes, códecs, fuentes y límites: [STREAMING_RESEARCH.md](STREAMING_RESEARCH.md).

**Actualiza servidor y .3dsx juntos:** esta versión usa ajustes PRC2/PRA2, incompatibles con el cliente anterior.

1. Detén el servidor y cierra su ventana. Ejecuta `python -m pip install -r requirements.txt` con el Python que abre la interfaz. Las dependencias nuevas ya están instaladas en el Python usado en esta PC.
2. Copia `dist/3ds/rogue_stream/rogue_stream.3dsx` a la SD. Conserva tu `server.txt` si ya tiene la IP correcta.
3. Reabre `start-server.ps1`. Selecciona red local, **320 × 192 · equilibrio JPEG**, **15 FPS** inicialmente.
4. Para sonido activa **Audio: transmitir salida Windows** antes de iniciar. Incluye otros sonidos de la PC, no solo PokéRogue. No captura el micrófono ni guarda grabaciones. El juego debe tener sonido activado y usar el dispositivo de salida predeterminado. Reinicia el servidor si cambias de dispositivo.
5. En la 3DS comprueba `sd:/3ds/dspfirm.cdc`. Si falta, usa Rosalina de Luma3DS: **Miscellaneous options... → Dump DSP firmware**, y reinicia el cliente. Usa el firmware extraído de tu consola. Sube su volumen físico. La pestaña Red indica si el DSP se inició; el video funciona aunque falle el audio.

| Modo | Imagen | Propósito |
|---|---|---|
| Fluidez | 200×120 RGB332, 24 KB/frame | Conserva el modo que ya funciona en tu consola |
| Equilibrio | 320×192 JPEG | Mayor definición con tráfico comprimido |
| Detalle | 400×240 JPEG | Resolución completa, con coste de descompresión |

Sin `--sharp`, la captura directa produce JPEG calidad 75 con suavizado y unsharp mask. Con `--sharp`, Pillow produce JPEG 4:4:4 con calidad configurable. El tamaño depende de la escena y el límite es 96000 bytes por JPEG; si lo supera en captura directa, el servidor avisa y descarta. El cliente usa IDCT preciso y prepara la imagen en un worker. Solo se mantiene un frame pendiente. Detalle se presenta 1:1; las otras resoluciones se amplían.

Los FPS seleccionados son el máximo. JPEG empieza hasta 20 FPS; el servidor reduce según descartes y FPS recibidos, y aumenta un FPS tras dos reportes considerados estables. Es una heurística: no demuestra congestión y puede reaccionar a una caída aislada. Cambiar el objetivo reinicia el ajuste. El contador de la consola incluye imágenes JPEG ya decodificadas y presentadas.

Audio: G.711 mu-law mono, 16 kHz, 320 muestras por paquete PAU1 (20 ms), 128 kbit/s de payload. La 3DS convierte a PCM16 y reproduce con NDSP. Precarga tres buffers (60 ms), mantiene hasta ocho (160 ms), descarta duplicados/paquetes antiguos y limpia tras 350 ms sin recepción. No retransmite audio perdido. No hay sincronización exacta entre audio y video; puede haber cortes o desfase. Pausar el stream detiene también el envío de sonido.

Para compilar, instala además `pacman -S 3ds-libjpeg-turbo` en MSYS2 de devkitPro. Las bibliotecas quedan enlazadas en el binario, no se copian a la SD.

Por petición del usuario, **esta revisión no se ha medido en PC ni probado en Azahar**. Se ha compilado y revisado la sintaxis. Las pruebas de rendimiento, sonido y estabilidad quedan para la Old 3DS física. Empieza con Fluidez y audio, después prueba Equilibrio y Detalle; indica FPS objetivo/recibidos y si el sonido se corta o se retrasa.

Requisito de firmware: [ejemplos oficiales de audio de devkitPro](https://github.com/devkitPro/3ds-examples/blob/master/audio/README.md).

## Prueba en la Old 3DS física

1. Copia el contenido de `dist/` a la raíz de la SD. Debe quedar:

   ```text
   sd:/3ds/rogue_stream/rogue_stream.3dsx
   sd:/3ds/rogue_stream/server.txt
   ```

2. Abre `server.txt` y comprueba que contiene solamente la IPv4 LAN de tu PC. El paquete está preparado con `192.168.18.156`, la IP Wi-Fi detectada al compilar. Confírmala con `ipconfig`; si cambia, edita este archivo y reinicia el cliente. Guarda como texto ASCII o UTF-8 sin BOM. No uses 127.0.0.1 en la consola física.
3. Conecta la 3DS y la PC a la misma red local. Configura previamente el Wi-Fi en los ajustes de la consola. Evita una red de invitados con aislamiento de dispositivos. Si puedes, conecta la PC por Ethernet.
4. En la PC abre `start-server.ps1` desde PowerShell, o ejecuta `pythonw server_gui.py`. En la ventana elige **Nintendo 3DS · red local**, **10 FPS**, **200 × 120 · fluidez** y captura **Directa**. Estos valores son un punto de partida para medir, no un rendimiento garantizado.
5. Pulsa **Iniciar servidor**. Inicia sesión manualmente en la ventana de Edge si el juego lo solicita. El perfil `.browser-profile` conserva la sesión y los datos del navegador.
6. Permite conexiones UDP entrantes al puerto **5000** para Python en el firewall de la PC, únicamente en la red privada. No es necesario abrir puertos en el router.
7. Abre Homebrew Launcher en la consola y ejecuta `rogue_stream.3dsx`. En **Red** verifica que figura la IP correcta y que el estado pasa a conectado.
8. Prueba primero botones y liberaciones. Después aumenta a 15 o 20 FPS desde **Video**. Prueba 400×240 solo si los FPS recibidos se mantienen y los descartes no crecen rápidamente.

El servidor admite un cliente activo. Cierra Azahar antes de probar la 3DS; sus heartbeats pueden mantener ocupada la sesión. Espera al menos dos segundos al cambiar de cliente.

## Panel inferior y controles

- **SELECT:** abre o cierra ajustes. No sale de la aplicación.
- **L/R dentro del panel:** cambia entre Video, Botones y Red.
- **Arriba/abajo:** elige una opción; **izquierda/derecha** cambia su valor; **A** avanza el valor o ejecuta la acción.
- **B:** vuelve al juego. Mientras el panel está activo, los botones se reservan para el panel.
- **Táctil:** toca una pestaña u opción para seleccionarla. Toca de nuevo la opción seleccionada o el botón **A: Cambiar** para modificarla. **B: Jugar** vuelve al juego.
- **Video:** FPS máximo, modos Detalle/Equilibrio/Fluidez y pausa. La pausa detiene video/audio y libera controles; no pausa necesariamente la simulación del juego en PC.
- **Botones:** dos páginas con A/B/X/Y y L/R/Start/Restaurar. Toca **Pagina** o avanza con arriba/abajo para cambiar de página.
- **Red:** IP de la PC, tráfico, descartes, reconexión y salida al Homebrew Launcher.

Mapeo inicial: cruceta → flechas; A → Z; B → X; X → C; Y → V; L → Q; R → E; Start → Enter. En Botones puedes asignar otras teclas de la lista. Los cambios se confirman con “Ajustes sincronizados”. El mapa del cliente se mantiene durante la ejecución; aún no se guarda en la SD.

## Instalar el servidor en otra PC

Requiere Python 3.10 o superior con Tkinter y Microsoft Edge instalado:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\pythonw server_gui.py
```

El lanzador `start-server.ps1` usa el Python disponible en PATH; si instalaste dependencias en `.venv`, usa el comando anterior. La interfaz permite iniciar/detener, elegir URL, destino, resolución, FPS y tipo de captura; muestra métricas y guarda preferencias en `server-settings.json`. Los ajustes iniciales se eligen antes de iniciar. Durante la conexión se modifican desde el panel de la consola.

Alternativa por terminal:

```powershell
python server.py --url https://pokerogue.net --channel msedge --visible --bind 0.0.0.0 --fps 15 --mode 0 --audio --sharp
```

También puedes usar la URL de un checkout local de PokéRogue ya levantado por separado. Este proyecto no incluye el juego. El modo `--capture screenshot` conserva una ruta PNG más lenta por compatibilidad. El servidor usa la LAN sin autenticación ni cifrado; no lo expongas a Internet.

## Azahar

Abre la interfaz Python, selecciona **Azahar · esta PC** y pulsa Iniciar. Después pulsa **Abrir Azahar**. El archivo `client/rogue_stream.3dsx` está compilado para 127.0.0.1. El archivo SD `server.txt`, si existe dentro de la SD virtual de Azahar, tiene prioridad sobre esa IP.

El paquete `dist/` es para la consola física y apunta a la IP LAN indicada arriba. No confundas ambos archivos al copiarlos. Las mediciones previas en Azahar llegaron aproximadamente a 29 FPS recibidos sin descartes; eso no demuestra el rendimiento en Old 3DS.

## Compilar

Instala devkitPro con devkitARM, libctru y herramientas 3DS. Desde la terminal MSYS2 de devkitPro:

```sh
cd /d/Proyectos/rogue_lan/client
make -B SERVER_IP=127.0.0.1
make -B SERVER_IP=192.168.18.156 TARGET=rogue_stream_3ds
```

Sustituye la segunda IP por la de tu PC. El segundo comando produce `rogue_stream_3ds.3dsx`; cópialo a la SD con el nombre `rogue_stream.3dsx`. El parámetro `-B` garantiza que el cambio de IP se recompila. En adelante puedes cambiar la IP mediante `server.txt`, sin compilar.

## Diagnóstico durante las pruebas

| Síntoma | Comprobación |
|---|---|
| Sin conexión | IP de server.txt, servidor en modo red local, firewall UDP 5000 y misma LAN |
| Conecta pero congela la imagen | Reducir FPS y usar 200×120; observar descartes y cercanía al router |
| Imagen negra con captura directa | Probar PNG compatible y revisar actividad del servidor |
| Botones no responden | Cerrar el panel con B/SELECT, reanudar video y revisar mapeo |
| Otro cliente no conecta | Cerrar el primer cliente y esperar dos segundos |
| Reinicio de servidor | Usar Reconectar en Red si no recupera la imagen; reiniciar cliente si persiste |

Prueba al menos: pulsar/soltar cada botón; abrir el panel con una tecla sostenida; cambiar resolución; pausar/reanudar; parar/reiniciar servidor; desconectar Wi-Fi; volver a conectar. Registra resolución, FPS objetivo y recibidos, descartes y RTT. El RTT es ida/vuelta de un paquete de control, no latencia input-a-fotón.

## Implementación y límites

La captura se genera en el navegador y se entrega a un buzón de un frame en Python. Fluidez cuesta 24 KB/frame; Equilibrio y Detalle usan JPEG de tamaño variable. El peso real depende de la imagen; no se asume una tasa fija.

UDP usa enteros big-endian y fragmentos de hasta 1200 bytes. PRF2 transporta RGB332; PRJ1 JPEG; PAU1 audio; PRI1 estado de 11 botones; PRC2/PRA2 ajustes y confirmación; PRS1 métricas; PRP1 ping. Fluidez tiene 20 fragmentos; JPEG tiene una cantidad variable y un último fragmento que puede ser menor. Se descartan parciales y secuencias antiguas. Los botones se envían al cambiar y cada 50 ms; el servidor libera teclas tras 500 ms sin entrada. Una pulsación breve puede perderse con UDP.

El cliente usa 1 MiB alineado para SOC, 192 KB para ensamblado e imagen y unos 1031 KiB adicionales para buffers JPEG, más memoria interna del decodificador y 64 KiB de pila. FEC añade 1200 bytes de paridad. La recepción no bloqueante tiene un presupuesto de 256 paquetes o 10 ms por vuelta. El panel se dibuja en RGB565 cuando cambia; el video usa BGR8. No requiere Citro2D ni RomFS.

## Verificación

- Compilación ARM de ambos binarios: correcta.
- Pruebas de protocolo y mapeo: `python -m unittest test_protocol -v`.
- Captura real en Edge, colores, resoluciones y cambios en vivo: `python test_capture.py`.
- La nueva interfaz gráfica requiere comprobación visual en Azahar y en la consola física; no se ha probado en hardware Old 3DS.

Referencias: [libctru SOC](https://github.com/devkitPro/libctru/blob/master/libctru/include/3ds/services/soc.h), [framebuffers](https://github.com/devkitPro/libctru/blob/master/libctru/source/gfx.c), [Playwright Keyboard](https://playwright.dev/python/docs/api/class-keyboard).
