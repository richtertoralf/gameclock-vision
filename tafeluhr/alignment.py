"""Bounded digit translation from red lamp positions, without changing calibration."""
import cv2
import numpy as np


class DigitAlignment:
    def __init__(self, rects):
        self.base = list(rects)
        # Horizontal fields must not sample the neighbouring vertical lamps.
        # Otherwise a broad middle box turns a real 0 into an 8.
        for digit in range(4):
            start=digit*7
            boxes=self.base[start:start+7]
            left=max(boxes[4][2],boxes[5][2])+2
            right=min(boxes[1][0],boxes[2][0])-2
            if right-left>=4:
                for segment in (0,3,6):
                    a,b,c,d=boxes[segment]
                    if min(c,right)-max(a,left)>=4:
                        self.base[start+segment]=(max(a,left),b,min(c,right),d)
        self.offsets = [(0, 0)] * 4
        self.pending = [None] * 4
        self.counts = [0] * 4

    def update(self, score):
        h, w = score.shape
        for digit in range(4):
            boxes = self.base[digit * 7:digit * 7 + 7]
            x0 = min(r[0] for r in boxes)
            y0 = min(r[1] for r in boxes)
            x1 = max(r[2] for r in boxes)
            y1 = max(r[3] for r in boxes)
            # Do not search outside the image or follow a neighbouring digit.
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                continue
            left, right = min(24, x0), min(24, w - x1)
            top, bottom = min(16, y0), min(16, h - y1)
            mask = np.full((y1-y0, x1-x0), -0.25, np.float32)
            for a,b,c,d in boxes:
                rh,rw=d-b,c-a
                yy,xx=np.mgrid[:rh,:rw]
                # Prefer lamp centres over a mere intersection with a box edge.
                weight = np.minimum(np.minimum(xx+1,rw-xx)/max(rw/2,1),
                                    np.minimum(yy+1,rh-yy)/max(rh/2,1))
                mask[b-y0:d-y0,a-x0:c-x0] = np.maximum(
                    mask[b-y0:d-y0,a-x0:c-x0], weight)
            patch = score[y0-top:y1+bottom,x0-left:x1+right].astype(np.float32)
            response = cv2.matchTemplate(patch, mask, cv2.TM_CCORR) / max(float(np.maximum(mask,0).sum()),1)
            ys,xs=np.mgrid[-top:bottom+1,-left:right+1]
            # Prefer small shifts when evidence is nearly equal.
            ranked=response - .005*(xs*xs+ys*ys)
            iy,ix=np.unravel_index(np.argmax(ranked),ranked.shape)
            candidate=(int(ix-left),int(iy-top))
            current=self.offsets[digit]
            baseline=response[current[1]+top,current[0]+left]
            if response[iy,ix] < max(3.0, float(baseline)*1.15):
                self.counts[digit]=0
                continue
            # At least two separate lamp rows/segments must support movement.
            dx,dy=candidate
            supported=sum(np.count_nonzero(score[b+dy:d+dy,a+dx:c+dx]>20)>=3 for a,b,c,d in boxes)
            if supported < 2:
                self.counts[digit]=0
                continue
            previous=self.pending[digit]
            if previous is not None and max(abs(candidate[i]-previous[i]) for i in (0,1))<=2:
                self.counts[digit]+=1
            else:
                self.counts[digit]=1
            self.pending[digit]=candidate
            if self.counts[digit]>=3:
                self.offsets[digit]=candidate
                self.counts[digit]=0
        return [(a+self.offsets[i//7][0],b+self.offsets[i//7][1],
                 c+self.offsets[i//7][0],d+self.offsets[i//7][1])
                for i,(a,b,c,d) in enumerate(self.base)]
