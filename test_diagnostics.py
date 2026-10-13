"""Offline correctness checks only: no sockets, timing measurements or emulation."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image, JpegImagePlugin
from diagnostics import CONFIG, FRAME, fragments, jpeg_payload, recommendation, save_report, percentile


def network_result(rate=256*1024, achieved=None, loss=0, repeat=1):
    return dict(stage=repeat,config=dict(kind='network',label='fixture',datagram_bytes=1200,
                target_bytes_s=rate,seconds=6),client=dict(aborted=False,decode_us=[0]*5,
                loop_us=[0]*5,underruns=0),tx=dict(bytes_s=rate if achieved is None else achieved),
                rtt_ms=dict(count=20,p95=30),loss_fraction=loss,presented_fps=0)


class DiagnosticsTests(unittest.TestCase):
    def test_wire_header_sizes_and_short_fragment(self):
        self.assertEqual(CONFIG.size,24)
        self.assertEqual(FRAME.size,20)
        original=bytes(range(256))*10
        packets=list(fragments(7,19,original))
        self.assertEqual([len(p) for p in packets],[1220,1220,180])
        self.assertEqual(FRAME.unpack(packets[-1][:20]),(b'RBD1',7,19,2,3,2560))
        self.assertEqual(b''.join(p[20:] for p in packets),original)

    def test_jpeg_subsampling_and_dimensions(self):
        source=Image.new('RGB',(400,240),'red')
        for size in [(400,240),(320,192)]:
            for sub in [0,2]:
                data=jpeg_payload(source,size,85,sub)
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.size,size)
                    self.assertEqual(JpegImagePlugin.get_sampling(image),sub)
                    self.assertNotIn('progressive',image.info)

    def test_do_not_claim_capacity_when_pc_did_not_send_target(self):
        result=network_result(rate=1024*1024,achieved=100*1024)
        self.assertIsNone(recommendation([result])['safe_total_bytes_s'])

    def test_one_failed_repeat_rejects_rate(self):
        good=network_result()
        failed=network_result(loss=.08,repeat=2)
        self.assertIsNone(recommendation([good,failed])['safe_total_bytes_s'])
        self.assertEqual(recommendation([good])['safe_total_bytes_s'],int(256*1024*.7))

    def test_aborted_and_missing_rtt_reject_capacity(self):
        result=network_result()
        result['client']['aborted']=True
        self.assertIsNone(recommendation([result])['safe_total_bytes_s'])
        result['client']['aborted']=False
        result['rtt_ms']['count']=0
        self.assertIsNone(recommendation([result])['safe_total_bytes_s'])

    def test_stream_candidate_requires_presentation_and_audio(self):
        r=network_result()
        r['config']=dict(kind='stream',label='fixture',size=[400,240],quality=85,subsampling=0,
                         fps=15,audio=True,jpeg_bytes=12000,seconds=6)
        r['tx'].update(frames=90,frames_s=15,errors=0,audio_packets=300,unsent_tail_fragments=0)
        r['client'].update(decode_errors=0,complete=90,dsp=True,audio_packets=300)
        r['presented_fps']=14.5
        self.assertEqual(len(recommendation([r])['passing_stream_profiles']),1)
        for key,value in [('underruns',1),('dsp',False),('complete',40),('audio_packets',0)]:
            failed=copy.deepcopy(r); failed['client'][key]=value
            self.assertEqual(recommendation([failed])['passing_stream_profiles'],[])
        r['presented_fps']=8
        self.assertEqual(recommendation([r])['passing_stream_profiles'],[])

    def test_partial_report_serialization(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            save_report(folder,dict(status='cancelled',results=[network_result()]))
            data=json.loads((folder/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'cancelled')
            self.assertTrue((folder/'results.csv').exists())
            self.assertIn('cancelled',(folder/'summary.md').read_text(encoding='utf-8'))
            self.assertFalse((folder/'report.tmp').exists())

    def test_percentile_empty_and_order(self):
        self.assertIsNone(percentile([],.95))
        self.assertEqual(percentile([3,1,2],.5),2)


if __name__=='__main__': unittest.main()
