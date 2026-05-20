(function() {
    'use strict';

    function addLogoGradients() {
        const logos = document.querySelectorAll('.logo-wordmark, .brand-logo');

        logos.forEach(logo => {
            // The brand logo is an <img> referencing the canonical
            // wordmark PNG — injecting SVG <defs> only makes sense on
            // inline SVG elements.  Skip anything else so we don't
            // throw on <img> tags.
            if (logo.tagName.toLowerCase() !== 'svg') return;
            if (logo.querySelector('defs')) return;

            const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            const gradient = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');
            gradient.setAttribute('id', 'logoGradient');
            gradient.setAttribute('x1', '0%');
            gradient.setAttribute('y1', '0%');
            gradient.setAttribute('x2', '100%');
            gradient.setAttribute('y2', '0%');

            const primaryColor = getComputedStyle(document.documentElement)
                .getPropertyValue('--primary-color') || '#204885';
            const secondaryColor = getComputedStyle(document.documentElement)
                .getPropertyValue('--secondary-color') || '#872a96';

            const stop1 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
            stop1.setAttribute('offset', '0%');
            stop1.setAttribute('stop-color', primaryColor);

            const stop2 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
            stop2.setAttribute('offset', '50%');
            stop2.setAttribute('stop-color', secondaryColor);

            const stop3 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
            stop3.setAttribute('offset', '100%');
            stop3.setAttribute('stop-color', primaryColor);

            const animate = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
            animate.setAttribute('attributeName', 'x1');
            animate.setAttribute('values', '0%;100%;0%');
            animate.setAttribute('dur', '4s');
            animate.setAttribute('repeatCount', 'indefinite');

            gradient.appendChild(stop1);
            gradient.appendChild(stop2);
            gradient.appendChild(stop3);
            gradient.appendChild(animate);
            defs.appendChild(gradient);
            logo.insertBefore(defs, logo.firstChild);
        });
    }

    function initLogoMagneticEffect() {
        const navbarBrand = document.querySelector('.navbar-brand');
        if (!navbarBrand) return;

        const logo = navbarBrand.querySelector('.logo-wordmark');
        if (!logo) return;

        navbarBrand.addEventListener('mousemove', function(e) {
            const rect = this.getBoundingClientRect();
            const x = e.clientX - rect.left - rect.width / 2;
            const y = e.clientY - rect.top - rect.height / 2;
            logo.style.transform = `translate(${x * 0.1}px, ${y * 0.1}px)`;
        });

        navbarBrand.addEventListener('mouseleave', function() {
            logo.style.transform = 'translate(0, 0)';
        });
    }

    function initLogoClickEffects() {
        const navbarBrands = document.querySelectorAll('.navbar-brand');
        navbarBrands.forEach(brand => {
            brand.addEventListener('click', function(e) {
                const logo = this.querySelector('.logo-wordmark');
                if (!logo) return;
                logo.classList.add('heartbeat');
                setTimeout(() => logo.classList.remove('heartbeat'), 1500);
            });
        });
    }

    let _themeObserver = null;
    let _logoObserver = null;

    function watchThemeChanges() {
        _themeObserver = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.attributeName === 'data-theme') {
                    setTimeout(() => updateGradientColors(), 100);
                }
            });
        });
        _themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme']
        });
    }

    function updateGradientColors() {
        const gradients = document.querySelectorAll('#logoGradient, #sleekGradient, #primaryGradient, #secondaryGradient, #modernGradient1, #modernGradient2');
        const primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--primary-color') || '#204885';
        const secondaryColor = getComputedStyle(document.documentElement).getPropertyValue('--secondary-color') || '#872a96';
        const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--accent-color') || '#4f6fb3';

        gradients.forEach(gradient => {
            const stops = gradient.querySelectorAll('stop');
            if (gradient.id === 'sleekGradient' && stops.length >= 3) {
                stops[0].setAttribute('stop-color', primaryColor);
                stops[1].setAttribute('stop-color', accentColor);
                stops[2].setAttribute('stop-color', secondaryColor);
            } else if (gradient.id === 'primaryGradient' && stops.length >= 2) {
                stops[0].setAttribute('stop-color', primaryColor);
                stops[1].setAttribute('stop-color', accentColor);
            } else if (gradient.id === 'secondaryGradient' && stops.length >= 2) {
                stops[0].setAttribute('stop-color', secondaryColor);
                stops[1].setAttribute('stop-color', accentColor);
            } else if ((gradient.id === 'modernGradient1' || gradient.id === 'logoGradient') && stops.length >= 2) {
                stops[0].setAttribute('stop-color', primaryColor);
                stops[1].setAttribute('stop-color', secondaryColor);
                if (stops.length >= 3) stops[2].setAttribute('stop-color', primaryColor);
            }
        });

        const textPrimary = document.querySelectorAll('.logo-text-primary');
        const textSecondary = document.querySelectorAll('.logo-text-secondary');

        textPrimary.forEach(text => text.setAttribute('fill', 'white'));
        textSecondary.forEach(text => text.setAttribute('fill', 'rgba(255, 255, 255, 0.85)'));
    }

    function addRainbowEffect() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.add('rainbow'));
    }

    function removeRainbowEffect() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.remove('rainbow'));
    }

    function addPulseGlow() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.add('pulse-glow'));
    }

    function removePulseGlow() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.remove('pulse-glow'));
    }

    function addMorphEffect() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.add('morph'));
    }

    function removeMorphEffect() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.remove('morph'));
    }

    function addCelebrationEffect() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.add('celebrate'));
    }

    function removeCelebrationEffect() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => logo.classList.remove('celebrate'));
    }

    function shakeLogo() {
        document.querySelectorAll('.logo-wordmark').forEach(logo => {
            logo.classList.add('shake');
            setTimeout(() => logo.classList.remove('shake'), 500);
        });
    }

    function setLogoLoading(loading) {
        document.querySelectorAll('.logo-wordmark').forEach(logo => {
            logo.classList.toggle('loading', loading);
        });
    }

    function initKonamiCode() {
        const konamiCode = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
        let konamiIndex = 0;

        document.addEventListener('keydown', (e) => {
            if (e.key === konamiCode[konamiIndex]) {
                konamiIndex++;
                if (konamiIndex === konamiCode.length) {
                    activateRainbowMode();
                    konamiIndex = 0;
                }
            } else {
                konamiIndex = 0;
            }
        });
    }

    function activateRainbowMode() {
        addRainbowEffect();
        addCelebrationEffect();
        if (window.showToast) {
            window.showToast('🌈 Rainbow mode activated!', 'success');
        }
        setTimeout(() => {
            removeRainbowEffect();
            removeCelebrationEffect();
        }, 10000);
    }

    function checkPerformance() {
        const isMobile = window.innerWidth <= 768;
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (isMobile || prefersReducedMotion) {
            document.querySelectorAll('.logo-wordmark').forEach(logo => {
                logo.style.animation = 'none';
            });
        }
    }

    function init() {
        if (typeof document.createElementNS !== 'function') return;
        addLogoGradients();
        checkPerformance();
        if (window.innerWidth > 768) initLogoMagneticEffect();
        initLogoClickEffects();
        watchThemeChanges();
        initKonamiCode();
    }

    function observeNewLogos() {
        _logoObserver = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.addedNodes.length > 0) {
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === 1) {
                            if (node.classList && (node.classList.contains('logo-wordmark') || node.classList.contains('brand-logo'))) {
                                addLogoGradients();
                            }
                            const logos = node.querySelectorAll('.logo-wordmark, .brand-logo');
                            if (logos.length > 0) addLogoGradients();
                        }
                    });
                }
            });
        });
        _logoObserver.observe(document.body, { childList: true, subtree: true });

        // Cleanup observers on page unload to prevent memory leaks
        window.addEventListener('pagehide', function() {
            if (_themeObserver) {
                _themeObserver.disconnect();
                _themeObserver = null;
            }
            if (_logoObserver) {
                _logoObserver.disconnect();
                _logoObserver = null;
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            init();
            observeNewLogos();
        });
    } else {
        init();
        observeNewLogos();
    }

    window.LogoEffects = {
        addRainbow: addRainbowEffect,
        removeRainbow: removeRainbowEffect,
        addPulseGlow: addPulseGlow,
        removePulseGlow: removePulseGlow,
        addMorph: addMorphEffect,
        removeMorph: removeMorphEffect,
        celebrate: addCelebrationEffect,
        stopCelebration: removeCelebrationEffect,
        shake: shakeLogo,
        setLoading: setLogoLoading,
        updateColors: updateGradientColors
    };
})();
