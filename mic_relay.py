"""Bounded, nonblocking microphone-to-call relay between independent audio devices."""
import queue

import numpy as np


class MicRelay:
    def __init__(self, input_rate, output_rate, max_blocks=6):
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.blocks = queue.Queue(maxsize=max_blocks)
        self.pending = np.zeros(0, dtype=np.float32)
        self.position = 0
        self.previous = None
        self.next_sample = 0.0
        self.input_frames = 0
        self.forwarded_frames = 0
        self.peak = 0.0
        self.dropped_blocks = 0
        self.input_statuses = 0
        self.output_statuses = 0

    def capture(self, data, frames, when, status):
        if status:
            self.input_statuses += 1
        # Capture all native mic channels, then mix to mono for the phone.
        mono = np.asarray(data, dtype=np.float32).mean(axis=1)
        self.input_frames += len(mono)
        if len(mono):
            self.peak = max(self.peak, float(np.max(np.abs(mono))))
        if self.input_rate != self.output_rate:
            samples = mono if self.previous is None else np.concatenate(([self.previous], mono))
            if not len(samples):
                return
            step = self.input_rate / self.output_rate
            positions = np.arange(self.next_sample, max(0, len(samples) - 1), step)
            mono = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)
            self.next_sample = (positions[-1] + step if len(positions) else self.next_sample) - (len(samples) - 1)
            self.previous = samples[-1]
        if not len(mono):
            return
        while True:
            try:
                self.blocks.put_nowait(mono)
                break
            except queue.Full:
                try:
                    self.blocks.get_nowait()
                    self.dropped_blocks += 1
                except queue.Empty:
                    pass

    def render(self, output, frames, when, status):
        if status:
            self.output_statuses += 1
        output.fill(0)
        written = 0
        while written < frames:
            if self.position >= len(self.pending):
                try:
                    self.pending = self.blocks.get_nowait()
                    self.position = 0
                except queue.Empty:
                    break
            count = min(frames - written, len(self.pending) - self.position)
            # Both cable channels carry the voice; no caller depends on a particular stereo channel.
            output[written:written + count, :] = self.pending[self.position:self.position + count, None]
            written += count
            self.position += count
        self.forwarded_frames += written

    def summary(self):
        return (f"mic input frames={self.input_frames}, peak={self.peak:.4f}; "
                f"cable voice frames={self.forwarded_frames}, dropped blocks={self.dropped_blocks}; "
                f"input status events={self.input_statuses}, output status events={self.output_statuses}")
