import asyncio
import io
import unittest
from PIL import Image
from server import encode, INPUT, FRAME, CONFIG, PING, Inputs, keys_for_mask, DEFAULT_MAPPING

class ProtocolTests(unittest.TestCase):
    def test_settings_ack_validation_and_order(self):
        sent=[]
        class Transport:
            def sendto(self, data, peer): sent.append((data,peer))
        state=Inputs()
        state.connection_made(Transport())
        peer=('127.0.0.1',1111)
        state.datagram_received(INPUT.pack(b'PRI1',1,0),peer)
        config=CONFIG.pack(b'PRC2',2,60,1,0,0,*DEFAULT_MAPPING)
        state.datagram_received(config,('127.0.0.1',2222))
        self.assertEqual(state.fps,30)
        state.datagram_received(config,peer)
        self.assertEqual((state.fps,state.half),(60,True))
        self.assertEqual(sent[-1],(b'PRA2'+config[4:],peer))
        state.datagram_received(CONFIG.pack(b'PRC2',1,10,0,0,0,*DEFAULT_MAPPING),peer)
        state.datagram_received(CONFIG.pack(b'PRC2',3,30,0,0,0,255,6,9,10,11,12,7),peer)
        self.assertEqual((state.fps,state.half),(60,True))
        ping=PING.pack(b'PRP1',123)
        state.datagram_received(ping,peer)
        self.assertEqual(sent[-1],(ping,peer))

    def test_mapping_and_duplicate_keys(self):
        self.assertEqual(keys_for_mask((1<<4)|(1<<7),DEFAULT_MAPPING),{'z','c'})
        mapping=(5,5,0,10,11,12,7)
        self.assertEqual(keys_for_mask((1<<4)|(1<<5)|(1<<7),mapping),{'z'})
        self.assertEqual(keys_for_mask(1<<5,mapping),{'z'})
        self.assertEqual(keys_for_mask(0,mapping),set())

    def test_pixels_and_fragments(self):
        png = io.BytesIO()
        Image.new('RGB', (400,240), (255,0,0)).save(png, format='PNG')
        frame = encode(png.getvalue())
        self.assertEqual(frame, bytes([224])*96000)
        packets = [FRAME.pack(b'PRF1',1,i,80,len(frame))+frame[i*1200:(i+1)*1200] for i in range(80)]
        self.assertTrue(all(len(p)==1216 for p in packets))
        self.assertEqual(b''.join(p[16:] for p in packets),frame)

    def test_input_sequence(self):
        state=Inputs()
        peer=('127.0.0.1',1234)
        state.datagram_received(INPUT.pack(b'PRI1',0xffffffff,16),peer)
        state.datagram_received(INPUT.pack(b'PRI1',0,0),peer)
        state.datagram_received(INPUT.pack(b'PRI1',0xffffffff,16),peer)
        self.assertEqual(state.mask,0)
        self.assertEqual(state.seq,0)

    def test_udp_same_source_port(self):
        async def check():
            loop=asyncio.get_running_loop()
            transport,_=await loop.create_datagram_endpoint(Inputs,local_addr=('127.0.0.1',0))
            duplicate=transport.get_extra_info('socket').dup()
            try:
                self.assertEqual(duplicate.getsockname(),transport.get_extra_info('sockname'))
            finally:
                duplicate.close()
                transport.close()
        asyncio.run(check())

if __name__=='__main__':
    unittest.main()
