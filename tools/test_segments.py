"""Run: .venv/bin/python -B -m unittest discover -s tools -p test_segments.py"""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from tafeluhr.app import Engine, create_app
from tafeluhr.decoder import Config, SegmentDecoder, segment_rects, FULL_W, FULL_H


class SegmentCalibrationTests(unittest.TestCase):
    def test_custom_field_changes_actual_measurement_only_there(self):
        cfg = Config()
        baseline = segment_rects(cfg)
        custom = [None] * 28
        custom[0] = [300, 100, 310, 110]
        cfg = Config.from_dict({"segment_overrides": custom})
        decoder = SegmentDecoder(cfg)
        score = np.zeros((FULL_H, FULL_W), np.uint8)
        score[100:110, 300:310] = 255
        self.assertEqual(SegmentDecoder(Config()).measure(score)[0], 0)
        self.assertEqual(decoder.measure(score)[0], 255)
        self.assertEqual(decoder.rects[1:], baseline[1:])

    def test_save_reload_reset_and_coarse_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'config.json')
            engine = Engine(path)
            custom = [None] * 28
            custom[4] = [20, 30, 25, 50]
            engine.update_config({'segment_overrides': custom})
            reloaded = Engine(path)
            self.assertEqual(reloaded.decoder.rects[4], (20, 30, 25, 50))
            reloaded.update_config({'min_contrast': 25})
            self.assertEqual(reloaded.cfg.segment_overrides, custom)
            reloaded.update_config({'digit_w': .18})
            self.assertIsNone(reloaded.cfg.segment_overrides)
            reloaded.update_config({'segment_overrides': custom})
            reloaded.update_config({'segment_overrides': None})
            self.assertEqual(reloaded.decoder.rects, segment_rects(Config(digit_w=.18)))

    def test_invalid_fields_rejected_without_changing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Engine(str(Path(tmp) / 'config.json'))
            before = engine.cfg.to_dict()
            for bad in ([], [None]*27, [[0,0,0,2]]+[None]*27,
                        [[-1,0,5,5]]+[None]*27, [[0,0,999,5]]+[None]*27,
                        [[0,0,5.5,5]]+[None]*27):
                with self.assertRaises(ValueError):
                    engine.update_config({'segment_overrides':bad})
                self.assertEqual(engine.cfg.to_dict(), before)

    def test_editing_background_has_no_baked_in_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Engine(str(Path(tmp) / 'config.json'))
            app = create_app(engine)
            debug = next(r.endpoint for r in app.routes if r.path == '/debug.jpg')
            plain = cv2.imdecode(np.frombuffer(debug(plain=True).body, np.uint8), 1)
            annotated = cv2.imdecode(np.frombuffer(debug().body, np.uint8), 1)
            self.assertEqual(plain.shape, (FULL_H * 2, FULL_W * 2, 3))
            self.assertEqual(plain.max(), 0)
            self.assertGreater(annotated.max(), 0)

    def test_api_exposes_effective_fields_and_rejects_invalid_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Engine(str(Path(tmp) / 'config.json'))
            app = create_app(engine)
            get = next(r.endpoint for r in app.routes if r.path == '/api/config' and 'GET' in r.methods)
            post = next(r.endpoint for r in app.routes if r.path == '/api/config' and 'POST' in r.methods)
            class Request:
                async def json(self):
                    return {'segment_overrides': []}
            response = asyncio.run(post(Request()))
            self.assertEqual(response.status_code, 400)
            self.assertFalse(json.loads(response.body)['ok'])
            self.assertEqual(get()['segment_rects'], engine.decoder.rects)
            self.assertEqual(get()['debug_size'], [FULL_W, FULL_H])

if __name__ == '__main__':
    unittest.main()
