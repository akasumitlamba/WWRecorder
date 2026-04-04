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
  const hoverTargets = 'a, button, [role="button"], .feature-card, .step-card, .nav-cta, .nav-logo, .btn-primary, .btn-secondary, .pill-icon-btn, .pill-btn-start, label, input, select, textarea';
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
  { threshold: 0.05, rootMargin: '0px 0px -20px 0px' },
);
allRevealEls.forEach((el) => revealObserver.observe(el));

/* ── Download redirection (Event Delegation) ── */
(function () {
  // Prevent redirection logic from running if we're already on the download page
  if (window.location.pathname.includes('download.html')) return;

  document.addEventListener('click', (e) => {
    const el = e.target.closest('.btn-primary, .nav-cta, .download-dropdown-item');
    if (el && el.href && el.href.endsWith('.exe')) {
      e.preventDefault();
      window.location.href = 'download.html?url=' + encodeURIComponent(el.href);
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
  if (nav) {
    if (window.scrollY > 8) {
      nav.style.boxShadow = '0 1px 40px rgba(0,0,0,0.6)';
    } else {
      nav.style.boxShadow = '';
    }
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

/* ── Fetch & Populate Releases ────────────── */
(async function () {
  const dlText = document.getElementById('dl-count-text');
  const dlContainer = document.getElementById('wwr-downloads');
  const mainBtn = document.getElementById('main-download-btn');
  const navBtn = document.getElementById('nav-download-cta');
  const dlList = document.getElementById('download-list');

  if (!dlText || !dlContainer) return;

  try {
    const res = await fetch('https://api.github.com/repos/akasumitlamba/WWRecorder/releases');
    if (!res.ok) throw new Error('API Error');
    const releases = await res.json();
    
    // Filter out pre-releases
    const stableWebReleases = releases.filter(rel => !rel.prerelease);
    if (stableWebReleases.length === 0) return;

    let totalDownloads = 0;
    let latestExe = null;
    let html = '';

    stableWebReleases.forEach((release, index) => {
      const exeAsset = release.assets.find(asset => asset.name.endsWith('.exe'));
      if (exeAsset) {
        totalDownloads += exeAsset.download_count;
        
        const isLatest = index === 0;
        if (isLatest) latestExe = exeAsset.browser_download_url;

        // Build dropdown item HTML
        html += `
          <a class="download-dropdown-item ${isLatest ? 'current' : ''}" 
             href="${exeAsset.browser_download_url}" target="_blank">
            <div class="download-dropdown-ver">
              <span class="ver-badge ${isLatest ? 'current' : 'older'}">${isLatest ? 'Latest' : 'Older'}</span>
              ${release.name || release.tag_name}
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </a>
        `;
      }
    });

    // Update Main Buttons
    if (latestExe) {
      if (mainBtn) mainBtn.href = latestExe;
      if (navBtn) navBtn.href = latestExe;
    }

    // Update Dropdown List
    if (dlList && html) {
      dlList.innerHTML = html;
    }

    // Update Total Count
    if (totalDownloads > 0) {
      dlText.textContent = totalDownloads.toLocaleString() + ' Downloads on GitHub';
      dlContainer.style.color = 'var(--pill-green)';
      setTimeout(() => dlContainer.style.color = 'var(--text-3)', 1500);
    } else {
      dlContainer.style.display = 'none';
    }
  } catch (err) {
    console.error('Failed to fetch releases:', err);
    // Don't hide the container if it already has hardcoded fallback content
    if (dlText.textContent.includes('Loading')) {
        dlContainer.style.display = 'none';
    }
  }
})();

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

/* ══════════════════════════════════════════
    AUTO-CYCLING SHOWCASE (How to Use)
══════════════════════════════════════════ */
(function () {
  const useSlides = ['dock', 'screenshot', 'recording', 'files', 'settings'];
  let useIdx = 0;
  let useTimer = null;
  let useHovered = false;

  window.switchShowcase = function (tabName) {
    // Update slides
    document.querySelectorAll('.showcase-slide').forEach(s => s.classList.remove('active'));
    const target = document.getElementById('slide-' + tabName);
    if (target) {
      target.style.animation = 'none';
      target.offsetHeight;
      target.style.animation = '';
      target.classList.add('active');
    }
    // Update step highlights
    document.querySelectorAll('.use-step').forEach(step => {
      step.classList.toggle('step-active', step.dataset.highlight === tabName);
    });
    // Sync index
    const idx = useSlides.indexOf(tabName);
    if (idx !== -1) useIdx = idx;
  };

  function useNext() {
    useIdx = (useIdx + 1) % useSlides.length;
    window.switchShowcase(useSlides[useIdx]);
  }

  function startUseTimer() {
    if (useTimer) return;
    useTimer = setInterval(() => {
      if (!useHovered) useNext();
    }, 3000);
  }

  function stopUseTimer() {
    if (useTimer) { clearInterval(useTimer); useTimer = null; }
  }

  // Step hover pauses auto-cycle, shows that step
  document.querySelectorAll('.use-step[data-highlight]').forEach(step => {
    step.addEventListener('mouseenter', () => {
      useHovered = true;
      window.switchShowcase(step.dataset.highlight);
    });
    step.addEventListener('mouseleave', () => {
      useHovered = false;
    });
    step.addEventListener('click', () => {
      window.switchShowcase(step.dataset.highlight);
    });
  });

  // Also pause auto-cycle when hovering over the visual area so the user can interact with the pill
  const useVisual = document.querySelector('.use-visual');
  if (useVisual) {
    useVisual.addEventListener('mouseenter', () => useHovered = true);
    useVisual.addEventListener('mouseleave', () => useHovered = false);
  }

  // Start/stop when section is visible
  const useSection = document.getElementById('use');
  if (useSection) {
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) startUseTimer();
        else stopUseTimer();
      });
    }, { threshold: 0.15 });
    obs.observe(useSection);
  }
})();

/* ── Appreciation Ribbon Overflow Logic ───── */
(function () {
  const container = document.querySelector('.thanks-marquee-container');
  const content = document.querySelector('.thanks-content');
  if (!container || !content) return;

  function updateMarquee() {
    if (!container || !content) return;
    
    // Reset to measure correctly
    content.classList.remove('marquee-active');
    container.classList.remove('marquee-active-mask');

    const containerWidth = container.offsetWidth;
    const contentWidth = content.scrollWidth;

    if (contentWidth > containerWidth) {
      // Duplicate list items for seamless loop if not already done
      const items = content.querySelectorAll('li:not(.thanks-duplicate)');
      if (content.querySelectorAll('.thanks-duplicate').length === 0) {
        items.forEach(item => {
          const clone = item.cloneNode(true);
          clone.classList.add('thanks-duplicate');
          content.appendChild(clone);
        });
      }
      content.classList.add('marquee-active');
      container.classList.add('marquee-active-mask');
    }
  }

  // Initial check and on resize
  window.addEventListener('load', updateMarquee);
  window.addEventListener('resize', updateMarquee);
  // Re-check after a brief delay for any dynamic font loading
  setTimeout(updateMarquee, 1500);
})();

/* ══════════════════════════════════════════
    AUTO-CYCLING CONFIG (Works your way)
══════════════════════════════════════════ */
(function () {
  const cfgSlides = ['output', 'hotkeys', 'defaults', 'save'];
  let cfgIdx = 0;
  let cfgTimer = null;
  let cfgHovered = false;

  window.switchCfgSlide = function (name) {
    // Update slides
    document.querySelectorAll('.cfg-slide').forEach(s => s.classList.remove('active'));
    const target = document.getElementById('cfgslide-' + name);
    if (target) {
      target.style.animation = 'none';
      target.offsetHeight;
      target.style.animation = '';
      target.classList.add('active');
    }
    // Update step highlights
    document.querySelectorAll('.cfg-step').forEach(step => {
      step.classList.toggle('step-active', step.dataset.cfghighlight === name);
    });
    // Sync index
    const idx = cfgSlides.indexOf(name);
    if (idx !== -1) cfgIdx = idx;
  };

  function cfgNext() {
    cfgIdx = (cfgIdx + 1) % cfgSlides.length;
    window.switchCfgSlide(cfgSlides[cfgIdx]);
  }

  function startCfgTimer() {
    if (cfgTimer) return;
    cfgTimer = setInterval(() => {
      if (!cfgHovered) cfgNext();
    }, 3000);
  }

  function stopCfgTimer() {
    if (cfgTimer) { clearInterval(cfgTimer); cfgTimer = null; }
  }

  // Step hover pauses auto-cycle, shows that step
  document.querySelectorAll('.cfg-step[data-cfghighlight]').forEach(step => {
    step.addEventListener('mouseenter', () => {
      cfgHovered = true;
      window.switchCfgSlide(step.dataset.cfghighlight);
    });
    step.addEventListener('mouseleave', () => {
      cfgHovered = false;
    });
    step.addEventListener('click', () => {
      window.switchCfgSlide(step.dataset.cfghighlight);
    });
  });

  // Start/stop when section is visible
  const cfgSection = document.getElementById('configure');
  if (cfgSection) {
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) startCfgTimer();
        else stopCfgTimer();
      });
    }, { threshold: 0.15 });
    obs.observe(cfgSection);
  }
})();

/* ══════════════════════════════════════════
    DOWNLOAD DROPDOWN
══════════════════════════════════════════ */
window.toggleDownloadDropdown = function (e) {
  e.preventDefault();
  e.stopPropagation();
  const dropdown = document.getElementById('download-dropdown');
  const toggle = document.getElementById('download-toggle');
  const isOpen = dropdown.classList.contains('open');

  if (isOpen) {
    dropdown.classList.remove('open');
    toggle.classList.remove('open');
  } else {
    dropdown.classList.add('open');
    toggle.classList.add('open');
  }
};

// Close dropdown on click outside
document.addEventListener('click', function (e) {
  const wrapper = document.getElementById('download-wrapper');
  const dropdown = document.getElementById('download-dropdown');
  const toggle = document.getElementById('download-toggle');
  if (!wrapper || !dropdown) return;

  if (!wrapper.contains(e.target)) {
    dropdown.classList.remove('open');
    if (toggle) toggle.classList.remove('open');
  }
});

// Close dropdown on Escape
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    const dropdown = document.getElementById('download-dropdown');
    const toggle = document.getElementById('download-toggle');
    if (dropdown) dropdown.classList.remove('open');
    if (toggle) toggle.classList.remove('open');
  }
});

/* ══════════════════════════════════════════
    R FLICKER ANIMATION (tubelight on the R)
══════════════════════════════════════════ */
(function () {
  const r = document.getElementById('flicker-r');
  if (!r) return;

  // Wait for the hero fade-up animation to finish, then start the R flicker
  setTimeout(() => {
    r.classList.add('flickering');

    // After the flicker animation (1.4s) completes, set final lit state
    setTimeout(() => {
      r.classList.remove('flickering');
      r.classList.add('lit');
    }, 1500);
  }, 1000);
})();

