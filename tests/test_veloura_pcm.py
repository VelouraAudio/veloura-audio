import struct
import unittest

from veloura.audio import pcm_add, pcm_mul, pcm_rms
import veloura.audio.pcm as pcm


def pack_samples(*samples: int) -> bytes:
    return struct.pack("<" + "h" * len(samples), *samples)


def unpack_samples(frame: bytes) -> tuple[int, ...]:
    return struct.unpack("<" + "h" * (len(frame) // 2), frame)


class PcmHelperTests(unittest.TestCase):
    def without_audioop(self, callback):
        original = pcm._audioop
        pcm._audioop = None
        try:
            return callback()
        finally:
            pcm._audioop = original

    def test_mul_scales_and_clips_with_fallback(self):
        def run():
            frame = pack_samples(1000, -1000, 24000, -24000)
            return unpack_samples(pcm_mul(frame, 2, 2.0))

        self.assertEqual(self.without_audioop(run), (2000, -2000, 32767, -32768))

    def test_add_clips_with_fallback(self):
        def run():
            left = pack_samples(20000, -20000, 1000)
            right = pack_samples(20000, -20000, -250)
            return unpack_samples(pcm_add(left, right, 2))

        self.assertEqual(self.without_audioop(run), (32767, -32768, 750))

    def test_rms_with_fallback(self):
        def run():
            return pcm_rms(pack_samples(3000, -3000, 3000, -3000), 2)

        self.assertEqual(self.without_audioop(run), 3000)


if __name__ == "__main__":
    unittest.main()
