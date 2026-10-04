"""Red LEDs only, occlusion and corrections of a running match clock."""
import unittest
import cv2
import numpy as np
from tafeluhr.decoder import Config, SegmentDecoder, color_score, DIGIT_PATTERNS, SEG_NAMES
from tafeluhr.tracker import ClockTracker, fmt


def frame(text, red=220):
    cfg = Config(quad=[[16,16],[656,16],[656,216],[16,216]])
    decoder = SegmentDecoder(cfg)
    img = np.full((232,672,3), 15, np.uint8)
    for i, (x0,y0,x1,y1) in enumerate(decoder.rects):
        active = SEG_NAMES[i%7] in DIGIT_PATTERNS[text[i//7]][0]
        img[y0:y1,x0:x1] = (20,20,red) if active else (240,240,240)
        # A bright green/white net covers part of each measurement region.
        img[(y0+y1)//2:(y0+y1)//2+2,x0:x1] = (210,255,225)
    return decoder, img


class RedDetectionTests(unittest.TestCase):
    def test_white_grey_green_and_warm_white_are_off(self):
        colors = np.array([[(255,255,255),(100,100,100),(160,230,180),
                            (225,235,255),(15,20,220)]],np.uint8)
        score = color_score(colors,'red')[0]
        self.assertEqual(score[:4].tolist(),[0,0,0,0])
        self.assertGreater(score[4],100)

    def test_all_digits_with_white_unlit_lamps_and_moving_net(self):
        for value in ('0000','1111','2222','3333','4444','5555','6606','7707','8808','9909','1455','1459'):
            for brightness in (90,160,240):
                decoder,img=frame(value,brightness)
                for offset in (30,60,90):
                    moving=img.copy(); moving[:,offset:offset+3]=(220,255,235)
                    with self.subTest(value=value,brightness=brightness,offset=offset):
                        self.assertEqual(decoder.decode(moving).text,value)

    def test_white_only_never_becomes_a_reading(self):
        decoder,img=frame('8888')
        img[:]=(255,255,255)
        self.assertIsNone(decoder.decode(img).text)


class RunningCorrectionsTests(unittest.TestCase):
    def feed(self,tr,start,end,values):
        states=[]
        for tick in range(start,end):
            t=tick/10
            value=values(t)
            states.append(tr.update(t,None if value is None else fmt(value).replace(':','')))
        return states

    def test_backward_correction_while_seconds_keep_advancing(self):
        tr=ClockTracker()
        self.feed(tr,0,30,lambda t:899)  # incorrect 14:59 instead of 14:55
        states=self.feed(tr,30,80,lambda t:895+int(t-3))
        self.assertTrue(states[15].running)
        self.assertEqual(states[15].seconds,896)
        self.assertEqual(states[-1].seconds,899)

    def test_reacquire_running_sequence_with_one_unreadable_second(self):
        tr=ClockTracker()
        self.feed(tr,0,30,lambda t:899)
        states=self.feed(tr,30,70,lambda t:None if 4<=t<5 else 895+int(t-3))
        self.assertTrue(states[25].running)
        self.assertEqual(states[25].seconds,897)

    def test_pause_and_resume(self):
        tr=ClockTracker()
        self.feed(tr,0,50,lambda t:660+int(t))
        states=self.feed(tr,50,90,lambda t:664)
        self.assertTrue(all(s.seconds==664 for s in states))
        self.assertFalse(states[-1].running)
        states=self.feed(tr,90,120,lambda t:665+int(t-9))
        self.assertTrue(states[-1].running)
        self.assertEqual(states[-1].seconds,667)

    def test_unconfirmed_errors_do_not_claim_fresh_board_data(self):
        tr=ClockTracker()
        self.feed(tr,0,30,lambda t:600)
        states=self.feed(tr,30,40,lambda t:1500+int(t*10)*7)
        self.assertTrue(all(s.source!='board' for s in states))
        self.assertEqual(states[-1].seconds,600)
        self.assertGreater(states[-1].last_board_age_ms,500)

if __name__=='__main__': unittest.main()
