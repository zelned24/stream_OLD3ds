# Transmisión para Old 3DS: evaluación y revisión implementada

Revisión: 2026-10-13. Investigación documental y de código; no se ha medido rendimiento en PC, Azahar ni consola durante esta revisión. Las prioridades y expectativas siguientes son decisiones de ingeniería, no resultados de benchmarks. Se comparan las familias relevantes, no todos los protocolos existentes.

## Diagnóstico de nitidez

El cliente recibe 400×240 en Detalle; 320×192 y 200×120 se amplían. La captura anterior aplica suavizado y unsharp mask antes de JPEG calidad 75. Ese enfoque puede producir halos y no recupera información perdida al reducir la imagen. El navegador no ofrece una opción de submuestreo de color en `toDataURL`; no se ha determinado el submuestreo real de la captura del usuario. Es una causa posible de bordes coloreados borrosos, no un diagnóstico confirmado en hardware.

La pérdida de UDP descarta imágenes incompletas en este programa: explica saltos/congelaciones, pero no la borrosidad de una imagen recibida correctamente. Ni RTP ni TCP hacen más nítido el contenido JPEG. Tampoco puede reconstruirse detalle de texto menor que un píxel físico. El tamaño interno del canvas, su relación de aspecto y el escalado previo del juego siguen importando. Una reducción no entera con vecino más próximo puede conservar bordes duros pero producir aliasing; debe compararse en consola.

## Transporte

| Alternativa | Qué aporta | Decisión para este proyecto |
|---|---|---|
| UDP propio, datagramas pequeños | Sin esperar retransmisión; control de colas y caducidad | Mantener como base existente; necesita control de ritmo y recuperación explícitos |
| UDP + FEC XOR | Recupera una pérdida con redundancia; sin viaje de ida y vuelta | Implementado opcionalmente; una paridad por JPEG |
| FEC Reed–Solomon por grupos | Puede recuperar varias pérdidas según redundancia | Candidato si se observan pérdidas múltiples; más CPU, tráfico y código |
| RTP/RTCP + JPEG | Secuencias, timestamps, fragmentación y feedback estandarizados | Útil para interoperabilidad, no mejora visual automática; RFC 2435 no es un contenedor arbitrario para nuestros JPEG 4:4:4 |
| TCP / WebSocket | Entrega fiable y ordenada | Una pérdida retrasa bytes posteriores; inadecuado como cambio automático para video fresco. WebSocket añade framing sobre TCP |
| ENet / KCP | Infraestructura de UDP fiable; KCP usa ARQ | Útiles para mensajes que deben llegar; retransmitir frames vencidos no ayuda a este flujo |
| SRT | Transporte de video con recuperación y búfer de latencia | Interesante en enlaces adversos; añadirlo a Old 3DS requiere portado y presupuestar recuperación |
| QUIC DATAGRAM | Datagramas no fiables dentro de QUIC | Posible diseño moderno, pero exige integrar QUIC y su seguridad; sin ventaja demostrada en esta LAN |
| WebRTC | Conjunto de transportes y seguridad para tiempo real | Muy útil en navegador a navegador; cliente 3DS nativo exige una integración considerable y sigue necesitando decodificar el video |

Fuentes primarias: [RTP/JPEG RFC 2435](https://www.rfc-editor.org/rfc/rfc2435), [FEC RFC 5109](https://www.rfc-editor.org/rfc/rfc5109), [TCP RFC 9293](https://www.rfc-editor.org/rfc/rfc9293), [WebSocket RFC 6455](https://www.rfc-editor.org/rfc/rfc6455), [QUIC DATAGRAM RFC 9221](https://www.rfc-editor.org/rfc/rfc9221), [WebRTC RFC 8835](https://www.rfc-editor.org/rfc/rfc8835), [ENet](https://github.com/lsalzman/enet), [KCP](https://github.com/skywind3000/kcp), [SRT](https://github.com/Haivision/srt).

## Compresión y coste del cliente

| Formato | Nitidez y coste | Decisión |
|---|---|---|
| JPEG convencional | Fotogramas independientes, compresión con pérdida; puede reducir resolución de color | Conservar para comparar con el modo que ya funciona |
| JPEG 4:4:4 | Mantiene resolución del color; aún tiene cuantización con pérdida | Implementado opcionalmente con calidad configurable; puede aumentar bytes y coste de decodificación |
| RGB565 sin comprimir | 192000 bytes/frame; 3.84 MB/s a 20 FPS, antes de cabeceras/audio | Menos trabajo de decodificación, pero demasiado tráfico para adoptarlo sin datos de la consola; cuantiza colores |
| RGB888 / RGBA | 288000 / 384000 bytes/frame a 400×240 | Solo RGBA dentro de la PC en el modo nuevo; nunca se transmite crudo por Wi-Fi |
| PNG / QOI / RGB + LZ4 | Compresión sin pérdida de sus píxeles de entrada | Buenos candidatos para texto y sprites; tamaño variable y nuevos decodificadores, no garantía de mejores FPS |
| Mosaicos independientes + regiones modificadas | Puede enviar solo cambios y conservar texto sin pérdida | Siguiente candidato si 4:4:4 sigue insuficiente; necesita versiones por mosaico, caducidad, actualización periódica y recuperación de desincronización |
| JPEG con restart markers / decodificación parcial | Puede limitar propagación de daños con empaquetado y decodificador adecuados | No equivale a permitir JPEG truncado arbitrario. No implementado; preferible reconstruir exactamente el fragmento faltante |
| H.264, H.265, VP8/VP9, AV1 | Compresión temporal; referencias entre frames y recuperación más compleja | No hay rendimiento acreditado aquí en Old 3DS. MVD de libctru es exclusivo de New 3DS; no adoptar un códec más complejo solo por ahorrar ancho de banda |

[Pillow documenta calidad y submuestreo JPEG](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#jpeg). [libjpeg-turbo explica el compromiso calidad/tamaño](https://libjpeg-turbo.org/About/SmartScale-Lossy). [MVD en libctru](https://github.com/devkitPro/libctru/blob/master/libctru/include/3ds/services/mvd.h) declara New3DS-only. [QOI](https://qoiformat.org/) y [LZ4](https://github.com/lz4/lz4) son alternativas sin pérdida; sus cifras publicadas en otras máquinas no se extrapolan a ARM11.

## Cambios implementados

- `--sharp`: captura por vecino más próximo, sin unsharp mask; RGBA viaja solo navegador → Python. Pillow convierte a JPEG baseline 4:4:4 en un worker. `--jpeg-quality 80` es el valor inicial, rango 30–95; solo se aplica con `--sharp`. El JPEG resultante sigue usando PRJ1, compatible con el cliente JPEG anterior.
- `--fec`: después de todos los fragmentos PRJ1, envía PRX1 con el mismo encabezado de 16 bytes: secuencia, índice 0, número de fragmentos de datos y tamaño JPEG. Payload: XOR de cada bloque de 1200 bytes, con el último rellenado con ceros. Cuesta un datagrama de 1216 bytes por JPEG, más cabeceras UDP/IP. Por ejemplo, para 16 fragmentos añade aproximadamente un 6.25% de datagramas.
- El cliente PRX1 nuevo recupera exactamente un fragmento faltante si recibe paridad y todos los demás antes de abandonar la secuencia. Acepta paridad antes o después de los datos y descarta duplicados. Si faltan dos fragmentos, no recupera. Si pierde solo paridad, los datos completos se presentan normalmente. No tolera corrupción arbitraria ni cruza imágenes. No es una implementación RTP/FEC RFC 5109.
- Se conserva un único ensamblado: la primera secuencia posterior abandona la incompleta, incluso si luego llega paridad antigua. Límite temporal de ensamblado: 300 ms, límite de JPEG: 96000 bytes. El contador FEC en Red cuenta reconstrucciones, no garantiza que el JPEG reconstruido se haya presentado.
- Rotación y escalado JPEG pasan al worker. Tablas de coordenadas eliminan divisiones por píxel. El hilo de entrada presenta con `memcpy` de 288000 bytes. Usa un buffer adicional de 288000 bytes. Se mantiene IDCT preciso; no se han cambiado audio ni su buffering.
- Las opciones nuevas están desactivadas por defecto y disponibles en la GUI. El cliente nuevo sigue aceptando PRJ1/PRF2 sin FEC. Un cliente anterior ignora PRX1; no obtiene recuperación.

## Qué falta demostrar y cómo comparar

1. Mantener escena, resolución, FPS objetivo y audio iguales en todas las pruebas físicas.
2. Probar cliente nuevo con servidor sin opciones nuevas: referencia de FPS, RTT, KB/s y descartes.
3. Activar solo `--sharp`: comparar letras, bordes coloreados y sprites. Si pierde fluidez, bajar `--jpeg-quality` a 70 manteniendo 4:4:4; no bajar resolución en la primera comparación.
4. Activar después `--fec`: comprobar contador FEC, descartes, fluidez y audio. Si no hay pérdidas, FEC solo añade tráfico y se puede desactivar.
5. Si con calidad 90 sigue borroso, investigar escalado/imagen de origen antes de otro transporte. Si 4:4:4 es nítido pero lento, distinguir tamaño de JPEG, tiempo de captura y coste de decodificación en la consola antes de implementar mosaicos sin pérdida.

El control de FPS y pacing existentes siguen siendo heurísticos; no prueban congestión real ni un óptimo. El RTT de control no es la latencia de imagen. Faltan métricas de duración de decodificación y edad de frame en hardware. No se prometen 30/60 FPS ni nitidez perfecta.
