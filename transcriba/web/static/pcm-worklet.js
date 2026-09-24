class PCM16Downsampler extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.target = (options.processorOptions && options.processorOptions.targetRate) || 16000;
    this.ratio = sampleRate / this.target;
    this.pos = 0;
    this.last = 0;
    this.frame = new Int16Array(this.target / 10);
    this.n = 0;
    this.blocks = 0;
    this.sumsq = 0;
    this.count = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const ch = input[0];
    const N = ch.length;
    for (let i = 0; i < N; i++) this.sumsq += ch[i] * ch[i];
    this.count += N;
    let p = this.pos;
    while (Math.floor(p) + 1 < N) {
      const i0 = Math.floor(p);
      const frac = p - i0;
      const s0 = i0 < 0 ? this.last : ch[i0];
      const s1 = ch[i0 + 1];
      let v = s0 + (s1 - s0) * frac;
      v = Math.max(-1, Math.min(1, v));
      this.frame[this.n++] = v < 0 ? v * 32768 : v * 32767;
      if (this.n >= this.frame.length) {
        this.port.postMessage({ type: "pcm", buffer: this.frame.buffer }, [this.frame.buffer]);
        this.frame = new Int16Array(this.target / 10);
        this.n = 0;
      }
      p += this.ratio;
    }
    this.pos = p - N;
    this.last = ch[N - 1];
    if (++this.blocks % 8 === 0) {
      const rms = Math.sqrt(this.sumsq / Math.max(1, this.count));
      this.port.postMessage({ type: "level", dbfs: rms > 1e-6 ? 20 * Math.log10(rms) : -100 });
      this.sumsq = 0; this.count = 0;
    }
    return true;
  }
}
registerProcessor("pcm16-downsampler", PCM16Downsampler);
