// ============ إعدادات التطبيق ============
const APP_CONFIG = {
    // اسم التطبيق
    appName: 'الأسواق السورية',
    version: '2.0.0',
    
    // إعدادات API
    api: {
        exchangeRate: 'https://api.exchangerate-api.com/v4/latest/USD',
        metalPrice: 'https://api.metalpriceapi.com/v1/latest?api_key=demo&base=USD&currencies=XAU,XAG',
        cryptoPrice: 'https://api.coingecko.com/api/v3/simple/price',
        refreshInterval: 300000, // 5 دقائق
    },
    
    // أسعار افتراضية
    defaults: {
        freeMarketUSD: 15000,
        centralBankUSD: 12500,
        goldPerOunce: 2000,
        silverPerOunce: 24,
        oilPerBarrel: 82.5,
        gasPerMMBtu: 2.8,
        dieselPerLiter: 0.85,
        wheatPerTon: 280,
        barleyPerTon: 210,
    },
    
    // العملات المدعومة
    currencies: {
        USD: { name: 'الدولار الأمريكي', flag: '🇺🇸', symbol: '$' },
        EUR: { name: 'اليورو', flag: '🇪🇺', symbol: '€' },
        GBP: { name: 'الجنيه الإسترليني', flag: '🇬🇧', symbol: '£' },
        SYP: { name: 'الليرة السورية', flag: '🇸🇾', symbol: 'ل.س' },
        SAR: { name: 'الريال السعودي', flag: '🇸🇦', symbol: 'ر.س' },
        AED: { name: 'الدرهم الإماراتي', flag: '🇦🇪', symbol: 'د.إ' },
        TRY: { name: 'الليرة التركية', flag: '🇹🇷', symbol: '₺' },
        IQD: { name: 'الدينار العراقي', flag: '🇮🇶', symbol: 'ع.د' },
        JOD: { name: 'الدينار الأردني', flag: '🇯🇴', symbol: 'د.أ' },
        EGP: { name: 'الجنيه المصري', flag: '🇪🇬', symbol: 'ج.م' },
    },
};

// ============ حالة التطبيق ============
const APP_STATE = {
    exchangeRates: {},
    goldPrices: {},
    cryptoPrices: {},
    freeMarketRate: APP_CONFIG.defaults.freeMarketUSD,
    centralBankRate: APP_CONFIG.defaults.centralBankUSD,
    lastUpdate: null,
    isOnline: navigator.onLine,
};

// ============ وظائف مساعدة ============
function formatNumber(num, decimals = 2) {
    return Number(num).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

function formatCurrency(amount, symbol = '$') {
    return `${symbol}${formatNumber(amount)}`;
}

function getChangeDirection(current, previous) {
    if (current > previous) return 'up';
    if (current < previous) return 'down';
    return 'stable';
}

function getChangeArrow(direction) {
    switch (direction) {
        case 'up': return '▲';
        case 'down': return '▼';
        default: return '■';
    }
}

function getChangeClass(direction) {
    switch (direction) {
        case 'up': return 'positive';
        case 'down': return 'negative';
        default: return '';
    }
}

// ============ إدارة التخزين المحلي ============
function saveToStorage(key, data) {
    try {
        localStorage.setItem(key, JSON.stringify(data));
    } catch (e) {
        console.warn('تعذر الحفظ في التخزين المحلي:', e);
    }
}

function loadFromStorage(key) {
    try {
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : null;
    } catch (e) {
        console.warn('تعذر التحميل من التخزين المحلي:', e);
        return null;
    }
}

function saveAppState() {
    saveToStorage('app_state', {
        exchangeRates: APP_STATE.exchangeRates,
        goldPrices: APP_STATE.goldPrices,
        freeMarketRate: APP_STATE.freeMarketRate,
        centralBankRate: APP_STATE.centralBankRate,
        lastUpdate: APP_STATE.lastUpdate,
    });
}

function loadAppState() {
    const saved = loadFromStorage('app_state');
    if (saved) {
        APP_STATE.exchangeRates = saved.exchangeRates || {};
        APP_STATE.goldPrices = saved.goldPrices || {};
        APP_STATE.freeMarketRate = saved.freeMarketRate || APP_CONFIG.defaults.freeMarketUSD;
        APP_STATE.centralBankRate = saved.centralBankRate || APP_CONFIG.defaults.centralBankUSD;
        APP_STATE.lastUpdate = saved.lastUpdate;
    }
}

// ============ إشعارات المستخدم ============
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--surface-light);
        color: var(--text);
        padding: 14px 28px;
        border-radius: 30px;
        border: 1px solid var(--gold);
        z-index: 9999;
        animation: slideUp 0.3s ease-out;
        font-size: 14px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideDown 0.3s ease-in';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// إضافة أنماط الإشعارات
const notificationStyles = document.createElement('style');
notificationStyles.textContent = `
    @keyframes slideUp {
        from { transform: translate(-50%, 20px); opacity: 0; }
        to { transform: translate(-50%, 0); opacity: 1; }
    }
    @keyframes slideDown {
        from { transform: translate(-50%, 0); opacity: 1; }
        to { transform: translate(-50%, 20px); opacity: 0; }
    }
`;
document.head.appendChild(notificationStyles);

// ============ مراقبة الاتصال ============
window.addEventListener('online', () => {
    APP_STATE.isOnline = true;
    showNotification('تم استعادة الاتصال بالإنترنت ✅');
});

window.addEventListener('offline', () => {
    APP_STATE.isOnline = false;
    showNotification('انقطع الاتصال بالإنترنت ⚠️');
});

console.log('🚀 إعدادات التطبيق جاهزة | الإصدار:', APP_CONFIG.version);