// ============ صفحة الأسهم والعملات الرقمية ============

// بيانات الأسهم
const stocksData = {
    TSLA: {
        name: 'تسلا',
        symbol: 'TSLA',
        basePrice: 245,
        marketCapBase: 780000000000,
        elementIds: {
            price: 'tslaPrice',
            change: 'tslaChange',
            marketCap: 'tslaMarketCap',
            volume: 'tslaVolume',
            range: 'tslaRange',
            chart: 'tslaChart',
        },
    },
    AAPL: {
        name: 'آبل',
        symbol: 'AAPL',
        basePrice: 178,
        marketCapBase: 2800000000000,
        elementIds: {
            price: 'aaplPrice',
            change: 'aaplChange',
            marketCap: 'aaplMarketCap',
            volume: 'aaplVolume',
            range: 'aaplRange',
            chart: 'aaplChart',
        },
    },
    MSFT: {
        name: 'مايكروسوفت',
        symbol: 'MSFT',
        basePrice: 380,
        marketCapBase: 2900000000000,
        elementIds: {
            price: 'msftPrice',
            change: 'msftChange',
            marketCap: 'msftMarketCap',
            volume: 'msftVolume',
            range: 'msftRange',
            chart: 'msftChart',
        },
    },
    GOOGL: {
        name: 'غوغل',
        symbol: 'GOOGL',
        basePrice: 142,
        marketCapBase: 1800000000000,
        elementIds: {
            price: 'googlPrice',
            change: 'googlChange',
            marketCap: 'googlMarketCap',
            volume: 'googlVolume',
            range: 'googlRange',
            chart: 'googlChart',
        },
    },
    XRP: {
        name: 'ريبل',
        symbol: 'XRP',
        basePrice: 0.62,
        marketCapBase: 34000000000,
        elementIds: {
            price: 'xrpPrice',
            change: 'xrpChange',
            marketCap: 'xrpMarketCap',
            volume: 'xrpVolume',
            ath: 'xrpAth',
            chart: 'xrpChart',
        },
    },
};

// بيانات العملات الرقمية
const cryptoConfig = {
    btc: { name: 'بيتكوين', symbol: 'BTC', elementIds: { price: 'btcPrice', change: 'btcChange', marketCap: 'btcMarketCap', volume: 'btcVolume' } },
    eth: { name: 'إيثيريوم', symbol: 'ETH', elementIds: { price: 'ethPrice', change: 'ethChange', marketCap: 'ethMarketCap', volume: 'ethVolume' } },
    bnb: { name: 'بينانس كوين', symbol: 'BNB', elementIds: { price: 'bnbPrice', change: 'bnbChange', marketCap: 'bnbMarketCap', volume: 'bnbVolume' } },
    usdt: { name: 'تيثر', symbol: 'USDT', elementIds: { price: 'usdtPrice', change: 'usdtChange', marketCap: 'usdtMarketCap', volume: 'usdtVolume' } },
};

// الأسعار الحالية
let currentStockPrices = {};

// توليد أسعار الأسهم
function generateStockPrices() {
    const prices = {};
    
    for (const [symbol, data] of Object.entries(stocksData)) {
        const change = (Math.random() - 0.5) * data.basePrice * 0.06;
        const price = data.basePrice + change;
        
        prices[symbol] = {
            price: price,
            change: change,
            changePercent: (change / data.basePrice) * 100,
            marketCap: data.marketCapBase * (price / data.basePrice),
            volume: Math.floor(Math.random() * 50000000) + 10000000,
            high: price + Math.abs(change) * 0.5,
            low: price - Math.abs(change) * 0.5,
        };
    }
    
    // سبيس إكس
    prices.SPACEX = {
        valuation: 180000000000 + Math.random() * 20000000000,
        funding: '2.5 مليار دولار',
        launches: 98 + Math.floor(Math.random() * 5),
    };
    
    currentStockPrices = prices;
    return prices;
}

// تحديث عرض الأسهم
function updateStocksDisplay() {
    const prices = currentStockPrices;
    
    for (const [symbol, data] of Object.entries(stocksData)) {
        const stockData = prices[symbol];
        if (!stockData) continue;
        
        const direction = getChangeDirection(stockData.price, data.basePrice);
        const changeClass = getChangeClass(direction);
        
        // تحديث السعر
        updateStockElement(data.elementIds.price, `$${formatNumber(stockData.price)}`);
        
        // تحديث التغير
        updateStockElement(data.elementIds.change, 
            `${getChangeArrow(direction)} ${formatNumber(Math.abs(stockData.change))} (${formatNumber(Math.abs(stockData.changePercent))}%)`,
            `stock-change ${changeClass}`
        );
        
        // تحديث التفاصيل
        updateStockElement(data.elementIds.marketCap, formatMarketCap(stockData.marketCap));
        updateStockElement(data.elementIds.volume, formatVolume(stockData.volume));
        updateStockElement(data.elementIds.range, 
            `$${formatNumber(stockData.low)} - $${formatNumber(stockData.high)}`);
    }
    
    // تحديث سبيس إكس
    if (prices.SPACEX) {
        updateStockElement('spacexPrice', `$${formatNumber(prices.SPACEX.valuation / 1000000000)}B`);
        updateStockElement('spacexChange', 'شركة خاصة');
        updateStockElement('spacexValuation', `$${formatNumber(prices.SPACEX.valuation / 1000000000, 1)} مليار`);
        updateStockElement('spacexFunding', prices.SPACEX.funding);
        updateStockElement('spacexLaunches', prices.SPACEX.launches);
    }
    
    // تحديث العملات الرقمية
    updateCryptoDisplay();
    
    // تحديث الجدول
    updateStocksTable();
    updateLastUpdateTime();
}

// تحديث العملات الرقمية
function updateCryptoDisplay() {
    for (const [key, config] of Object.entries(cryptoConfig)) {
        const cryptoData = APP_STATE.cryptoPrices[key];
        if (!cryptoData) continue;
        
        const direction = cryptoData.change > 0 ? 'up' : cryptoData.change < 0 ? 'down' : 'stable';
        const changeClass = getChangeClass(direction);
        
        updateStockElement(config.elementIds.price, `$${formatNumber(cryptoData.price)}`);
        updateStockElement(config.elementIds.change, 
            `${getChangeArrow(direction)} ${formatNumber(Math.abs(cryptoData.change), 2)}%`,
            `crypto-change ${changeClass}`
        );
        updateStockElement(config.elementIds.marketCap, formatMarketCap(cryptoData.marketCap));
        updateStockElement(config.elementIds.volume, formatVolume(cryptoData.volume));
    }
}

// تحديث عنصر السهم
function updateStockElement(id, text, className = null) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = text;
        if (className) el.className = className;
    }
}

// تنسيق القيمة السوقية
function formatMarketCap(cap) {
    if (!cap) return '--';
    if (cap >= 1e12) return `$${formatNumber(cap / 1e12, 2)}T`;
    if (cap >= 1e9) return `$${formatNumber(cap / 1e9, 2)}B`;
    if (cap >= 1e6) return `$${formatNumber(cap / 1e6, 2)}M`;
    return `$${formatNumber(cap)}`;
}

// تنسيق حجم التداول
function formatVolume(vol) {
    if (!vol) return '--';
    if (vol >= 1e9) return `${formatNumber(vol / 1e9, 2)}B`;
    if (vol >= 1e6) return `${formatNumber(vol / 1e6, 2)}M`;
    return formatNumber(vol);
}

// تحديث جدول الأسهم
function updateStocksTable() {
    const tbody = document.getElementById('stocksTableBody');
    if (!tbody) return;
    
    const rows = [];
    
    // الأسهم
    for (const [symbol, data] of Object.entries(stocksData)) {
        const stockData = currentStockPrices[symbol];
        if (!stockData) continue;
        
        const sign = stockData.change >= 0 ? '+' : '';
        const color = stockData.change >= 0 ? 'var(--success)' : 'var(--danger)';
        
        rows.push(`
            <tr>
                <td>${data.name}</td>
                <td>${symbol}</td>
                <td>$${formatNumber(stockData.price)}</td>
                <td style="color: ${color};">${sign}${formatNumber(stockData.change)}</td>
                <td style="color: ${color};">${sign}${formatNumber(stockData.changePercent)}%</td>
                <td>${formatMarketCap(stockData.marketCap)}</td>
            </tr>
        `);
    }
    
    // العملات الرقمية
    for (const [key, config] of Object.entries(cryptoConfig)) {
        const cryptoData = APP_STATE.cryptoPrices[key];
        if (!cryptoData) continue;
        
        const sign = cryptoData.change >= 0 ? '+' : '';
        const color = cryptoData.change >= 0 ? 'var(--success)' : 'var(--danger)';
        
        rows.push(`
            <tr>
                <td>🪙 ${config.name}</td>
                <td>${config.symbol}</td>
                <td>$${formatNumber(cryptoData.price)}</td>
                <td style="color: ${color};">${sign}${formatNumber(cryptoData.change, 2)}%</td>
                <td style="color: ${color};">${sign}${formatNumber(cryptoData.change, 2)}%</td>
                <td>${formatMarketCap(cryptoData.marketCap)}</td>
            </tr>
        `);
    }
    
    tbody.innerHTML = rows.join('');
}

// تحديث الأسهم
async function refreshStocks() {
    const container = document.querySelector('.main-container');
    if (container) container.classList.add('loading');
    
    try {
        generateStockPrices();
        await fetchCryptoPrices();
        updateStocksDisplay();
        updateTicker();
        showNotification('تم تحديث أسعار الأسهم ✅');
    } catch (error) {
        console.error('خطأ في تحديث الأسهم:', error);
        showNotification('حدث خطأ في تحديث البيانات ❌');
    } finally {
        if (container) container.classList.remove('loading');
    }
}

// تهيئة صفحة الأسهم
async function initStocksPage() {
    console.log('📈 تهيئة صفحة الأسهم...');
    
    loadAppState();
    
    if (Object.keys(APP_STATE.cryptoPrices).length === 0) {
        setDefaultCryptoPrices();
    }
    
    generateStockPrices();
    await fetchCryptoPrices();
    updateStocksDisplay();
    updateTicker();
    
    // تحديث دوري
    setInterval(async () => {
        generateStockPrices();
        await fetchCryptoPrices();
        updateStocksDisplay();
        updateTicker();
    }, APP_CONFIG.api.refreshInterval);
    
    console.log('✅ صفحة الأسهم جاهزة');
}

// بدء الصفحة
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStocksPage);
} else {
    initStocksPage();
}