// QuestWay 2026 theme — scroll reveal + animated counters.
// Kept separate from script.js (legacy widget logic) so the new design
// system's behavior stays easy to reason about on its own.
(function () {
    function initReveal() {
        const targets = document.querySelectorAll('.qw-reveal, .qw-reveal-stagger');
        if (!targets.length) return;

        if (!('IntersectionObserver' in window)) {
            targets.forEach(function (el) { el.classList.add('qw-in'); });
            return;
        }

        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('qw-in');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15, rootMargin: '0px 0px -60px 0px' });

        targets.forEach(function (el) { observer.observe(el); });
    }

    function initCounters() {
        const counters = document.querySelectorAll('.qw-counting[data-target]');
        if (!counters.length) return;

        function animateCounter(el) {
            const target = parseFloat(el.getAttribute('data-target'));
            const suffix = el.getAttribute('data-suffix') || '';
            const duration = 1400;
            const start = performance.now();

            function tick(now) {
                const progress = Math.min((now - start) / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 3);
                const value = Math.round(target * eased);
                el.textContent = value.toLocaleString('en-US') + suffix;
                if (progress < 1) requestAnimationFrame(tick);
            }
            requestAnimationFrame(tick);
        }

        if (!('IntersectionObserver' in window)) {
            counters.forEach(animateCounter);
            return;
        }

        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    animateCounter(entry.target);
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.4 });

        counters.forEach(function (el) { observer.observe(el); });
    }

    function initScrollCues() {
        document.querySelectorAll('.qw-scroll-cue[role="button"]').forEach(function (cue) {
            cue.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    cue.click();
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initReveal();
        initCounters();
        initScrollCues();
    });
})();
