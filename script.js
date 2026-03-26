/* ── Custom Cursor ────────────────────────── */
(function () {
  const dot = document.getElementById('cursor-dot');
  const ring = document.getElementById('cursor-ring');
  if (!dot || !ring) return;

  let mouseX = -100, mouseY = -100;
  let ringX = -100, ringY = -100;
  let rafId;

  /* Move dot instantly */
  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
    dot.style.left = mouseX + 'px';
    dot.style.top = mouseY + 'px';
  });

  /* Lazy-follow ring via RAF for smooth trailing */
  function animateRing() {
    ringX += (mouseX - ringX) * 0.12;
    ringY += (mouseY - ringY) * 0.12;
    ring.style.left = ringX + 'px';
    ring.style.top = ringY + 'px';
    rafId = requestAnimationFrame(animateRing);
  }
  animateRing();

  /* Hover state on interactive elements */
  const hoverTargets = 'a, button, [role="button"], .feature-card, .step-card, .nav-cta, .btn-primary, .btn-secondary, .pill-icon-btn, .pill-btn-start, label, input, select, textarea';
  document.addEventListener('mouseover', (e) => {
    if (e.target.closest(hoverTargets)) {
      document.body.classList.add('cursor-hover');
    }
  });
  document.addEventListener('mouseout', (e) => {
    if (e.target.closest(hoverTargets)) {
      document.body.classList.remove('cursor-hover');
    }
  });

  /* Click burst */
  document.addEventListener('mousedown', () => document.body.classList.add('cursor-click'));
  document.addEventListener('mouseup', () => document.body.classList.remove('cursor-click'));

  /* Hide when leaving window */
  document.addEventListener('mouseleave', () => {
    dot.style.opacity = '0';
    ring.style.opacity = '0';
  });
  document.addEventListener('mouseenter', () => {
    dot.style.opacity = '';
    ring.style.opacity = '';
  });
})();

/* ── Reveal on scroll (bidirectional) ────── */
const revealClasses = ['.reveal', '.reveal-left', '.reveal-right', '.reveal-scale', '.reveal-flip', '.section-eyebrow', '.stat-item'];
const allRevealEls = document.querySelectorAll(revealClasses.join(','));

const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => {
      /* Add class when entering viewport, remove when leaving */
      if (e.isIntersecting) {
        e.target.classList.add('visible');
      } else {
        e.target.classList.remove('visible');
      }
    });
  },
  { threshold: 0.12, rootMargin: '0px 0px -40px 0px' },
);
allRevealEls.forEach((el) => revealObserver.observe(el));

/* ── Download redirection ───────────────────── */
(function () {
  /* Intercept all download links (.btn-primary and .nav-cta pointing to .exe releases) */
  document.querySelectorAll('.btn-primary, .nav-cta').forEach((el) => {
    if (el.href && el.href.endsWith('.exe')) {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        window.location.href = 'download.html?url=' + encodeURIComponent(el.href);
      });
    }
  });
})();


(function () {
  const glow = document.querySelector('.hero-glow');
  const grid = document.querySelector('.hero-grid');
  if (!glow && !grid) return;

  let ticking = false;
  window.addEventListener('scroll', () => {
    if (!ticking) {
      requestAnimationFrame(() => {
        const y = window.scrollY;
        if (glow) glow.style.transform = `translate(-50%, calc(-50% + ${y * 0.18}px))`;
        if (grid) grid.style.transform = `translateY(${y * 0.08}px)`;
        ticking = false;
      });
      ticking = true;
    }
  });
})();

/* ── Section entrance line (horizontal rule sweep) ── */
(function () {
  const eyebrows = document.querySelectorAll('.section-eyebrow');
  const lineObserver = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add('eyebrow-visible');
        lineObserver.unobserve(e.target);
      }
    });
  }, { threshold: 0.5 });
  eyebrows.forEach((el) => lineObserver.observe(el));
})();

/* ── Configure: note ↔ group highlight bridge ── */
(function () {
  const notes = document.querySelectorAll('.cfg-note[data-target]');
  notes.forEach((note) => {
    const target = document.getElementById(note.dataset.target);
    if (!target) return;

    note.addEventListener('mouseenter', () => {
      target.classList.add('highlighted');
      note.classList.add('active');
    });
    note.addEventListener('mouseleave', () => {
      target.classList.remove('highlighted');
      note.classList.remove('active');
    });
  });
})();


function toggleMenu() {
  document.getElementById('nav-links').classList.toggle('open');
}
document.querySelectorAll('#nav-links a').forEach((a) => {
  a.addEventListener('click', () => {
    document.getElementById('nav-links').classList.remove('open');
  });
});

/* ── Nav shadow on scroll ─────────────────── */
window.addEventListener('scroll', () => {
  const nav = document.querySelector('nav');
  if (window.scrollY > 8) {
    nav.style.boxShadow = '0 1px 40px rgba(0,0,0,0.6)';
  } else {
    nav.style.boxShadow = '';
  }
});

/* ── Modals ───────────────────────────────── */
function openModal(id) {
  document.getElementById(id).classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
  document.body.style.overflow = '';
}
function closeModalOutside(e, id) {
  if (e.target === document.getElementById(id)) closeModal(id);
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach((m) => {
      m.classList.remove('open');
      document.body.style.overflow = '';
    });
  }
});

/* ── Pill UI Interactive Logic ────────────── */
let pillRunning = false;
let pillPaused = false;
let pillSeconds = 0;
let pillInterval = null;

const pillIdle = document.getElementById('pill-idle');
const pillRec = document.getElementById('pill-recording');
const pillTimerEl = document.getElementById('pill-timer-display');
const pillPauseBtn = document.getElementById('pill-pause-btn');
const pillHint = document.getElementById('pill-hint');

function formatTime(s) {
  const h = String(Math.floor(s / 3600)).padStart(2, '0');
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const sec = String(s % 60).padStart(2, '0');
  return `${h}:${m}:${sec}`;
}

window.pillStartRecording = function () {
  if (pillRunning) return;
  pillRunning = true;
  pillPaused = false;
  pillSeconds = 0;

  pillIdle.style.opacity = '0';
  pillIdle.style.transform = 'scale(0.92)';
  setTimeout(() => {
    pillIdle.classList.add('hidden');
    pillRec.classList.remove('hidden');
    pillRec.style.opacity = '0';
    pillRec.style.transform = 'scale(0.92)';
    requestAnimationFrame(() => {
      pillRec.style.transition = 'opacity 0.35s, transform 0.35s';
      pillRec.style.opacity = '1';
      pillRec.style.transform = 'scale(1)';
    });
  }, 250);

  if (pillHint) pillHint.innerHTML = 'Click <strong>⏸</strong> to pause or <strong>■</strong> to stop';

  pillInterval = setInterval(() => {
    if (!pillPaused) {
      pillSeconds++;
      if (pillTimerEl) pillTimerEl.textContent = formatTime(pillSeconds);
    }
  }, 1000);
};

window.pillStopRecording = function () {
  if (!pillRunning) return;
  clearInterval(pillInterval);
  pillRunning = false;
  pillPaused = false;
  pillSeconds = 0;

  pillRec.style.transition = 'opacity 0.3s, transform 0.3s';
  pillRec.style.opacity = '0';
  pillRec.style.transform = 'scale(0.92)';

  setTimeout(() => {
    pillRec.classList.add('hidden');
    pillRec.style.opacity = '';
    pillRec.style.transform = '';

    pillIdle.classList.remove('hidden');
    pillIdle.style.opacity = '0';
    pillIdle.style.transform = 'scale(0.92)';
    pillIdle.style.transition = 'opacity 0.35s, transform 0.35s';
    requestAnimationFrame(() => {
      pillIdle.style.opacity = '1';
      pillIdle.style.transform = 'scale(1)';
    });
  }, 300);

  if (pillTimerEl) pillTimerEl.textContent = '00:00:00';
  if (pillHint) pillHint.innerHTML = 'Click <strong>Start</strong> to try the interactive demo ↑';

  if (pillPauseBtn) {
    pillPauseBtn.classList.remove('paused');
    pillPauseBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>`;
    pillPauseBtn.title = 'Pause';
  }
};

window.togglePillPause = function () {
  if (!pillRunning) return;
  pillPaused = !pillPaused;

  if (pillPauseBtn) {
    if (pillPaused) {
      pillPauseBtn.classList.add('paused');
      pillPauseBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>`;
      pillPauseBtn.title = 'Resume';
      if (pillHint) pillHint.innerHTML = '<em>Paused — last frame is being re-sent to FFmpeg</em>';
    } else {
      pillPauseBtn.classList.remove('paused');
      pillPauseBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>`;
      pillPauseBtn.title = 'Pause';
      if (pillHint) pillHint.innerHTML = 'Click <strong>⏸</strong> to pause or <strong>■</strong> to stop';
    }
  }
};

window.togglePillAudio = function (btn) {
  btn.classList.toggle('active');
  const isOn = btn.classList.contains('active');
  btn.title = isOn ? 'Mute system audio' : 'Unmute system audio';
  btn.style.transform = 'scale(0.85)';
  setTimeout(() => { btn.style.transform = ''; }, 150);
};

window.togglePillMic = function (btn) {
  btn.classList.toggle('active');
  const isOn = btn.classList.contains('active');
  btn.title = isOn ? 'Mute mic' : 'Unmute mic';
  btn.style.transform = 'scale(0.85)';
  setTimeout(() => { btn.style.transform = ''; }, 150);
};
