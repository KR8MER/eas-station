(function() {
    'use strict';

    function init3DTilt() {
        const tiltCards = document.querySelectorAll('.card-3d-tilt');

        tiltCards.forEach(card => {
            card.addEventListener('mousemove', function(e) {
                const rect = this.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;

                const centerX = rect.width / 2;
                const centerY = rect.height / 2;

                const deltaX = (x - centerX) / centerX;
                const deltaY = (y - centerY) / centerY;

                const tiltX = deltaY * -10; // Max 10 degrees
                const tiltY = deltaX * 10;

                this.style.setProperty('--tilt-x', `${tiltX}deg`);
                this.style.setProperty('--tilt-y', `${tiltY}deg`);
            });

            card.addEventListener('mouseleave', function() {
                this.style.setProperty('--tilt-x', '0deg');
                this.style.setProperty('--tilt-y', '0deg');
            });
        });
    }

    function initMagneticEffect() {
        const magneticElements = document.querySelectorAll('.magnetic');

        magneticElements.forEach(element => {
            element.addEventListener('mousemove', function(e) {
                const rect = this.getBoundingClientRect();
                const x = e.clientX - rect.left - rect.width / 2;
                const y = e.clientY - rect.top - rect.height / 2;

                const distance = Math.sqrt(x * x + y * y);
                const maxDistance = 100;

                if (distance < maxDistance) {
                    const strength = (maxDistance - distance) / maxDistance;
                    const moveX = x * strength * 0.3;
                    const moveY = y * strength * 0.3;

                    this.style.transform = `translate(${moveX}px, ${moveY}px)`;
                }
            });

            element.addEventListener('mouseleave', function() {
                this.style.transform = 'translate(0, 0)';
            });
        });
    }

    // ============================================
    // PARALLAX SCROLL EFFECT
    // ============================================

    function initParallax() {
        const parallaxElements = document.querySelectorAll('.parallax-bg');

        function updateParallax() {
            parallaxElements.forEach(element => {
                const rect = element.parentElement.getBoundingClientRect();
                const scrolled = window.pageYOffset;
                const rate = scrolled * -0.3;

                element.style.transform = `translate3d(0, ${rate}px, 0)`;
            });
        }

        window.addEventListener('scroll', updateParallax, { passive: true });
        updateParallax();
    }

    // ============================================
    // ANIMATED PAGE HEADER WITH ORBS
    // ============================================

    function addOrbsToElement(element, orbCount) {
        if (element.classList.contains('orbs-added')) {
            return;
        }
        
        for (let i = 0; i < orbCount; i++) {
            const orb = document.createElement('div');
            orb.className = 'orb';
            element.appendChild(orb);
        }
        element.classList.add('orbs-added');
    }

    function initHeaderOrbs() {
        // Add orbs to page headers
        const headers = document.querySelectorAll('.page-header:not(.orbs-added)');
        headers.forEach(header => addOrbsToElement(header, 3));

        // Add orbs to page-shell only on larger screens to avoid mobile layout breakage
        const isDesktopViewport = window.matchMedia('(min-width: 992px)').matches;
        if (!isDesktopViewport) {
            return;
        }

        const pageShells = document.querySelectorAll('.page-shell:not(.orbs-added)');
        pageShells.forEach(shell => addOrbsToElement(shell, 5));
    }

    // ============================================
    // MORPHING SHAPES BACKGROUND
    // ============================================

    function initMorphingShapes() {
        const sections = document.querySelectorAll('.aurora-bg:not(.shapes-added)');

        sections.forEach(section => {
            const shape1 = document.createElement('div');
            shape1.className = 'morph-shape';
            shape1.style.top = '10%';
            shape1.style.left = '10%';

            const shape2 = document.createElement('div');
            shape2.className = 'morph-shape';
            shape2.style.top = '60%';
            shape2.style.right = '15%';
            shape2.style.animationDelay = '-5s';

            section.appendChild(shape1);
            section.appendChild(shape2);
            section.classList.add('shapes-added');
        });
    }

    // ============================================
    // STAGGERED FADE-IN ANIMATION
    // ============================================

    function initStaggeredAnimations() {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('stagger-fade-in');
                    observer.unobserve(entry.target);
                }
            });
        }, {
            threshold: 0.1
        });

        const animatedSections = document.querySelectorAll('.animate-on-scroll');
        animatedSections.forEach(section => observer.observe(section));
    }

    // ============================================
    // ENHANCED ICON INTERACTIONS
    // ============================================

    function initIconEffects() {
        // Add bounce effect to icons on hover
        document.querySelectorAll('.fa, .fas, .far, .fab').forEach(icon => {
            const parent = icon.parentElement;

            if (parent.classList.contains('btn') ||
                parent.classList.contains('nav-link') ||
                parent.classList.contains('card-title')) {
                icon.classList.add('icon-bounce');
            }
        });
    }

    // ============================================
    // MAP ENHANCEMENTS
    // ============================================

    function initMapEnhancements() {
        // Add gradient border animation to map card
        const mapCard = document.querySelector('.map-card');
        if (mapCard && !mapCard.classList.contains('enhanced')) {
            mapCard.classList.add('enhanced');

            // Add status badge animation
            const statusBadge = document.getElementById('map-status-badge');
            if (statusBadge) {
                statusBadge.classList.add('badge-animated');
            }
        }

        // Enhance layer sections
        const layerSections = document.querySelectorAll('.layer-section');
        layerSections.forEach((section, index) => {
            section.style.animationDelay = `${index * 0.1}s`;
            section.classList.add('slide-up');
        });
    }

    // ============================================
    // SMOOTH SCROLL ENHANCEMENTS
    // ============================================

    function initSmoothScroll() {
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                const href = this.getAttribute('href');
                if (href === '#' || href === '#!') return;

                const target = document.querySelector(href);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });
    }

    // ============================================
    // BUTTON RIPPLE EFFECT ENHANCEMENT
    // ============================================

    function enhanceButtonRipple() {
        document.querySelectorAll('.btn').forEach(button => {
            button.addEventListener('click', function(e) {
                const ripple = document.createElement('span');
                ripple.className = 'ripple-effect';

                const rect = this.getBoundingClientRect();
                const size = Math.max(rect.width, rect.height);
                const x = e.clientX - rect.left - size / 2;
                const y = e.clientY - rect.top - size / 2;

                ripple.style.width = ripple.style.height = size + 'px';
                ripple.style.left = x + 'px';
                ripple.style.top = y + 'px';
                ripple.style.position = 'absolute';
                ripple.style.borderRadius = '50%';
                ripple.style.background = 'rgba(255, 255, 255, 0.5)';
                ripple.style.transform = 'scale(0)';
                ripple.style.animation = 'ripple 0.6s ease-out';
                ripple.style.pointerEvents = 'none';

                this.appendChild(ripple);

                setTimeout(() => ripple.remove(), 600);
            });
        });
    }

    // ============================================
    // GRADIENT TEXT ANIMATION
    // ============================================

    // Surfaces whose background is itself painted from --primary-color /
    // --secondary-color. A heading sitting on one of these must NOT get
    // .gradient-text: that class fills the glyphs with the same two-colour
    // ramp and sets -webkit-text-fill-color: transparent, so the title ends up
    // drawn in the colours of the surface directly behind it and is very close
    // to invisible. This affected the title of every page using the standard
    // page header.
    const GRADIENT_TEXT_EXCLUDED_SURFACES =
        '.page-header, .page-header-gradient, .eas-hero, .navbar, .hero, .card-header';

    function initGradientText() {
        // Apply gradient text to main headings on plain backgrounds only.
        document.querySelectorAll('h1, .page-title').forEach(heading => {
            if (heading.closest(GRADIENT_TEXT_EXCLUDED_SURFACES)) {
                return;
            }
            if (!heading.classList.contains('gradient-applied')) {
                heading.classList.add('gradient-text');
                heading.classList.add('gradient-applied');
            }
        });
    }

    // ============================================
    // CARD HOVER EFFECTS
    // ============================================

    function enhanceCardHovers() {
        document.querySelectorAll('.card:not(.enhanced)').forEach(card => {
            card.classList.add('enhanced');

            // Add subtle 3D effect to stat cards
            if (card.classList.contains('stat-card') ||
                card.classList.contains('metric-card')) {
                card.classList.add('card-3d');
            }

            // Add glass effect to certain cards
            if (card.classList.contains('control-card') ||
                card.classList.contains('insight-card') ||
                card.classList.contains('legend-card')) {
                card.classList.add('glass-effect');
            }
        });
    }

    // ============================================
    // PERFORMANCE OPTIMIZATIONS
    // ============================================

    function checkReducedMotion() {
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
        return prefersReducedMotion.matches;
    }

    function optimizeForMobile() {
        return window.innerWidth <= 768;
    }

    // ============================================
    // INITIALIZE ALL EFFECTS
    // ============================================

    function initAllEffects() {
        const isMobile = optimizeForMobile();
        const reducedMotion = checkReducedMotion();

        // Always init these
        initSmoothScroll();
        enhanceButtonRipple();
        initMapEnhancements();
        enhanceCardHovers();

        // Skip heavy animations on mobile or if reduced motion is preferred
        if (!isMobile && !reducedMotion) {
            init3DTilt();
            initMagneticEffect();
            initParallax();
            initHeaderOrbs();
            initMorphingShapes();
            initStaggeredAnimations();
            initGradientText();
        }

        // Always init icon effects
        initIconEffects();
    }

    // ============================================
    // REINITIALIZE ON DYNAMIC CONTENT
    // ============================================

    let _contentObserver = null;

    function observeNewContent() {
        _contentObserver = new MutationObserver((mutations) => {
            let shouldReinit = false;

            mutations.forEach((mutation) => {
                if (mutation.addedNodes.length > 0) {
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === 1 &&
                            (node.classList.contains('card') ||
                             node.classList.contains('btn') ||
                             node.querySelector('.card, .btn'))) {
                            shouldReinit = true;
                        }
                    });
                }
            });

            if (shouldReinit) {
                // Debounce re-initialization
                clearTimeout(window.visualEffectsTimeout);
                window.visualEffectsTimeout = setTimeout(() => {
                    enhanceCardHovers();
                    initIconEffects();
                    initMapEnhancements();
                }, 300);
            }
        });

        _contentObserver.observe(document.body, {
            childList: true,
            subtree: true
        });

        // Cleanup observer on page unload to prevent memory leaks
        window.addEventListener('pagehide', function() {
            if (_contentObserver) {
                _contentObserver.disconnect();
                _contentObserver = null;
            }
        });
    }

    // ============================================
    // ENTRY POINT
    // ============================================

    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initAllEffects();
            observeNewContent();
        });
    } else {
        initAllEffects();
        observeNewContent();
    }

    // Re-initialize on window resize (debounced)
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            optimizeForMobile();
        }, 250);
    });

    // Export for manual re-initialization if needed
    window.EASVisualEffects = {
        init: initAllEffects,
        enhanceCards: enhanceCardHovers,
        enhanceMap: initMapEnhancements
    };

})();
