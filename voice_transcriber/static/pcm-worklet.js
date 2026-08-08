class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.buf = [];
    this.pos = 0;
  }

  process(inputs) {
    const input = inputs[0][0];
    if (!input) return true;

    for (let i = 0; i < input.length; i++) this.buf.push(input[i]);

    const out = [];
    while (this.pos < this.buf.length) {
      const idx = Math.floor(this.pos);
      let s = this.buf[idx];
      if (s === undefined) break;
      s = Math.max(-1, Math.min(1, s));
      out.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      this.pos += this.ratio;
    }

    const consumed = Math.floor(this.pos);
    this.buf = this.buf.slice(consumed);
    this.pos -= consumed;

    if (out.length) {
      this.port.postMessage(new Int16Array(out).buffer);
    }
    return true;
  }
}

registerProcessor('pcm-worklet', PCMWorklet);