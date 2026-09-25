// WAV 录音器：getUserMedia + AudioContext 采集 PCM，降采样 16kHz 单声道 16bit，编码 WAV
// 供服务端 ASR（小米 MiMo）使用——MiMo 只收 wav/mp3，浏览器 MediaRecorder 出的 webm 不行
export class WavRecorder {
  constructor(maxSeconds = 60) {
    this.maxSeconds = maxSeconds
    this._chunks = []
    this._timer = null
  }

  async start() {
    this._stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    this._ctx = new (window.AudioContext || window.webkitAudioContext)()
    this._src = this._ctx.createMediaStreamSource(this._stream)
    this._proc = this._ctx.createScriptProcessor(4096, 1, 1)
    this._chunks = []
    this._proc.onaudioprocess = (e) => {
      this._chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
    }
    this._src.connect(this._proc)
    this._proc.connect(this._ctx.destination) // ScriptProcessor 必须接 destination 才触发
    if (this.maxSeconds > 0) {
      this._timer = setTimeout(() => { this.onMaxReached && this.onMaxReached() }, this.maxSeconds * 1000)
    }
  }

  async stop() {
    // 返回 WAV Blob；未 start 返回 null
    if (this._timer) { clearTimeout(this._timer); this._timer = null }
    if (!this._ctx) return null
    this._proc.disconnect()
    this._src.disconnect()
    this._stream.getTracks().forEach((t) => t.stop())
    const sampleRate = this._ctx.sampleRate
    const chunks = this._chunks
    await this._ctx.close()
    this._ctx = null
    const pcm = _merge(chunks)
    if (!pcm.length) return null
    const pcm16k = _downsample(pcm, sampleRate, 16000)
    return new Blob([_encodeWav(pcm16k, 16000)], { type: 'audio/wav' })
  }
}

function _merge(chunks) {
  const len = chunks.reduce((s, c) => s + c.length, 0)
  const out = new Float32Array(len)
  let off = 0
  for (const c of chunks) { out.set(c, off); off += c.length }
  return out
}

function _downsample(pcm, fromRate, toRate) {
  if (fromRate === toRate) return pcm
  const ratio = fromRate / toRate
  const outLen = Math.floor(pcm.length / ratio)
  const out = new Float32Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio
    const i0 = Math.floor(pos)
    const i1 = Math.min(i0 + 1, pcm.length - 1)
    out[i] = pcm[i0] + (pcm[i1] - pcm[i0]) * (pos - i0) // 线性插值
  }
  return out
}

function _encodeWav(pcm, sampleRate) {
  const n = pcm.length
  const buf = new ArrayBuffer(44 + n * 2)
  const v = new DataView(buf)
  const wstr = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)) }
  wstr(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); wstr(8, 'WAVE')
  wstr(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true)
  v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true)
  v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  wstr(36, 'data'); v.setUint32(40, n * 2, true)
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]))
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true)
  }
  return buf
}
