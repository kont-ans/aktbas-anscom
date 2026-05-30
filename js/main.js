// ============ الصفحة الرئيسية - العملات والذهب ============

// تحديث عرض الصفحة الرئيسية
function updateMainDisplay() {
    updateFreeMarketDisplay();
    updateCurrencyCards();
    updateConverter();
    updateLastUpdateTime();
}

// تحديث عرض السوق الحر والبنك المركزي
function updateFreeMarketDisplay() {
    const freeMarketEl = document.getElementById('freeMarketRate');
    const centralBankEl = document.getElementById('centralBankRate');
    const differenceEl = document.getElementById('rateDifference');
    
    if (freeMarketEl) {
        freeMarketEl.textContent = `${formatNumber(APP_STATE.freeMarketRate, 0)} ل.س`;
    }
    
    if (centralBankEl) {
        centralBankEl.textContent = `${formatNumber(APP_STATE.centralBankRate, 0)} ل.س`;
    }
    
    if (differenceEl) {
        const diff = APP_STATE.freeMarketRate - APP_STATE.centralBankRate;
        const diffPercent = ((diff / APP_STATE.centralBankRate) * 100).toFixed(1);
        differenceEl.textContent = `${formatNumber(diff, 0)} ل.س (${diffPercent}%)`;
    }
}

// تحديث بطاقات العملات
function updateCurrencyCards() {
    const currencies = ['USD', 'EUR', 'GBP'];
    
    currencies.forEach(currency => {
        const marketRate = APP_STATE.freeMarketRate / (APP_STATE.exchangeRates[currency] || 1);
        const bankRate = APP_STATE.centralBankRate / (APP_STATE.exchangeRates[currency] || 1);
        const diff = marketRate - bankRate;
        
        // تحديث السعر الرئيسي
        const marketEl = document.getElementById(`${currency.toLowerCase()}MarketRate`);
        if (marketEl) {
            marketEl.innerHTML = `${formatNumber(marketRate)} <span style="font-size:16px;color:var(--text-secondary);">ل.س</span>`;
        }
        
        // تحديث أسعار السوق والبنك
        const freeEl = document.getElementById(`${currency.toLowerCase()}Free`);
        const bankEl = document.getElementById(`${currency.toLowerCase()}Bank`);
        
        if (freeEl) freeEl.textContent = formatNumber(marketRate);
        if (bankEl) bankEl.textContent = formatNumber(bankRate);
        
        // تحديث نسبة التغير
        const changeEl = document.getElementById(`${currency.toLowerCase()}Change`);
        if (changeEl) {
            const direction = getChangeDirection(marketRate, bankRate);
            changeEl.textContent = `الفرق: ${formatNumber(diff)} ل.س (${getChangeArrow(direction)})`;
            changeEl.className = `rate-change ${direction}`;
        }
    });
}

// تحديث المحول
function updateConverter() {
    const fromCurrency = document.getElementById('fromCurrency')?.value;
    const toCurrency = document.getElementById('toCurrency')?.value;
    const fromAmount = parseFloat(document.getElementById('fromAmount')?.value) || 0;
    
    if (!fromCurrency || !toCurrency) return;
    
    let rate;
    
    if (fromCurrency === 'SYP' && toCurrency === 'SYP') {
        rate = 1;
    } else if (fromCurrency === 'SYP') {
        rate = 1 / (APP_STATE.exchangeRates[toCurrency] * APP_STATE.freeMarketRate);
    } else if (toCurrency === 'SYP') {
        rate = (APP_STATE.exchangeRates[fromCurrency] || 1) * APP_STATE.freeMarketRate;
    } else {
        const fromRate = APP_STATE.exchangeRates[fromCurrency] || 1;
        const toRate = APP_STATE.exchangeRates[toCurrency] || 1;
        rate = toRate / fromRate;
    }
    
    const result = fromAmount * rate;
    
    const toAmountEl = document.getElementById('toAmount');
    const resultEl = document.getElementById('conversionResult');
    
    if (toAmountEl) {
        toAmountEl.value = result.toFixed(2);
    }
    
    if (resultEl) {
        const fromName = APP_CONFIG.currencies[fromCurrency]?.name || fromCurrency;
        const toName = APP_CONFIG.currencies[toCurrency]?.name || toCurrency;
        resultEl.textContent = `${formatNumber(fromAmount)} ${fromName} = ${formatNumber(result)} ${toName}`;
    }
}

// تبديل العملات
function swapCurrencies() {
    const fromSelect = document.getElementById('fromCurrency');
    const toSelect = document.getElementById('toCurrency');
    
    if (fromSelect && toSelect) {
        const temp = fromSelect.value;
        fromSelect.value = toSelect.value;
        toSelect.value = temp;
        updateConverter();
    }
}

// تعيين المبلغ
function setAmount(amount) {
    const fromAmount = document.getElementById('fromAmount');
    if (fromAmount) {
        fromAmount.value = amount;
        updateConverter();
    }
}

// تحديث وقت آخر تحديث
function updateLastUpdateTime() {
    const lastUpdateEl = document.getElementById('lastUpdate');
    if (lastUpdateEl && APP_STATE.lastUpdate) {
        lastUpdateEl.textContent = new Date(APP_STATE.lastUpdate).toLocaleString('ar-SY');
    }
}

// تحديث جميع البيانات
async function refreshAllData() {
    const mainContainer = document.querySelector('.main-container');
    if (mainContainer) mainContainer.classList.add('loading');
    
    try {
        await Promise.all([
            fetchExchangeRates(),
            fetchGoldPrices(),
            fetchCryptoPrices(),
        ]);
        
        updateMainDisplay();
        updateTicker();
        
        showNotification('تم تحديث جميع الأسعار بنجاح ✅');
    } catch (error) {
        console.error('خطأ في التحديث:', error);
        showNotification('حدث خطأ في تحديث البيانات ❌');
    } finally {
        if (mainContainer) mainContainer.classList.remove('loading');
    }
}

// تهيئة الصفحة الرئيسية
async function initMainPage() {
    console.log('📄 تهيئة الصفحة الرئيسية...');
    
    // تحميل الحالة المحفوظة
    loadAppState();
    
    // تعيين القيم الافتراضية إذا لزم الأمر
    if (Object.keys(APP_STATE.exchangeRates).length === 0) {
        setDefaultRates();
    }
    
    if (Object.keys(APP_STATE.goldPrices).length === 0) {
        APP_STATE.goldPrices = {
            gold: APP_CONFIG.defaults.goldPerOunce,
            silver: APP_CONFIG.defaults.silverPerOunce,
        };
    }
    
    if (Object.keys(APP_STATE.cryptoPrices).length === 0) {
        setDefaultCryptoPrices();
    }
    
    // تحديث العرض الأولي
    updateMainDisplay();
    updateTicker();
    
    // جلب البيانات الحية
    await Promise.all([
        fetchExchangeRates(),
        fetchGoldPrices(),
        fetchCryptoPrices(),
    ]);
    
    updateMainDisplay();
    updateTicker();
    
    // إعداد المستمعين
    setupMainEventListeners();
    
    // تحديث دوري
    setInterval(async () => {
        await Promise.all([
            fetchExchangeRates(),
            fetchGoldPrices(),
            fetchCryptoPrices(),
        ]);
        updateMainDisplay();
        updateTicker();
    }, APP_CONFIG.api.refreshInterval);
    
    // تحديث الشريط كل دقيقة
    setInterval(updateTicker, 60000);
    
    console.log('✅ الصفحة الرئيسية جاهزة');
}

// إعداد مستمعي الأحداث
function setupMainEventListeners() {
    const fromAmount = document.getElementById('fromAmount');
    const fromCurrency = document.getElementById('fromCurrency');
    const toCurrency = document.getElementById('toCurrency');
    
    if (fromAmount) {
        fromAmount.addEventListener('input', updateConverter);
        fromAmount.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') updateConverter();
        });
    }
    
    if (fromCurrency) fromCurrency.addEventListener('change', updateConverter);
    if (toCurrency) toCurrency.addEventListener('change', updateConverter);
}

// بدء التطبيق عند تحميل الصفحة
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMainPage);
} else {
    initMainPage();
}