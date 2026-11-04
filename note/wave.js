// The wave: one smooth wave drifting along the bars. Its height follows the sound, eased so it swells and settles, and never jumps.
const WAVE_BARS = 26;
const WAVE_REACH = 30;  // how far above its resting height a bar can rise
const WAVE_RISE_MS = 90;
const WAVE_FALL_MS = 470;
const WAVE_BEND = 3.84;  // how much quiet sound is lifted
const WAVE_RIPPLES = 7.5;
const WAVE_SPEED = 8.3;

// Lifts quiet sound the most, while loud sound still tops out at full height, so the wave keeps showing loud from soft.
function liftedLevel(level) {
  return (1 - Math.exp(-WAVE_BEND * level)) / (1 - Math.exp(-WAVE_BEND));
}

function startWave(box, level) {
  const stillMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let shown = 0;
  let lastFrame = 0;
  for (let i = 0; i < WAVE_BARS; i++) {
    const bar = document.createElement('span');
    bar.className = 'bar';
    box.appendChild(bar);
  }
  function move(now) {
    requestAnimationFrame(move);
    const passed = Math.min(now - lastFrame, 100);
    lastFrame = now;
    const target = liftedLevel(level());
    const ease = target > shown ? WAVE_RISE_MS : WAVE_FALL_MS;
    shown += (target - shown) * (1 - Math.exp(-passed / ease));
    if (box.hidden) return;
    const bars = box.children;
    const seconds = stillMotion.matches ? 0 : now / 1000;
    for (let i = 0; i < bars.length; i++) {
      const place = (i / (bars.length - 1)) * 2 - 1;  // -1 at the left end, 1 at the right
      const fade = Math.cos((place * Math.PI) / 2);  // low at both ends
      const swell = 0.5 + 0.5 * Math.sin(place * WAVE_RIPPLES - seconds * WAVE_SPEED);
      const drift = 0.5 + 0.5 * Math.sin(place * 2.1 + seconds * 1.3);
      const shape = 0.3 + 0.45 * swell + 0.25 * drift;
      bars[i].style.height = `${6 + WAVE_REACH * shown * fade * shape}px`;
    }
  }
  requestAnimationFrame(move);
}
