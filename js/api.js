// ============ وظائف جلب البيانات من APIs ============

// جلب أسعار الصرف
async function fetchExchangeRates() {
    try {
        const response = await fetch(APP_CONFIG.api.exchangeRate);
        if (!response.ok) throw new Error('فشل في جلب أسعار الصرف');
        
        const data = await response.json();
        APP_STATE.exchangeRates = data.rates;
        APP_STATE.exchangeRates.USD = 1;
        
        // محاكاة سعر السوق الحر (في الواقع يمكن استخدام API خاص)
        APP_STATE.freeMarketRate = 14500 + Math.floor(Math.random() * 1500);
        APP_STATE.centralBankRate = APP_CONFIG.defaults.centralBankUSD;
        
        if (!APP_STATE.exchangeRates.SYP) {
            APP_STATE.exchangeRates.SYP = APP_STATE.freeMarketRate;
        }
        
        APP_STATE.lastUpdate = new Date().toISOString();
        saveAppState();
        
        console.log('✅ تم تحديث أسعار الصرف');
        return true;
    } catch (error) {
        console.error('❌ خطأ في جلب أسعار الصرف:', error);
        loadAppState();
        
        if (Object.keys(APP_STATE.exchangeRates).length === 0) {
            setDefaultRates();
        }
        return false;
    }
}

// جلب أسعار الذهب والفضة
async function fetchGoldPrices() {
    try {
        const response = await fetch(APP_CONFIG.api.metalPrice);
        if (response.ok) {
            const data = await response.json();
            APP_STATE.goldPrices = {
                gold: data.rates.XAU ? (1 / data.rates.XAU) : APP_CONFIG.defaults.goldPerOunce,
                silver: data.rates.XAG ? (1 / data.rates.XAG) : APP_CONFIG.defaults.silverPerOunce,
            };
        } else {
            throw new Error('API غير متاح');
        }
    } catch (error) {
        console.log('⚠️ استخدام أسعار الذهب والفضة المحلية');
        APP_STATE.goldPrices = {
            gold: APP_CONFIG.defaults.goldPerOunce + (Math.random() - 0.5) * 100,
            silver: APP_CONFIG.defaults.silverPerOunce + (Math.random() - 0.5) * 5,
        };
    }
    
    saveAppState();
    return APP_STATE.goldPrices;
}

// جلب أسعار العملات الرقمية
async function fetchCryptoPrices() {
    try {
        const response = await fetch(
            `${APP_CONFIG.api.cryptoPrice}?ids=bitcoin,ethereum,binancecoin,ripple,tether&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true`
        );
        
        if (response.ok) {
            const data = await response.json();
            APP_STATE.cryptoPrices = {
                btc: {
                    price: data.bitcoin.usd,
                    marketCap: data.bitcoin.usd_market_cap,
                    volume: data.bitcoin.usd_24h_vol,
                    change: data.bitcoin.usd_24h_change,
                },
                eth: {
                    price: data.ethereum.usd,
                    marketCap: data.ethereum.usd_market_cap,
                    volume: data.ethereum.usd_24h_vol,
                    change: data.ethereum.usd_24h_change,
                },
                bnb: {
                    price: data.binancecoin.usd,
                    marketCap: data.binancecoin.usd_market_cap,
                    volume: data.binancecoin.usd_24h_vol,
                    change: data.binancecoin.usd_24h_change,
                },
                xrp: {
                    price: data.ripple.usd,
                    marketCap: data.ripple.usd_market_cap,
                    volume: data.ripple.usd_24h_vol,
                    change: data.ripple.usd_24h_change,
                },
                usdt: {
                    price: data.tether.usd,
                    marketCap: data.tether.usd_market_cap,
                    volume: data.tether.usd_24h_vol,
                    change: data.tether.usd_24h_change || 0,
                },
            };
        }
    } catch (error) {
        console.log('⚠️ استخدام أسعار العملات الرقمية المحلية');
        setDefaultCryptoPrices();
    }
    
    return APP_STATE.cryptoPrices;
}

// جلب أسعار الأسهم (محاكاة)
async function fetchStockPrices() {
    // في الإصدار الحقيقي، استخدم API مثل Alpha Vantage أو Yahoo Finance
    const stocks = {
        TSLA: { base: 245, name: 'تسلا' },
        AAPL: { base: 178, name: 'آبل' },
        MSFT: { base: 380, name: 'مايكروسوفت' },
        GOOGL: { base: 142, name: 'غوغل' },
        XRP: { base: 0.62, name: 'ريبل' },
    };
    
    const result = {};
    
    for (const [symbol, data] of Object.entries(stocks)) {
        const change = (Math.random() - 0.5) * data.base * 0.05;
        result[symbol] = {
            price: data.base + change,
            change: change,
            changePercent: (change / data.base) * 100,
            name: data.name,
        };
    }
    
    // سبيس إكس (شركة خاصة - تقييم تقديري)
    result.SPACEX = {
        price: 180 + Math.random() * 20,
        valuation: 180000000000,
        funding: '2.5 مليار دولار',
        launches: 98,
    };
    
    return result;
}

// تعيين الأسعار الافتراضية
function setDefaultRates() {
    APP_STATE.exchangeRates = {
        USD: 1,
        EUR: 0.92,
        GBP: 0.79,
        SYP: APP_CONFIG.defaults.freeMarketUSD,
        SAR: 3.75,
        AED: 3.67,
        TRY: 30.5,
        IQD: 1310,
        JOD: 0.71,
        EGP: 47.5,
    };
}

function setDefaultCryptoPrices() {
    APP_STATE.cryptoPrices = {
        btc: { price: 43000 + Math.random() * 2000, marketCap: 850000000000, volume: 25000000000, change: 0 },
        eth: { price: 2300 + Math.random() * 200, marketCap: 280000000000, volume: 15000000000, change: 0 },
        bnb: { price: 310 + Math.random() * 20, marketCap: 48000000000, volume: 2000000000, change: 0 },
        xrp: { price: 0.62, marketCap: 34000000000, volume: 1500000000, change: 0 },
        usdt: { price: 1.00, marketCap: 95000000000, volume: 50000000000, change: 0 },
    };
}

// تحديث شريط الأخبار
function updateTicker() {
    const ticker = document.getElementById('tickerContent');
    if (!ticker) return;
    
    const now = new Date();
    const dateStr = now.toLocaleDateString('ar-SY', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
    });
    
    const goldPriceSYP = (APP_STATE.goldPrices.gold * APP_STATE.freeMarketRate).toFixed(0);
    const silverPriceSYP = (APP_STATE.goldPrices.silver * APP_STATE.freeMarketRate).toFixed(0);
    
    const tickerHTML = `
        <div class="ticker-item">
            <span class="ticker-label">📅</span>
            <span class="ticker-date">${dateStr}</span>
        </div>
        <div class="ticker-item">
            <span class="ticker-label">🥇 ذهب:</span>
            <span class="ticker-value gold-price">${formatNumber(APP_STATE.goldPrices.gold)}$ | ${formatNumber(goldPriceSYP, 0)} ل.س</span>
        </div>
        <div class="ticker-item">
            <span class="ticker-label">🥈 فضة:</span>
            <span class="ticker-value silver-price">${formatNumber(APP_STATE.goldPrices.silver)}$ | ${formatNumber(silverPriceSYP, 0)} ل.س</span>
        </div>
        <div class="ticker-item">
            <span class="ticker-label">💵 سوق حر:</span>
            <span class="ticker-value" style="color:var(--warning);">${formatNumber(APP_STATE.freeMarketRate, 0)} ل.س</span>
        </div>
        <div class="ticker-item">
            <span class="ticker-label">🏦 بنك مركزي:</span>
            <span class="ticker-value" style="color:var(--info);">${formatNumber(APP_STATE.centralBankRate, 0)} ل.س</span>
        </div>
        <div class="ticker-item">
            <span class="ticker-label">₿ بيتكوين:</span>
            <span class="ticker-value" style="color:#f7931a;">${APP_STATE.cryptoPrices.btc ? formatNumber(APP_STATE.cryptoPrices.btc.price, 0) : '--'}$</span>
        </div>
    `;
    
    ticker.innerHTML = tickerHTML + tickerHTML;
}

console.log('🔌 وحدة API جاهزة');