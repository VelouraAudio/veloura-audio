const canvas = document.getElementById("waveform");
const context = canvas.getContext("2d");
const audioVisuals = [
  {
    audio: document.getElementById("demo-audio"),
    bars: Array.from(document.querySelectorAll("#demo .demo-meter span")),
    playhead: document.querySelector("#demo .timeline-playhead"),
  },
  {
    audio: document.getElementById("lossless-audio"),
    bars: Array.from(document.querySelectorAll("#lossless .demo-meter span")),
    playhead: document.querySelector("#lossless .timeline-playhead"),
  },
];

const presets = {
  streamer: {
    name: "Streamer",
    description: "Balanced transitions for livestreams, Discord queues, and background music.",
    crossfade: "8s",
    analysis: "Balanced",
    fit: "General queues",
  },
  automix: {
    name: "AutoMix",
    description: "Pair-aware planning with beat confidence, intro trim, and conservative tempo nudges.",
    crossfade: "Adaptive",
    analysis: "Beat-aware",
    fit: "Adjacent songs",
  },
  broadcast: {
    name: "Broadcast",
    description: "Longer, smoother blends for station-style queues and relaxed listening.",
    crossfade: "10s",
    analysis: "Smooth",
    fit: "Radio streams",
  },
  "low-latency": {
    name: "Low latency",
    description: "Shorter analysis windows and faster transitions for weaker machines or rapid queues.",
    crossfade: "4s",
    analysis: "Fast",
    fit: "Busy bots",
  },
};

function resize() {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
}

function draw(time = 0) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  context.clearRect(0, 0, width, height);

  const center = height * 0.53;
  const bands = [
    { color: "rgba(255, 79, 216, 0.58)", amp: 86, speed: 0.002, offset: 0 },
    { color: "rgba(157, 92, 255, 0.46)", amp: 62, speed: 0.0015, offset: 1.8 },
    { color: "rgba(104, 247, 255, 0.22)", amp: 38, speed: 0.0024, offset: 3.1 },
  ];

  for (const band of bands) {
    context.beginPath();
    context.lineWidth = 2;
    context.strokeStyle = band.color;

    for (let x = -20; x <= width + 20; x += 10) {
      const normalized = x / Math.max(1, width);
      const wave =
        Math.sin(normalized * Math.PI * 5 + time * band.speed + band.offset) *
          band.amp +
        Math.sin(normalized * Math.PI * 13 + time * band.speed * 0.7) *
          band.amp *
          0.24;
      const y = center + wave;
      if (x === -20) {
        context.moveTo(x, y);
      } else {
        context.lineTo(x, y);
      }
    }

    context.stroke();
  }

  context.fillStyle = "rgba(255, 138, 240, 0.38)";
  for (let x = 0; x < width; x += 42) {
    const level = 24 + 58 * Math.abs(Math.sin(x * 0.024 + time * 0.0012));
    context.fillRect(x, center - level / 2, 2, level);
  }

  requestAnimationFrame(draw);
}

function updateMeter(time = 0) {
  audioVisuals.forEach(({ audio, bars, playhead }, visualIndex) => {
    const active = audio && !audio.paused && !audio.ended;
    bars.forEach((bar, index) => {
      const pulse = Math.sin(time * 0.006 + index * 0.9 + visualIndex * 0.6);
      const drift = Math.sin(time * 0.002 + index * 0.35 + visualIndex);
      const height = active ? 18 + Math.abs(pulse) * 62 + Math.abs(drift) * 18 : 12 + (index % 4) * 6;
      bar.style.height = `${height}px`;
      bar.style.opacity = active ? "0.92" : "0.58";
    });

    if (audio && playhead) {
      const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
      const progress = duration > 0 ? audio.currentTime / duration : 0;
      playhead.style.left = `${Math.max(0, Math.min(1, progress)) * 100}%`;
    }
  });

  requestAnimationFrame(updateMeter);
}

function setupCopyButtons() {
  document.querySelectorAll(".copy-command").forEach((button) => {
    button.addEventListener("click", async () => {
      const value = button.getAttribute("data-copy") || "";
      try {
        await navigator.clipboard.writeText(value);
        button.textContent = "Copied";
        button.classList.add("copied");
        window.setTimeout(() => {
          button.textContent = "Copy";
          button.classList.remove("copied");
        }, 1400);
      } catch {
        button.textContent = "Select";
      }
    });
  });
}

function setupPresetTabs() {
  const name = document.getElementById("preset-name");
  const description = document.getElementById("preset-description");
  const crossfade = document.getElementById("preset-crossfade");
  const analysis = document.getElementById("preset-analysis");
  const fit = document.getElementById("preset-fit");

  document.querySelectorAll(".preset-tab").forEach((button) => {
    button.addEventListener("click", () => {
      const preset = presets[button.dataset.preset];
      if (!preset) {
        return;
      }
      document.querySelectorAll(".preset-tab").forEach((tab) => tab.classList.remove("active"));
      button.classList.add("active");
      name.textContent = preset.name;
      description.textContent = preset.description;
      crossfade.textContent = preset.crossfade;
      analysis.textContent = preset.analysis;
      fit.textContent = preset.fit;
    });
  });
}

resize();
draw();
updateMeter();
setupCopyButtons();
setupPresetTabs();
window.addEventListener("resize", resize);
