const questions = [
    { text: "Do you prefer warm or cold climates?", options: { "Warm": "warm", "Cold": "cold" } },
    { text: "Do you like historical places or modern cities?", options: { "Historical": "historical", "Modern": "modern" } },
    { text: "Are you interested in nature or urban life?", options: { "Nature": "nature", "Urban": "urban" } },
    { text: "Do you prefer a budget-friendly or luxury trip?", options: { "Budget-friendly": "budget", "Luxury": "luxury" } },
    { text: "What kind of food do you like?", options: { "Local": "local", "International": "international" } }
];

// Ülkeleri belirleyen veri yapısı
const countryPreferences = {
    "Germany": ["cold", "modern", "urban", "budget", "international"],
    "Austria": ["cold", "historical", "nature", "luxury", "local"],
    "Belgium": ["cold", "modern", "urban", "budget", "international"],
    "Bulgaria": ["warm", "historical", "nature", "budget", "local"],
    "Czechia": ["cold", "historical", "urban", "budget", "local"],
    "Denmark": ["cold", "modern", "urban", "luxury", "international"],
    "Estonia": ["cold", "historical", "nature", "budget", "local"],
    "Finland": ["cold", "nature", "budget", "local"],
    "France": ["warm", "historical", "urban", "luxury", "international"],
    "Cyprus": ["warm", "historical", "nature", "luxury", "local"],
    "Croatia": ["warm", "historical", "nature", "budget", "local"],
    "Netherlands": ["cold", "modern", "urban", "luxury", "international"],
    "Ireland": ["cold", "historical", "nature", "budget", "local"],
    "Spain": ["warm", "modern", "urban", "luxury", "international"],
    "Sweden": ["cold", "modern", "nature", "budget", "local"],
    "Italy": ["warm", "historical", "urban", "luxury", "local"],
    "Latvia": ["cold", "historical", "nature", "budget", "local"],
    "Lithuania": ["cold", "historical", "nature", "budget", "local"],
    "Luxembourg": ["cold", "modern", "urban", "luxury", "international"],
    "Hungary": ["warm", "historical", "urban", "budget", "local"],
    "Malta": ["warm", "historical", "nature", "luxury", "local"],
    "Poland": ["cold", "historical", "urban", "budget", "local"],
    "Portugal": ["warm", "modern", "urban", "luxury", "local"],
    "Romania": ["cold", "historical", "nature", "budget", "local"],
    "Slovakia": ["cold", "historical", "nature", "budget", "local"],
    "Slovenia": ["cold", "historical", "nature", "budget", "local"],
    "Greece": ["warm", "historical", "urban", "luxury", "local"]
};

let userPreferences = [];
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
    userPreferences = [];

    const firstMessage = document.createElement("div");
    firstMessage.classList.add("message", "bot-message");
    firstMessage.innerHTML = "<p>Hello! I'm your AI travel assistant. I'll ask you a few questions to recommend the perfect destination for you!</p>";
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
        messageDiv.innerHTML = `<p><strong>Question ${currentQuestion + 1}:</strong> ${questionObj.text}</p>`;
        chatMessages.appendChild(messageDiv);

        const buttonsDiv = document.createElement("div");
        buttonsDiv.classList.add("question-options");

        Object.keys(questionObj.options).forEach(option => {
            const button = document.createElement("button");
            button.classList.add("option-btn");
            button.innerText = option;
            button.onclick = () => handleAnswer(questionObj.options[option]);
            buttonsDiv.appendChild(button);
        });

        chatMessages.appendChild(buttonsDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    } else {
        showCountryRecommendation();
    }
}

function handleAnswer(answer) {
    userPreferences.push(answer);

    // Add user's answer to chat
    const chatMessages = document.getElementById("chatMessages");
    const answerDiv = document.createElement("div");
    answerDiv.classList.add("message", "user-message");
    answerDiv.innerHTML = `<p>${Object.keys(questions[currentQuestion].options).find(key => questions[currentQuestion].options[key] === answer)}</p>`;
    chatMessages.appendChild(answerDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    setTimeout(() => {
        showQuestion();
    }, 1000);
}

// En uygun ülkeyi bul ve göster
function showCountryRecommendation() {
    const chatMessages = document.getElementById("chatMessages");

    let bestMatch = "";
    let maxMatches = 0;

    // Kullanıcının tercihlerine en çok uyan ülkeyi bul
    for (const country in countryPreferences) {
        let matches = countryPreferences[country].filter(pref => userPreferences.includes(pref)).length;

        if (matches > maxMatches) {
            maxMatches = matches;
            bestMatch = country;
        }
    }

    const resultMessage = document.createElement("div");
    resultMessage.classList.add("message", "bot-message", "recommendation");
    resultMessage.innerHTML = `
        <p><strong>🎯 Based on your preferences, I recommend:</strong></p>
        <div class="recommended-countries">
            <div class="country-recommendation">
                <h4>${bestMatch}</h4>
                <button class="explore-btn" onclick="exploreCountry('${bestMatch}')">Explore ${bestMatch}</button>
            </div>
        </div>
        <div class="restart-chat">
            <button class="restart-btn" onclick="restartChat()">Start New Recommendation</button>
        </div>
    `;
    chatMessages.appendChild(resultMessage);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function exploreCountry(country) {
    window.location.href = `/country?country=${encodeURIComponent(country)}`;
}

function restartChat() {
    currentQuestion = -1;
    userPreferences = [];
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
        messageDiv.innerHTML = `<p>${message}</p>`;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        input.value = '';
        
        // Show bot response
        setTimeout(() => {
            const botResponse = document.createElement("div");
            botResponse.classList.add("message", "bot-message");
            botResponse.innerHTML = "<p>Please use the option buttons to answer the questions. This helps me provide better recommendations!</p>";
            chatMessages.appendChild(botResponse);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 500);
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
    
    // Auto-start AI chat when page loads
    setTimeout(() => {
        startChat();
    }, 1000);

    initThemeToggle();
    initLanguageToggle();
});

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
        home_title: 'Find your next adventure',
        home_subtitle: 'Discover amazing places, read reviews, and plan your perfect trip',
    },
    tr: {
        nav_home: 'Ana Sayfa', nav_explore: 'Keşfet', nav_reviews: 'Yorumlar', nav_search: 'Ara',
        nav_forum: 'Forum', nav_wishlist: 'İstek Listesi', nav_itineraries: 'Gezi Planlarım',
        nav_profile: 'Profil', nav_admin: 'Yönetim', nav_logout: 'Çıkış Yap', nav_login: 'Giriş Yap', nav_register: 'Kayıt Ol',
        home_title: 'Bir sonraki maceranı keşfet',
        home_subtitle: 'Harika yerler keşfet, yorumları oku ve mükemmel gezini planla',
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