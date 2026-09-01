(() => {
  'use strict';

  const RELEASES_API = 'https://api.github.com/repos/akasumitlamba/WWRecorder/releases?per_page=30';
  const RELEASES_FALLBACK = 'https://github.com/akasumitlamba/WWRecorder/releases/latest';
  const OFFICIAL_ASSET_PREFIX = 'https://github.com/akasumitlamba/WWRecorder/releases/download/';

  // GitHub-published installer names and SHA-256 digests from release asset metadata.
  const OFFICIAL_INSTALLER_RELEASES = Object.freeze([
    Object.freeze({ releaseName: 'WWRecorder 1.6.3', filename: 'WWRecorder_Setup_1.6.3.exe', sha256: 'ec30b53e4f0ce2ac57ffac66d3f9c90340b4dca5c7ca9e6391926e6a82720eb9' }),
    Object.freeze({ releaseName: 'WWRecorder v1.6.0 Public Beta', filename: 'WWRecorder_Setup_1.6.exe', sha256: 'caa0cc1d8741a81937933ab1105510397305913bff516cef7e5c9287636e1694' }),
    Object.freeze({ releaseName: 'WWRecorder v1.5.0', filename: 'WWRecorder_Setup_1.5.exe', sha256: 'caf5d2afaa366f503453f8ac09211ce47af8b457163eafd853bb24dbd7a4a687' }),
    Object.freeze({ releaseName: 'WWRecorder v1.4.0', filename: 'WWRecorder_Setup_1.4.exe', sha256: '79606df1d4401fdb1b1a81efea358799d2e9bb1d231a127fa770d81a8f4d30c0' }),
    Object.freeze({ releaseName: 'WWRecorder v1.3.0', filename: 'WWRecorder_Setup_1.3.exe', sha256: '92d4423ad2847abdba62b5e9f9c17d1ab6093c48438a3ef59dabfb6a6c4da551' }),
    Object.freeze({ releaseName: 'WWRecorder v1.2.0', filename: 'WWRecorder_Setup_1.2.0.exe', sha256: 'aa311bf01c4c8d9a1cfeb03567bce5024cdda20fb79e926a8b364245908a5f05' }),
    Object.freeze({ releaseName: 'WWRecorder v1.1.0', filename: 'WWRecorder_Setup_1.1.0.exe', sha256: '2e43ad4bb835ef2fd963810491ec9cf3a0206a26f315d61016e961b33cc54621' }),
    Object.freeze({ releaseName: 'WWRecorder v1.0.0', filename: 'WWRecorder_Setup_1.0.0.exe', sha256: '72c7ef30b60dc5cbbe59971b9d3f61aa6a19d209e3d50f9fb443a26eabb4a2cf' })
  ]);

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const header = document.querySelector('[data-header]');
  const menuButton = document.querySelector('.menu-toggle');
  const nav = document.querySelector('#site-nav');

  document.querySelectorAll('[data-current-year]').forEach((node) => {
    node.textContent = String(new Date().getFullYear());
  });

  const updateScroll = () => {
    const top = window.scrollY || document.documentElement.scrollTop;
    header?.classList.toggle('scrolled', top > 12);
  };
  updateScroll();
  window.addEventListener('scroll', updateScroll, { passive: true });

  let scrollFramePending = false;
  const updateScrollEffects = () => {
    scrollFramePending = false;
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    if (reduceMotion) return;

    document.querySelectorAll('.feature-story').forEach((story) => {
      const rect = story.getBoundingClientRect();
      const active = rect.top < window.innerHeight * .68 && rect.bottom > window.innerHeight * .32;
      story.classList.toggle('is-active', active);
      const travel = Math.max(1, rect.height - window.innerHeight);
      const amount = Math.max(0, Math.min(1, -rect.top / travel));
      story.style.setProperty('--story-shift', `${(amount - .5) * -18}px`);
      story.style.setProperty('--story-scale', String(.008 + amount * .012));
    });
  };
  const requestScrollEffects = () => {
    if (scrollFramePending) return;
    scrollFramePending = true;
    requestAnimationFrame(updateScrollEffects);
  };
  updateScrollEffects();
  window.addEventListener('scroll', requestScrollEffects, { passive: true });
  window.addEventListener('resize', requestScrollEffects, { passive: true });

  if (!reduceMotion && window.matchMedia('(pointer:fine)').matches) {
    document.addEventListener('pointermove', (event) => {
      document.body.style.setProperty('--pointer-x', `${event.clientX}px`);
      document.body.style.setProperty('--pointer-y', `${event.clientY}px`);
      const hero = document.querySelector('.hero-centered');
      if (hero && event.clientY <= hero.offsetHeight) {
        const x = event.clientX / window.innerWidth - .5;
        const y = event.clientY / Math.max(1, hero.offsetHeight) - .5;
        hero.style.setProperty('--hero-grid-x', `${x * -9}px`);
        hero.style.setProperty('--hero-grid-y', `${y * -9}px`);
        hero.style.setProperty('--hero-orbit-x', `${x * 15}px`);
        hero.style.setProperty('--hero-orbit-y', `${y * 15}px`);
      }
    }, { passive: true });

    document.querySelectorAll('.capability,.fit-card,.practical-item,.engineering-card,.project-card,.pipeline-node,.tech-note,.spec-card,.code-card').forEach((card) => {
      card.addEventListener('pointermove', (event) => {
        const rect = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${event.clientX - rect.left}px`);
        card.style.setProperty('--my', `${event.clientY - rect.top}px`);
      }, { passive: true });
    });
  }

  menuButton?.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') !== 'true';
    menuButton.setAttribute('aria-expanded', String(open));
    nav?.classList.toggle('open', open);
  });
  nav?.querySelectorAll('a,button').forEach((item) => item.addEventListener('click', () => {
    nav.classList.remove('open');
    menuButton?.setAttribute('aria-expanded', 'false');
  }));

  const revealNodes = document.querySelectorAll('.reveal,.reveal-left,.reveal-right,.project-reveal-left,.project-reveal-right');
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
        }
      });
    }, { threshold: 0.01, rootMargin: '0px 0px 40px 0px' });
    revealNodes.forEach((node) => observer.observe(node));
  } else {
    revealNodes.forEach((node) => node.classList.add('in-view'));
  }

  let releasePromise;
  const fetchStableReleases = () => {
    if (!releasePromise) {
      releasePromise = fetch(RELEASES_API, { headers: { Accept: 'application/vnd.github+json' } })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error('Release lookup failed')))
        .then((releases) => releases
          .filter((release) => !release.draft && !release.prerelease)
          .map((release) => ({
            name: release.name || release.tag_name,
            tag: release.tag_name,
            published: release.published_at,
            asset: Array.isArray(release.assets) ? release.assets.find((asset) => /\.exe$/i.test(asset.name)) : null
          }))
          .filter((release) => release.asset && release.asset.browser_download_url.startsWith(OFFICIAL_ASSET_PREFIX)));
    }
    return releasePromise;
  };

  const formatReleaseDate = (value) => {
    if (!value) return '';
    return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
  };

  let modal = document.querySelector('[data-download-modal]');
  if (!modal) {
    document.body.insertAdjacentHTML('beforeend', `
      <div class="download-modal" data-download-modal hidden>
        <div class="modal-backdrop" data-modal-close></div>
        <section class="download-dialog" role="dialog" aria-modal="true" aria-labelledby="download-title-shared">
          <button class="modal-close" type="button" aria-label="Close download choices" data-modal-close>×</button>
          <div class="modal-heading">
            <span class="download-glyph has-svg" aria-hidden="true"><img class="download-icon" src="icons/download-tray.svg" alt=""></span>
            <div class="modal-heading-text">
              <p class="section-kicker">Download WWRecorder</p>
              <h2 id="download-title-shared">Choose an installation source</h2>
            </div>
          </div>
          <div class="download-choices">
            <a class="download-choice store-choice" href="https://aka.ms/AA1364bx" target="_blank" rel="noopener">
              <span class="choice-icon-wrap" aria-hidden="true"><span class="ms-logo large"><i></i><i></i><i></i><i></i></span></span>
              <span class="choice-text">
                <small>RECOMMENDED</small>
                <strong>Microsoft Store</strong>
                <em>Install and receive Store updates</em>
              </span>
            </a>
            <a class="download-choice installer-choice" href="download.html">
              <span class="choice-icon-wrap" aria-hidden="true"><img class="download-icon" src="icons/download-tray.svg" alt=""></span>
              <span class="choice-text">
                <small>STANDALONE</small>
                <strong>Installer</strong>
                <em>Latest stable release from GitHub</em>
              </span>
            </a>
          </div>
          <details class="release-picker"><summary>Older stable installers</summary><div class="release-list" data-release-list><span>Loading published releases…</span></div></details>
          <a class="modal-help" href="install-help.html">Having trouble downloading or installing? View help →</a>
        </section>
      </div>`);
    modal = document.querySelector('[data-download-modal]');
  }

  const releaseLists = document.querySelectorAll('[data-release-list]');
  const renderReleaseLists = (releases) => {
    releaseLists.forEach((list) => {
      list.replaceChildren();
      if (!releases.length) {
        const link = document.createElement('a');
        link.href = RELEASES_FALLBACK;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = 'Open GitHub release history';
        list.append(link);
        return;
      }
      releases.forEach((release, index) => {
        const link = document.createElement('a');
        const params = new URLSearchParams({ url: release.asset.browser_download_url, version: release.tag });
        link.href = `download.html?${params}`;
        const title = document.createElement('span');
        title.textContent = `${release.tag} · ${release.asset.name}`;
        const meta = document.createElement(index === 0 ? 'b' : 'small');
        meta.textContent = index === 0 ? 'Latest stable' : formatReleaseDate(release.published);
        link.append(title, meta);
        list.append(link);
      });
    });
  };

  if (releaseLists.length) {
    fetchStableReleases().then(renderReleaseLists).catch(() => renderReleaseLists([]));
  }

  let lastFocused;
  const openDownloadModal = () => {
    if (!modal) return;
    lastFocused = document.activeElement;
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    modal.querySelector('.modal-close')?.focus();
    if (releaseLists.length) fetchStableReleases().then(renderReleaseLists).catch(() => renderReleaseLists([]));
  };
  const closeDownloadModal = () => {
    if (!modal) return;
    modal.hidden = true;
    document.body.style.overflow = '';
    lastFocused?.focus?.();
  };
  document.querySelectorAll('.js-download-open').forEach((button) => button.addEventListener('click', openDownloadModal));
  modal?.querySelectorAll('[data-modal-close]').forEach((button) => button.addEventListener('click', closeDownloadModal));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal && !modal.hidden) closeDownloadModal();
  });

  const initializeDownloadPage = async () => {
    if (document.body.dataset.page !== 'download') return;
    const statusCard = document.querySelector('[data-download-status-card]');
    const statusTitle = document.querySelector('[data-download-title]');
    const statusText = document.querySelector('[data-download-text]');
    const manualLink = document.querySelector('[data-manual-download]');
    const versionSelect = document.querySelector('[data-version-select]');
    const releaseName = document.querySelector('[data-selected-release]');
    const params = new URLSearchParams(window.location.search);
    let requestedUrl = params.get('url') || '';
    const requestedVersion = params.get('version') || '';
    let activeUrl = '';

    const targetPill = document.querySelector('[data-target-pill]');
    const targetName = document.querySelector('[data-target-name]');
    const buttonLabel = document.querySelector('[data-button-label]');

    const setActiveRelease = (release, isAutoStarting = false) => {
      if (!release?.asset?.browser_download_url?.startsWith(OFFICIAL_ASSET_PREFIX)) return false;
      activeUrl = release.asset.browser_download_url;
      if (manualLink) {
        manualLink.href = activeUrl;
        if (buttonLabel) {
          buttonLabel.textContent = `Download ${release.tag}`;
        } else {
          manualLink.innerHTML = `<img class="download-icon" src="icons/download-tray.svg" alt="" aria-hidden="true"> Download ${release.tag}`;
        }
      }
      if (releaseName) releaseName.textContent = `${release.tag} · ${release.asset.name}`;
      if (targetName) targetName.textContent = `${release.tag} (${release.asset.name})`;
      if (targetPill) targetPill.style.display = 'inline-flex';

      if (statusTitle) {
        statusTitle.textContent = isAutoStarting ? `Downloading ${release.tag}` : `Ready to download ${release.tag}`;
      }
      if (statusText) {
        statusText.textContent = isAutoStarting
          ? `Starting download for ${release.asset.name}. If the download does not start automatically, click Download ${release.tag} below.`
          : `Selected target: ${release.asset.name} (${formatReleaseDate(release.published)}). Click Download ${release.tag} below to start.`;
      }
      return true;
    };

    const startDownload = () => {
      if (!activeUrl) return;
      statusCard?.classList.add('ready');
      window.location.href = activeUrl;
    };

    manualLink?.addEventListener('click', (event) => {
      if (!activeUrl) event.preventDefault();
    });

    try {
      const releases = await fetchStableReleases();
      if (!releases.length) throw new Error('No stable installer found');
      const requested = requestedUrl.startsWith(OFFICIAL_ASSET_PREFIX)
        ? releases.find((release) => release.asset.browser_download_url === requestedUrl)
        : releases.find((release) => release.tag === requestedVersion);
      const chosen = requested || releases[0];
      setActiveRelease(chosen, true);

      if (versionSelect) {
        versionSelect.replaceChildren();
        releases.forEach((release, index) => {
          const option = document.createElement('option');
          option.value = release.asset.browser_download_url;
          option.textContent = `${release.tag}${index === 0 ? ' (latest stable)' : ''} · ${formatReleaseDate(release.published)}`;
          option.selected = release.asset.browser_download_url === activeUrl;
          versionSelect.append(option);
        });
        versionSelect.addEventListener('change', () => {
          const release = releases.find((item) => item.asset.browser_download_url === versionSelect.value);
          if (release) {
            setActiveRelease(release, false);
            statusCard?.classList.add('ready');
          }
        });
      }
      window.setTimeout(startDownload, 900);
    } catch (error) {
      if (statusTitle) statusTitle.textContent = 'Open the stable release page';
      if (statusText) statusText.textContent = 'The live installer lookup is unavailable. Review the latest stable release directly on GitHub.';
      if (manualLink) {
        manualLink.href = RELEASES_FALLBACK;
        manualLink.textContent = 'Open GitHub releases';
      }
    }
  };

  initializeDownloadPage();

  
  document.querySelector('[data-copy-cmd]')?.addEventListener('click', async () => {
    const btn = document.querySelector('[data-copy-cmd]');
    const cmdText = document.querySelector('[data-powershell-cmd]')?.textContent || 'Get-FileHash -Algorithm SHA256 "C:\\path\\to\\WWRecorder_Setup.exe"';
    try {
      await navigator.clipboard.writeText(cmdText);
      if (btn) {
        btn.classList.add('copied');
        const span = btn.querySelector('span');
        if (span) span.textContent = 'Copied!';
        setTimeout(() => {
          btn.classList.remove('copied');
          if (span) span.textContent = 'Copy command';
        }, 2000);
      }
    } catch (e) {
      if (btn) {
        const span = btn.querySelector('span');
        if (span) span.textContent = 'Press Ctrl+C';
      }
    }
  });

  const hashInput = document.querySelector('[data-hash-input]');
  const hashResult = document.querySelector('[data-hash-result]');
  const normaliseHash = (value) => String(value || '').trim().replace(/\s+/g, '').toLowerCase();
  const showHashResult = (message, state) => {
    if (!hashResult) return;
    hashResult.textContent = message;
    hashResult.dataset.state = state;
  };

  document.querySelector('[data-paste-hash]')?.addEventListener('click', async () => {
    try {
      const value = await navigator.clipboard.readText();
      if (hashInput) hashInput.value = value.trim();
      showHashResult('Pasted. Select Check to compare the fingerprint.', 'neutral');
    } catch (error) {
      showHashResult('Clipboard access was unavailable. Paste into the field manually.', 'warning');
      hashInput?.focus();
    }
  });

  document.querySelector('[data-check-hash]')?.addEventListener('click', () => {
    const entered = normaliseHash(hashInput?.value);
    if (!/^[a-f0-9]{64}$/.test(entered)) {
      showHashResult('Enter the complete 64-character SHA-256 value shown by PowerShell.', 'warning');
      return;
    }
    const published = OFFICIAL_INSTALLER_RELEASES
      .map((release) => ({ ...release, sha256: normaliseHash(release.sha256) }))
      .filter((release) => /^[a-f0-9]{64}$/.test(release.sha256));
    if (!published.length) {
      showHashResult('Official fingerprints have not been published here yet. This file cannot be verified on this page.', 'warning');
      return;
    }
    const matchedRelease = published.find((release) => release.sha256 === entered);
    if (matchedRelease) {
      showHashResult(`Verified. This matches ${matchedRelease.releaseName} (${matchedRelease.filename}).`, 'success');
    } else {
      showHashResult('No match. Do not run this file. Download it again from Microsoft Store or the official GitHub release.', 'danger');
    }
  });

  // Navbar active item indicator (red and bold on active page or scrolled section)
  const navLinks = Array.from(document.querySelectorAll('#site-nav a:not(.nav-download)'));
  const currentPath = window.location.pathname.split('/').pop() || 'index.html';

  const updateActiveNavLink = () => {
    const isHomePage = currentPath === 'index.html' || currentPath === '' || document.body.dataset.page === 'home';

    if (isHomePage) {
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      const atBottom = window.innerHeight + scrollTop >= document.documentElement.scrollHeight - 70;
      const scrollPos = scrollTop + Math.min(240, window.innerHeight * 0.35);
      const sections = [
        { id: 'under-the-hood', el: document.getElementById('under-the-hood') },
        { id: 'fit', el: document.getElementById('fit') },
        { id: 'features', el: document.getElementById('features') }
      ];

      let activeSectionId = null;
      if (atBottom && sections[0].el) {
        activeSectionId = sections[0].id;
      } else {
        for (const section of sections) {
          if (section.el && section.el.offsetTop <= scrollPos) {
            activeSectionId = section.id;
            break;
          }
        }
      }

      navLinks.forEach((link) => {
        const href = link.getAttribute('href') || '';
        const targetId = href.startsWith('#') ? href.slice(1) : href.split('#')[1];
        if (targetId && activeSectionId && targetId === activeSectionId) {
          link.classList.add('is-active');
          link.setAttribute('aria-current', 'true');
        } else {
          link.classList.remove('is-active');
          if (link.getAttribute('aria-current') !== 'page') {
            link.removeAttribute('aria-current');
          }
        }
      });
    } else {
      navLinks.forEach((link) => {
        const href = link.getAttribute('href') || '';
        const linkFile = href.split('#')[0].split('/').pop();
        if (linkFile && linkFile === currentPath) {
          link.classList.add('is-active');
          link.setAttribute('aria-current', 'page');
        } else {
          link.classList.remove('is-active');
          if (link.getAttribute('aria-current') === 'page') {
            link.removeAttribute('aria-current');
          }
        }
      });
    }
  };

  updateActiveNavLink();
  window.addEventListener('scroll', updateActiveNavLink, { passive: true });
  window.addEventListener('resize', updateActiveNavLink, { passive: true });

  // Document Table of Contents scroll spy
  const docTocLinks = Array.from(document.querySelectorAll('.doc-toc a'));
  if (docTocLinks.length) {
    const docSections = docTocLinks.map((link) => {
      const id = (link.getAttribute('href') || '').replace('#', '');
      return { id, el: document.getElementById(id), link };
    }).filter((item) => item.el);

    const updateDocToc = () => {
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      const atBottom = window.innerHeight + scrollTop >= document.documentElement.scrollHeight - 70;
      const scrollPos = scrollTop + Math.min(240, window.innerHeight * 0.35);

      let activeItem = null;
      if (atBottom && docSections.length) {
        activeItem = docSections[docSections.length - 1];
      } else {
        for (let i = docSections.length - 1; i >= 0; i--) {
          if (docSections[i].el.offsetTop <= scrollPos) {
            activeItem = docSections[i];
            break;
          }
        }
      }
      if (!activeItem && docSections.length) activeItem = docSections[0];

      docSections.forEach((item) => {
        item.link.classList.toggle('is-active', activeItem && item.id === activeItem.id);
      });
    };

    updateDocToc();
    window.addEventListener('scroll', updateDocToc, { passive: true });
    window.addEventListener('resize', updateDocToc, { passive: true });
  }

})();
