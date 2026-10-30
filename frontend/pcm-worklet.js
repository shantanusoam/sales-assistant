/* AudioWorklet: resample browser mic to mono 16 kHz PCM16, emit ~100 ms frames.
 * We use a running box-filter average for downsampling; microphone sample rate is
 * commonly 44.1 or 48 kHz. No third-party dependency or media container.
 */
class Pcm16CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.outputRate = 16000;
    this.ratio = this.outputRate / sampleRate;
    this.phase = 0;
    this.sum = 0;
    this.samples = 0;
    this.block = new Int16Array(1600);
    this.index = 0;
    this.meterSum = 0;
    this.meterSamples = 0;
  }

  process(inputs, outputs) {
    const channels = inputs[0];
    // Keep the node alive without feeding microphone audio to the speakers.
    for (const output of (outputs[0] || [])) output.fill(0);
    if (!channels || !channels.length || !channels[0]) return true;

    const count = channels[0].length;
    for (let i = 0; i < count; i++) {
      let sample = 0;
      for (let ch = 0; ch < channels.length; ch++) sample += channels[ch][i];
      sample /= channels.length;
      this.sum += sample;
      this.samples++;
      this.phase += this.ratio;
      this.meterSum += sample * sample;
      this.meterSamples++;
      if (this.phase >= 1) {
        const averaged = this.sum / this.samples;
        const clamped = Math.max(-1, Math.min(1, averaged));
        this.block[this.index++] = clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);
        this.phase -= 1;
        this.sum = 0;
        this.samples = 0;
        if (this.index === this.block.length) {
          const payload = this.block.buffer;
          this.port.postMessage({type: 'audio', buffer: payload}, [payload]);
          this.block = new Int16Array(1600);
          this.index = 0;
          const rms = Math.sqrt(this.meterSum / Math.max(1, this.meterSamples));
          this.port.postMessage({type: 'meter', rms});
          this.meterSum = 0;
          this.meterSamples = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('pcm16-capture', Pcm16CaptureProcessor);
