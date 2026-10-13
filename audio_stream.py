"""Windows output loopback -> 16 kHz mono G.711 mu-law, 20 ms packets."""
import asyncio
import struct
import threading

async def stream_audio(sock, state, stop):
    try:
        import audioop
        import numpy as np
        import pyaudiowpatch as pa
    except ImportError as error:
        print(f'Audio: instala requirements.txt ({error})',flush=True)
        return
    loop = asyncio.get_running_loop()
    frames = asyncio.Queue(maxsize=20)
    def deliver(data):
        if frames.full(): frames.get_nowait()
        frames.put_nowait(data)
    def record():
        try:
            with pa.PyAudio() as p:
                device = p.get_default_wasapi_loopback()
                channels = int(device['maxInputChannels'])
                rate = int(device['defaultSampleRate'])
                print(f'Audio: salida Windows {device["name"]}; mono 16000 Hz', flush=True)
                resampler = None
                pending = b''
                with p.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                            input_device_index=device['index'], frames_per_buffer=max(256,rate//50)) as source:
                    while not stop.is_set():
                        pcm = source.read(max(256,rate//50), exception_on_overflow=False)
                        samples = np.frombuffer(pcm,dtype='<i2').reshape(-1,channels)
                        mono = samples.mean(axis=1).astype('<i2').tobytes()
                        converted,resampler = audioop.ratecv(mono,2,1,rate,16000,resampler)
                        pending += converted
                        while len(pending)>=640:
                            block,pending = pending[:640],pending[640:]
                            loop.call_soon_threadsafe(deliver,audioop.lin2ulaw(block,2))
        except Exception as error:
            print(f'Audio no disponible: {error}', flush=True)
    worker = threading.Thread(target=record,daemon=True)
    worker.start()
    seq=0
    try:
        while not stop.is_set():
            try: block=await asyncio.wait_for(frames.get(),.25)
            except asyncio.TimeoutError: continue
            if state.capture_settings()['active']:
                seq=(seq+1)&0xffffffff
                try: sock.sendto(struct.pack('!4sI',b'PAU1',seq)+block,state.peer)
                except (BlockingIOError,OSError): pass
    finally:
        stop.set()
        await asyncio.to_thread(worker.join,1)
