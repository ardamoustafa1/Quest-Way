const questions = [
    { key: "region", text: "Which part of the world would you most like to explore?", options: {
        "Europe": "Europe", "Asia": "Asia", "Africa": "Africa",
        "Americas": "Americas", "Oceania": "Oceania", "Surprise me": "any"
    }},
    { key: "season", text: "When are you planning to travel?", options: {
        "Spring": "spring", "Summer": "summer", "Autumn": "autumn",
        "Winter": "winter", "Flexible": "flexible"
    }},
    { key: "climate", text: "What weather would make the trip feel right?", options: {
        "Warm & sunny": "warm", "Mild": "mild", "Cool": "cool",
        "Snowy": "snow", "No preference": "any"
    }},
    { key: "duration", text: "How much time do you have?", options: {
        "Weekend": "weekend", "4–7 days": "week", "8–14 days": "fortnight",
        "2+ weeks": "long"
    }},
    { key: "budget", text: "What is your preferred spending level?", options: {
        "Value focused": "budget", "Comfortable": "midrange",
        "Premium": "luxury", "Flexible": "any"
    }},
    { key: "style", text: "What should be at the heart of this trip?", options: {
        "History & culture": "history", "Nature & wildlife": "nature",
        "Food": "food", "Beaches": "beach", "Cities & nightlife": "city"
    }},
    { key: "pace", text: "Which travel pace suits you?", options: {
        "Slow & restorative": "slow", "Balanced": "balanced",
        "See as much as possible": "active"
    }},
    { key: "company", text: "Who are you traveling with?", options: {
        "Solo": "solo", "Partner": "couple", "Family": "family",
        "Friends": "friends"
    }},
    { key: "stay", text: "What kind of stay do you prefer?", options: {
        "Local guesthouse": "local", "Hotel": "hotel",
        "Resort": "resort", "No preference": "any"
    }}
];

// Country-specific strengths are intentionally curated. Countries without an
// override still participate through their continent profile.
const destinationProfiles = {
    Japan: ["history", "food", "city", "active", "luxury"],
    Italy: ["history", "food", "city", "couple", "midrange"],
    France: ["history", "food", "city", "couple", "luxury"],
    Spain: ["warm", "food", "beach", "city", "friends"],
    Portugal: ["mild", "food", "beach", "slow", "midrange"],
    Greece: ["warm", "history", "beach", "couple", "resort"],
    Turkey: ["history", "food", "beach", "midrange", "family"],
    Germany: ["history", "city", "active", "hotel", "midrange"],
    Iceland: ["cool", "snow", "nature", "active", "luxury"],
    Norway: ["cool", "snow", "nature", "active", "luxury"],
    Finland: ["cool", "snow", "nature", "slow", "family"],
    Switzerland: ["cool", "snow", "nature", "active", "luxury"],
    Croatia: ["warm", "history", "beach", "midrange", "couple"],
    Morocco: ["warm", "history", "food", "local", "budget"],
    Egypt: ["warm", "history", "active", "midrange", "family"],
    Kenya: ["warm", "nature", "active", "luxury", "family"],
    Tanzania: ["warm", "nature", "beach", "active", "luxury"],
    "South Africa": ["nature", "food", "city", "active", "midrange"],
    Namibia: ["warm", "nature", "active", "local", "luxury"],
    Rwanda: ["mild", "nature", "active", "local", "midrange"],
    Thailand: ["warm", "food", "beach", "budget", "friends"],
    Vietnam: ["warm", "food", "history", "budget", "active"],
    Indonesia: ["warm", "nature", "beach", "budget", "resort"],
    Malaysia: ["warm", "food", "city", "beach", "midrange"],
    Singapore: ["warm", "food", "city", "hotel", "luxury"],
    India: ["warm", "history", "food", "budget", "active"],
    Nepal: ["cool", "nature", "active", "budget", "local"],
    Bhutan: ["cool", "nature", "history", "slow", "local"],
    "South Korea": ["food", "city", "history", "active", "hotel"],
    Australia: ["warm", "nature", "beach", "city", "active"],
    "New Zealand": ["cool", "nature", "active", "friends", "midrange"],
    Fiji: ["warm", "beach", "resort", "couple", "slow"],
    Canada: ["cool", "snow", "nature", "city", "family"],
    "United States": ["city", "nature", "active", "family", "hotel"],
    Mexico: ["warm", "history", "food", "beach", "budget"],
    "Costa Rica": ["warm", "nature", "beach", "active", "local"],
    Cuba: ["warm", "history", "food", "beach", "local"],
    Brazil: ["warm", "nature", "beach", "city", "friends"],
    Argentina: ["food", "nature", "city", "active", "midrange"],
    Peru: ["history", "food", "nature", "active", "budget"],
    Chile: ["nature", "food", "active", "midrange", "hotel"]
};

const continentDefaults = {
    Africa: ["warm", "nature", "history", "local", "active"],
    Asia: ["food", "history", "city", "local", "active"],
    Europe: ["history", "food", "city", "hotel", "midrange"],
    "North America": ["nature", "city", "active", "hotel", "family"],
    "South America": ["warm", "nature", "food", "active", "local"],
    Oceania: ["nature", "beach", "active", "midrange", "friends"]
};

let userPreferences = {};
let currentQuestion = -1;

function toggleChat() {
    const chatAssistant = document.getElementById("chatAssistant");
    const toggleBtn = document.getElementById("aiToggleBtn");
    
    if (chatAssistant.style.display === "none" || chatAssistant.style.display === "") {
        chatAssistant.style.display = "flex";
        toggleBtn.style.display = "none";
        startChat();
    } else {
        chatAssistant.style.display = "none";
        toggleBtn.style.display = "flex";
    }
}

function startChat() {
    const chatMessages = document.getElementById("chatMessages");
    chatMessages.innerHTML = "";
    currentQuestion = -1;
    userPreferences = {};

    const firstMessage = document.createElement("div");
    firstMessage.classList.add("message", "bot-message");
    firstMessage.innerHTML = "<p><strong>Let’s build your travel profile.</strong><br>I’ll consider timing, budget, pace and interests, then compare destinations from our complete country catalogue.</p>";
    chatMessages.appendChild(firstMessage);

    setTimeout(() => {
        showQuestion();
    }, 1500);
}

function showQuestion() {
    if (currentQuestion < questions.length - 1) {
        currentQuestion++;

        const chatMessages = document.getElementById("chatMessages");

        const questionObj = questions[currentQuestion];

        const messageDiv = document.createElement("div");
        messageDiv.classList.add("message", "bot-message");
        messageDiv.innerHTML = `<p><strong>${currentQuestion + 1} of ${questions.length}</strong><br>${questionObj.text}</p>`;
        chatMessages.appendChild(messageDiv);

        const buttonsDiv = document.createElement("div");
        buttonsDiv.classList.add("question-options");

        Object.keys(questionObj.options).forEach(option => {
            const button = document.createElement("button");
            button.classList.add("option-btn");
            button.innerText = option;
            button.onclick = () => handleAnswer(questionObj.options[option], option);
            buttonsDiv.appendChild(button);
        });

        chatMessages.appendChild(buttonsDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    } else {
        showCountryRecommendation();
    }
}

function handleAnswer(answer, label) {
    userPreferences[questions[currentQuestion].key] = answer;

    // Add user's answer to chat
    const chatMessages = document.getElementById("chatMessages");
    const answerDiv = document.createElement("div");
    answerDiv.classList.add("message", "user-message");
    answerDiv.textContent = label || answer;
    const optionGroups = chatMessages.querySelectorAll(".question-options");
    optionGroups[optionGroups.length - 1]?.remove();
    chatMessages.appendChild(answerDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    setTimeout(() => {
        showQuestion();
    }, 1000);
}

function getCountryCandidates() {
    const catalog = window.QW_COUNTRY_CATALOG || {};
    return Object.entries(catalog).flatMap(([continent, countries]) =>
        countries.map(country => ({ country, continent }))
    );
}

function scoreDestination(candidate) {
    const tags = new Set([
        ...(continentDefaults[candidate.continent] || []),
        ...(destinationProfiles[candidate.country] || [])
    ]);
    let score = destinationProfiles[candidate.country] ? 2 : 0;
    const reasons = [];
    const requestedRegion = userPreferences.region;
    const regionMatches = requestedRegion === "Americas"
        ? candidate.continent.includes("America")
        : requestedRegion === candidate.continent;
    if (requestedRegion === "any" || regionMatches) {
        score += requestedRegion === "any" ? 1 : 5;
        if (requestedRegion !== "any") reasons.push(requestedRegion);
    } else {
        score -= 4;
    }
    ["climate", "budget", "style", "pace", "company", "stay"].forEach(key => {
        const value = userPreferences[key];
        if (value && value !== "any" && tags.has(value)) {
            score += key === "style" ? 4 : 2;
            reasons.push(Object.keys(questions.find(q => q.key === key).options)
                .find(label => questions.find(q => q.key === key).options[label] === value));
        }
    });
    // Short trips favour compact destinations; longer trips can reward range.
    if (userPreferences.duration === "weekend" &&
        ["Singapore", "Malta", "Luxembourg", "Monaco", "Andorra", "San Marino"].includes(candidate.country)) {
        score += 3;
        reasons.push("easy for a short escape");
    }
    if (userPreferences.duration === "long" && tags.has("active")) score += 2;
    return { ...candidate, score, reasons: [...new Set(reasons)].slice(0, 3) };
}

function showCountryRecommendation() {
    const chatMessages = document.getElementById("chatMessages");
    const recommendations = getCountryCandidates()
        .map(scoreDestination)
        .sort((a, b) => b.score - a.score || a.country.localeCompare(b.country))
        .slice(0, 3);

    const resultMessage = document.createElement("div");
    resultMessage.classList.add("message", "bot-message", "recommendation");
    resultMessage.innerHTML = `
        <p><strong>Three destinations matched to your travel profile</strong></p>
        <p class="recommendation-summary">${userPreferences.duration || "Flexible"} trip · ${userPreferences.budget || "flexible"} budget · ${userPreferences.style || "mixed"} focus</p>
        <div class="recommended-countries">
            ${recommendations.map((item, index) => `
                <div class="country-recommendation">
                    <span class="match-rank">0${index + 1} · ${item.continent}</span>
                    <h4>${item.country}</h4>
                    <p>${item.reasons.length ? `Strong match for ${item.reasons.join(", ").toLowerCase()}.` : "A balanced match for your preferences."}</p>
                    <button class="explore-btn" data-country="${item.country}">Explore ${item.country}</button>
                </div>
            `).join("")}
        </div>
        <div class="restart-chat">
            <button class="restart-btn" onclick="restartChat()">Start New Recommendation</button>
        </div>
    `;
    chatMessages.appendChild(resultMessage);
    resultMessage.querySelectorAll(".explore-btn").forEach(button => {
        button.addEventListener("click", () => exploreCountry(button.dataset.country));
    });
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function exploreCountry(country) {
    window.location.href = `/country?country=${encodeURIComponent(country)}`;
}

function restartChat() {
    currentQuestion = -1;
    userPreferences = {};
    startChat();
}

// Send message function for AI chat
function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    
    if (message) {
        // Add user message to chat
        const chatMessages = document.getElementById("chatMessages");
        const messageDiv = document.createElement("div");
        messageDiv.classList.add("message", "user-message");
        messageDiv.textContent = message;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        input.value = '';
        
        const question = questions[currentQuestion];
        const normalized = message.toLocaleLowerCase();
        const match = question && Object.entries(question.options).find(([label, value]) =>
            normalized.includes(label.toLocaleLowerCase()) ||
            normalized.includes(String(value).toLocaleLowerCase())
        );
        setTimeout(() => {
            if (match) {
                handleAnswer(match[1], match[0]);
                return;
            }
            const botResponse = document.createElement("div");
            botResponse.classList.add("message", "bot-message");
            botResponse.innerHTML = `<p>I understand natural answers such as <em>“warm weather”</em>, <em>“a one-week cultural trip”</em>, or one of the choices above. For this question, please mention one of the listed preferences.</p>`;
            chatMessages.appendChild(botResponse);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 350);
    }
}

// Mobile Menu Functionality
function initMobileMenu() {
    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    const mobileMenu = document.getElementById('mobileMenu');
    const mobileMenuClose = document.getElementById('mobileMenuClose');
    
    if (mobileMenuToggle && mobileMenu && mobileMenuClose) {
        mobileMenuToggle.addEventListener('click', function() {
            mobileMenu.classList.add('active');
            document.body.style.overflow = 'hidden'; // Prevent background scrolling
        });
        
        mobileMenuClose.addEventListener('click', function() {
            mobileMenu.classList.remove('active');
            document.body.style.overflow = 'auto'; // Restore scrolling
        });
        
        // Close menu when clicking outside
        mobileMenu.addEventListener('click', function(e) {
            if (e.target === mobileMenu) {
                mobileMenu.classList.remove('active');
                document.body.style.overflow = 'auto';
            }
        });
        
        // Close menu when clicking on links
        const mobileNavLinks = mobileMenu.querySelectorAll('.mobile-nav-links a');
        mobileNavLinks.forEach(link => {
            link.addEventListener('click', function() {
                mobileMenu.classList.remove('active');
                document.body.style.overflow = 'auto';
            });
        });
    }
}

// Touch-friendly interactions
function initTouchInteractions() {
    // Add touch feedback to buttons
    const touchButtons = document.querySelectorAll('.touch-button, .main-nav a, .search-submit-btn');
    touchButtons.forEach(button => {
        button.addEventListener('touchstart', function() {
            this.style.transform = 'scale(0.95)';
        });
        
        button.addEventListener('touchend', function() {
            this.style.transform = '';
        });
    });
}

// Smooth scrolling for mobile
function initSmoothScrolling() {
    const links = document.querySelectorAll('a[href^="#"]');
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href').substring(1);
            const targetElement = document.getElementById(targetId);
            
            if (targetElement) {
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Form optimization for mobile
function initFormOptimization() {
    const formInputs = document.querySelectorAll('input, textarea, select');
    formInputs.forEach(input => {
        // Prevent zoom on iOS
        if (input.type === 'text' || input.type === 'email' || input.type === 'password' || input.tagName === 'TEXTAREA') {
            input.style.fontSize = '16px';
        }
        
        // Add focus states
        input.addEventListener('focus', function() {
            this.style.transform = 'translateY(-2px)';
            this.style.boxShadow = '0 4px 15px rgba(30, 58, 138, 0.2)';
        });
        
        input.addEventListener('blur', function() {
            this.style.transform = '';
            this.style.boxShadow = '';
        });
    });
}

// Enter key support for chat input
document.addEventListener('DOMContentLoaded', function() {
    const input = document.getElementById('chatInput');
    if (input) {
        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
    }
    
    // Initialize mobile functionality
    initMobileMenu();
    initTouchInteractions();
    initSmoothScrolling();
    initFormOptimization();
    
    initThemeToggle();
    initLanguageToggle();
    initConfirmForms();
});

// Destructive forms (admin delete/ban) opt in via data-confirm="..." instead of
// an inline onsubmit="" attribute, so this works under a CSP without 'unsafe-inline'.
function initConfirmForms() {
    document.querySelectorAll('form[data-confirm]').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (!confirm(form.getAttribute('data-confirm'))) {
                e.preventDefault();
            }
        });
    });
}

// ---- Dark mode ----
function initThemeToggle() {
    const toggle = document.getElementById('qw-theme-toggle');
    const icon = document.getElementById('qw-theme-icon');
    if (!toggle) return;

    function applyIcon() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        icon.classList.toggle('fa-moon', !isDark);
        icon.classList.toggle('fa-sun', isDark);
    }
    applyIcon();

    toggle.addEventListener('click', function() {
        const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('qw-theme', next);
        applyIcon();
    });
}

// ---- TR/EN interface language (chrome-level: nav, buttons, common labels).
// This does NOT translate user-generated content (reviews, forum posts) —
// that would need a translation API call per piece of content, out of scope
// for this pass. It covers the site's own interface text. ----
const QW_TRANSLATIONS = {
    en: {
        nav_home: 'Home', nav_explore: 'Explore', nav_reviews: 'Reviews', nav_search: 'Search',
        nav_forum: 'Forum', nav_wishlist: 'Wishlist', nav_itineraries: 'Itineraries',
        nav_profile: 'Profile', nav_admin: 'Admin', nav_logout: 'Logout', nav_login: 'Login', nav_register: 'Register',
        home_subtitle: 'A considered guide for travelers who read carefully before they book — real reviews, AI-assisted itineraries, and a community that\'s actually been there.',
    },
    tr: {
        nav_home: 'Ana Sayfa', nav_explore: 'Keşfet', nav_reviews: 'Yorumlar', nav_search: 'Ara',
        nav_forum: 'Forum', nav_wishlist: 'İstek Listesi', nav_itineraries: 'Gezi Planlarım',
        nav_profile: 'Profil', nav_admin: 'Yönetim', nav_logout: 'Çıkış Yap', nav_login: 'Giriş Yap', nav_register: 'Kayıt Ol',
        home_subtitle: 'Rezervasyondan önce dikkatle okuyan gezginler için: gerçek yorumlar, yapay zeka destekli gezi planları ve gerçekten oraya gitmiş bir topluluk.',
    },
};

function applyLanguage(lang) {
    const dict = QW_TRANSLATIONS[lang] || QW_TRANSLATIONS.en;
    document.querySelectorAll('[data-i18n]').forEach(function(el) {
        const key = el.getAttribute('data-i18n');
        if (dict[key]) el.textContent = dict[key];
    });
    const label = document.getElementById('qw-lang-label');
    if (label) label.textContent = lang.toUpperCase();
    document.documentElement.setAttribute('lang', lang);
}

function initLanguageToggle() {
    const toggle = document.getElementById('qw-lang-toggle');
    let lang = localStorage.getItem('qw-lang') || 'en';
    applyLanguage(lang);
    if (!toggle) return;

    toggle.addEventListener('click', function() {
        lang = lang === 'en' ? 'tr' : 'en';
        localStorage.setItem('qw-lang', lang);
        applyLanguage(lang);
    });
}
