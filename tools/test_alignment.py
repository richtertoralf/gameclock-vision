import unittest
import numpy as np
from tafeluhr.alignment import DigitAlignment
from tafeluhr.decoder import Config, segment_rects


class AlignmentTests(unittest.TestCase):
    def score(self, align, dx=0, dy=0):
        score=np.zeros((232,672),np.uint8)
        for a,b,c,d in align.base:
            score[b+dy:d+dy,a+dx:c+dx]=100
        return score

    def test_shift_needs_multiple_frames_and_is_bounded(self):
        cfg=Config(digit_w=.15,digit_x=[.05,.28,.55,.78],y_top=.1,y_bot=.85)
        original=segment_rects(cfg)
        align=DigitAlignment(original)
        score=self.score(align,10,5)
        align.update(score)
        self.assertEqual(align.offsets,[(0,0)]*4)
        for _ in range(4):align.update(score)
        for x,y in align.offsets:
            self.assertLessEqual(abs(x-10),2)
            self.assertLessEqual(abs(y-5),2)
        saved=list(align.offsets)
        for _ in range(20):align.update(score)
        self.assertEqual(align.offsets,saved)
        self.assertEqual(segment_rects(cfg),original)

    def test_occlusion_does_not_move_fields(self):
        align=DigitAlignment(segment_rects(Config()))
        for _ in range(10):align.update(np.zeros((232,672),np.uint8))
        self.assertEqual(align.offsets,[(0,0)]*4)

    def test_middle_field_cannot_overlap_right_lamps(self):
        rects=segment_rects(Config())
        a,b,c,d=rects[6]
        rects[6]=(a,b,rects[1][2],d)
        align=DigitAlignment(rects)
        self.assertLess(align.base[6][2],align.base[1][0])

if __name__=='__main__':unittest.main()
