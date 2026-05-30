// ============ صفحة السلع والنفط ============

// بيانات السلع مع الأسعار الأساسية
const commoditiesData = {
    oil: {
        name: 'النفط الخام (برنت)',
        icon: '🛢️',
        unit: 'برميل',
        basePrice: APP_CONFIG.defaults.oilPerBarrel,
        elementIds: {
            price: 'oilPrice',
            trend: 'oilTrend',
            change: 'oilChange',
            changePercent: 'oilChangePercent',
            chart: 'oilChart',
        },
    },
    gas: {
        name: 'الغاز الطبيعي',
        icon: '🔥',
        unit: 'MMBtu',
        basePrice: APP_CONFIG.defaults.gasPerMMBtu,
        elementIds: {
            price: 'gasPrice',
            trend: 'gasTrend',
            change: 'gasChange',
            changePercent: 'gasChangePercent',
            chart: 'gasChart',
        },
    },
    diesel: {
        name: 'المازوت (الديزل)',
        icon: '⛽',
        unit: 'لتر',
        basePrice: APP_CONFIG.defaults.dieselPerLiter,
        elementIds: {
            price: 'dieselPrice',
            trend: 'dieselTrend',
            local: 'dieselLocal',
            global: 'dieselGlobal',
        },
    },
    wheat: {
        name: 'القمح (الحنطة)',
        icon: '🌾',
        unit: 'طن',
        basePrice: APP_CONFIG.defaults.wheatPerTon,
        elementIds: {
            price: 'wheatPrice',
            trend: 'wheatTrend',
            ton: 'wheatTon',
            kg: 'wheatKg',
        },
    },
    barley: {
        name: 'الشعير',
        icon: '🌿',
        unit: 'طن',
        basePrice: APP_CONFIG.defaults.barleyPerTon,
        elementIds: {
            price: 'barleyPrice',
            trend: 'barleyTrend',
            ton: 'barleyTon',
            kg: 'barleyKg',
        },
    },
};

// الأسعار الحالية
let currentCommodityPrices = {};

// توليد أسعار السلع
function generateCommodityPrices() {
    const prices = {};
    
    for (const [key, commodity] of Object.entries(commoditiesData)) {
        const volatility = commodity.basePrice * 0.03; // 3% تقلب
        prices[key] = commodity.basePrice + (Math.random() - 0.5) * volatility * 2;
    }
    
    currentCommodityPrices = prices;
    return prices;
}

// تحديث عرض السلع
function updateCommoditiesDisplay() {
    const prices = currentCommodityPrices;
    
    for (const [key, commodity] of Object.entries(commoditiesData)) {
        const price = prices[key];
        if (price === undefined) continue;
        
        const change = price - commodity.basePrice;
        const changePercent = (change / commodity.basePrice) * 100;
        const direction = getChangeDirection(price, commodity.basePrice);
        
        // تحديث السعر
        updateElement(commodity.elementIds.price, `$${formatNumber(price)}`);
        
        // تحديث الاتجاه
        updateElement(commodity.elementIds.trend, 
            `${direction === 'up' ? '📈' : direction === 'down' ? '📉' : '📊'} ${
                direction === 'up' ? 'ارتفاع' : direction === 'down' ? 'انخفاض' : 'مستقر'
            }`,
            `trend-indicator trend-${direction}`
        );
        
        // تحديث التغير
        updateElement(commodity.elementIds.change, 
            `${change >= 0 ? '+' : ''}${formatNumber(change)}`);
        updateElement(commodity.elementIds.changePercent, 
            `${change >= 0 ? '+' : ''}${formatNumber(changePercent)}%`);
        
        // تحديثات خاصة
        if (key === 'diesel') {
            updateElement(commodity.elementIds.local, 
                `${formatNumber(price * APP_STATE.freeMarketRate, 0)} ل.س`);
            updateElement(commodity.elementIds.global, `$${formatNumber(price)}`);
        }
        
        if (key === 'wheat' || key === 'barley') {
            updateElement(commodity.elementIds.ton, `$${formatNumber(price)}`);
            updateElement(commodity.elementIds.kg, `$${formatNumber(price / 1000, 3)}`);
        }
    }
    
    // تحديث الجدول
    updateCommoditiesTable();
    updateLastUpdateTime();
}

// تحديث عنصر في DOM
function updateElement(id, text, className = null) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = text;
        if (className) el.className = className;
    }
}

// تحديث جدول السلع
function updateCommoditiesTable() {
    const tbody = document.getElementById('priceTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = Object.entries(commoditiesData).map(([key, commodity]) => {
        const price = currentCommodityPrices[key];
        if (price === undefined) return '';
        
        const change = price - commodity.basePrice;
        const changePercent = (change / commodity.basePrice) * 100;
        const sign = change >= 0 ? '+' : '';
        const color = change >= 0 ? 'var(--success)' : 'var(--danger)';
        
        return `
            <tr>
                <td>${commodity.icon} ${commodity.name}</td>
                <td>$${formatNumber(price)} / ${commodity.unit}</td>
                <td style="color: ${color};">${sign}${formatNumber(change)}</td>
                <td style="color: ${color};">${sign}${formatNumber(changePercent)}%</td>
                <td>${new Date().toLocaleTimeString('ar-SY')}</td>
            </tr>
        `;
    }).join('');
}

// تحديث بيانات السلع
async function refreshCommodities() {
    const container = document.querySelector('.main-container');
    if (container) container.classList.add('loading');
    
    try {
        generateCommodityPrices();
        updateCommoditiesDisplay();
        updateTicker();
        showNotification('تم تحديث أسعار السلع ✅');
    } catch (error) {
        console.error('خطأ في تحديث السلع:', error);
        showNotification('حدث خطأ في تحديث البيانات ❌');
    } finally {
        if (container) container.classList.remove('loading');
    }
}

// تهيئة صفحة السلع
function initCommoditiesPage() {
    console.log('🛢️ تهيئة صفحة السلع...');
    
    loadAppState();
    generateCommodityPrices();
    updateCommoditiesDisplay();
    updateTicker();
    
    // تحديث دوري
    setInterval(() => {
        generateCommodityPrices();
        updateCommoditiesDisplay();
        updateTicker();
    }, APP_CONFIG.api.refreshInterval);
    
    console.log('✅ صفحة السلع جاهزة');
}

// بدء الصفحة
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCommoditiesPage);
} else {
    initCommoditiesPage();
}