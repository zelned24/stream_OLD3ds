"""Physical 3DS streaming probe controller. No emulator or PC performance benchmark.

python diagnostics.py --gui
python diagnostics.py --seconds 6 --repeats 2 --audio
"""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import queue
import select
import socket
import struct
import threading
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
CONTROL = struct.Struct('!4sII')
CONFIG = struct.Struct('!4sIIIII')
FRAME = struct.Struct('!4sIIHHI')
VERSION = 1
MODES = {'network': 0, 'decode': 1, 'stream': 2, 'render': 3}


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered)-1)*quantile)]


def test_image(path=None):
    if path:
        with Image.open(path) as source:
            return ImageOps.pad(source.convert('RGB'), (400, 240), method=Image.Resampling.NEAREST)
    image = Image.new('RGB', (400, 240), '#202535')
    draw = ImageDraw.Draw(image)
    for y in range(240):
        draw.line((0, y, 399, y), fill=(20+y//4, 25+y//5, 40+y//3))
    for x in range(0, 400, 4):
        draw.line((x, 8, x, 38), fill='white' if x % 8 else 'red')
    for i, color in enumerate(('red', 'lime', 'blue', 'white', 'yellow', 'cyan')):
        draw.rectangle((10+i*64, 48, 60+i*64, 78), fill=color)
    draw.text((12, 92), 'Rogue Probe: 400x240 / texto ABC 0123456789', fill='white')
    draw.text((12, 108), 'Color, bordes, gradiente y detalle fino', fill='yellow')
    for y in range(135, 230):
        for x in range(12, 388):
            value = ((x*37) ^ (y*71)) & 255
            draw.point((x, y), fill=(value, (value*3) & 255, (value*7) & 255))
    return image


def jpeg_payload(image, size, quality, subsampling):
    output = io.BytesIO()
    image.resize(size, Image.Resampling.NEAREST).save(
        output, format='JPEG', quality=quality, subsampling=subsampling,
        progressive=False, optimize=False)
    data = output.getvalue()
    if len(data) > 96000:
        raise ValueError('JPEG de prueba supera 96000 bytes: usa otra imagen o menor calidad.')
    return data


def fragments(stage, sequence, payload):
    count = (len(payload)+1199)//1200
    for index in range(count):
        yield FRAME.pack(b'RBD1', stage, sequence, index, count, len(payload)) + payload[index*1200:(index+1)*1200]


def tone_packets():
    # Match the client's G.711 decoder, using a quiet 440 Hz tone. No microphone.
    def decode(value):
        value = (~value) & 255
        sample = (((value & 15) << 3)+132) << ((value >> 4) & 7)
        return 132-sample if value & 128 else sample-132
    levels = [decode(i) for i in range(256)]
    cycle = [min(range(256), key=lambda k: abs(levels[k]-int(1000*math.sin(2*math.pi*440*i/16000))))
             for i in range(400)]
    return [bytes(cycle[(j*320+i) % 400] for i in range(320)) for j in range(5)]


class Cancelled(Exception):
    pass


class Probe:
    def __init__(self, bind, port, stop, log):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        self.sock.bind((bind, port))
        self.sock.setblocking(False)
        self.stop, self.log = stop, log
        self.peer = None
        self.model = None
        self.session = None
        self.stage = 0
        self.acks, self.reports = set(), {}
        self.pings, self.rtt, self.input_times = {}, [], []
        self.input_last = 0
        self.input_missing = 0
        self.ping_seq = 0
        self.next_ping = 0
        self.live = None

    def send(self, data):
        try:
            return self.sock.sendto(data, self.peer) == len(data)
        except OSError:
            return False

    def control(self, magic, value=0):
        return self.send(CONTROL.pack(magic, self.stage, value))

    def poll(self, seconds=0):
        if self.stop.is_set():
            raise Cancelled('Cancelado en PC')
        if select.select([self.sock], [], [], max(0, seconds))[0]:
            for _ in range(256):
                try:
                    packet, addr = self.sock.recvfrom(2048)
                except BlockingIOError:
                    break
                if len(packet) == 12 and packet[:4] == b'RBH1':
                    _, session, model = CONTROL.unpack(packet)
                    if self.peer is None:
                        self.peer, self.session, self.model = addr, session, model
                        self.log(f'Consola conectada: {addr[0]} ({"New" if model == 2 else "Old"} 3DS/2DS)')
                    elif addr == self.peer and session != self.session:
                        raise Cancelled('El cliente se reinicio; inicia una sesion nueva.')
                    continue
                if addr != self.peer or len(packet) < 8:
                    continue
                stage = struct.unpack_from('!I', packet, 4)[0]
                if stage != self.stage:
                    continue
                if packet[:4] == b'RBL1' and len(packet)==24:
                    _, _, ms, received, complete, shown = struct.unpack('!4sIIIII',packet)
                    self.live = (time.perf_counter(),ms,received,complete,shown)
                elif packet[:4] == b'RBR1':
                    try:
                        value = json.loads(packet[8:])
                        if not isinstance(value, dict) or not isinstance(value.get('ms'), (float, int)):
                            continue
                        self.reports[stage] = value
                        self.control(b'RBA1', 3)
                    except (ValueError, UnicodeError):
                        continue
                elif len(packet) == 12:
                    _, _, value = CONTROL.unpack(packet)
                    if packet[:4] == b'RBA1':
                        self.acks.add((stage, value))
                    elif packet[:4] == b'RBP1':
                        sent = self.pings.pop(value, None)
                        if sent is not None:
                            self.rtt.append((time.perf_counter()-sent)*1000)
                    elif packet[:4] == b'RBU1' and value > self.input_last:
                        self.input_missing += max(0, value-self.input_last-1)
                        self.input_last = value
                        self.input_times.append(time.perf_counter())
                    elif packet[:4] == b'RBQ1':
                        raise Cancelled('Cancelado desde la consola')

    def retry(self, packet, ack, timeout=8):
        end = time.perf_counter()+timeout
        while (self.stage, ack) not in self.acks:
            if time.perf_counter() > end:
                raise TimeoutError(f'La consola no confirma la etapa {self.stage} (ACK {ack}).')
            self.send(packet)
            until = time.perf_counter()+.2
            while time.perf_counter() < until and (self.stage, ack) not in self.acks:
                self.poll(.02)

    def run_stage(self, config, payload=None):
        self.stage += 1
        stage = self.stage
        self.rtt, self.pings, self.input_times = [], {}, []
        self.input_last = self.input_missing = 0
        self.live = None
        self.retry(CONFIG.pack(b'RBG1', stage, MODES[config['kind']],
                               int(config['seconds']*1000), int(config.get('audio', False)), VERSION), 0)
        if config['kind'] == 'decode':
            deadline = time.perf_counter()+10
            while (stage, 2) not in self.acks:
                if time.perf_counter() > deadline:
                    raise TimeoutError('No se pudo cargar el JPEG de prueba en la consola.')
                for packet in fragments(stage, 1, payload):
                    self.send(packet)
                    self.poll(.002)
                self.poll(.1)
        tones = tone_packets() if config.get('audio') else []
        self.retry(CONTROL.pack(b'RBS1', stage, 0), 1)
        start = time.perf_counter()
        end = start+config['seconds']
        next_data = next_frame = next_audio = start
        sequence = sent = sent_bytes = frame_count = send_errors = late = 0
        pending = []
        packet_spacing = 0
        audio_sequence = audio_sent = 0
        self.next_ping = start
        next_status = start+1
        while time.perf_counter() < end:
            now = time.perf_counter()
            if now >= self.next_ping:
                self.ping_seq += 1
                self.pings[self.ping_seq] = now
                self.control(b'RBP1', self.ping_seq)
                self.next_ping = now+.1
            if tones and now >= next_audio:
                audio_sequence += 1
                audio_sent += self.send(CONTROL.pack(b'RBO1', stage, audio_sequence)+tones[(audio_sequence-1) % 5])
                next_audio = max(next_audio+.02, now)
            if config['kind'] == 'network':
                interval = config['datagram_bytes']/config['target_bytes_s']
                for _ in range(8):
                    if now < next_data:
                        break
                    data = CONTROL.pack(b'RBN1', stage, sequence)+bytes(config['datagram_bytes']-12)
                    if self.send(data):
                        sequence += 1
                        sent += 1
                        sent_bytes += len(data)
                    else:
                        send_errors += 1
                    next_data += interval
                if now-next_data > .05:
                    late += 1
                    next_data = now
            elif config['kind'] == 'stream':
                if not pending and now >= next_frame:
                    frame_count += 1
                    pending = list(fragments(stage, frame_count, payload))
                    packet_spacing = .7/config['fps']/len(pending)
                    next_data = now
                    if now-next_frame > 1/config['fps']:
                        late += 1
                    next_frame = now+1/config['fps']
                for _ in range(8):
                    if not pending or now < next_data:
                        break
                    data = pending.pop(0)
                    if self.send(data):
                        sent += 1
                        sent_bytes += len(data)
                    else:
                        send_errors += 1
                    next_data += packet_spacing
            self.poll(.001)
            if now>=next_status:
                elapsed=now-start
                if self.live and now-self.live[0]<2:
                    _,ms,received,complete,shown=self.live
                    detail=f'3DS: RX {received}, frames {complete}, presentados {shown}'
                else:
                    detail='Sin telemetria reciente de 3DS (comprueba version v1.2)'
                self.log(f'En curso {elapsed:.0f}/{config["seconds"]} s | TX {sent} paquetes | {detail}')
                next_status=now+1
        actual_seconds = time.perf_counter()-start
        # Drain in-flight packets before finalising; no backlog/retransmission of video.
        drain_end = time.perf_counter()+.2
        while time.perf_counter() < drain_end:
            self.poll(.005)
        deadline = time.perf_counter()+8
        while stage not in self.reports:
            if time.perf_counter() > deadline:
                raise TimeoutError('Falta el informe de la consola; resultados previos guardados.')
            self.control(b'RBE1')
            self.poll(.1)
        client = self.reports.pop(stage)
        result = dict(stage=stage, config=config, client=client,
                      tx=dict(seconds=actual_seconds, datagrams=sent, bytes=sent_bytes,
                              bytes_s=sent_bytes/actual_seconds, frames=frame_count,
                              frames_s=frame_count/actual_seconds, errors=send_errors,
                              pacing_late=late, audio_packets=audio_sent, unsent_tail_fragments=len(pending)),
                      rtt_ms=dict(count=len(self.rtt), p50=percentile(self.rtt,.5),
                                  p95=percentile(self.rtt,.95), maximum=max(self.rtt,default=None)),
                      control=dict(received=len(self.input_times), missing=self.input_missing,
                                   interval_p95_ms=percentile([(b-a)*1000 for a,b in zip(self.input_times,self.input_times[1:])],.95)))
        if config['kind'] == 'network':
            result['loss_fraction'] = max(0, 1-client['unique']/sent) if sent else None
        result['presented_fps'] = client['shown']/(client['ms']/1000) if client['ms'] else 0
        return result


def recommendation(results):
    network = [r for r in results if r['config']['kind'] == 'network' and not r['client']['aborted']
               and r['loss_fraction'] is not None and r['loss_fraction'] <= .01
               and r['tx']['bytes_s'] >= .9*r['config']['target_bytes_s']
               and r['rtt_ms']['count'] >= 5 and r['rtt_ms']['p95'] <= 100]
    groups = {}
    for r in network:
        key = (r['config']['datagram_bytes'], r['config']['target_bytes_s'])
        groups.setdefault(key, []).append(r)
    eligible = []
    for key, group in groups.items():
        all_group = [r for r in results if r['config']['kind']=='network' and
                     (r['config']['datagram_bytes'],r['config']['target_bytes_s']) == key]
        if len(group) == len(all_group):
            eligible.append((min(r['tx']['bytes_s'] for r in group), key, len(group)))
    best = max(eligible, default=None)
    # Heuristic headroom, not a guaranteed hardware limit. Reserve room for audio/control.
    budget = int(best[0]*.7) if best else None
    profiles = {}
    for r in results:
        c, client = r['config'], r['client']
        if c['kind'] != 'stream':
            continue
        key = (tuple(c['size']), c['quality'], c['subsampling'], c['fps'], c.get('audio',False))
        frames = r['tx']['frames']
        # One deliberately cut final frame is excluded from the loss check.
        expected = max(0, frames-bool(r['tx'].get('unsent_tail_fragments')))
        passed = (not client['aborted'] and not client['decode_errors'] and not r['tx']['errors']
                  and expected > 0 and client['complete'] >= expected*.99
                  and r['tx']['frames_s'] >= .9*c['fps']
                  and r['presented_fps'] >= .9*c['fps']
                  and r['rtt_ms']['count'] >= 5 and r['rtt_ms']['p95'] <= 100
                  and (not c.get('audio') or (client['dsp'] and not client['underruns']
                       and r['tx']['audio_packets'] >= .9*c['seconds']*50
                       and client['audio_packets'] >= r['tx']['audio_packets']*.99)))
        profiles.setdefault(key, []).append((passed, r))
    candidates = []
    for key, attempts in profiles.items():
        if all(passed for passed, _ in attempts):
            c = attempts[0][1]['config']
            candidates.append({k:c[k] for k in ('size','quality','subsampling','fps','audio','jpeg_bytes')})
    candidates.sort(key=lambda c:(c['size'][0],-c['subsampling'],c['fps'],c['quality']),reverse=True)
    return {'safe_total_bytes_s': budget, 'datagram_bytes': best[1][0] if best else None,
            'passing_stream_profiles': candidates,
            'passing_repeats': best[2] if best else 0,
            'basis': 'Todos los intentos de ese punto: perdida <=1%, envio >=90% objetivo, RTT p95 <=100ms; margen 30%.',
            'scope': 'Presupuesto de datagramas de aplicacion, incluido video/audio/control; no incluye cabeceras UDP/IP/Wi-Fi.',
            'warning': 'Heuristica de esta sesion e imagen. No es el maximo del hardware ni garantiza FPS o calidad visual.'}


def save_report(folder, document):
    folder.mkdir(parents=True, exist_ok=True)
    document['recommendation'] = recommendation(document['results'])
    temporary = folder/'report.tmp'
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(folder/'report.json')
    with (folder/'results.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['stage','kind','label','tx_KiB_s','loss_percent','presented_fps','rtt_p95_ms','decode_p95_us','loop_p95_us','audio_underruns'])
        for r in document['results']:
            writer.writerow([r['stage'],r['config']['kind'],r['config']['label'],round(r['tx']['bytes_s']/1024,2),
                             None if r.get('loss_fraction') is None else round(r['loss_fraction']*100,2),
                             round(r['presented_fps'],2),r['rtt_ms']['p95'],r['client']['decode_us'][3],
                             r['client']['loop_us'][3],r['client']['underruns']])
    rec = document['recommendation']
    lines = ['# Diagnostico Rogue Probe', '', f"Estado: {document['status']}", '',
             f"Consola: {document.get('model','pendiente')}; IP: {document.get('peer','pendiente')}", '',
             f"Presupuesto orientativo: {rec['safe_total_bytes_s']} bytes/s; datagrama: {rec['datagram_bytes']} bytes.",
             rec['basis'], rec['warning'], '',
             '| Prueba | TX KiB/s | Perdida % | FPS presentados | RTT p95 ms | JPEG p95 ms |',
             '|---|---:|---:|---:|---:|---:|']
    for r in document['results']:
        loss = '-' if r.get('loss_fraction') is None else f"{100*r['loss_fraction']:.2f}"
        rtt = '-' if r['rtt_ms']['p95'] is None else f"{r['rtt_ms']['p95']:.1f}"
        lines.append(f"| {r['config']['label']} | {r['tx']['bytes_s']/1024:.1f} | {loss} | {r['presented_fps']:.1f} | {rtt} | {r['client']['decode_us'][3]/1000:.2f} |")
    lines += ['', 'Los tiempos de copia/flush miden llamadas CPU, no el instante visible del LCD.',
              'RTT no es latencia input-a-foton. Los percentiles del cliente usan las ultimas 2048 muestras.',
              'FPS de streaming incluyen 200 ms de drenaje y handshake; son conservadores.',
              'Una prueba local JPEG no incluye captura, red ni presentacion.',
              'Sin pruebas de cambios entre imagenes, estos datos no determinan el ahorro de un protocolo por mosaicos.']
    lines += ['', '## Perfiles de streaming que pasaron todas sus repeticiones', '',
              'Criterios: envio/presentacion >=90% del objetivo, frames completos >=99%, RTT p95 <=100ms y sin errores de decodificacion. Con audio: DSP disponible, sin underruns detectados y recepcion >=99%.']
    if not rec['passing_stream_profiles']:
        lines.append('Ninguno confirmado. Revisar caudal realmente enviado, JPEG p95, perdidas y limite de presentacion antes de aumentar calidad.')
    for profile in rec['passing_stream_profiles']:
        lines.append(f"- {profile['size'][0]}x{profile['size'][1]}, Q{profile['quality']}, subsampling={profile['subsampling']}, {profile['fps']} FPS, audio={profile['audio']}, {profile['jpeg_bytes']} bytes/JPEG.")
    (folder/'summary.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def run(args, stop, log):
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder = Path(args.output)/stamp
    document = {'version': VERSION, 'created_local': stamp, 'status': 'waiting', 'results': [],
                'test_seconds': args.seconds, 'repeats': args.repeats,
                'audio_requested': args.audio, 'image_source': str(args.image) if args.image else 'synthetic-v1'}
    probe = None
    try:
        image = test_image(args.image)
        document['image_sha256'] = hashlib.sha256(image.tobytes()).hexdigest()
        folder.mkdir(parents=True)
        image.save(folder/'reference.png')
        save_report(folder, document)
        probe = Probe(args.bind, args.port, stop, log)
        log(f'Esperando 3DS en UDP {args.port}. Abre rogue_probe.3dsx y pulsa A.\nInformes: {folder}')
        while probe.peer is None:
            probe.poll(.1)
        document.update(peer=probe.peer[0], model='New3DS/2DS' if probe.model==2 else 'Old3DS/2DS', status='running')
        tests = []
        for repeat in range(args.repeats):
            tests.append((dict(kind='render',label=f'Copia/presentacion #{repeat+1}',seconds=args.seconds),None))
            for packet_size in (600, 1200):
                for rate in (128, 256, 512, 768, 1024):
                    tests.append((dict(kind='network',label=f'UDP {packet_size}B {rate}KiB/s #{repeat+1}',
                                       seconds=args.seconds,datagram_bytes=packet_size,target_bytes_s=rate*1024),None))
            for size in ((320,192),(400,240)):
                for quality in (70,85):
                    for subsampling in (2,0):
                        payload = jpeg_payload(image,size,quality,subsampling)
                        description = f'{size[0]}x{size[1]} Q{quality} {"420" if subsampling else "444"}'
                        base = dict(seconds=args.seconds,size=size,quality=quality,subsampling=subsampling,
                                    jpeg_bytes=len(payload),repeat=repeat+1)
                        tests.append((dict(base,kind='decode',label=f'JPEG local {description} #{repeat+1}'),payload))
                        for fps in (15,30):
                            tests.append((dict(base,kind='stream',label=f'Stream {description} {fps}FPS #{repeat+1}',
                                               fps=fps,audio=args.audio),payload))
        for index, (config, payload) in enumerate(tests):
            log(f'[{index+1}/{len(tests)}] {config["label"]}')
            result = probe.run_stage(config, payload)
            document['results'].append(result)
            save_report(folder, document)
            log(f'  Presentados {result["presented_fps"]:.1f} FPS; TX {result["tx"]["bytes_s"]/1024:.1f} KiB/s; RTT p95 {result["rtt_ms"]["p95"]}')
            if result['client']['aborted']:
                raise Cancelled('La consola cancelo o agoto el tiempo de la etapa.')
        document['status'] = 'complete'
        probe.control(b'RBF1')
        log('Bateria terminada. Abre summary.md y report.json para revisar los resultados.')
    except (Cancelled, KeyboardInterrupt) as error:
        document['status'] = 'cancelled'
        document['error'] = str(error)
        log(f'Cancelado. Se conservan las etapas completas: {folder}')
    except Exception as error:
        document['status'] = 'error'
        document['error'] = str(error)
        log(f'Error: {error}\nResultados parciales: {folder}')
    finally:
        if probe:
            if probe.peer:
                probe.control(b'RBE1')
                probe.control(b'RBF1')
            probe.sock.close()
        save_report(folder, document)
    return folder


def gui(args):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title('Rogue Probe — diagnóstico en 3DS física')
    root.geometry('880x600')
    pane = ttk.Frame(root,padding=20); pane.pack(fill='both',expand=True)
    ttk.Label(pane,text='Mide la consola. Conserva resultados. Decide el protocolo.',font=('Segoe UI',15)).pack(anchor='w')
    ttk.Label(pane,text='Abre rogue_probe.3dsx en la 3DS y pulsa A. No necesitas abrir el juego.\nUna pasada tarda aproximadamente 5 minutos. B en consola cancela; START sale.').pack(anchor='w',pady=12)
    options = ttk.Frame(pane); options.pack(fill='x')
    repeats = tk.StringVar(value=str(args.repeats))
    ttk.Label(options,text='Pasadas:').pack(side='left')
    repeat_box=ttk.Combobox(options,textvariable=repeats,values=['1','2','3'],width=5,state='readonly')
    repeat_box.pack(side='left',padx=8)
    audio = tk.BooleanVar(value=args.audio)
    audio_box=ttk.Checkbutton(options,text='Añadir tono de audio a las pruebas de streaming',variable=audio)
    audio_box.pack(side='left')
    controls=ttk.Frame(pane); controls.pack(fill='x',pady=12)
    status=tk.StringVar(value='Detenido')
    ttk.Label(pane,textvariable=status,wraplength=800).pack(anchor='w')
    activity=tk.StringVar(value='Pulsa Iniciar diagnóstico; después A en la consola.')
    ttk.Label(pane,textvariable=activity,wraplength=800).pack(anchor='w',pady=5)
    progress=ttk.Progressbar(pane,mode='determinate',maximum=35*args.repeats)
    progress.pack(fill='x',pady=5)
    output=tk.Text(pane,height=18,wrap='word',state='disabled')
    output.pack(fill='both',expand=True,pady=10)
    events=queue.Queue(); stop=threading.Event(); worker=None
    def start():
        nonlocal worker
        if worker and worker.is_alive(): return
        stop.clear(); args.repeats=int(repeats.get()); args.audio=audio.get()
        begin.configure(state='disabled'); repeat_box.configure(state='disabled'); audio_box.configure(state='disabled')
        status.set('Esperando consola / pruebas en curso')
        progress.configure(maximum=35*args.repeats,value=0)
        def work():
            try: events.put(('done',str(run(args,stop,lambda text:events.put(('log',text))))))
            except Exception as error: events.put(('done',f'Error al guardar: {error}'))
        worker=threading.Thread(target=work,daemon=True); worker.start()
    begin=ttk.Button(controls,text='Iniciar diagnóstico',command=start); begin.pack(side='left')
    ttk.Button(controls,text='Detener y guardar',command=stop.set).pack(side='left',padx=10)
    closing=False
    def close():
        nonlocal closing
        closing=True; stop.set()
    def poll():
        while not events.empty():
            kind,text=events.get_nowait()
            if kind=='done':
                activity.set(f'Informe: {text}'); begin.configure(state='normal')
                repeat_box.configure(state='readonly'); audio_box.configure(state='normal')
            else:
                if text.startswith('['):
                    current,total=text.split(']',1)[0][1:].split('/')
                    progress.configure(maximum=int(total),value=int(current)-1)
                    status.set(text)
                elif text.startswith(('Esperando','Consola conectada','Error:','Cancelado.','Bateria terminada')):
                    status.set(text)
                    if text.startswith('Bateria terminada'): progress.configure(value=35*args.repeats)
                elif text.startswith('En curso'):
                    activity.set(text)
                output.configure(state='normal'); output.insert('end',text+'\n'); output.see('end'); output.configure(state='disabled')
        if closing and (not worker or not worker.is_alive()): root.destroy(); return
        root.after(100,poll)
    root.protocol('WM_DELETE_WINDOW',close); root.after(100,poll); root.mainloop()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    interface=parser.add_mutually_exclusive_group()
    interface.add_argument('--gui',action='store_true',help='Abrir interfaz (predeterminada)')
    interface.add_argument('--cli',action='store_true',help='Usar solo terminal')
    parser.add_argument('--bind',default='0.0.0.0')
    parser.add_argument('--port',type=int,default=5001,choices=[5001])
    parser.add_argument('--seconds',type=int,default=6,choices=range(2,16))
    parser.add_argument('--repeats',type=int,default=1,choices=[1,2,3])
    parser.add_argument('--audio',action='store_true')
    parser.add_argument('--image',type=Path,help='Imagen de juego propia para una segunda bateria representativa')
    parser.add_argument('--output',type=Path,default=ROOT/'diagnostics-results')
    options=parser.parse_args()
    if options.cli: run(options,threading.Event(),lambda text:print(text,flush=True))
    else: gui(options)
