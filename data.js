// حفظ في ملف data.js
const ans_data = {
    users: [],
    quotes: [],
    notifications: []
};

// تهيئة البيانات إذا كانت فارغة
function initData() {
    if (!localStorage.getItem('ans_users')) {
        const sampleUsers = [
            {
                id: 1,
                name: "أحمد الحكيم",
                username: "ahmed_hakim",
                email: "ahmed@example.com",
                password: "123456", // في الواقع يجب تشفيرها
                avatar: "https://ui-avatars.com/api/?name=أحمد&background=7B68EE&color=fff",
                bio: "محب للحكمة والأدب",
                followers: 1245,
                following: 543,
                posts: 67,
                likes: 4567,
                joinDate: "2023-01-15"
            }
        ];
        localStorage.setItem('ans_users', JSON.stringify(sampleUsers));
    }
    
    if (!localStorage.getItem('ans_quotes')) {
        // بيانات الاقتباسات
    }
    
    if (!localStorage.getItem('ans_stats')) {
        const stats = {
            quotes: 15842,
            users: 8456,
            likes: 124589,
            shares: 45231
        };
        localStorage.setItem('ans_stats', JSON.stringify(stats));
    }
}