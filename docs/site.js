const canvas = document.getElementById("waveform");
const context = canvas.getContext("2d");

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

  const center = height * 0.52;
  const bands = [
    { color: "rgba(28, 124, 112, 0.48)", amp: 78, speed: 0.0018, offset: 0 },
    { color: "rgba(201, 125, 44, 0.34)", amp: 52, speed: 0.0013, offset: 1.8 },
    { color: "rgba(21, 23, 26, 0.22)", amp: 34, speed: 0.0021, offset: 3.1 },
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

  context.fillStyle = "rgba(255, 255, 255, 0.54)";
  for (let x = 0; x < width; x += 46) {
    const level = 22 + 42 * Math.abs(Math.sin(x * 0.022 + time * 0.001));
    context.fillRect(x, center - level / 2, 2, level);
  }

  requestAnimationFrame(draw);
}

resize();
draw();
window.addEventListener("resize", resize);
