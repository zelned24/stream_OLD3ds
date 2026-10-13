"""Local browser -> Old 3DS. Python 3.10+, Playwright, Pillow."""
import argparse
import base64
import asyncio
import io
import socket
import struct
import time
import threading
from pathlib import Path
from PIL import Image, ImageOps
from playwright.async_api import async_playwright

INPUT = struct.Struct('!4sIH')
FRAME = struct.Struct('!4sIHHI')
CHUNK = 1200
STATS = struct.Struct('!4sIIII')
CONFIG = struct.Struct('!4sIBBBB7B')
PING = struct.Struct('!4sI')
CAPTURE = Path(__file__).with_name('capture.js').read_text(encoding='utf-8')
PUSH = Path(__file__).with_name('capture_push.js').read_text(encoding='utf-8')
KEY_TABLE = ['', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
             'z', 'x', 'Enter', 'Escape', 'c', 'v', 'q', 'e', 'Space', 'Shift']
DEFAULT_MAPPING = (5, 6, 9, 10, 11, 12, 7)  # A B X Y L R Start
BUTTON_BITS = (4, 5, 7, 8, 9, 10, 6)

def keys_for_mask(mask, mapping):
    keys = {KEY_TABLE[i+1] for i in range(4) if mask & (1 << i)}
    keys.update(KEY_TABLE[key] for bit, key in zip(BUTTON_BITS, mapping)
                if key and mask & (1 << bit))
    return keys

def encode(png):
    im = ImageOps.contain(Image.open(io.BytesIO(png)).convert('RGB'), (400, 240))
    canvas = Image.new('RGB', (400, 240))
    canvas.paste(im, ((400-im.width)//2, (240-im.height)//2))
    rgb = canvas.tobytes()
    return bytes((rgb[i] & 224) | ((rgb[i+1] & 224) >> 3) | (rgb[i+2] >> 6)
                 for i in range(0, len(rgb), 3))

class Inputs(asyncio.DatagramProtocol):
    def __init__(self, fps=30, half=False):
        self.peer = None
        self.seq = None
        self.mask = 0
        self.seen = 0
        self.log_mask = None
        self.stats = None
        self.fps = fps
        self.half = int(half)
        self.effective_fps = min(fps, 20) if half != 1 else fps
        self.adapt_previous = None
        self.good_reports = 0
        self.paused = False
        self.mapping = DEFAULT_MAPPING
        self.config_seq = None
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def capture_settings(self):
        return dict(fps=self.effective_fps, half=self.half,
                    active=bool(self.peer and time.monotonic()-self.seen < .5 and not self.paused))

    def datagram_received(self, data, addr):
        if addr == self.peer and self.transport:
            if len(data) == PING.size and data[:4] == b'PRP1':
                self.transport.sendto(data, addr)
                return
            if len(data) == CONFIG.size and data[:4] == b'PRC2':
                _, seq, fps, half, paused, reserved, *mapping = CONFIG.unpack(data)
                if fps not in (10, 15, 20, 30, 45, 60) or half > 2 or paused > 1 or reserved or any(k>=len(KEY_TABLE) for k in mapping):
                    return
                if self.config_seq is None or 0 < ((seq-self.config_seq)&0xffffffff) < 0x80000000:
                    if self.config_seq is None and seq == 1:
                        fps, half = int(self.fps), int(self.half)
                    self.config_seq, self.fps, self.half, self.paused = seq, fps, int(half), bool(paused)
                    self.mapping = tuple(mapping)
                    self.effective_fps = min(fps, 20) if half != 1 else fps
                    self.adapt_previous = None
                    print(f'Ajustes: fps={fps}, resolucion={(400,200,320)[half]}, pausa={paused}, mapa={mapping}', flush=True)
                if seq == self.config_seq:
                    self.transport.sendto(CONFIG.pack(b'PRA2',seq,int(self.fps),int(self.half),int(self.paused),0,*self.mapping), addr)
                return
        if len(data) == STATS.size and data[:4] == b'PRS1' and addr == self.peer:
            _, frame, completed, dropped, packets = STATS.unpack(data)
            self.stats = (time.monotonic(), frame, completed, dropped, packets)
            previous = self.adapt_previous
            if previous and completed >= previous[2] and dropped >= previous[3]:
                dt = self.stats[0]-previous[0]
                if dt >= .5:
                    rx = (completed-previous[2])/dt
                    lost = dropped-previous[3]
                    if not self.paused and (lost > 1 or (lost > 0 and rx < self.effective_fps*.85) or rx < self.effective_fps*.70):
                        step = 2 if lost >= 3 else 1
                        self.effective_fps = max(5, self.effective_fps - step)
                        self.good_reports = 0
                    else:
                        self.good_reports += 1
                        if self.good_reports >= 2:
                            self.effective_fps = min(self.fps, self.effective_fps + 1)
                            self.good_reports = 0
            self.adapt_previous = self.stats
            return
        if len(data) != INPUT.size:
            return
        magic, seq, mask = INPUT.unpack(data)
        now = time.monotonic()
        if magic != b'PRI1' or mask & ~2047:
            return
        if self.peer and addr != self.peer and now-self.seen < 2:
            return
        if now-self.seen > 2:
            self.seq = None
            self.config_seq = None
        if self.seq is not None and not 0 < ((seq-self.seq) & 0xffffffff) < 0x80000000:
            return
        self.peer, self.seq, self.mask, self.seen = addr, seq, mask, now
        if mask != self.log_mask:
            print(f'Entrada: cliente={addr}, botones={mask}', flush=True)
            self.log_mask = mask

async def main(args):
    loop = asyncio.get_running_loop()
    state = Inputs(args.fps, 1 if args.half else args.mode)
    transport, _ = await loop.create_datagram_endpoint(lambda: state, local_addr=(args.bind, args.port))
    # Duplicate the endpoint: same local port, no asyncio video send queue.
    video = transport.get_extra_info('socket').dup()
    video.setblocking(False)
    async with async_playwright() as p:
        options = dict(headless=not args.visible, viewport={'width': 800, 'height': 480})
        if args.audio:
            options['ignore_default_args'] = ['--mute-audio']
        options['args'] = ['--disable-background-timer-throttling',
                           '--disable-renderer-backgrounding',
                           '--disable-backgrounding-occluded-windows']
        if args.channel:
            options['channel'] = args.channel
        context = await p.chromium.launch_persistent_context(args.profile, **options)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(args.url)
        canvas = page.locator(args.canvas).first
        await canvas.wait_for(state='visible')
        await canvas.click()
        print(f'Juego listo: {args.url}; UDP {args.bind}:{args.port}', flush=True)

        async def keyboard():
            held = set()
            try:
                while True:
                    mask = state.mask if time.monotonic()-state.seen < .5 and not state.paused else 0
                    target = keys_for_mask(mask, state.mapping)
                    for key in held-target:
                        await page.keyboard.up(key)
                    for key in target-held:
                        await page.keyboard.down(key)
                    held = target
                    await asyncio.sleep(.004)
            finally:
                for key in held:
                    await page.keyboard.up(key)

        task = asyncio.create_task(keyboard())
        audio_stop = threading.Event()
        audio_task = None
        if args.audio:
            from audio_stream import stream_audio
            audio_task = asyncio.create_task(stream_audio(video,state,audio_stop))
        mailbox = asyncio.Queue(maxsize=1)
        async def receive_frame(encoded, half, duration):
            if encoded and state.capture_settings()['active']:
                frame = base64.b64decode(encoded)
                if (half == 1 and len(frame) == 24000) or (half in (0,2) and 4 <= len(frame) <= 96000 and frame[:2] == b"\xff\xd8"):
                    if mailbox.full():
                        mailbox.get_nowait()
                    mailbox.put_nowait((frame, duration, half))
            return state.capture_settings()
        if args.capture == 'canvas':
            await page.expose_function('__rogueFrame', receive_frame)
            await page.evaluate('() => { window.__rogueCapture = ('+CAPTURE+'); }')
            await page.evaluate(PUSH, dict(selector=args.canvas, initial=state.capture_settings()))
        seq = 0
        report = loop.time()
        report_frames = 0
        capture_ms = 0
        previous_stats = None
        try:
            while not (args.stop_file and Path(args.stop_file).exists()):
                start = loop.time()
                if state.capture_settings()['active']:
                    capture_start = loop.time()
                    if args.capture == 'canvas':
                        try:
                            frame, duration, mode = await asyncio.wait_for(mailbox.get(), 1)
                        except asyncio.TimeoutError:
                            continue
                    else:
                        png = await canvas.screenshot(type='png', timeout=5000)
                        mode = state.half
                        if mode == 1:
                            raw = await asyncio.to_thread(encode, png)
                            frame = bytes(raw[y*400+x] for y in range(0,240,2) for x in range(0,400,2))
                        else:
                            def jpeg():
                                size = (320,192) if mode == 2 else (400,240)
                                im = ImageOps.pad(Image.open(io.BytesIO(png)).convert('RGB'), size)
                                output = io.BytesIO()
                                im.save(output,format='JPEG',quality=50,progressive=False)
                                return output.getvalue()
                            frame = await asyncio.to_thread(jpeg)
                        duration = (loop.time()-capture_start)*1000
                    if len(frame) > 96000:
                        continue
                    capture_ms += duration
                    report_frames += 1
                    seq = (seq+1) & 0xffffffff
                    count = (len(frame)+CHUNK-1)//CHUNK
                    peer = state.peer
                    for index in range(count):
                        packet = FRAME.pack(b'PRF2' if mode == 1 else b'PRJ1', seq, index, count, len(frame)) + frame[index*CHUNK:(index+1)*CHUNK]
                        try:
                            video.sendto(packet, peer)
                        except (BlockingIOError, OSError):
                            break  # Never queue stale frames.
                        # Batch pacing avoids 80 tiny Windows timer sleeps.
                        if (index+1) % 8 == 0:
                            if peer[0].startswith('127.'):
                                await asyncio.sleep(0)
                            else:
                                deadline = start + (index+1)/(state.effective_fps*count)
                                await asyncio.sleep(max(0, deadline-loop.time()))
                    if loop.time()-report > 5:
                        elapsed = loop.time()-report
                        detail = 'RX pendiente'
                        if state.stats and previous_stats and state.stats[0]>previous_stats[0] and state.stats[2]>=previous_stats[2]:
                            dt = state.stats[0]-previous_stats[0]
                            detail = (f'RX={(state.stats[2]-previous_stats[2])/dt:.1f} FPS, '
                                      f'descartados={state.stats[3]-previous_stats[3]}, '
                                      f'paquetes/s={(state.stats[4]-previous_stats[4])/dt:.0f}')
                        print(f'Video: TX={report_frames/elapsed:.1f} FPS, captura={capture_ms/report_frames:.1f}ms, {detail}', flush=True)
                        previous_stats = state.stats
                        report_frames = 0
                        capture_ms = 0
                        report = loop.time()
                if args.capture != 'canvas' or not state.capture_settings()['active']:
                    await asyncio.sleep(max(.005, 1/state.effective_fps-(loop.time()-start)))
        finally:
            audio_stop.set()
            if audio_task:
                audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            transport.close()
            video.close()
            await context.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://pokerogue.net')
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--fps', type=int, choices=[10,15,20,30,45,60], default=20)
    parser.add_argument('--canvas', default='canvas')
    parser.add_argument('--visible', action='store_true')
    parser.add_argument('--channel', choices=['chrome', 'msedge'], default='msedge')
    parser.add_argument('--profile', default='.browser-profile')
    parser.add_argument('--capture', choices=['canvas', 'screenshot'], default='canvas')
    parser.add_argument('--half', action='store_true')
    parser.add_argument('--mode', type=int, choices=[0,1,2], default=0)
    parser.add_argument('--audio', action='store_true')
    parser.add_argument('--stop-file')
    args = parser.parse_args()
    if not 1 <= args.fps <= 60:
        parser.error('--fps debe estar entre 1 y 60')
    asyncio.run(main(args))
