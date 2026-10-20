/* Kiosk sounds: built-in presets (made with the Web Audio API, no files needed)
   plus optional uploaded audio files for each kind of tap.
   Used by the kiosk and by the Settings page (Preview buttons). */
(function () {
  "use strict";

  // Each note: f = frequency (Hz), to = glide to this frequency, d = length (s),
  // at = start time (s), w = waveform, g = loudness, p = extra partial (bell overtone ratio)
  const PRESETS = {
    classic: {
      label: "Classic beep",
      in:    [{f: 659, d: .09}, {f: 988, d: .16, at: .08}],
      late:  [{f: 659, d: .09}, {f: 988, d: .16, at: .08}, {f: 784, d: .14, at: .26}],
      out:   [{f: 988, d: .09}, {f: 659, d: .16, at: .08}],
      warn:  [{f: 587, d: .08}, {f: 587, d: .08, at: .14}],
      error: [{f: 220, d: .12, w: "square", g: .06}, {f: 220, d: .12, at: .17, w: "square", g: .06}, {f: 220, d: .16, at: .34, w: "square", g: .06}],
    },
    chime: {
      label: "Chime",
      in:    [{f: 784, d: .5, w: "triangle"}, {f: 1175, d: .7, at: .12, w: "triangle"}],
      late:  [{f: 784, d: .45, w: "triangle"}, {f: 1175, d: .5, at: .12, w: "triangle"}, {f: 988, d: .6, at: .3, w: "triangle"}],
      out:   [{f: 1175, d: .5, w: "triangle"}, {f: 784, d: .7, at: .12, w: "triangle"}],
      warn:  [{f: 880, d: .3, w: "triangle"}, {f: 880, d: .35, at: .2, w: "triangle"}],
      error: [{f: 330, d: .45, w: "triangle"}, {f: 247, d: .6, at: .18, w: "triangle"}],
    },
    bell: {
      label: "School bell",
      in:    [{f: 1047, d: 1.1, p: 2.76, g: .18}],
      late:  [{f: 1047, d: .7, p: 2.76, g: .18}, {f: 880, d: 1.0, at: .22, p: 2.76, g: .16}],
      out:   [{f: 784, d: 1.1, p: 2.76, g: .18}],
      warn:  [{f: 932, d: .4, p: 2.76, g: .15}, {f: 932, d: .5, at: .22, p: 2.76, g: .15}],
      error: [{f: 262, d: .7, p: 2.76, g: .2}, {f: 262, d: .7, at: .3, p: 2.76, g: .2}],
    },
    arcade: {
      label: "Arcade",
      in:    [{f: 523, d: .07, w: "square", g: .07}, {f: 659, d: .07, at: .07, w: "square", g: .07}, {f: 784, d: .12, at: .14, w: "square", g: .07}],
      late:  [{f: 523, d: .07, w: "square", g: .07}, {f: 659, d: .07, at: .07, w: "square", g: .07}, {f: 622, d: .16, at: .14, w: "square", g: .07}],
      out:   [{f: 784, d: .07, w: "square", g: .07}, {f: 659, d: .07, at: .07, w: "square", g: .07}, {f: 523, d: .12, at: .14, w: "square", g: .07}],
      warn:  [{f: 440, d: .06, w: "square", g: .06}, {f: 440, d: .06, at: .12, w: "square", g: .06}],
      error: [{f: 330, to: 110, d: .4, w: "sawtooth", g: .07}],
    },
    soft: {
      label: "Soft click",
      in:    [{f: 1320, d: .05, g: .14}],
      late:  [{f: 1320, d: .05, g: .14}, {f: 990, d: .05, at: .09, g: .12}],
      out:   [{f: 880, d: .05, g: .14}],
      warn:  [{f: 660, d: .04, g: .1}, {f: 660, d: .04, at: .1, g: .1}],
      error: [{f: 200, d: .12, g: .2}, {f: 200, d: .12, at: .16, g: .2}],
    },
  };

  const KINDS = ["in", "late", "out", "warn", "error"];
  let ctx = null;
  let current = null;            // the uploaded clip that is playing, so the next tap can cut it off

  function audio() {
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") ctx.resume();
    } catch (e) { ctx = null; }
    return ctx;
  }

  function tone(c, n, t0) {
    const t = t0 + (n.at || 0), peak = n.g ?? .22;
    const partials = n.p ? [[1, 1], [n.p, .35], [5.4, .12]] : [[1, 1]];
    for (const [ratio, level] of partials) {
      const osc = c.createOscillator(), gain = c.createGain();
      osc.type = n.w || "sine";
      osc.frequency.setValueAtTime(n.f * ratio, t);
      if (n.to) osc.frequency.exponentialRampToValueAtTime(n.to * ratio, t + n.d);
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(peak * level, t + 0.008);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + n.d * (ratio > 1 ? .6 : 1));
      osc.connect(gain).connect(c.destination);
      osc.start(t); osc.stop(t + n.d + 0.03);
    }
  }

  function playPreset(preset, kind) {
    const c = audio();
    if (!c) return false;
    const p = PRESETS[preset] || PRESETS.classic;
    const go = () => (p[kind] || p.in).forEach(n => tone(c, n, c.currentTime + 0.005));
    if (c.state === "running") go();
    else c.resume().then(() => { if (c.state === "running") go(); }).catch(() => {});
    return true;
  }

  const cache = {};
  function playFile(url) {
    if (current) { current.pause(); current.currentTime = 0; }
    const a = cache[url] || (cache[url] = new Audio(url));
    a.currentTime = 0;
    current = a;
    return a.play().then(() => true).catch(() => false);
  }

  /** config = {preset: "chime", files: {in: "/sounds/x.mp3", ...}} */
  function play(config, kind) {
    const file = config && config.files && config.files[kind];
    if (current) { current.pause(); current.currentTime = 0; current = null; }
    if (file) return playFile(file);
    return Promise.resolve(playPreset(config && config.preset, kind));
  }

  function preload(config) {
    Object.values((config && config.files) || {}).forEach(url => {
      if (url && !cache[url]) { cache[url] = new Audio(url); cache[url].preload = "auto"; }
    });
  }

  window.KioskSounds = { PRESETS, KINDS, play, playPreset, playFile, preload, unlock: audio };
})();
